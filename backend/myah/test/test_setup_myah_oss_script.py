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

REPO_ROOT = Path(__file__).resolve().parents[3]
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
    """Run ``setup-myah-oss.sh`` inside ``repo_dir`` with HERMES_HOME pinned.

    Sets ``MYAH_OSS_SETUP_ENV_ONLY=1`` so the script exits after writing env
    files and skips the plugin-install / hermes-venv-detection steps, which
    require network access and a real Hermes installation.

    On non-zero exit, raises ``AssertionError`` with the script's stdout AND
    stderr inlined. ``subprocess.run(check=True)`` would raise
    ``CalledProcessError`` instead, which most pytest configurations
    truncate the captured output of — making it impossible to tell whether
    the failure was a missing prereq, a missing binary, or a real bug.
    """
    result = subprocess.run(
        ['bash', str(repo_dir / 'scripts' / 'setup-myah-oss.sh'), *args],
        capture_output=True,
        text=True,
        env={
            **os.environ,
            'HERMES_HOME': str(hermes_home),
            'MYAH_OSS_SETUP_ENV_ONLY': '1',
        },
    )
    if result.returncode != 0:
        raise AssertionError(
            f'setup-myah-oss.sh exited {result.returncode}\n'
            f'--- STDOUT ---\n{result.stdout}\n'
            f'--- STDERR ---\n{result.stderr}'
        )
    return result


@pytest.fixture
def sandbox(tmp_path: Path) -> tuple[Path, Path]:
    """Return ``(repo_dir, hermes_home)`` with an empty platform .env.

    The script is copied (not symlinked) so each test gets a fully isolated
    invocation — modifying the script under test would not affect siblings.
    A minimal ``versions.env`` is also seeded; without it the script would
    bail out before reaching even the env-write steps.
    """
    repo_dir = tmp_path / 'repo'
    repo_dir.mkdir()
    (repo_dir / '.env').touch()
    (repo_dir / 'versions.env').write_text(
        'HERMES_SHA=0000000000000000000000000000000000000000\n'
        'MYAH_PLUGIN_SHA=0000000000000000000000000000000000000000\n'
    )

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
        assert first_platform[key] == second_platform[key], f'{key} rotated on re-run (idempotent contract violated)'
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
    assert platform_env['OAUTH_SESSION_TOKEN_ENCRYPTION_KEY'], 'Missing OAUTH key must be generated'
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
        'Legacy WEBUI_SECRET_KEY should seed the new MYAH_SECRET_KEY rather than the script generating a fresh one'
    )


def test_next_steps_guidance_is_correct():
    """Final guidance block in the script points to the right hermes command
    and skips the obsolete signup prompt (Phase D finding D7).

    Checked against the script source rather than the runtime stdout because
    the guidance block executes after the plugin-install step, which the
    other tests skip via ``MYAH_OSS_SETUP_ENV_ONLY``.
    """
    src = SCRIPT_PATH.read_text()

    assert 'hermes gateway run' in src, 'Expected `hermes gateway run` in script guidance'
    # D7: must not tell OSS users to "sign up" (no signup screen after Phase 1B)
    assert 'sign up' not in src.lower(), 'Stale sign-up guidance still present'
    # Positive: should clarify the no-signup flow
    assert 'single-user OSS' in src or 'no sign-up' in src.lower()


def test_hermes_env_has_myah_platform_bearer(sandbox):
    """The plugin's attachment adapter (adapter.py) reads only the literal
    ``MYAH_PLATFORM_BEARER`` env var with no alias fallback. The script must
    write that name with the same value as the other four bearer slots, or
    every attachment upload returns 500 with 'Adapter missing
    MYAH_PLATFORM_BASE_URL / MYAH_PLATFORM_BEARER env'."""
    repo_dir, hermes_home = sandbox

    _run_script(repo_dir, hermes_home)

    platform_env = _parse_env(repo_dir / '.env')
    hermes_env = _parse_env(hermes_home / '.env')

    bearer = platform_env['MYAH_AGENT_BEARER_TOKEN']
    assert hermes_env.get('MYAH_PLATFORM_BEARER') == bearer, (
        'MYAH_PLATFORM_BEARER must match MYAH_AGENT_BEARER_TOKEN in hermes .env'
    )


