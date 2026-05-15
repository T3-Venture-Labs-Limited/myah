"""
Tests for ``scripts/setup-myah-oss.sh`` — the one-shot OSS bootstrap helper.

This is the script first-time users run after ``git clone`` to align the
agent ↔ platform shared bearer token AND generate the two cryptographic
secrets the platform needs to boot without crashing:

* ``MYAH_AGENT_BEARER_TOKEN`` — bearer token mirrored to BOTH the platform
  ``.env`` and ``~/.hermes/.env`` so the platform can talk to the host-side
  hermes gateway.
* ``OAUTH_SESSION_TOKEN_ENCRYPTION_KEY`` — Fernet-compatible encryption
  key. ``oauth_sessions.py`` raises ``Exception`` at module import time
  when this is unset (Phase D finding D2).
* ``MYAH_SECRET_KEY`` — HMAC secret for JWT session-cookie signing. An
  empty key triggers ``InsecureKeyLengthWarning`` from python-jose
  (Phase D finding D10).

Each test invokes the script in a sandbox directory: a fresh repo root
with an empty ``.env`` and a HERMES_HOME pointed at a sibling tmp dir.
This isolates from the developer's real ``~/.hermes`` and avoids needing
to mock subprocess machinery.
"""

import os
import shutil
import subprocess
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[4]
SCRIPT_PATH = REPO_ROOT / 'scripts' / 'setup-myah-oss.sh'

# The three keys that must always end up populated in the platform .env
PLATFORM_KEYS = (
    'MYAH_AGENT_BEARER_TOKEN',
    'OAUTH_SESSION_TOKEN_ENCRYPTION_KEY',
    'MYAH_SECRET_KEY',
)


# ── helpers ────────────────────────────────────────────────────────────


def _parse_env(path: Path) -> dict[str, str]:
    """Parse a simple ``KEY=VALUE`` env file into a dict. Last-write wins."""
    out: dict[str, str] = {}
    if not path.exists():
        return out
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        key, _, value = line.partition('=')
        out[key.strip()] = value
    return out


def _run_script(repo_dir: Path, hermes_home: Path, *args: str) -> subprocess.CompletedProcess:
    """Run ``setup-myah-oss.sh`` inside ``repo_dir`` with HERMES_HOME pinned."""
    return subprocess.run(
        ['bash', str(repo_dir / 'scripts' / 'setup-myah-oss.sh'), *args],
        capture_output=True,
        text=True,
        env={**os.environ, 'HERMES_HOME': str(hermes_home)},
        check=True,
    )


@pytest.fixture
def sandbox(tmp_path: Path) -> tuple[Path, Path]:
    """Return ``(repo_dir, hermes_home)`` with an empty platform .env.

    The script is copied (not symlinked) so each test gets a fully isolated
    invocation — modifying the script under test would not affect siblings.
    """
    repo_dir = tmp_path / 'repo'
    repo_dir.mkdir()
    (repo_dir / '.env').touch()

    scripts_dir = repo_dir / 'scripts'
    scripts_dir.mkdir()
    shutil.copy(SCRIPT_PATH, scripts_dir / 'setup-myah-oss.sh')

    hermes_home = tmp_path / 'hermes'
    # Script will create the dir itself, but creating it here proves the
    # script behaves correctly with a pre-existing (empty) directory too.
    hermes_home.mkdir()

    return repo_dir, hermes_home


# ── tests ──────────────────────────────────────────────────────────────


def test_fresh_run_generates_all_three_keys(sandbox):
    """First-run on an empty .env populates the bearer token + both crypto keys."""
    repo_dir, hermes_home = sandbox

    _run_script(repo_dir, hermes_home)

    platform_env = _parse_env(repo_dir / '.env')
    hermes_env = _parse_env(hermes_home / '.env')

    # All three platform-side keys present and non-empty
    for key in PLATFORM_KEYS:
        assert key in platform_env, f'{key} missing from platform .env'
        assert platform_env[key], f'{key} is empty in platform .env'

    # Crypto keys are 64-char hex (32 bytes from `openssl rand -hex 32`)
    assert len(platform_env['OAUTH_SESSION_TOKEN_ENCRYPTION_KEY']) == 64
    assert len(platform_env['MYAH_SECRET_KEY']) == 64
    assert all(c in '0123456789abcdef' for c in platform_env['OAUTH_SESSION_TOKEN_ENCRYPTION_KEY'])
    assert all(c in '0123456789abcdef' for c in platform_env['MYAH_SECRET_KEY'])

    # Bearer token mirrored into hermes .env
    bearer = platform_env['MYAH_AGENT_BEARER_TOKEN']
    assert hermes_env.get('MYAH_AGENT_BEARER_TOKEN') == bearer
    assert hermes_env.get('API_SERVER_KEY') == bearer


