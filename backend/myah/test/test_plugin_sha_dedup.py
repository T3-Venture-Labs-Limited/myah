"""Ensure the public plugin SHA pin is valid and used by public workflows.

The hosted monorepo pins the plugin in ``agent/Dockerfile.stock`` and deploy
workflows extract it from there. The public OSS repo does not ship ``agent/``;
its canonical pin source is ``versions.env``.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
VERSIONS_ENV = ROOT / 'versions.env'
E2E_WORKFLOW = ROOT / '.github' / 'workflows' / 'oss-e2e-shape.yml'


def _read_versions_sha() -> str:
    text = VERSIONS_ENV.read_text()
    m = re.search(r'^MYAH_PLUGIN_SHA=([a-f0-9]{40})\s*$', text, re.M)
    assert m, f'MYAH_PLUGIN_SHA not found in {VERSIONS_ENV}'
    return m.group(1)


def _read_workflow_sha() -> str | None:
    """Read a literal workflow SHA, if present.

    The preferred public workflow shape sources ``versions.env`` at runtime and
    therefore has no literal SHA to drift.
    """
    text = E2E_WORKFLOW.read_text()
    m = re.search(r'MYAH_PLUGIN_SHA=([a-f0-9]{40})', text)
    return m.group(1) if m else None


def test_plugin_sha_versions_env_format_is_valid():
    """versions.env MUST have MYAH_PLUGIN_SHA=<40-char-hex>."""
    sha = _read_versions_sha()
    assert len(sha) == 40
    assert all(c in '0123456789abcdef' for c in sha)


def test_plugin_sha_workflow_matches_or_sources_versions_env():
    """The public E2E workflow must source versions.env or match its literal."""
    versions_sha = _read_versions_sha()
    workflow_sha = _read_workflow_sha()

    if workflow_sha is None:
        text = E2E_WORKFLOW.read_text()
        assert 'source ./versions.env' in text
        assert 'MYAH_PLUGIN_SHA' in text
        return

    assert versions_sha == workflow_sha, (
        f'MYAH_PLUGIN_SHA mismatch:\n'
        f'  versions.env: {versions_sha}\n'
        f'  Workflow:   {workflow_sha}\n'
        'Either align them OR migrate workflow to source versions.env.'
    )
