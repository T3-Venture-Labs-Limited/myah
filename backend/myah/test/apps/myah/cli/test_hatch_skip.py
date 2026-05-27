"""Tests for the MYAH_SKIP_HATCH_NPM=1 env-var skip path in hatch_build.py.

Why this exists (Slice 0 spike findings): per-worktree venv installs
need to bypass hatch_build.py's `npm install --force` step. Without
the skip, `pip install -e .` from inside a worktree mutates main's
symlinked node_modules and dies.

These are STRUCTURAL tests against the source text of hatch_build.py —
fast, no subprocess. The slow integration test that does a full
fresh-venv install lives in the `slow` marker.
"""

from pathlib import Path

import pytest


_REPO_ROOT = Path(__file__).resolve().parents[7]  # walk up to repo root (above platform-oss/)
_HATCH_BUILD = _REPO_ROOT / 'platform-oss' / 'hatch_build.py'


def test_hatch_build_recognizes_skip_env_var() -> None:
    """The string 'MYAH_SKIP_HATCH_NPM' appears in hatch_build.py.

    Lightweight structural assertion — if a refactor accidentally removes
    the env-var check, this test fails before any per-worktree install
    breaks.
    """
    text = _HATCH_BUILD.read_text()
    assert 'MYAH_SKIP_HATCH_NPM' in text, (
        'hatch_build.py must check the MYAH_SKIP_HATCH_NPM env var to enable '
        'per-worktree venv installs (Slice 0 spike Investigation B finding). '
        'Without this skip, npm install --force runs against the symlinked venv.'
    )


def test_hatch_build_skip_appears_before_npm_call() -> None:
    """The env-var skip MUST come BEFORE the `npm` invocation in initialize().

    If the skip is positioned after `shutil.which('npm')` or after the
    subprocess.run([npm, ...]) calls, the npm-not-found case would still
    raise RuntimeError on machines without Node. Order matters.
    """
    text = _HATCH_BUILD.read_text()
    skip_idx = text.find('MYAH_SKIP_HATCH_NPM')
    npm_call_idx = text.find('subprocess.run')
    assert skip_idx > 0, 'MYAH_SKIP_HATCH_NPM not found'
    assert npm_call_idx > 0, 'subprocess.run not found in hatch_build.py'
    assert skip_idx < npm_call_idx, (
        'MYAH_SKIP_HATCH_NPM check must come BEFORE the subprocess.run([npm, ...]) '
        'call so that node-less environments work when the skip is set.'
    )


def test_build_directory_exists_with_gitkeep() -> None:
    """platform-oss/build/ must exist on disk for hatch force-include to validate.

    Per Slice 0 spike Investigation B: hatchling validates the
    `force-include = { build = "myah/frontend" }` source path during
    editable metadata generation, BEFORE running the custom build hook.
    If platform-oss/build/ doesn't exist, install fails with
    FileNotFoundError BEFORE the MYAH_SKIP_HATCH_NPM skip would have
    a chance to kick in.

    The .gitkeep is a 0-byte file. Hatchling only requires the directory
    to exist and be iterable.
    """
    build_dir = _REPO_ROOT / 'platform-oss' / 'build'
    gitkeep = build_dir / '.gitkeep'
    assert build_dir.is_dir(), (
        f'platform-oss/build/ must exist for hatch force-include validation. '
        f'Looked at: {build_dir}'
    )
    assert gitkeep.exists(), (
        f'platform-oss/build/.gitkeep must exist to keep the directory tracked. '
        f'Looked at: {gitkeep}'
    )


@pytest.mark.slow
def test_hatch_build_skip_succeeds_in_fresh_venv(tmp_path) -> None:
    """Slow integration: MYAH_SKIP_HATCH_NPM=1 lets pip install -e succeed in a fresh venv.

    This catches the case where the env-var skip is present but doesn't
    actually short-circuit the npm step. Reproduces the Slice 0 spike
    Investigation B Step 4 verification.

    Requires python3.11 on PATH. Skipped if not available.
    """
    import os
    import shutil
    import subprocess

    python311 = shutil.which('python3.11')
    if python311 is None:
        pytest.skip('python3.11 not on PATH; cannot create a clean venv')

    venv_dir = tmp_path / 'test_venv'
    subprocess.run([python311, '-m', 'venv', str(venv_dir)], check=True)
    venv_pip = venv_dir / 'bin' / 'pip'
    subprocess.run([str(venv_pip), 'install', '--upgrade', 'pip', '--quiet'], check=True)

    env = os.environ.copy()
    env['MYAH_SKIP_HATCH_NPM'] = '1'
    result = subprocess.run(
        [str(venv_pip), 'install', '-e', str(_REPO_ROOT / 'platform-oss')],
        capture_output=True,
        text=True,
        env=env,
        timeout=300,  # cap at 5 min
    )
    assert result.returncode == 0, (
        f'pip install -e failed even with MYAH_SKIP_HATCH_NPM=1.\n'
        f'stdout (last 50 lines): {result.stdout.splitlines()[-50:]}\n'
        f'stderr (last 30 lines): {result.stderr.splitlines()[-30:]}'
    )
    # Verify the resulting venv works
    myah_bin = venv_dir / 'bin' / 'myah'
    assert myah_bin.exists(), f'myah binary not installed at {myah_bin}'
    help_result = subprocess.run([str(myah_bin), '--help'], capture_output=True, text=True)
    assert help_result.returncode == 0, f'myah --help failed: {help_result.stderr[:200]}'
