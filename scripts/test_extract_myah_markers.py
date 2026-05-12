# Markers point at our additions in upstream code. Each one is a small
# letter we left in someone else's house, addressed to the future merger.

"""
Tests for `scripts/extract-myah-markers.py`.

The extractor is deliberately stdlib-only and lives at the repo root so it
works from any worktree without depending on `platform/` being installed.
We import it here by file path (since its filename has a hyphen, plain
`import` is impossible).
"""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest


# Resolve the script under test once, so tests can import it as a module.
_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT_PATH = _REPO_ROOT / 'scripts' / 'extract-myah-markers.py'


def _load_extractor():
    """Import `scripts/extract-myah-markers.py` as a module despite the hyphen."""
    spec = importlib.util.spec_from_file_location('extract_myah_markers', _SCRIPT_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f'cannot load {_SCRIPT_PATH}')
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope='module')
def extractor():
    if not _SCRIPT_PATH.exists():
        pytest.skip(f'{_SCRIPT_PATH} not present yet')
    return _load_extractor()


# ── unit: regex-level recognition ───────────────────────────────────────


def test_block_marker_opener_recognized(extractor):
    line = '# ── Myah: session-keyed secret capture ───────────────────────────────────'
    m = extractor.BLOCK_OPEN_RE.match(line)
    assert m is not None
    assert m.group('purpose').strip() == 'session-keyed secret capture'


def test_block_marker_opener_indented(extractor):
    line = '    # ── Myah: scoped helper ─────────────────────────────────────────────'
    m = extractor.BLOCK_OPEN_RE.match(line)
    assert m is not None
    assert m.group('purpose').strip() == 'scoped helper'


def test_block_marker_closer_recognized(extractor):
    line = '# ────────────────────────────────────────────────────────────────────────'
    assert extractor.BLOCK_CLOSE_RE.match(line) is not None


def test_block_closer_requires_min_dashes(extractor):
    # Fewer than 40 dashes after the leading "# " should not count.
    short = '# ─────'
    assert extractor.BLOCK_CLOSE_RE.match(short) is None


def test_inline_marker_recognized(extractor):
    line = '        "myah": Platform.MYAH,  # Myah: platform map entry'
    m = extractor.INLINE_RE.search(line)
    assert m is not None
    assert m.group('purpose').strip() == 'platform map entry'


def test_inline_marker_does_not_match_block_opener(extractor):
    # Block openers contain the substring "Myah:" but should be excluded
    # from inline matches by the extractor's filter (any post-match logic).
    line = '# ── Myah: foo ────────────────────────────────────────────────────────'
    # Inline regex itself may "find" the substring; the extractor must
    # not classify a line that already matches BLOCK_OPEN_RE as inline.
    is_block = extractor.BLOCK_OPEN_RE.match(line) is not None
    assert is_block is True


# ── integration: walk a synthetic tree ──────────────────────────────────


