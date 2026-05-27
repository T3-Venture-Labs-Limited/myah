"""Tests for `myah install` — the end-to-end OSS installer command.

Sub-phase 4f of Slice 4. Covers ``myah.cli.install.install_command`` and
its registration as a top-level Typer command in ``myah.cli.__init__``.

Test strategy:
  - Mock every lib helper that touches the system (detect_hermes_venv,
    bootstrap_pip, pip_install_plugin_at_sha, materialize_dashboard_shim,
    enable_myah_platform, install_systemd_user_units, install_launchd_plists,
    verify_dashboard_plugin_mounted, post_install_doctor_run).
  - Patch at the install module's consumer namespace
    (``myah.cli.install.<helper>``) — the H4 mocking discipline.
  - Use tmp_path for HERMES_HOME via env override.
  - Pre-populate a fake repo root with agent/Dockerfile.stock containing
    a pinned SHA, then invoke from that directory.
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterator

import pytest
from typer.testing import CliRunner

from myah import app
from myah.lib.cli.doctor_checks import CheckResult, CheckStatus
from myah.lib.cli.env_loader import parse_env_file


runner = CliRunner()


# ── fixtures ──────────────────────────────────────────────────────────


@pytest.fixture
def fake_repo(tmp_path: Path) -> Path:
    """Build a minimal fake repo root containing agent/Dockerfile.stock.

    The Dockerfile pins a deterministic 40-char hex SHA so plugin SHA
    resolution succeeds without network access.
    """
    repo = tmp_path / 'fake-repo'
    (repo / 'agent').mkdir(parents=True)
    (repo / 'agent' / 'Dockerfile.stock').write_text(
        'ARG HERMES_SHA=aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\n'
        'ARG MYAH_PLUGIN_SHA=bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb\n',
        encoding='utf-8',
    )
    return repo


@pytest.fixture
def hermes_home(tmp_path: Path) -> Path:
    """A tmp Hermes home directory."""
    h = tmp_path / 'hermes-home'
    h.mkdir(parents=True)
    return h


@pytest.fixture
def install_env(
    monkeypatch: pytest.MonkeyPatch,
    fake_repo: Path,
    hermes_home: Path,
) -> Iterator[dict[str, Path]]:
    """Set HERMES_HOME + chdir to fake_repo; yield key paths.

    Also mocks shutil.which('hermes') to return a fake path so the
    pre-flight check passes.
    """
    monkeypatch.setenv('HERMES_HOME', str(hermes_home))
    monkeypatch.chdir(fake_repo)

    def fake_which(name: str) -> str | None:
        if name == 'hermes':
            return '/usr/local/bin/hermes'
        return None

    monkeypatch.setattr('myah.cli.install.shutil.which', fake_which)

    yield {
        'repo': fake_repo,
        'hermes_home': hermes_home,
        'platform_env': fake_repo / 'platform-oss' / '.env',
        'hermes_env': hermes_home / '.env',
    }


@pytest.fixture
def all_lib_mocks(mocker) -> dict[str, object]:
    """Mock every system-touching lib helper at the install module's namespace.

    Returns the dict of mocker.patch return values keyed by short name so
    individual tests can inspect call_args.
    """
    venv_path = Path('/tmp/fake-venv')
    mocks = {
        'detect_hermes_venv': mocker.patch(
            'myah.cli.install.detect_hermes_venv', return_value=venv_path
        ),
        'bootstrap_pip': mocker.patch('myah.cli.install.bootstrap_pip'),
        'pip_install_plugin_at_sha': mocker.patch('myah.cli.install.pip_install_plugin_at_sha'),
        'materialize_dashboard_shim': mocker.patch('myah.cli.install.materialize_dashboard_shim'),
        'enable_myah_platform': mocker.patch(
            'myah.cli.install.enable_myah_platform', return_value='created'
        ),
        'install_systemd_user_units': mocker.patch('myah.cli.install.install_systemd_user_units'),
        'install_launchd_plists': mocker.patch('myah.cli.install.install_launchd_plists'),
        'verify_dashboard_plugin_mounted': mocker.patch(
            'myah.cli.install.verify_dashboard_plugin_mounted', return_value=True
        ),
        'post_install_doctor_run': mocker.patch(
            'myah.cli.install.post_install_doctor_run',
            return_value=[
                CheckResult(name='hermes binary', status=CheckStatus.OK, message='ok'),
            ],
        ),
    }
    return mocks


# ── happy paths ───────────────────────────────────────────────────────


def test_non_interactive_happy_path(install_env, all_lib_mocks) -> None:
    """Scenario 1: --non-interactive + --service none with all helpers OK → exit 0."""
    result = runner.invoke(app, ['install', '--non-interactive', '--service', 'none'])
    assert result.exit_code == 0, f'stdout: {result.stdout}\nexc: {result.exception}'
    # Sanity: helpers were called
    all_lib_mocks['detect_hermes_venv'].assert_called_once()
    all_lib_mocks['bootstrap_pip'].assert_called_once()
    all_lib_mocks['pip_install_plugin_at_sha'].assert_called_once()
    all_lib_mocks['materialize_dashboard_shim'].assert_called_once()
    all_lib_mocks['enable_myah_platform'].assert_called_once()
    all_lib_mocks['post_install_doctor_run'].assert_called_once()


# ── failure-mode flags ────────────────────────────────────────────────


def test_non_interactive_without_service_fails(install_env, all_lib_mocks) -> None:
    """Scenario 2: --non-interactive without --service → exit non-zero with clear error."""
    result = runner.invoke(app, ['install', '--non-interactive'])
    assert result.exit_code != 0
    assert '--service' in result.stdout or '--service' in str(result.exception)


def test_service_systemd(install_env, all_lib_mocks) -> None:
    """Scenario 3: --service systemd invokes install_systemd_user_units only."""
    result = runner.invoke(app, ['install', '--non-interactive', '--service', 'systemd'])
    assert result.exit_code == 0, result.stdout
    all_lib_mocks['install_systemd_user_units'].assert_called_once()
    all_lib_mocks['install_launchd_plists'].assert_not_called()


def test_service_launchd(install_env, all_lib_mocks) -> None:
    """Scenario 4: --service launchd invokes install_launchd_plists only."""
    result = runner.invoke(app, ['install', '--non-interactive', '--service', 'launchd'])
    assert result.exit_code == 0, result.stdout
    all_lib_mocks['install_launchd_plists'].assert_called_once()
    all_lib_mocks['install_systemd_user_units'].assert_not_called()


def test_service_none_skips_both(install_env, all_lib_mocks) -> None:
    """Scenario 5: --service none skips both systemd + launchd; prints acknowledgment."""
    result = runner.invoke(app, ['install', '--non-interactive', '--service', 'none'])
    assert result.exit_code == 0, result.stdout
    all_lib_mocks['install_systemd_user_units'].assert_not_called()
    all_lib_mocks['install_launchd_plists'].assert_not_called()
    assert 'skipped' in result.stdout.lower() or 'none' in result.stdout.lower()


# ── token rotation semantics ─────────────────────────────────────────


def test_rotate_regenerates_bearer_tokens(install_env, all_lib_mocks) -> None:
    """Scenario 6: --rotate forces fresh bearer token even if existing tokens align."""
    # Pre-populate aligned tokens.
    existing = 'preexisting-bearer-token-value-xxxxxx'
    hermes_env = install_env['hermes_env']
    platform_env = install_env['platform_env']
    platform_env.parent.mkdir(parents=True, exist_ok=True)
    for key in (
        'MYAH_AGENT_BEARER_TOKEN', 'MYAH_ADAPTER_AUTH_KEY', 'API_SERVER_KEY', 'MYAH_PLATFORM_BEARER',
    ):
        hermes_env.write_text(
            (hermes_env.read_text() if hermes_env.exists() else '')
            + f'{key}={existing}\n'
        )
    platform_env.write_text(f'MYAH_AGENT_BEARER_TOKEN={existing}\n')

    result = runner.invoke(
        app, ['install', '--non-interactive', '--service', 'none', '--rotate']
    )
    assert result.exit_code == 0, result.stdout

    # After rotate, the bearer token should have changed.
    after = parse_env_file(platform_env).get('MYAH_AGENT_BEARER_TOKEN', '')
    assert after, 'bearer token should be set'
    assert after != existing, 'bearer token should have rotated'


def test_rotate_overrides_legacy_webui_secret_key(install_env, all_lib_mocks) -> None:
    """Scenario 6b: --rotate must generate a fresh MYAH_SECRET_KEY even when
    the legacy WEBUI_SECRET_KEY is present.

    Regression for the documented contract: ``--rotate`` "regenerates all
    generated tokens/keys (bearer, web session, OAuth, JWT secret)". A user
    migrating from Open WebUI typically has ``WEBUI_SECRET_KEY`` set and no
    ``MYAH_SECRET_KEY``; pre-fix, ``adopt_legacy_webui_key()`` would silently
    copy the OLD value into ``MYAH_SECRET_KEY`` and the fresh JWT secret was
    never generated — i.e. ``--rotate`` was a no-op for the most common OWUI
    migration audience.
    """
    platform_env = install_env['platform_env']
    platform_env.parent.mkdir(parents=True, exist_ok=True)
    legacy_value = 'legacy-webui-secret-do-not-rotate-into-myah'
    platform_env.write_text(f'WEBUI_SECRET_KEY={legacy_value}\n')

    result = runner.invoke(
        app, ['install', '--non-interactive', '--service', 'none', '--rotate']
    )
    assert result.exit_code == 0, result.stdout

    parsed = parse_env_file(platform_env)
    myah_key = parsed.get('MYAH_SECRET_KEY', '')
    assert myah_key, 'MYAH_SECRET_KEY should be set after --rotate'
    assert myah_key != legacy_value, (
        f'--rotate must NOT adopt legacy WEBUI_SECRET_KEY; '
        f'expected fresh JWT secret, got legacy value {legacy_value!r}'
    )
    # Legacy key remains in place — adopt_legacy_webui_key never modifies
    # WEBUI_SECRET_KEY, and the fresh-JWT path on --rotate doesn't either.
    assert parsed.get('WEBUI_SECRET_KEY') == legacy_value


def test_no_rotate_preserves_aligned_tokens(install_env, all_lib_mocks) -> None:
    """Scenario 7: no --rotate + already-aligned tokens → existing value survives."""
    existing = 'preexisting-bearer-aligned-zzzzzzzz'
    hermes_env = install_env['hermes_env']
    platform_env = install_env['platform_env']
    platform_env.parent.mkdir(parents=True, exist_ok=True)
    hermes_env.write_text(
        f'MYAH_AGENT_BEARER_TOKEN={existing}\n'
        f'MYAH_ADAPTER_AUTH_KEY={existing}\n'
        f'API_SERVER_KEY={existing}\n'
        f'MYAH_PLATFORM_BEARER={existing}\n'
    )
    platform_env.write_text(f'MYAH_AGENT_BEARER_TOKEN={existing}\n')

    result = runner.invoke(app, ['install', '--non-interactive', '--service', 'none'])
    assert result.exit_code == 0, result.stdout

    after = parse_env_file(platform_env).get('MYAH_AGENT_BEARER_TOKEN', '')
    assert after == existing, f'expected {existing!r}, got {after!r}'


def test_rotate_and_keep_data_conflict(install_env, all_lib_mocks) -> None:
    """Scenario 8: --rotate + --keep-data → exit non-zero with mutual-exclusion error."""
    result = runner.invoke(
        app,
        ['install', '--non-interactive', '--service', 'none', '--rotate', '--keep-data'],
    )
    assert result.exit_code != 0
    out = result.stdout.lower()
    assert 'rotate' in out and 'keep-data' in out and 'exclusive' in out


# ── openrouter-key + repo root detection ─────────────────────────────


def test_openrouter_key_written_to_hermes_env(install_env, all_lib_mocks) -> None:
    """Scenario 9: --openrouter-key writes OPENROUTER_API_KEY into hermes .env."""
    key = 'sk-or-xyz-test-12345'
    result = runner.invoke(
        app,
        ['install', '--non-interactive', '--service', 'none', '--openrouter-key', key],
    )
    assert result.exit_code == 0, result.stdout
    hermes_env_parsed = parse_env_file(install_env['hermes_env'])
    assert hermes_env_parsed.get('OPENROUTER_API_KEY') == key


def test_repo_root_dockerfile_present(install_env, all_lib_mocks) -> None:
    """Scenario 10: install succeeds when agent/Dockerfile.stock exists at CWD."""
    result = runner.invoke(app, ['install', '--non-interactive', '--service', 'none'])
    assert result.exit_code == 0, result.stdout
    # Plugin SHA read from Dockerfile (40 b's)
    call_args = all_lib_mocks['pip_install_plugin_at_sha'].call_args
    assert call_args.args[0] == 'b' * 40


def test_repo_root_versions_env_only(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    hermes_home: Path,
    all_lib_mocks,
) -> None:
    """Scenario 11: install succeeds with versions.env (no Dockerfile.stock)."""
    public_repo = tmp_path / 'public-oss-repo'
    public_repo.mkdir()
    plugin_sha = 'c' * 40
    (public_repo / 'versions.env').write_text(
        f'# auto-generated\nMYAH_PLUGIN_SHA={plugin_sha}\n'
    )

    monkeypatch.setenv('HERMES_HOME', str(hermes_home))
    monkeypatch.chdir(public_repo)
    monkeypatch.setattr(
        'myah.cli.install.shutil.which',
        lambda name: '/usr/local/bin/hermes' if name == 'hermes' else None,
    )

    result = runner.invoke(app, ['install', '--non-interactive', '--service', 'none'])
    assert result.exit_code == 0, f'stdout: {result.stdout}\nexc: {result.exception}'
    call_args = all_lib_mocks['pip_install_plugin_at_sha'].call_args
    assert call_args.args[0] == plugin_sha


def test_repo_root_neither_sentinel_fails(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    hermes_home: Path,
    all_lib_mocks,
) -> None:
    """Scenario 12: install fails with clear error if neither sentinel exists."""
    empty = tmp_path / 'empty'
    empty.mkdir()
    monkeypatch.setenv('HERMES_HOME', str(hermes_home))
    monkeypatch.chdir(empty)
    monkeypatch.setattr(
        'myah.cli.install.shutil.which',
        lambda name: '/usr/local/bin/hermes' if name == 'hermes' else None,
    )

    result = runner.invoke(app, ['install', '--non-interactive', '--service', 'none'])
    assert result.exit_code != 0
    # C-2 fix: the RuntimeError is caught and re-emitted as a Rich-styled
    # error to stdout, not surfaced as a raw exception traceback.
    assert 'Dockerfile.stock' in result.stdout or 'versions.env' in result.stdout


# ── post-install verification rendering + exit codes ─────────────────


def test_post_install_renders_status_indicators(install_env, mocker) -> None:
    """Scenario 13: post-install verification rendering shows status icons."""
    # Mock all the system-touching lib helpers so we don't need install_env
    for name in (
        'detect_hermes_venv', 'bootstrap_pip', 'pip_install_plugin_at_sha',
        'materialize_dashboard_shim', 'enable_myah_platform',
        'verify_dashboard_plugin_mounted',
    ):
        if name == 'detect_hermes_venv':
            mocker.patch(f'myah.cli.install.{name}', return_value=Path('/tmp/v'))
        elif name == 'verify_dashboard_plugin_mounted':
            mocker.patch(f'myah.cli.install.{name}', return_value=True)
        elif name == 'enable_myah_platform':
            mocker.patch(f'myah.cli.install.{name}', return_value='created')
        else:
            mocker.patch(f'myah.cli.install.{name}')
    mocker.patch(
        'myah.cli.install.post_install_doctor_run',
        return_value=[
            CheckResult(name='check-ok', status=CheckStatus.OK, message='ok'),
            CheckResult(name='check-warn', status=CheckStatus.WARN, message='warn'),
        ],
    )

    result = runner.invoke(app, ['install', '--non-interactive', '--service', 'none'])
    assert result.exit_code == 0
    # Look for status text (OK / WARN words from the rendered Rich table).
    out = result.stdout
    assert 'check-ok' in out
    assert 'check-warn' in out


def test_post_install_fail_exits_one(install_env, mocker) -> None:
    """Scenario 14: any FAIL result → exit code 1."""
    for name in (
        'bootstrap_pip', 'pip_install_plugin_at_sha', 'materialize_dashboard_shim',
        'verify_dashboard_plugin_mounted',
    ):
        if name == 'verify_dashboard_plugin_mounted':
            mocker.patch(f'myah.cli.install.{name}', return_value=True)
        else:
            mocker.patch(f'myah.cli.install.{name}')
    mocker.patch('myah.cli.install.detect_hermes_venv', return_value=Path('/tmp/v'))
    mocker.patch('myah.cli.install.enable_myah_platform', return_value='created')
    mocker.patch(
        'myah.cli.install.post_install_doctor_run',
        return_value=[
            CheckResult(name='ok-check', status=CheckStatus.OK, message='ok'),
            CheckResult(name='bad-check', status=CheckStatus.FAIL, message='broken'),
        ],
    )

    result = runner.invoke(app, ['install', '--non-interactive', '--service', 'none'])
    assert result.exit_code == 1


def test_post_install_all_ok_exits_zero(install_env, all_lib_mocks) -> None:
    """Scenario 15: all OK results → exit code 0."""
    all_lib_mocks['post_install_doctor_run'].return_value = [
        CheckResult(name=f'check-{i}', status=CheckStatus.OK, message='ok') for i in range(3)
    ]
    result = runner.invoke(app, ['install', '--non-interactive', '--service', 'none'])
    assert result.exit_code == 0


def test_post_install_all_warn_exits_zero(install_env, all_lib_mocks) -> None:
    """Scenario 16: all WARN (no FAIL) → exit code 0."""
    all_lib_mocks['post_install_doctor_run'].return_value = [
        CheckResult(name=f'check-{i}', status=CheckStatus.WARN, message='warn') for i in range(3)
    ]
    result = runner.invoke(app, ['install', '--non-interactive', '--service', 'none'])
    assert result.exit_code == 0


# ── 2-slot web session desync recovery ───────────────────────────────


def test_web_session_desync_realigned_to_platform_value(
    install_env, all_lib_mocks,
) -> None:
    """Scenario 17: desync (platform=foo, hermes=bar) → both end up at platform value."""
    platform_value = 'platform-web-session-foo-xxxxxxxxxxxxxxxxx'
    hermes_value = 'hermes-web-session-bar-xxxxxxxxxxxxxxxxxxx'
    hermes_env = install_env['hermes_env']
    platform_env = install_env['platform_env']
    platform_env.parent.mkdir(parents=True, exist_ok=True)
    hermes_env.write_text(f'HERMES_WEB_SESSION_TOKEN={hermes_value}\n')
    platform_env.write_text(f'MYAH_HERMES_WEB_SESSION_TOKEN={platform_value}\n')

    result = runner.invoke(app, ['install', '--non-interactive', '--service', 'none'])
    assert result.exit_code == 0, result.stdout

    assert parse_env_file(platform_env).get('MYAH_HERMES_WEB_SESSION_TOKEN') == platform_value
    assert parse_env_file(hermes_env).get('HERMES_WEB_SESSION_TOKEN') == platform_value


# ── HERMES_HOME env override ─────────────────────────────────────────


def test_hermes_home_env_with_tilde_expands(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """C-5 regression: HERMES_HOME=~/.foo expands to $HOME/.foo, not literal '~/.foo'.

    Python does not auto-expand tildes in env-var values; the _hermes_home
    helper must call os.path.expanduser explicitly. Without that, a Path('~/.foo')
    becomes a relative path in CWD and writes go to the wrong place.
    """
    from myah.cli.install import _hermes_home

    monkeypatch.setenv('HERMES_HOME', '~/.tmp-myah-test')

    result = _hermes_home()

    assert result == Path.home() / '.tmp-myah-test'
    # Belt-and-suspenders: ensure the resolved path is absolute (would be
    # CWD-relative if expansion silently failed).
    assert result.is_absolute()


def test_hermes_home_env_override(
    monkeypatch: pytest.MonkeyPatch,
    fake_repo: Path,
    tmp_path: Path,
    all_lib_mocks,
) -> None:
    """Scenario 18: HERMES_HOME=tmp_path/custom-hermes → hermes-side writes go there."""
    custom = tmp_path / 'custom-hermes'
    monkeypatch.setenv('HERMES_HOME', str(custom))
    monkeypatch.chdir(fake_repo)
    monkeypatch.setattr(
        'myah.cli.install.shutil.which',
        lambda name: '/usr/local/bin/hermes' if name == 'hermes' else None,
    )

    result = runner.invoke(app, ['install', '--non-interactive', '--service', 'none'])
    assert result.exit_code == 0, f'stdout: {result.stdout}\nexc: {result.exception}'

    custom_env = custom / '.env'
    assert custom_env.is_file()
    parsed = parse_env_file(custom_env)
    assert parsed.get('MYAH_AGENT_BEARER_TOKEN'), 'bearer should be written under HERMES_HOME'


# ── interactive prompt ────────────────────────────────────────────────


def test_interactive_service_prompt_accepts_default(
    install_env, all_lib_mocks, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Scenario 19: TTY + no --service → interactive prompt fires and uses default."""
    # Simulate TTY via the install module's testable predicate.
    monkeypatch.setattr('myah.cli.install._stdin_is_tty', lambda: True)
    # Force linux default so systemd is the platform-appropriate default.
    monkeypatch.setattr('myah.cli.install.sys.platform', 'linux')

    # `input='\n'` accepts the default via CliRunner.
    result = runner.invoke(app, ['install'], input='\n')
    assert result.exit_code == 0, f'stdout: {result.stdout}\nexc: {result.exception}'
    all_lib_mocks['install_systemd_user_units'].assert_called_once()