def test_rotate_flag_rotates_platform_bearer_too(sandbox):
    """``--rotate`` must also rotate MYAH_PLATFORM_BEARER, otherwise the
    five token slots drift apart and outbound attachment fetches fail
    auth at the platform with a 401."""
    repo_dir, hermes_home = sandbox

    _run_script(repo_dir, hermes_home)
    before = _parse_env(hermes_home / '.env')['MYAH_PLATFORM_BEARER']

    _run_script(repo_dir, hermes_home, '--rotate')
    after_hermes = _parse_env(hermes_home / '.env')
    after_platform = _parse_env(repo_dir / '.env')

    assert after_hermes['MYAH_PLATFORM_BEARER'] != before, 'MYAH_PLATFORM_BEARER did not rotate with --rotate flag'
    assert after_hermes['MYAH_PLATFORM_BEARER'] == after_platform['MYAH_AGENT_BEARER_TOKEN'], (
        'After rotate, MYAH_PLATFORM_BEARER must equal the new MYAH_AGENT_BEARER_TOKEN'
    )


def test_idempotent_reruns_keep_platform_bearer_stable(sandbox):
    """Re-running the script must not rotate MYAH_PLATFORM_BEARER (the
    idempotency contract that already applies to the other token slots)."""
    repo_dir, hermes_home = sandbox

    _run_script(repo_dir, hermes_home)
    first = _parse_env(hermes_home / '.env')['MYAH_PLATFORM_BEARER']

    _run_script(repo_dir, hermes_home)
    second = _parse_env(hermes_home / '.env')['MYAH_PLATFORM_BEARER']

    assert first == second, 'MYAH_PLATFORM_BEARER rotated on re-run'


def test_platform_base_url_default_is_loopback(sandbox):
    """Fresh install: MYAH_PLATFORM_BASE_URL must default to a host-resolvable
    address. The previous default (host.docker.internal:8080) only resolves
    from inside a container — host-side hermes can't reach the platform with
    it, surfacing as a 502 'Cannot connect' on attachment fetches."""
    repo_dir, hermes_home = sandbox

    _run_script(repo_dir, hermes_home)

    hermes_env = _parse_env(hermes_home / '.env')
    assert hermes_env.get('MYAH_PLATFORM_BASE_URL') == 'http://127.0.0.1:8080', (
        'MYAH_PLATFORM_BASE_URL must default to http://127.0.0.1:8080 '
        '(matches docker-compose port-publish 127.0.0.1:8080:8080)'
    )


def test_migrates_legacy_broken_host_docker_internal_url(sandbox):
    """Users who installed before this fix have the broken
    host.docker.internal URL persisted in hermes .env. Re-running the
    script must replace that specific value so they don't have to know
    to delete the line manually."""
    repo_dir, hermes_home = sandbox
    hermes_env_path = hermes_home / '.env'
    hermes_env_path.write_text('MYAH_PLATFORM_BASE_URL=http://host.docker.internal:8080\n')

    _run_script(repo_dir, hermes_home)

    hermes_env = _parse_env(hermes_env_path)
    assert hermes_env['MYAH_PLATFORM_BASE_URL'] == 'http://127.0.0.1:8080', (
        'Legacy broken default must be migrated to the working loopback URL'
    )


def test_preserves_custom_platform_base_url(sandbox):
    """A user who points hermes at a remote platform (e.g. running on
    another machine, or a non-default port) must NOT have their custom
    URL clobbered by the migration."""
    repo_dir, hermes_home = sandbox
    hermes_env_path = hermes_home / '.env'
    custom_url = 'http://192.168.1.50:9090'
    hermes_env_path.write_text(f'MYAH_PLATFORM_BASE_URL={custom_url}\n')

    _run_script(repo_dir, hermes_home)

    hermes_env = _parse_env(hermes_env_path)
    assert hermes_env['MYAH_PLATFORM_BASE_URL'] == custom_url, (
        'Custom MYAH_PLATFORM_BASE_URL must be preserved across re-runs'
    )