def test_rerun_is_idempotent(sandbox):
    """Re-running the script does not rotate any of the three keys."""
    repo_dir, hermes_home = sandbox

    _run_script(repo_dir, hermes_home)
    first_platform = _parse_env(repo_dir / '.env')
    first_hermes = _parse_env(hermes_home / '.env')

    _run_script(repo_dir, hermes_home)
    second_platform = _parse_env(repo_dir / '.env')
    second_hermes = _parse_env(hermes_home / '.env')

    for key in PLATFORM_KEYS:
        assert first_platform[key] == second_platform[key], (
            f'{key} rotated on re-run (idempotent contract violated)'
        )
    assert first_hermes['MYAH_AGENT_BEARER_TOKEN'] == second_hermes['MYAH_AGENT_BEARER_TOKEN']
    assert first_hermes['API_SERVER_KEY'] == second_hermes['API_SERVER_KEY']


def test_rotate_flag_rotates_all_three_keys(sandbox):
    """``--rotate`` forces fresh values for all three keys."""
    repo_dir, hermes_home = sandbox

    _run_script(repo_dir, hermes_home)
    before = _parse_env(repo_dir / '.env')

    _run_script(repo_dir, hermes_home, '--rotate')
    after = _parse_env(repo_dir / '.env')

    for key in PLATFORM_KEYS:
        assert before[key] != after[key], f'{key} did not rotate with --rotate flag'

    # Bearer token rotation must also propagate to hermes side
    hermes_after = _parse_env(hermes_home / '.env')
    assert hermes_after['MYAH_AGENT_BEARER_TOKEN'] == after['MYAH_AGENT_BEARER_TOKEN']
    assert hermes_after['API_SERVER_KEY'] == after['MYAH_AGENT_BEARER_TOKEN']


def test_partial_existing_state_fills_only_missing_keys(sandbox):
    """A pre-existing key keeps its value; only the missing keys are generated."""
    repo_dir, hermes_home = sandbox
    platform_env_path = repo_dir / '.env'

    # Pre-seed MYAH_SECRET_KEY with a known value (a previous user already
    # filled it manually); the other two keys are missing.
    preset_secret = 'a' * 64
    platform_env_path.write_text(f'MYAH_SECRET_KEY={preset_secret}\n')

    _run_script(repo_dir, hermes_home)

    platform_env = _parse_env(platform_env_path)
    assert platform_env['MYAH_SECRET_KEY'] == preset_secret, (
        'Pre-existing MYAH_SECRET_KEY must be preserved, not regenerated'
    )
    assert platform_env['OAUTH_SESSION_TOKEN_ENCRYPTION_KEY'], (
        'Missing OAUTH key must be generated'
    )
    assert platform_env['MYAH_AGENT_BEARER_TOKEN'], 'Missing bearer must be generated'


def test_legacy_webui_secret_key_promoted_to_myah_secret_key(sandbox):
    """A pre-rename install with WEBUI_SECRET_KEY set adopts that value
    into the canonical MYAH_SECRET_KEY slot rather than generating a new one."""
    repo_dir, hermes_home = sandbox
    platform_env_path = repo_dir / '.env'

    legacy_value = 'b' * 64
    platform_env_path.write_text(f'WEBUI_SECRET_KEY={legacy_value}\n')

    _run_script(repo_dir, hermes_home)

    platform_env = _parse_env(platform_env_path)
    assert platform_env['MYAH_SECRET_KEY'] == legacy_value, (
        'Legacy WEBUI_SECRET_KEY should seed the new MYAH_SECRET_KEY rather '
        'than the script generating a fresh one'
    )


def test_next_steps_guidance_is_correct(sandbox):
    """Final guidance block points to the right hermes command and skips the
    obsolete signup prompt (Phase D finding D7)."""
    repo_dir, hermes_home = sandbox

    result = _run_script(repo_dir, hermes_home)
    out = result.stdout

    # D7: correct command for HTTP API server
    assert 'hermes gateway run --replace' in out, (
        f'Expected `hermes gateway run --replace` in guidance, got:\n{out}'
    )
    # D7: must not advertise the stale messaging-gateway start command
    assert 'hermes gateway start' not in out, (
        'Stale "hermes gateway start" guidance still present in script output'
    )
    # D7: must not tell OSS users to "sign up" (no signup screen after Phase 1B)
    assert 'sign up' not in out.lower(), 'Stale sign-up guidance still present'
    # Positive: should clarify the no-signup flow
    assert 'single-user OSS' in out or 'no sign-up' in out.lower()
