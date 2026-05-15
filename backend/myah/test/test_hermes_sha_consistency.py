"""Freshness check for the public plugin SHA pin.

After Phase 1 of the fork-model-subtree migration (2026-05-15), the
plugin lives at T3-Venture-Labs-Limited/myah-hermes-plugin and is pip-
installed by hosted via a SHA pin in agent/Dockerfile.stock. The plugin
advances independently when community PRs land in its repo; hosted may
lag.

This test:
- Reads MYAH_PLUGIN_SHA from agent/Dockerfile.stock (offline format check).
- (Optional, when MYAH_RUN_NETWORK_TESTS=1) Compares against
  T3-VL/myah-hermes-plugin/master to assert hosted lags by at most
  MAX_LAG commits.

The freshness assertion runs only when MYAH_RUN_NETWORK_TESTS=1 so
local test runs (offline) skip it. CI runs with network and gates.

Note: the original cross-repo HERMES_SHA invariant (Dockerfile vs
plugin pyproject.toml) is no longer enforceable from this repo since
the plugin's pyproject.toml lives in the public repo. A separate
follow-up could fetch the plugin's pyproject.toml via gh api and
compare. Out of scope for Task 1.5; tracked as a known gap.
"""
from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

import pytest


# This file lives at platform-oss/backend/myah/test/test_hermes_sha_consistency.py
# So parents[0]=test/, [1]=myah/, [2]=backend/, [3]=platform-oss/, [4]=repo-root.
_REPO_ROOT = Path(__file__).resolve().parents[4]
_DOCKERFILE = _REPO_ROOT / 'agent' / 'Dockerfile.stock'
_PLUGIN_REPO = 'T3-Venture-Labs-Limited/myah-hermes-plugin'

# Hosted is allowed to lag this many commits behind the plugin's master.
# Tune via env var if a deliberate canary or freeze period needs more lag.
_MAX_LAG = int(os.environ.get('MYAH_PLUGIN_MAX_LAG', '20'))


def _read_pin() -> str:
    """Extract the MYAH_PLUGIN_SHA value from the Dockerfile."""
    text = _DOCKERFILE.read_text(encoding='utf-8')
    m = re.search(r'^ARG\s+MYAH_PLUGIN_SHA=([a-f0-9]{7,40})', text, re.MULTILINE)
    if not m:
        pytest.fail(f'No MYAH_PLUGIN_SHA pin found in {_DOCKERFILE}')
    return m.group(1)


def test_plugin_sha_pin_is_full_40_char_hex() -> None:
    """The pin must be a full 40-char SHA (no abbreviated forms)."""
    sha = _read_pin()
    assert re.fullmatch(r'[a-f0-9]{40}', sha), (
        f'MYAH_PLUGIN_SHA must be a full 40-char SHA, got {sha!r}. '
        f'Abbreviated SHAs are ambiguous and may resolve to different '
        f'commits over time as the public repo grows.'
    )


@pytest.mark.skipif(
    os.environ.get('MYAH_RUN_NETWORK_TESTS') != '1',
    reason='Network test — set MYAH_RUN_NETWORK_TESTS=1 to enable.',
)
def test_plugin_sha_pin_is_recent() -> None:
    """Pinned SHA should be within MAX_LAG commits of master HEAD.

    Skipped offline. Run in CI to gate against ancient pins.

    Uses gh CLI (must be authenticated) to query the public repo's
    compare endpoint. Falls back to skip if gh is unavailable or the
    network call fails — preserves CI uptime under transient outages.
    """
    pinned = _read_pin()
    result = subprocess.run(
        [
            'gh', 'api',
            f'repos/{_PLUGIN_REPO}/compare/{pinned}...master',
            '--jq', '.ahead_by',
        ],
        capture_output=True, text=True, check=False,
    )
    if result.returncode != 0:
        pytest.skip(f'gh api compare failed (transient?): {result.stderr.strip()}')

    try:
        ahead_by = int(result.stdout.strip())
    except ValueError:
        pytest.skip(f'Unparseable gh api output: {result.stdout!r}')

    assert ahead_by <= _MAX_LAG, (
        f'Plugin pin is {ahead_by} commits behind {_PLUGIN_REPO}/master '
        f'(max {_MAX_LAG}). Bump MYAH_PLUGIN_SHA in agent/Dockerfile.stock '
        f'or raise MYAH_PLUGIN_MAX_LAG for a deliberate freeze.'
    )