# ── invalid --service value ──────────────────────────────────────────


def test_service_invalid_value_rejected(install_env, all_lib_mocks) -> None:
    """Scenario 20: --service garbage → exit non-zero."""
    result = runner.invoke(
        app, ['install', '--non-interactive', '--service', 'garbage']
    )
    assert result.exit_code != 0


# ── cold-start sentinel ──────────────────────────────────────────────


def test_module_does_not_import_heavy_libs_at_top_level() -> None:
    """Mirrors 4a/4c/4d pattern: Rich + typer.prompt/confirm stay out of module top.

    Typer itself is at module top (needed for @app.command decorators
    and typer.Exit). That's fine — Typer is already on the cold path.

    Scans the actual code prefix (imports + module-level constants)
    only, NOT the leading docstring — the docstring describes the
    module's design and may legitimately mention symbols like
    ``typer.prompt`` while the code lazy-imports them.
    """
    from myah.cli import install as mod

    source = Path(mod.__file__).read_text(encoding='utf-8')
    # Strip the leading module docstring (closes with the second `"""`).
    if source.startswith('"""'):
        end = source.find('"""', 3)
        if end != -1:
            source = source[end + 3:]
    head = source.split('\ndef ', 1)[0]

    for offender in ('import rich', 'from rich', 'typer.prompt(', 'typer.confirm('):
        assert offender not in head, f'install.py top-level uses {offender!r}'


def test_install_command_help_works() -> None:
    """`myah install --help` prints help without crashing."""
    result = runner.invoke(app, ['install', '--help'])
    assert result.exit_code == 0
    assert 'install' in result.stdout.lower()
    # Flags should appear in help text
    assert '--non-interactive' in result.stdout
    assert '--service' in result.stdout
    assert '--rotate' in result.stdout
