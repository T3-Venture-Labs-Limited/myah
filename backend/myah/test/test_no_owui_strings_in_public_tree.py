"""
Anti-regression gate for "Open WebUI" / "OpenWebUI" brand references in the
public OSS tree (Phase A.3 of the OSS launch completion plan).

Scope: tracked files under the directories listed in ``_PUBLIC_SCOPE_PREFIXES``
plus the exact root-level files in ``_PUBLIC_SCOPE_FILES``. These together
are the public OSS surface — files that either ship to the OSS mirror or
describe how the mirror is built (CI workflows, compose files, etc.).

The test counts files containing a case-insensitive match for the regex
``open[ _-]?webui`` (catches ``Open WebUI``, ``OpenWebUI``, ``openwebui``,
``open-webui``, ``open_webui`` — but NOT ``WEBUI_AUTH`` / ``WEBUI_API_BASE_URL``
identifiers; those are tracked separately by Phase B Task B.2 rename PRs).
It then subtracts an explicit ALLOWLIST of files where the reference is
**intentional** (license history, attribution paragraphs, "inherited from
upstream" code comments, fork-origin docs).

The remainder is the "offending" count. The test asserts
``offending == BASELINE_OFFENDING_FILES`` (exact match, not ``<=``). This
enforces **lock-step**: a PR that cleans files MUST decrement the constant
in the same commit, or the test fails red. We chose exact-equality instead
of ``<=`` after a Phase A review surfaced that the previous ``<=`` /
``pytest.skip`` design silently goes green in CI when the developer
forgets to lower the baseline — which is precisely the failure mode this
gate exists to prevent.

End state: ``BASELINE_OFFENDING_FILES = 0`` — at which point this test can
be promoted into the ``backend-curated`` required CI gate (currently
advisory) and the OSS tree carries only allow-listed (intentional) OWUI
references.

The catalog of all OWUI references and the rationale for each ALLOWLIST
entry lives in ``docs/oss-launch/branding-cleanup-catalog.md``.

Reference: ``docs/superpowers/plans/2026-05-14-oss-launch-completion.md``
(Phase A.3).
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest


# Regex that matches the public OWUI brand-name forms but NOT the
# code-identifier forms (``WEBUI_API_BASE_URL`` etc.) — those are tracked
# separately by Phase B Task B.2 rename PRs.
_OWUI_BRAND_PATTERN = re.compile(r'open[ _-]?webui', re.IGNORECASE)


# Repo root is monorepo root (parent of ``platform-oss/``). Resolves through
# worktrees correctly because ``git rev-parse --show-toplevel`` is used below.
def _repo_root() -> Path:
    out = subprocess.check_output(['git', 'rev-parse', '--show-toplevel'], text=True)
    return Path(out.strip())


# Directory prefixes (always end in ``/``) that constitute the **public OSS
# surface**. A tracked file under any of these prefixes is in scope.
_PUBLIC_SCOPE_PREFIXES: tuple[str, ...] = (
    'platform-oss/',
    'agent/',
    'myah-hermes-plugin/',
    'scripts/',
    '.github/workflows/',
)


# Exact root-level filenames that are public-facing (i.e. either ship to the
# OSS mirror or describe how it is built). Listed explicitly so a future
# top-level file with an OWUI string can't sneak past the prefix matcher.
# Some entries may not exist yet — Workstream F / H creates them as part of
# the launch package. Once created, they enter scope automatically.
_PUBLIC_SCOPE_FILES: frozenset[str] = frozenset({
    'README.md',
    'docker-compose.yml',
    'docker-compose.prod.yaml',
    '.dockerignore',
    '.env.example',
    '.env.prod.example',
    # Public-facing launch-package files (some may not exist yet).
    'LICENSE',
    'LICENSE-COMMERCIAL.md',
    'CONTRIBUTING.md',
    'CODE_OF_CONDUCT.md',
    'SECURITY.md',
    'PRIVACY.md',
    'CHANGELOG.md',
})


# Files where OWUI references are **intentional** and must not be cleaned.
# See ``docs/oss-launch/branding-cleanup-catalog.md`` "HISTORICAL-KEEP" for
# the rationale on each entry.
#
# Conventions:
# - List paths exactly (no globs) so additions are explicit and reviewable.
# - When in doubt, leave a file OFF the allow-list — Phase B will clean it
#   or add it here with explicit reasoning.
#
# NOTE: ``platform-oss/LICENSE_NOTICE`` is deliberately NOT in this list.
# It claims new code is "licensed under the Open WebUI License" — actively
# false for Myah (AGPL-3.0-or-later). Phase B.0c fixes it alongside the CLA.
# Rationale captured in branding-cleanup-catalog.md "CRITICAL #5".
_ALLOWLIST: frozenset[str] = frozenset({
    # License history — original OWUI license preserved per fork conventions.
    'platform-oss/LICENSE_HISTORY_OWUI',
    # README attributions (Q10 launch decision: keep comparison table + lineage paragraph).
    'README.md',
    'platform-oss/README-platform.md',
    # CI workflow comments describing the inherited Open WebUI codebase.
    '.github/workflows/deploy.yml',
    '.github/workflows/pr-tests.yml',
    # Code comments that explicitly attribute upstream OWUI provenance.
    'platform-oss/src/lib/components/chat/Messages.svelte',
    'platform-oss/src/lib/types/contract.ts',
    'platform-oss/shared/contract/output_items.py',
    'platform-oss/src/lib/stores/index.ts',
    'platform-oss/src/routes/(app)/+layout.svelte',
    # Test-file comment explicitly describing inherited OWUI behavior.
    'platform-oss/backend/myah/test/test_no_submodule_references.py',
    # This very test file — it must enumerate the patterns it searches for,
    # which naturally makes it match its own regex. Self-reference.
    'platform-oss/backend/myah/test/test_no_owui_strings_in_public_tree.py',
})


# Baseline captured at end of Phase A (2026-05-14, post-review revisions).
# Phase B PRs MUST decrement this constant in lock-step with the files they
# clean — the test asserts exact equality, not a bound, so a PR that cleans
# files but forgets to update this number fails red.
#
# To recompute: run the test and read ``count=N`` from the failure message;
# set this to N.
#
# End state: ``0`` — at which point the test can be promoted to required CI.
BASELINE_OFFENDING_FILES: int = 28


def _is_in_scope(rel_path: str) -> bool:
    """Return True if ``rel_path`` is part of the public OSS surface."""
    if rel_path in _PUBLIC_SCOPE_FILES:
        return True
    return any(rel_path.startswith(prefix) for prefix in _PUBLIC_SCOPE_PREFIXES)


def _list_tracked_public_files(repo_root: Path) -> list[Path]:
    """Return all tracked files inside the public OSS surface."""
    out = subprocess.check_output(['git', 'ls-files'], cwd=repo_root, text=True)
    rel_paths = out.strip().splitlines()
    return [Path(p) for p in rel_paths if _is_in_scope(p)]


def _file_has_owui_brand(repo_root: Path, rel_path: Path) -> bool:
    """Return True if the file contains a case-insensitive OWUI brand match.

    Binary files and unreadable files are treated as non-matching.
    """
    abs_path = repo_root / rel_path
    try:
        # Read with errors='ignore' so a stray non-UTF-8 byte doesn't blow
        # the test up on otherwise-text files.
        text = abs_path.read_text(encoding='utf-8', errors='ignore')
    except (OSError, UnicodeDecodeError):
        return False
    return bool(_OWUI_BRAND_PATTERN.search(text))


def _offending_files(repo_root: Path) -> list[str]:
    """Return tracked public-tree files with OWUI brand refs, minus ALLOWLIST."""
    candidates = _list_tracked_public_files(repo_root)
    offending: list[str] = []
    for rel_path in candidates:
        key = str(rel_path)
        if key in _ALLOWLIST:
            continue
        if _file_has_owui_brand(repo_root, rel_path):
            offending.append(key)
    return sorted(offending)


def test_owui_brand_refs_match_baseline():
    """Lock-step anti-regression gate: ``count == BASELINE_OFFENDING_FILES``.

    Two failure modes, distinct messages:

    1. ``count > BASELINE``: a new file with an OWUI brand reference was
       added. Either clean the reference (preferred) or, if it is
       legitimate historical attribution, add the file to ``_ALLOWLIST``
       with a comment explaining the rationale.

    2. ``count < BASELINE``: a PR removed an OWUI reference but forgot to
       lower ``BASELINE_OFFENDING_FILES``. Drop the constant to ``count``
       in the same commit that cleans the file. This is intentional
       lock-step — see module docstring.

    End state: ``BASELINE_OFFENDING_FILES = 0`` — at which point this test
    can be promoted to the required CI gate.
    """
    repo_root = _repo_root()
    offending = _offending_files(repo_root)
    count = len(offending)

    if count > BASELINE_OFFENDING_FILES:
        pytest.fail(
            f'OWUI brand references in public-tree files: {count} '
            f'(baseline: {BASELINE_OFFENDING_FILES}). '
            f'A new file with an OWUI reference was added.\n\n'
            f'Offending files:\n  - ' + '\n  - '.join(offending) + '\n\n'
            f'Either clean the new reference or — if it is legitimate '
            f'historical attribution — add the file to _ALLOWLIST in '
            f'{Path(__file__).name} with a comment explaining the rationale. '
            f'See docs/oss-launch/branding-cleanup-catalog.md for the full '
            f'cleanup catalog.'
        )

    if count < BASELINE_OFFENDING_FILES:
        pytest.fail(
            f'OWUI brand references in public-tree files dropped from '
            f'{BASELINE_OFFENDING_FILES} (baseline) to {count} (current). '
            f'Lower BASELINE_OFFENDING_FILES to {count} in '
            f'{Path(__file__).name} as part of the cleanup PR.\n\n'
            f'Remaining offending files (informational):\n  - '
            + '\n  - '.join(offending)
        )


def test_allowlist_entries_actually_exist():
    """Sanity: every path in ``_ALLOWLIST`` is a currently-tracked file.

    Catches typos and stale entries when the allow-list is edited.
    """
    repo_root = _repo_root()
    out = subprocess.check_output(['git', 'ls-files'], cwd=repo_root, text=True)
    tracked = set(out.strip().splitlines())
    missing = sorted(p for p in _ALLOWLIST if p not in tracked)
    assert not missing, (
        f'_ALLOWLIST contains paths that are not tracked by git:\n  - '
        + '\n  - '.join(missing)
        + '\n\nEither the file was deleted (remove the allow-list entry) '
        'or the path is mistyped.'
    )


def test_allowlist_entries_actually_contain_owui_refs():
    """Sanity: every allow-listed file actually contains an OWUI reference.

    Catches stale allow-list entries that no longer match anything (the
    underlying file was cleaned without removing the entry).
    """
    repo_root = _repo_root()
    stale: list[str] = []
    for path in sorted(_ALLOWLIST):
        if not _file_has_owui_brand(repo_root, Path(path)):
            stale.append(path)
    assert not stale, (
        f'_ALLOWLIST contains paths that no longer contain an OWUI '
        f'reference (cleanup PR forgot to remove the allow-list entry):'
        f'\n  - ' + '\n  - '.join(stale) + '\n'
    )


def test_scope_prefixes_match_existing_paths():
    """Sanity: every ``_PUBLIC_SCOPE_PREFIXES`` entry matches at least one
    tracked path.

    Catches silent-degradation cases where a directory is renamed (e.g.
    ``agent/`` → ``hermes-agent-config/``) and the test starts including
    zero files from that subtree without anyone noticing.

    ``_PUBLIC_SCOPE_FILES`` is **not** asserted to exist — many of those
    entries (LICENSE, CONTRIBUTING.md, etc.) are scaffolded by Workstream
    F / H later in the OSS launch sequence.
    """
    repo_root = _repo_root()
    out = subprocess.check_output(['git', 'ls-files'], cwd=repo_root, text=True)
    tracked = out.strip().splitlines()
    empty_prefixes = sorted(
        p for p in _PUBLIC_SCOPE_PREFIXES if not any(t.startswith(p) for t in tracked)
    )
    assert not empty_prefixes, (
        f'_PUBLIC_SCOPE_PREFIXES contains directories with zero tracked '
        f'files (renamed or removed?):\n  - ' + '\n  - '.join(empty_prefixes)
    )