def _write(p: Path, content: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(textwrap.dedent(content).lstrip('\n'), encoding='utf-8')


@pytest.fixture
def fake_hermes(tmp_path):
    """Build a tiny tree shaped like agent/hermes/ with a few markers."""
    root = tmp_path / 'fake_hermes'
    _write(
        root / 'tools' / 'sample.py',
        '''
        import os

        # ── Myah: helper alpha ───────────────────────────────────────────────────
        def myah_alpha():
            return 1
        # ────────────────────────────────────────────────────────────────────────

        def upstream_thing():  # Myah: tag inline-purpose-here
            return 2
        ''',
    )
    _write(
        root / 'gateway' / 'platforms' / 'foo.py',
        '''
        ITEMS = [
            "telegram",
            "myah",  # Myah: registry entry
        ]

        # ── Myah: helper beta ────────────────────────────────────────────────────
        def myah_beta():
            return 3
        # ────────────────────────────────────────────────────────────────────────
        ''',
    )
    # Should be ignored
    (root / '.venv' / 'lib').mkdir(parents=True)
    _write(
        root / '.venv' / 'lib' / 'ignored.py',
        '''
        # ── Myah: should not appear ──────────────────────────────────────────────
        x = 1
        # ────────────────────────────────────────────────────────────────────────
        ''',
    )
    return root


def test_walk_finds_expected_markers(extractor, fake_hermes):
    markers = extractor.collect_markers(fake_hermes)
    purposes = sorted(m['purpose'] for m in markers)
    assert purposes == [
        'helper alpha',
        'helper beta',
        'registry entry',
        'tag inline-purpose-here',
    ]


def test_walk_skips_venv(extractor, fake_hermes):
    markers = extractor.collect_markers(fake_hermes)
    for m in markers:
        assert '.venv' not in Path(m['file']).parts


def test_block_marker_records_line_range_and_kind(extractor, fake_hermes):
    markers = extractor.collect_markers(fake_hermes)
    by_purpose = {m['purpose']: m for m in markers}
    alpha = by_purpose['helper alpha']
    assert alpha['kind'] == 'block'
    assert alpha['start_line'] < alpha['end_line']
    assert alpha['loc'] >= 3  # opener + body + closer


def test_inline_marker_has_single_line(extractor, fake_hermes):
    markers = extractor.collect_markers(fake_hermes)
    inline = next(m for m in markers if m['purpose'] == 'registry entry')
    assert inline['kind'] == 'inline'
    assert inline['start_line'] == inline['end_line']
    assert inline['loc'] == 1


def test_collect_markers_is_deterministic(extractor, fake_hermes):
    a = extractor.collect_markers(fake_hermes)
    b = extractor.collect_markers(fake_hermes)
    assert a == b


def test_nested_block_markers_both_captured(extractor, tmp_path):
    """A real-world case from gateway/run.py where a Myah block is
    nested inside another Myah block. Both must be extracted."""
    root = tmp_path / 'nested'
    _write(
        root / 'a.py',
        '''
        # ── Myah: outer block ────────────────────────────────────────────────────
        x = 1
        if cond:
            # ── Myah: inner block ────────────────────────────────────────────────
            y = 2
            # ────────────────────────────────────────────────────────────────────
        z = 3
        # ────────────────────────────────────────────────────────────────────────
        ''',
    )
    markers = extractor.collect_markers(root)
    purposes = sorted(m['purpose'] for m in markers)
    assert purposes == ['inner block', 'outer block']
    outer = next(m for m in markers if m['purpose'] == 'outer block')
    inner = next(m for m in markers if m['purpose'] == 'inner block')
    assert outer['start_line'] < inner['start_line']
    assert outer['end_line'] > inner['end_line']


def test_orphan_block_opener_warns_but_continues(extractor, tmp_path, capsys):
    root = tmp_path / 'orphan'
    _write(
        root / 'a.py',
        '''
        # ── Myah: orphan opener ──────────────────────────────────────────────────
        x = 1

        # ── Myah: real marker ────────────────────────────────────────────────────
        y = 2
        # ────────────────────────────────────────────────────────────────────────
        ''',
    )
    markers = extractor.collect_markers(root)
    captured = capsys.readouterr()
    assert 'orphan' in captured.err.lower()
    # The real marker still gets extracted.
    purposes = [m['purpose'] for m in markers]
    assert 'real marker' in purposes


# ── slug + sha helpers ──────────────────────────────────────────────────


def test_slugify_purpose(extractor):
    assert extractor.slugify('Public API for platform integration') == 'public-api-for-platform-integration'
    assert extractor.slugify('  weird  spacing &  punctuation!! ') == 'weird-spacing-punctuation'
    assert extractor.slugify('') == 'unnamed'


def test_disambiguate_slug_with_file_basename(extractor, fake_hermes):
    markers = extractor.collect_markers(fake_hermes)
    slugs = [extractor.marker_slug(m) for m in markers]
    # All distinct after slug+disambiguation
    assert len(slugs) == len(set(slugs))


def test_content_sha_changes_with_content(extractor, fake_hermes):
    markers = extractor.collect_markers(fake_hermes)
    a = next(m for m in markers if m['purpose'] == 'helper alpha')
    b = next(m for m in markers if m['purpose'] == 'helper beta')
    assert a['sha256'] != b['sha256']
    # SHA is hex string, 64 chars
    assert len(a['sha256']) == 64


# ── baseline / inventory / patches ──────────────────────────────────────


@pytest.fixture
def fake_repo(tmp_path, fake_hermes, monkeypatch):
    """
    Wire the script's pathing constants to the temp tree.

    The script normally targets `<repo_root>/agent/hermes/` and writes to
    `<repo_root>/docs/fork-markers/`. We patch those constants for the
    duration of one test.
    """
    repo = tmp_path / 'repo'
    repo.mkdir()
    # Move fake_hermes under repo/agent/hermes
    target = repo / 'agent' / 'hermes'
    target.parent.mkdir(parents=True)
    shutil.move(str(fake_hermes), str(target))
    return repo


def test_run_extract_writes_inventory_and_patches(extractor, fake_repo):
    extractor.run_extract(fake_repo, update_baseline=True, generate_patches=False)
    inv_path = fake_repo / 'docs' / 'fork-markers' / 'inventory.json'
    base_path = fake_repo / 'docs' / 'fork-markers' / 'baseline.json'
    assert inv_path.exists()
    assert base_path.exists()

    inv = json.loads(inv_path.read_text())
    assert inv['count'] == 4
    assert len(inv['markers']) == 4

    base = json.loads(base_path.read_text())
    assert base['count'] == 4
    assert 'per_purpose' in base


def test_run_extract_creates_justification_stubs(extractor, fake_repo):
    extractor.run_extract(fake_repo, update_baseline=True, generate_patches=False)
    just_dir = fake_repo / 'docs' / 'fork-markers' / 'justifications'
    assert just_dir.exists()
    files = list(just_dir.glob('*.md'))
    assert len(files) == 4


def test_run_extract_does_not_overwrite_existing_justifications(extractor, fake_repo):
    extractor.run_extract(fake_repo, update_baseline=True, generate_patches=False)
    just_dir = fake_repo / 'docs' / 'fork-markers' / 'justifications'
    one = next(just_dir.glob('*.md'))
    one.write_text('CUSTOM CONTENT — DO NOT OVERWRITE')

    extractor.run_extract(fake_repo, update_baseline=True, generate_patches=False)
    assert one.read_text() == 'CUSTOM CONTENT — DO NOT OVERWRITE'


def test_run_extract_idempotent(extractor, fake_repo):
    extractor.run_extract(fake_repo, update_baseline=True, generate_patches=False)
    inv_first = (fake_repo / 'docs' / 'fork-markers' / 'inventory.json').read_text()
    extractor.run_extract(fake_repo, update_baseline=True, generate_patches=False)
    inv_second = (fake_repo / 'docs' / 'fork-markers' / 'inventory.json').read_text()
    assert inv_first == inv_second


# ── --check mode ────────────────────────────────────────────────────────


def test_check_mode_passes_when_count_matches(extractor, fake_repo):
    extractor.run_extract(fake_repo, update_baseline=True, generate_patches=False)
    rc = extractor.run_check(fake_repo)
    assert rc == 0


def test_check_mode_fails_when_count_increases(extractor, fake_repo):
    extractor.run_extract(fake_repo, update_baseline=True, generate_patches=False)
    # Add a new marker after baselining
    new_file = fake_repo / 'agent' / 'hermes' / 'tools' / 'extra.py'
    new_file.write_text(
        textwrap.dedent('''
        # ── Myah: surprise marker ──────────────────────────────────────────────
        x = 1
        # ────────────────────────────────────────────────────────────────────────
        ''').lstrip('\n')
    )
    rc = extractor.run_check(fake_repo)
    assert rc == 1


def test_check_mode_passes_when_count_decreases(extractor, fake_repo):
    extractor.run_extract(fake_repo, update_baseline=True, generate_patches=False)
    # Delete a marker by editing the file
    sample = fake_repo / 'agent' / 'hermes' / 'tools' / 'sample.py'
    text = sample.read_text()
    text = text.replace('# Myah: tag inline-purpose-here', '')
    sample.write_text(text)
    rc = extractor.run_check(fake_repo)
    assert rc == 0


def test_check_mode_does_not_write_files(extractor, fake_repo):
    extractor.run_extract(fake_repo, update_baseline=True, generate_patches=False)
    inv_before = (fake_repo / 'docs' / 'fork-markers' / 'inventory.json').read_text()
    # Modify markers but only check
    new_file = fake_repo / 'agent' / 'hermes' / 'tools' / 'extra.py'
    new_file.write_text(
        '# ── Myah: surprise ──────────────────────────────────────────────────\nx=1\n# ────────────────────────────────────────────────────────────────────────\n'
    )
    extractor.run_check(fake_repo)
    inv_after = (fake_repo / 'docs' / 'fork-markers' / 'inventory.json').read_text()
    assert inv_before == inv_after


# ── CLI entry point ─────────────────────────────────────────────────────


def test_cli_invocation_check_mode_returns_nonzero_on_increase(tmp_path):
    if not _SCRIPT_PATH.exists():
        pytest.skip(f'{_SCRIPT_PATH} not present yet')
    # Build a minimal repo with no markers and a baseline of zero.
    repo = tmp_path / 'minirepo'
    (repo / 'agent' / 'hermes' / 'tools').mkdir(parents=True)
    (repo / 'docs' / 'fork-markers').mkdir(parents=True)
    (repo / 'docs' / 'fork-markers' / 'baseline.json').write_text(
        json.dumps({'count': 0, 'per_purpose': {}, 'content_hash': 'x'})
    )
    # Add one marker
    (repo / 'agent' / 'hermes' / 'tools' / 'a.py').write_text(
        '# ── Myah: cli test ──────────────────────────────────────────────────\nx=1\n# ────────────────────────────────────────────────────────────────────────\n'
    )
    proc = subprocess.run(
        [sys.executable, str(_SCRIPT_PATH), '--check', '--repo-root', str(repo)],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 1
    assert 'increase' in proc.stdout.lower() or 'increase' in proc.stderr.lower()
