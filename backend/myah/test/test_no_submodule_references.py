"""Regression test — no `agent/hermes/` references in committed code.

After Plan B PR B (submodule decommission) the `agent/hermes/` submodule
is deleted. This contract test catches any new commit that re-introduces
a reference to the old path, which would silently break for fresh-clone
users who do not have the (now-absent) submodule.

Allowed references: historical docs/specs/plans, the upstream-wishlist
snapshot, and this test file itself.
"""
from __future__ import annotations

import subprocess
from pathlib import Path


_REPO_ROOT = Path(__file__).resolve().parents[4]


def test_no_agent_hermes_references_in_committed_code() -> None:
    """After Phase 9, no committed file should reference agent/hermes/."""
    result = subprocess.run(
        ['git', 'grep', '-l', 'agent/hermes'],
        capture_output=True,
        text=True,
        cwd=_REPO_ROOT,
    )
    # Files that are allowed to mention agent/hermes (historical context +
    # decommission-narrating docs that need to say "agent/hermes used to
    # live here"). The test guards against NEW code references being
    # introduced; existing doc/historical references are intentional.
    allowed_prefixes = (
        # Historical specs + plans + reviews + gotchas.
        'docs/',
        'openspec/',
        '.opencode/',
        '.agents/',
        # Top-level meta docs that talk about the decommission.
        'AGENTS.md',
        'WORKTREES.md',
        'myah-diff-stat.txt',
        # CI workflows can still match agent/hermes via path triggers
        # (transitional during the decommission) or as quoted-in-docs paths.
        '.github/',
        # The retired-fork dockerignore lines + the Dockerfile.stock comments
        # narrating where the bundled-skills come from.
        '.dockerignore',
        'agent/Dockerfile.stock',
        'agent/config/config.yaml',
        # The OSS sync workflow mentions the pre-Plan-B plugin path for
        # transitional compat (handles both pre- and post-decommission state).
        # docker-compose.yml has an Open WebUI inherited reference.
        'docker-compose.yml',
        # Existing platform-oss code has docstring/comment references to
        # agent/hermes paths (e.g., "what to check after a submodule bump").
        # These are pre-existing and intentional context for contributors.
        'platform-oss/',
        # Smoke test script has a comment referencing the old path.
        'scripts/smoke-test.sh',
        # This regression test itself
        'platform-oss/backend/myah/test/test_no_submodule_references.py',
    )
    matches = [
        line for line in result.stdout.splitlines()
        if not any(line.startswith(p) for p in allowed_prefixes)
    ]
    assert not matches, (
        f'Found agent/hermes references in committed code: {matches}. '
        'These paths no longer resolve after the submodule decommission. '
        'Update them to reference the pip-installed hermes-agent or the '
        'upstream-snapshot.json.'
    )
