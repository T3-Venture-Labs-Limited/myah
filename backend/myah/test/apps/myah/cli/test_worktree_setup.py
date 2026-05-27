"""Tests for venv-side worktree setup primitives.

Commit A of Slice 2 Task 2.2 covers `setup_venv` and
`install_platform_into_venv`. Commit B adds Hermes-side primitives.
Commit C (this batch) adds env-composition primitives. The
create_worktree orchestrator (Commit D) wires them together with
rollback.

Mocks target the CONSUMER namespace (`myah.lib.cli.worktree_setup.run`),
not the source (`myah.lib.cli.shell.run`). Because worktree_setup.py does
`from myah.lib.cli.shell import run`, the `run` name lives as a local
binding inside the consumer module; patching the source module would
silently no-op.
"""

from __future__ import annotations

import json
import string
import sys
from pathlib import Path

import pytest
import yaml
from myah.lib.cli.shell import ShellError, ShellResult
from myah.lib.cli.worktree_setup import (
    _NON_BEARER_SECRET_KEYS,
    WorktreeAlreadyExistsError,
    WorktreeCreationError,
    WorktreeInfo,
    _read_hermes_sha,
    _read_plugin_sha,
    align_hermes_env_tokens,
    create_worktree,
    generate_fresh_tokens,
    install_hermes_into_venv,
    install_platform_into_venv,
    install_plugin_into_hermes,
    materialize_dashboard_shim,
    read_main_env_for_copy,
    set_env_var,
    setup_isolated_hermes,
    setup_venv,
    unset_env_var,
    write_worktree_env,
    write_worktree_platform_env,
)

# ----- setup_venv ----------------------------------------------------------


def test_setup_venv_invokes_python_venv_module(tmp_path: Path, mocker) -> None:
    """setup_venv shells out to `<sys.executable> -m venv <worktree>/.venv` with check=True."""
    mock_run = mocker.patch('myah.lib.cli.worktree_setup.run')
    mock_run.return_value = ShellResult(returncode=0, stdout='', stderr='')

    setup_venv(tmp_path)

    assert mock_run.call_count == 1
    call_args, call_kwargs = mock_run.call_args
    assert call_args[0] == [sys.executable, '-m', 'venv', str(tmp_path / '.venv')]
    assert call_kwargs.get('check') is True


def test_setup_venv_is_idempotent_when_venv_exists(tmp_path: Path, mocker) -> None:
    """If `<worktree>/.venv/bin/python` already exists, setup_venv must NOT re-create."""
    venv_python = tmp_path / '.venv' / 'bin' / 'python'
    venv_python.parent.mkdir(parents=True)
    venv_python.touch()

    mock_run = mocker.patch('myah.lib.cli.worktree_setup.run')

    setup_venv(tmp_path)

    assert mock_run.call_count == 0, 'setup_venv must not re-invoke python -m venv on an existing venv'


# ----- install_platform_into_venv ------------------------------------------


def _make_pip_stub(tmp_path: Path) -> Path:
    """Helper: pre-create a stub pip binary inside the worktree venv layout."""
    pip = tmp_path / '.venv' / 'bin' / 'pip'
    pip.parent.mkdir(parents=True, exist_ok=True)
    pip.touch()
    return pip


def test_install_platform_into_venv_calls_pip_with_editable_install(tmp_path: Path, mocker) -> None:
    """Shells out to `<venv>/bin/pip install -e <worktree>/platform-oss[dev]` with check=True."""
    pip = _make_pip_stub(tmp_path)
    mock_run = mocker.patch('myah.lib.cli.worktree_setup.run')
    mock_run.return_value = ShellResult(returncode=0, stdout='', stderr='')

    install_platform_into_venv(tmp_path)

    assert mock_run.call_count == 1
    call_args, call_kwargs = mock_run.call_args
    cmd = call_args[0]
    assert cmd[0] == str(pip), 'must invoke the absolute venv-relative pip path (spike Investigation C)'
    assert 'install' in cmd
    assert '-e' in cmd
    # Editable target must reference the worktree's platform-oss with the [dev] extra.
    target = f'{tmp_path / "platform-oss"}[dev]'
    assert target in cmd, f'expected editable target {target!r} in cmd {cmd!r}'
    assert call_kwargs.get('check') is True


def test_install_platform_into_venv_merges_skip_hatch_npm_env(
    tmp_path: Path, mocker, monkeypatch: pytest.MonkeyPatch
) -> None:
    """env= must MERGE with os.environ, not replace it.

    Regression gate for the env-merge invariant in shell.run: passing an
    empty/sparse `env=` dict would strip PATH and break the subprocess
    completely. install_platform_into_venv must compose
    {**os.environ, 'MYAH_SKIP_HATCH_NPM': '1'}.
    """
    _make_pip_stub(tmp_path)
    monkeypatch.setenv('MYAH_TEST_SENTINEL', 'present')

    mock_run = mocker.patch('myah.lib.cli.worktree_setup.run')
    mock_run.return_value = ShellResult(returncode=0, stdout='', stderr='')

    install_platform_into_venv(tmp_path, skip_hatch_npm=True)

    _, call_kwargs = mock_run.call_args
    env = call_kwargs.get('env')
    assert env is not None, 'env must be passed when skip_hatch_npm=True'
    assert env.get('MYAH_SKIP_HATCH_NPM') == '1', 'MYAH_SKIP_HATCH_NPM must be set to "1"'
    assert env.get('MYAH_TEST_SENTINEL') == 'present', (
        'parent environment vars must be preserved (env merge, not replace) — '
        "otherwise PATH gets stripped and the pip subprocess can't find anything"
    )


def test_install_platform_into_venv_no_env_when_skip_disabled(tmp_path: Path, mocker) -> None:
    """When skip_hatch_npm=False, env must be None (inherit) — not a partial dict."""
    _make_pip_stub(tmp_path)
    mock_run = mocker.patch('myah.lib.cli.worktree_setup.run')
    mock_run.return_value = ShellResult(returncode=0, stdout='', stderr='')

    install_platform_into_venv(tmp_path, skip_hatch_npm=False)

    _, call_kwargs = mock_run.call_args
    # Either env was not passed, or it was passed as None — both mean inherit.
    assert call_kwargs.get('env') is None


def test_install_platform_into_venv_raises_when_venv_missing(tmp_path: Path) -> None:
    """If `<worktree>/.venv/bin/pip` is missing, raise RuntimeError telling user to run setup_venv first."""
    with pytest.raises(RuntimeError) as exc_info:
        install_platform_into_venv(tmp_path)

    assert 'setup_venv' in str(exc_info.value), (
        'error message must mention setup_venv so the caller knows how to recover'
    )


# ----- setup_isolated_hermes -----------------------------------------------


_EXPECTED_HERMES_SUBDIRS = ('plugins', 'data', 'skills', 'models', 'cache', 'logs')


def test_setup_isolated_hermes_creates_directory_tree(tmp_path: Path) -> None:
    """All six expected subdirs under <worktree>/.hermes/ must exist post-call."""
    setup_isolated_hermes(tmp_path)

    hermes_root = tmp_path / '.hermes'
    assert hermes_root.is_dir(), f'expected {hermes_root} to be a directory'
    for sub in _EXPECTED_HERMES_SUBDIRS:
        assert (hermes_root / sub).is_dir(), f'expected {hermes_root / sub} to exist'


def test_setup_isolated_hermes_writes_env_with_adapter_auth_key(tmp_path: Path) -> None:
    """`.env` must exist and contain a non-empty MYAH_ADAPTER_AUTH_KEY= line.

    Per Slice 0 Investigation A: the plugin install runs an interactive
    getpass prompt for MYAH_ADAPTER_AUTH_KEY that hangs on non-TTY CI.
    Pre-populating it here is what makes the subsequent plugin install run
    non-interactively. Commit C overwrites this with the canonical aligned
    token; we just need *something* present so the prompt doesn't fire.
    """
    setup_isolated_hermes(tmp_path)

    env_file = tmp_path / '.hermes' / '.env'
    assert env_file.is_file(), f'expected {env_file} to exist'
    content = env_file.read_text(encoding='utf-8')
    # Match the canonical KEY=VALUE shape, capture the value.
    lines = [ln for ln in content.splitlines() if ln.startswith('MYAH_ADAPTER_AUTH_KEY=')]
    assert len(lines) == 1, f'expected exactly one MYAH_ADAPTER_AUTH_KEY= line, got {lines!r}'
    value = lines[0].split('=', 1)[1]
    assert value, 'MYAH_ADAPTER_AUTH_KEY must have a non-empty value'


def test_setup_isolated_hermes_writes_config_yaml_with_myah_enabled(tmp_path: Path) -> None:
    """config.yaml must enable gateway.platforms.myah (the platform won't bind otherwise)."""
    setup_isolated_hermes(tmp_path)

    config_path = tmp_path / '.hermes' / 'config.yaml'
    assert config_path.is_file(), f'expected {config_path} to exist'
    config = yaml.safe_load(config_path.read_text(encoding='utf-8'))
    assert config is not None, 'config.yaml must parse to a non-None object'
    assert config['gateway']['platforms']['myah']['enabled'] is True


def test_setup_isolated_hermes_does_not_overwrite_existing_env(tmp_path: Path) -> None:
    """A pre-existing .env (user-edited tokens) must survive a re-run."""
    hermes_root = tmp_path / '.hermes'
    hermes_root.mkdir()
    env_file = hermes_root / '.env'
    sentinel = 'MYAH_ADAPTER_AUTH_KEY=user-edited-sentinel-value\n'
    env_file.write_text(sentinel, encoding='utf-8')

    setup_isolated_hermes(tmp_path)

    assert env_file.read_text(encoding='utf-8') == sentinel, (
        'setup_isolated_hermes must not overwrite an existing .env file '
        '(the user may have hand-edited tokens)'
    )


def test_setup_isolated_hermes_does_not_overwrite_existing_config_yaml(tmp_path: Path) -> None:
    """A pre-existing config.yaml must survive a re-run."""
    hermes_root = tmp_path / '.hermes'
    hermes_root.mkdir()
    config_path = hermes_root / 'config.yaml'
    sentinel = 'gateway:\n  platforms:\n    myah:\n      enabled: false  # user-edited\n'
    config_path.write_text(sentinel, encoding='utf-8')

    setup_isolated_hermes(tmp_path)

    assert config_path.read_text(encoding='utf-8') == sentinel, (
        'setup_isolated_hermes must not overwrite an existing config.yaml file'
    )


def test_setup_isolated_hermes_does_not_touch_real_hermes_home(tmp_path: Path) -> None:
    """The entire point of per-worktree isolation is that ~/.hermes/ is untouched."""
    real_home = Path.home() / '.hermes'
    snapshot_before = sorted(p.name for p in real_home.iterdir()) if real_home.is_dir() else None

    setup_isolated_hermes(tmp_path)

    snapshot_after = sorted(p.name for p in real_home.iterdir()) if real_home.is_dir() else None
    assert snapshot_before == snapshot_after, (
        f'real ~/.hermes/ contents changed: before={snapshot_before!r} after={snapshot_after!r}. '
        'setup_isolated_hermes must operate purely under <worktree>/.hermes/.'
    )


# ----- install_hermes_into_venv --------------------------------------------


_FAKE_HERMES_SHA = 'faa13e49f81480771ceeb55991bb0c27edf1a5fb'


def test_install_hermes_into_venv_uses_absolute_pip_path(tmp_path: Path, mocker) -> None:
    """cmd[0] must be the absolute <worktree>/.venv/bin/pip path, not a bare 'pip'."""
    pip = _make_pip_stub(tmp_path)
    mock_run = mocker.patch('myah.lib.cli.worktree_setup.run')
    mock_run.return_value = ShellResult(returncode=0, stdout='', stderr='')

    install_hermes_into_venv(tmp_path, _FAKE_HERMES_SHA)

    call_args, _ = mock_run.call_args
    cmd = call_args[0]
    assert cmd[0] == str(pip), 'must invoke the absolute venv-relative pip path (spike Investigation C)'
    assert '.venv/bin/' in cmd[0], 'cmd[0] must reference the worktree venv layout'


def test_install_hermes_into_venv_builds_git_sha_url(tmp_path: Path, mocker) -> None:
    """The pip-install arg must be hermes-agent[<extras>] @ git+https://...@<sha> (Slice 0 Decision 1)."""
    _make_pip_stub(tmp_path)
    mock_run = mocker.patch('myah.lib.cli.worktree_setup.run')
    mock_run.return_value = ShellResult(returncode=0, stdout='', stderr='')

    install_hermes_into_venv(tmp_path, _FAKE_HERMES_SHA)

    call_args, _ = mock_run.call_args
    cmd = call_args[0]
    joined = ' '.join(cmd)
    assert f'git+https://github.com/NousResearch/Hermes-Agent@{_FAKE_HERMES_SHA}' in joined, (
        f'expected git+SHA URL with sha={_FAKE_HERMES_SHA} in cmd {cmd!r}'
    )
    assert 'hermes-agent[' in joined, 'pip arg must include the bracketed extras list'


def test_install_hermes_into_venv_includes_default_extras(tmp_path: Path, mocker) -> None:
    """All 7 canonical extras must appear in the pip arg string."""
    _make_pip_stub(tmp_path)
    mock_run = mocker.patch('myah.lib.cli.worktree_setup.run')
    mock_run.return_value = ShellResult(returncode=0, stdout='', stderr='')

    install_hermes_into_venv(tmp_path, _FAKE_HERMES_SHA)

    call_args, _ = mock_run.call_args
    cmd = call_args[0]
    joined = ' '.join(cmd)
    for extra in ('messaging', 'cron', 'honcho', 'mcp', 'voice', 'pty', 'web'):
        assert extra in joined, f'expected default extra {extra!r} in cmd {cmd!r}'


def test_install_hermes_into_venv_uses_check_true(tmp_path: Path, mocker) -> None:
    """check=True so the orchestrator can roll back on pip failure."""
    _make_pip_stub(tmp_path)
    mock_run = mocker.patch('myah.lib.cli.worktree_setup.run')
    mock_run.return_value = ShellResult(returncode=0, stdout='', stderr='')

    install_hermes_into_venv(tmp_path, _FAKE_HERMES_SHA)

    _, call_kwargs = mock_run.call_args
    assert call_kwargs.get('check') is True


def test_install_hermes_into_venv_raises_when_venv_missing(tmp_path: Path) -> None:
    """If <worktree>/.venv/bin/pip is missing, raise RuntimeError mentioning setup_venv."""
    with pytest.raises(RuntimeError) as exc_info:
        install_hermes_into_venv(tmp_path, _FAKE_HERMES_SHA)
    assert 'setup_venv' in str(exc_info.value), 'error must hint at setup_venv recovery path'


# ----- install_plugin_into_hermes ------------------------------------------


_FAKE_PLUGIN_SHA = '4a1a6c5eb6ee19fc968b892b26983c0d13aad4bf'


def _make_hermes_env_stub(tmp_path: Path) -> Path:
    """Helper: pre-create a minimal <worktree>/.hermes/.env to satisfy install_plugin_into_hermes."""
    env_file = tmp_path / '.hermes' / '.env'
    env_file.parent.mkdir(parents=True, exist_ok=True)
    env_file.write_text('MYAH_ADAPTER_AUTH_KEY=stub\n', encoding='utf-8')
    return env_file


def test_install_plugin_uses_pip_with_plugin_sha(tmp_path: Path, mocker) -> None:
    """The pip arg must include the plugin's git+SHA URL at the requested SHA."""
    _make_pip_stub(tmp_path)
    _make_hermes_env_stub(tmp_path)
    mock_run = mocker.patch('myah.lib.cli.worktree_setup.run')
    mock_run.return_value = ShellResult(returncode=0, stdout='', stderr='')

    install_plugin_into_hermes(tmp_path, _FAKE_PLUGIN_SHA)

    call_args, _ = mock_run.call_args
    cmd = call_args[0]
    joined = ' '.join(cmd)
    expected_url = (
        f'myah-hermes-plugin @ git+https://github.com/T3-Venture-Labs-Limited/'
        f'myah-hermes-plugin@{_FAKE_PLUGIN_SHA}'
    )
    assert expected_url in joined, f'expected {expected_url!r} in cmd {cmd!r}'


def test_install_plugin_uses_absolute_pip_path(tmp_path: Path, mocker) -> None:
    """cmd[0] must be <worktree>/.venv/bin/pip (Investigation C — no PATH-based fallback)."""
    pip = _make_pip_stub(tmp_path)
    _make_hermes_env_stub(tmp_path)
    mock_run = mocker.patch('myah.lib.cli.worktree_setup.run')
    mock_run.return_value = ShellResult(returncode=0, stdout='', stderr='')

    install_plugin_into_hermes(tmp_path, _FAKE_PLUGIN_SHA)

    call_args, _ = mock_run.call_args
    cmd = call_args[0]
    assert cmd[0] == str(pip)
    assert '.venv/bin/' in cmd[0]


def test_install_plugin_uses_check_true(tmp_path: Path, mocker) -> None:
    """check=True so the orchestrator can roll back on pip failure."""
    _make_pip_stub(tmp_path)
    _make_hermes_env_stub(tmp_path)
    mock_run = mocker.patch('myah.lib.cli.worktree_setup.run')
    mock_run.return_value = ShellResult(returncode=0, stdout='', stderr='')

    install_plugin_into_hermes(tmp_path, _FAKE_PLUGIN_SHA)

    _, call_kwargs = mock_run.call_args
    assert call_kwargs.get('check') is True


def test_install_plugin_raises_when_venv_missing(tmp_path: Path) -> None:
    """Missing venv pip → RuntimeError mentioning setup_venv."""
    # .hermes/.env doesn't matter — the venv check happens first.
    with pytest.raises(RuntimeError) as exc_info:
        install_plugin_into_hermes(tmp_path, _FAKE_PLUGIN_SHA)
    assert 'setup_venv' in str(exc_info.value)


def test_install_plugin_raises_when_hermes_env_missing(tmp_path: Path) -> None:
    """Missing <worktree>/.hermes/.env → RuntimeError hinting at setup_isolated_hermes.

    The .env must be pre-populated with MYAH_ADAPTER_AUTH_KEY before plugin
    install so the interactive getpass prompt (Investigation A) doesn't
    block non-TTY callers.
    """
    _make_pip_stub(tmp_path)
    # Deliberately do NOT call _make_hermes_env_stub.
    with pytest.raises(RuntimeError) as exc_info:
        install_plugin_into_hermes(tmp_path, _FAKE_PLUGIN_SHA)
    assert 'setup_isolated_hermes' in str(exc_info.value), (
        'error must hint at setup_isolated_hermes — that is what writes .env'
    )


# ----- materialize_dashboard_shim ------------------------------------------


def _make_console_script_stub(tmp_path: Path) -> Path:
    """Helper: pre-create a stub <venv>/bin/myah-hermes-plugin console script."""
    script = tmp_path / '.venv' / 'bin' / 'myah-hermes-plugin'
    script.parent.mkdir(parents=True, exist_ok=True)
    script.touch()
    return script


def test_materialize_dashboard_shim_invokes_console_script(tmp_path: Path, mocker) -> None:
    """cmd must be the absolute console-script path + install --dashboard-only --target <plugins/>."""
    script = _make_console_script_stub(tmp_path)
    mock_run = mocker.patch('myah.lib.cli.worktree_setup.run')
    mock_run.return_value = ShellResult(returncode=0, stdout='', stderr='')

    materialize_dashboard_shim(tmp_path)

    call_args, _ = mock_run.call_args
    cmd = call_args[0]
    assert cmd[0] == str(script), 'must invoke the absolute venv-relative console-script path'
    assert 'install' in cmd
    assert '--dashboard-only' in cmd
    assert '--target' in cmd
    target_idx = cmd.index('--target')
    target_value = cmd[target_idx + 1]
    plugins_dir = tmp_path / '.hermes' / 'plugins'
    # Accept either "<plugins>/" or "<plugins>" — the canonical script uses a trailing slash.
    assert target_value.rstrip('/') == str(plugins_dir).rstrip('/'), (
        f'--target value {target_value!r} must point at {plugins_dir}'
    )


def test_materialize_dashboard_shim_merges_hermes_home_env(
    tmp_path: Path, mocker, monkeypatch: pytest.MonkeyPatch
) -> None:
    """env= must MERGE os.environ with HERMES_HOME, not replace it.

    Same env-merge invariant as install_platform_into_venv. The console
    script may also read HERMES_HOME internally (defensive — --target is
    explicit but the shim's plugin_api may look up HERMES_HOME for other
    paths). PATH must survive.
    """
    _make_console_script_stub(tmp_path)
    monkeypatch.setenv('PATH', 'sentinel-path-value')

    mock_run = mocker.patch('myah.lib.cli.worktree_setup.run')
    mock_run.return_value = ShellResult(returncode=0, stdout='', stderr='')

    materialize_dashboard_shim(tmp_path)

    _, call_kwargs = mock_run.call_args
    env = call_kwargs.get('env')
    assert env is not None, 'env must be passed (HERMES_HOME override)'
    assert env.get('HERMES_HOME') == str(tmp_path / '.hermes')
    assert env.get('PATH') == 'sentinel-path-value', (
        'PATH from parent env must survive the env merge — '
        'otherwise the subprocess loses PATH and breaks any shebang/dep lookup'
    )


def test_materialize_dashboard_shim_uses_check_true(tmp_path: Path, mocker) -> None:
    """check=True so a missing/broken plugin surfaces as a ShellError to the orchestrator."""
    _make_console_script_stub(tmp_path)
    mock_run = mocker.patch('myah.lib.cli.worktree_setup.run')
    mock_run.return_value = ShellResult(returncode=0, stdout='', stderr='')

    materialize_dashboard_shim(tmp_path)

    _, call_kwargs = mock_run.call_args
    assert call_kwargs.get('check') is True


def test_materialize_dashboard_shim_raises_when_console_script_missing(tmp_path: Path) -> None:
    """If <venv>/bin/myah-hermes-plugin doesn't exist, raise RuntimeError hinting at install_plugin_into_hermes."""
    with pytest.raises(RuntimeError) as exc_info:
        materialize_dashboard_shim(tmp_path)
    assert 'install_plugin_into_hermes' in str(exc_info.value), (
        'error must hint at install_plugin_into_hermes — that is what creates the console script'
    )


# ----- read_main_env_for_copy ---------------------------------------------

# The H2 hosted-mode secret distribution decision: copy non-bearer secrets
# from main, generate fresh bearer/signing tokens per worktree.
_EXPECTED_NON_BEARER_KEYS = frozenset({
    'OPENROUTER_API_KEY',
    'SENTRY_DSN_PLATFORM',
    'LANGFUSE_PUBLIC_KEY',
    'LANGFUSE_SECRET_KEY',
    'LANGFUSE_HOST',
    'OAUTH_SESSION_TOKEN_ENCRYPTION_KEY',
})

_EXPECTED_BEARER_KEYS = frozenset({
    'MYAH_AGENT_BEARER_TOKEN',
    'MYAH_HERMES_WEB_SESSION_TOKEN',
    'MYAH_SECRET_KEY',
})


def test_non_bearer_key_set_matches_h2_decision() -> None:
    """Lock the constant against drift: must equal the 6-element H2 set exactly."""
    assert frozenset(_NON_BEARER_SECRET_KEYS) == _EXPECTED_NON_BEARER_KEYS


def test_read_main_env_for_copy_returns_empty_dict_when_file_missing(tmp_path: Path) -> None:
    """Missing .env file → empty dict. Caller may warn but it is not fatal."""
    missing = tmp_path / 'does-not-exist.env'
    assert read_main_env_for_copy(missing) == {}


def test_read_main_env_for_copy_returns_only_non_bearer_keys(tmp_path: Path) -> None:
    """Write a mixed .env; assert only non-bearer keys come back."""
    env = tmp_path / '.env'
    env.write_text(
        'OPENROUTER_API_KEY=sk-or-abc\n'
        'SENTRY_DSN_PLATFORM=https://sentry.example/1\n'
        'LANGFUSE_PUBLIC_KEY=pk-lf\n'
        'LANGFUSE_SECRET_KEY=sk-lf\n'
        'LANGFUSE_HOST=https://lf.example\n'
        'OAUTH_SESSION_TOKEN_ENCRYPTION_KEY=oauth-key\n'
        'MYAH_AGENT_BEARER_TOKEN=bearer-should-NOT-leak\n'
        'MYAH_HERMES_WEB_SESSION_TOKEN=session-should-NOT-leak\n'
        'MYAH_SECRET_KEY=secret-should-NOT-leak\n'
        'SOMETHING_ELSE=ignored\n',
        encoding='utf-8',
    )

    result = read_main_env_for_copy(env)

    assert set(result.keys()) == _EXPECTED_NON_BEARER_KEYS
    assert result['OPENROUTER_API_KEY'] == 'sk-or-abc'
    assert result['LANGFUSE_HOST'] == 'https://lf.example'
    for bearer in _EXPECTED_BEARER_KEYS:
        assert bearer not in result, f'bearer key {bearer!r} must NOT be copied (H2 decision)'


def test_read_main_env_for_copy_skips_empty_values(tmp_path: Path) -> None:
    """A KEY= with no value (or whitespace-only) must be omitted from the result."""
    env = tmp_path / '.env'
    env.write_text(
        'OPENROUTER_API_KEY=\n'
        'SENTRY_DSN_PLATFORM=   \n'
        'LANGFUSE_HOST=https://present.example\n',
        encoding='utf-8',
    )

    result = read_main_env_for_copy(env)

    assert 'OPENROUTER_API_KEY' not in result, 'empty value must be skipped'
    assert 'SENTRY_DSN_PLATFORM' not in result, 'whitespace-only value must be skipped'
    assert result.get('LANGFUSE_HOST') == 'https://present.example'


def test_read_main_env_for_copy_handles_quoted_values(tmp_path: Path) -> None:
    """Strip a matching pair of single or double quotes wrapping the value."""
    env = tmp_path / '.env'
    env.write_text(
        'OPENROUTER_API_KEY="quoted-double"\n'
        "SENTRY_DSN_PLATFORM='quoted-single'\n"
        'LANGFUSE_HOST=unquoted\n',
        encoding='utf-8',
    )

    result = read_main_env_for_copy(env)

    assert result['OPENROUTER_API_KEY'] == 'quoted-double'
    assert result['SENTRY_DSN_PLATFORM'] == 'quoted-single'
    assert result['LANGFUSE_HOST'] == 'unquoted'


def test_read_main_env_for_copy_handles_export_prefix(tmp_path: Path) -> None:
    """`export KEY=value` must parse identically to `KEY=value`."""
    env = tmp_path / '.env'
    env.write_text(
        'export OPENROUTER_API_KEY=exported-value\n'
        'LANGFUSE_HOST=plain-value\n',
        encoding='utf-8',
    )

    result = read_main_env_for_copy(env)

    assert result['OPENROUTER_API_KEY'] == 'exported-value'
    assert result['LANGFUSE_HOST'] == 'plain-value'


def test_read_main_env_for_copy_skips_comments_and_blank_lines(tmp_path: Path) -> None:
    """Comment lines and blank lines must not produce dict entries or errors."""
    env = tmp_path / '.env'
    env.write_text(
        '# a header comment\n'
        '\n'
        'OPENROUTER_API_KEY=ok\n'
        '   \n'
        '# inline reminder\n'
        'LANGFUSE_HOST=fine\n',
        encoding='utf-8',
    )

    result = read_main_env_for_copy(env)

    assert result == {'OPENROUTER_API_KEY': 'ok', 'LANGFUSE_HOST': 'fine'}


# ----- generate_fresh_tokens ----------------------------------------------


def test_generate_fresh_tokens_returns_three_token_keys() -> None:
    """Exactly the three bearer/signing keys must be returned."""
    tokens = generate_fresh_tokens()
    assert set(tokens.keys()) == _EXPECTED_BEARER_KEYS


def test_generate_fresh_tokens_values_are_distinct() -> None:
    """Three distinct token_urlsafe calls — no two values may be equal."""
    tokens = generate_fresh_tokens()
    values = list(tokens.values())
    assert len(set(values)) == len(values), f'expected all distinct, got {values!r}'


def test_generate_fresh_tokens_values_are_non_empty_and_urlsafe() -> None:
    """Each token must be > 30 chars and contain only URL-safe base64 chars."""
    tokens = generate_fresh_tokens()
    urlsafe_chars = set(string.ascii_letters + string.digits + '-_')
    for key, value in tokens.items():
        assert len(value) > 30, f'{key} token length too short: {len(value)}'
        assert set(value).issubset(urlsafe_chars), (
            f'{key} contains non-URL-safe characters: {set(value) - urlsafe_chars!r}'
        )


def test_bearer_keys_are_not_in_non_bearer_copy_set() -> None:
    """Cross-invariant lock: the bearer set and the copy set must be disjoint."""
    assert _EXPECTED_BEARER_KEYS.isdisjoint(_NON_BEARER_SECRET_KEYS), (
        'bearer keys must NEVER appear in the non-bearer copy set — '
        'H2 decision: generate fresh per worktree, do NOT copy from main'
    )


# ----- write_worktree_env --------------------------------------------------


_FAKE_PORTS_JSON = '{"backend_port": 8189, "frontend_port": 5234}'


def _mock_e2e_ports(mocker, backend_port: int = 8189, frontend_port: int = 5234):
    """Helper: patch run() to return a ShellResult with a JSON ports payload."""
    payload = json.dumps({'backend_port': backend_port, 'frontend_port': frontend_port})
    mock_run = mocker.patch('myah.lib.cli.worktree_setup.run')
    mock_run.return_value = ShellResult(returncode=0, stdout=payload, stderr='')
    return mock_run


def test_write_worktree_env_invokes_e2e_ports_via_subprocess(tmp_path: Path, mocker) -> None:
    """The canonical command shape: <main>/.venv/bin/python <main>/scripts/e2e_ports.py --format json --branch <branch>."""
    main_root = tmp_path / 'main'
    main_root.mkdir()
    worktree = tmp_path / 'worktree'
    worktree.mkdir()
    mock_run = _mock_e2e_ports(mocker)

    write_worktree_env(worktree, branch='feat/example', main_repo_root=main_root)

    assert mock_run.call_count == 1
    call_args, call_kwargs = mock_run.call_args
    cmd = call_args[0]
    assert cmd[0] == str(main_root / 'platform-oss' / '.venv' / 'bin' / 'python')
    assert cmd[1] == str(main_root / 'platform-oss' / 'scripts' / 'e2e_ports.py')
    assert '--format' in cmd and 'json' in cmd
    assert '--branch' in cmd and 'feat/example' in cmd
    assert call_kwargs.get('check') is True


def test_write_worktree_env_writes_file_at_worktree_root(tmp_path: Path, mocker) -> None:
    main_root = tmp_path / 'main'
    main_root.mkdir()
    worktree = tmp_path / 'worktree'
    worktree.mkdir()
    _mock_e2e_ports(mocker)

    write_worktree_env(worktree, branch='feat/x', main_repo_root=main_root)

    assert (worktree / '.worktree-env').is_file()


def test_write_worktree_env_file_contains_backend_and_frontend_port(tmp_path: Path, mocker) -> None:
    main_root = tmp_path / 'main'
    main_root.mkdir()
    worktree = tmp_path / 'worktree'
    worktree.mkdir()
    _mock_e2e_ports(mocker, backend_port=8123, frontend_port=5234)

    write_worktree_env(worktree, branch='feat/x', main_repo_root=main_root)

    content = (worktree / '.worktree-env').read_text(encoding='utf-8')
    assert 'export BACKEND_PORT=8123' in content
    assert 'export FRONTEND_PORT=5234' in content


def test_write_worktree_env_contains_myah_platform_port_equal_to_backend_port(
    tmp_path: Path, mocker
) -> None:
    """**H7 regression gate.** MYAH_PLATFORM_PORT must equal BACKEND_PORT.

    Failure mode this catches: a refactor accidentally writes a different
    value, hosted-mode agent containers then fetch attachments from the
    baked default 8082 instead of the worktree's port, silently breaking
    the worktree's chat flow.
    """
    main_root = tmp_path / 'main'
    main_root.mkdir()
    worktree = tmp_path / 'worktree'
    worktree.mkdir()
    _mock_e2e_ports(mocker, backend_port=8189, frontend_port=5234)

    write_worktree_env(worktree, branch='feat/x', main_repo_root=main_root)

    content = (worktree / '.worktree-env').read_text(encoding='utf-8')
    assert 'export MYAH_PLATFORM_PORT=8189' in content, (
        f'H7 invariant violation: MYAH_PLATFORM_PORT must equal BACKEND_PORT (8189). '
        f'File content was:\n{content}'
    )


def test_write_worktree_env_file_contains_worktree_branch(tmp_path: Path, mocker) -> None:
    main_root = tmp_path / 'main'
    main_root.mkdir()
    worktree = tmp_path / 'worktree'
    worktree.mkdir()
    _mock_e2e_ports(mocker)

    write_worktree_env(worktree, branch='feat/my-branch', main_repo_root=main_root)

    content = (worktree / '.worktree-env').read_text(encoding='utf-8')
    assert 'export WORKTREE_BRANCH=feat/my-branch' in content


def test_write_worktree_env_file_contains_cors_allow_origin(tmp_path: Path, mocker) -> None:
    """CORS must include both the worktree frontend port and main's 5173 default."""
    main_root = tmp_path / 'main'
    main_root.mkdir()
    worktree = tmp_path / 'worktree'
    worktree.mkdir()
    _mock_e2e_ports(mocker, backend_port=8189, frontend_port=5234)

    write_worktree_env(worktree, branch='feat/x', main_repo_root=main_root)

    content = (worktree / '.worktree-env').read_text(encoding='utf-8')
    assert "export CORS_ALLOW_ORIGIN='http://localhost:5234;http://localhost:5173'" in content


def test_write_worktree_env_returns_ports_dict(tmp_path: Path, mocker) -> None:
    main_root = tmp_path / 'main'
    main_root.mkdir()
    worktree = tmp_path / 'worktree'
    worktree.mkdir()
    _mock_e2e_ports(mocker, backend_port=8189, frontend_port=5234)

    result = write_worktree_env(worktree, branch='feat/x', main_repo_root=main_root)

    assert result == {'backend_port': 8189, 'frontend_port': 5234}


def test_write_worktree_env_overwrites_existing_file(tmp_path: Path, mocker) -> None:
    """Not idempotent: regenerate every time so port reassignments take effect."""
    main_root = tmp_path / 'main'
    main_root.mkdir()
    worktree = tmp_path / 'worktree'
    worktree.mkdir()
    stale = worktree / '.worktree-env'
    stale.write_text('STALE_CONTENT_THAT_MUST_NOT_SURVIVE\n', encoding='utf-8')

    _mock_e2e_ports(mocker)

    write_worktree_env(worktree, branch='feat/x', main_repo_root=main_root)

    content = stale.read_text(encoding='utf-8')
    assert 'STALE_CONTENT_THAT_MUST_NOT_SURVIVE' not in content
    assert 'export BACKEND_PORT=' in content


def test_write_worktree_env_uses_absolute_paths_for_python_and_e2e_ports(
    tmp_path: Path, mocker
) -> None:
    """cmd[0] must be an absolute path containing /.venv/bin/python; cmd[1] absolute e2e_ports.py."""
    main_root = tmp_path / 'main'
    main_root.mkdir()
    worktree = tmp_path / 'worktree'
    worktree.mkdir()
    mock_run = _mock_e2e_ports(mocker)

    write_worktree_env(worktree, branch='feat/x', main_repo_root=main_root)

    call_args, _ = mock_run.call_args
    cmd = call_args[0]
    assert Path(cmd[0]).is_absolute(), f'cmd[0] must be absolute, got {cmd[0]!r}'
    assert '/.venv/bin/python' in cmd[0], f'cmd[0] must contain /.venv/bin/python, got {cmd[0]!r}'
    assert Path(cmd[1]).is_absolute(), f'cmd[1] must be absolute, got {cmd[1]!r}'
    assert cmd[1].endswith('e2e_ports.py'), f'cmd[1] must end with e2e_ports.py, got {cmd[1]!r}'


# ----- _read_hermes_sha / _read_plugin_sha --------------------------------


_VALID_HERMES_SHA = 'faa13e49f81480771ceeb55991bb0c27edf1a5fb'
_VALID_PLUGIN_SHA = '4a1a6c5eb6ee19fc968b892b26983c0d13aad4bf'


def _write_stub_dockerfile(tmp_path: Path, *, hermes_sha: str | None, plugin_sha: str | None) -> Path:
    """Helper: write a minimal Dockerfile.stock-shaped file with optional ARG lines."""
    lines = ['# stub Dockerfile.stock\n']
    if hermes_sha is not None:
        lines.append(f'ARG HERMES_SHA={hermes_sha}\n')
    if plugin_sha is not None:
        lines.append(f'ARG MYAH_PLUGIN_SHA={plugin_sha}\n')
    path = tmp_path / 'Dockerfile.stock'
    path.write_text(''.join(lines), encoding='utf-8')
    return path


def test_read_hermes_sha_from_dockerfile_stock(tmp_path: Path) -> None:
    path = _write_stub_dockerfile(tmp_path, hermes_sha=_VALID_HERMES_SHA, plugin_sha=_VALID_PLUGIN_SHA)
    assert _read_hermes_sha(path) == _VALID_HERMES_SHA


def test_read_hermes_sha_raises_on_missing_arg(tmp_path: Path) -> None:
    path = _write_stub_dockerfile(tmp_path, hermes_sha=None, plugin_sha=_VALID_PLUGIN_SHA)
    with pytest.raises(RuntimeError) as exc_info:
        _read_hermes_sha(path)
    assert 'HERMES_SHA' in str(exc_info.value)


def test_read_hermes_sha_raises_on_malformed_sha(tmp_path: Path) -> None:
    path = _write_stub_dockerfile(tmp_path, hermes_sha='not-a-real-sha', plugin_sha=_VALID_PLUGIN_SHA)
    with pytest.raises(RuntimeError) as exc_info:
        _read_hermes_sha(path)
    assert 'HERMES_SHA' in str(exc_info.value)


def test_read_hermes_sha_tolerates_trailing_whitespace(tmp_path: Path) -> None:
    """`ARG HERMES_SHA=<sha>   ` with trailing space must still parse."""
    path = tmp_path / 'Dockerfile.stock'
    path.write_text(f'ARG HERMES_SHA={_VALID_HERMES_SHA}   \n', encoding='utf-8')
    assert _read_hermes_sha(path) == _VALID_HERMES_SHA


def test_read_plugin_sha_from_dockerfile_stock(tmp_path: Path) -> None:
    path = _write_stub_dockerfile(tmp_path, hermes_sha=_VALID_HERMES_SHA, plugin_sha=_VALID_PLUGIN_SHA)
    assert _read_plugin_sha(path) == _VALID_PLUGIN_SHA


def test_read_plugin_sha_raises_on_missing_arg(tmp_path: Path) -> None:
    path = _write_stub_dockerfile(tmp_path, hermes_sha=_VALID_HERMES_SHA, plugin_sha=None)
    with pytest.raises(RuntimeError) as exc_info:
        _read_plugin_sha(path)
    assert 'MYAH_PLUGIN_SHA' in str(exc_info.value)


def test_read_plugin_sha_raises_on_malformed_sha(tmp_path: Path) -> None:
    path = _write_stub_dockerfile(tmp_path, hermes_sha=_VALID_HERMES_SHA, plugin_sha='shortsha')
    with pytest.raises(RuntimeError) as exc_info:
        _read_plugin_sha(path)
    assert 'MYAH_PLUGIN_SHA' in str(exc_info.value)


# ----- set_env_var --------------------------------------------------------


def test_set_env_var_inserts_new_key_into_empty_file(tmp_path: Path) -> None:
    path = tmp_path / '.env'
    path.write_text('', encoding='utf-8')

    set_env_var(path, 'NEW_KEY', 'new-value')

    assert 'NEW_KEY=new-value' in path.read_text(encoding='utf-8')


def test_set_env_var_updates_existing_key(tmp_path: Path) -> None:
    path = tmp_path / '.env'
    path.write_text('OTHER=keep\nNEW_KEY=old\nALSO=keep\n', encoding='utf-8')

    set_env_var(path, 'NEW_KEY', 'new-value')

    content = path.read_text(encoding='utf-8')
    assert 'NEW_KEY=new-value' in content
    assert 'NEW_KEY=old' not in content
    assert 'OTHER=keep' in content
    assert 'ALSO=keep' in content


def test_set_env_var_preserves_export_prefix(tmp_path: Path) -> None:
    path = tmp_path / '.env'
    path.write_text('export NEW_KEY=old\n', encoding='utf-8')

    set_env_var(path, 'NEW_KEY', 'new-value')

    content = path.read_text(encoding='utf-8')
    assert 'export NEW_KEY=new-value' in content
    assert 'NEW_KEY=old' not in content


def test_set_env_var_handles_missing_file(tmp_path: Path) -> None:
    path = tmp_path / 'does-not-exist.env'
    assert not path.exists()

    set_env_var(path, 'NEW_KEY', 'new-value')

    assert path.is_file()
    assert 'NEW_KEY=new-value' in path.read_text(encoding='utf-8')


def test_set_env_var_appends_when_key_absent_but_file_has_other_keys(tmp_path: Path) -> None:
    path = tmp_path / '.env'
    path.write_text('EXISTING=value\n', encoding='utf-8')

    set_env_var(path, 'NEW_KEY', 'new-value')

    content = path.read_text(encoding='utf-8')
    assert 'EXISTING=value' in content
    assert 'NEW_KEY=new-value' in content


# ----- unset_env_var ------------------------------------------------------


class TestUnsetEnvVar:
    """Dual of set_env_var. Removes matching KEY lines via atomic write-back."""

    def test_removes_only_matching_line(self, tmp_path: Path) -> None:
        path = tmp_path / '.env'
        path.write_text('FOO=bar\n', encoding='utf-8')

        removed = unset_env_var(path, 'FOO')

        assert removed is True
        assert 'FOO' not in path.read_text(encoding='utf-8')

    def test_preserves_comments_blank_lines_and_other_entries(self, tmp_path: Path) -> None:
        path = tmp_path / '.env'
        original = (
            '# header comment\n'
            '\n'
            'KEEP_ME=alpha\n'
            'DROP_ME=beta\n'
            '\n'
            '# trailing comment\n'
            'ALSO_KEEP=gamma\n'
        )
        path.write_text(original, encoding='utf-8')

        removed = unset_env_var(path, 'DROP_ME')

        assert removed is True
        content = path.read_text(encoding='utf-8')
        assert 'DROP_ME' not in content
        assert '# header comment' in content
        assert '# trailing comment' in content
        assert 'KEEP_ME=alpha' in content
        assert 'ALSO_KEEP=gamma' in content
        # Order preserved: KEEP_ME appears before ALSO_KEEP.
        assert content.find('KEEP_ME') < content.find('ALSO_KEEP')

    def test_returns_false_when_key_absent(self, tmp_path: Path) -> None:
        path = tmp_path / '.env'
        path.write_text('FOO=bar\n', encoding='utf-8')

        removed = unset_env_var(path, 'NOT_PRESENT')

        assert removed is False
        # File untouched.
        assert path.read_text(encoding='utf-8') == 'FOO=bar\n'

    def test_returns_false_when_file_does_not_exist(self, tmp_path: Path) -> None:
        path = tmp_path / 'does-not-exist.env'
        assert not path.exists()

        removed = unset_env_var(path, 'FOO')

        assert removed is False
        # Does NOT create the file.
        assert not path.exists()

    def test_handles_export_prefixed_lines(self, tmp_path: Path) -> None:
        path = tmp_path / '.env'
        path.write_text('export FOO=bar\nKEEP=yes\n', encoding='utf-8')

        removed = unset_env_var(path, 'FOO')

        assert removed is True
        content = path.read_text(encoding='utf-8')
        assert 'FOO' not in content
        assert 'KEEP=yes' in content

    def test_removes_all_duplicate_matches(self, tmp_path: Path) -> None:
        """If a key appears twice (a malformed .env), all matches go."""
        path = tmp_path / '.env'
        path.write_text('FOO=one\nKEEP=ok\nFOO=two\n', encoding='utf-8')

        removed = unset_env_var(path, 'FOO')

        assert removed is True
        content = path.read_text(encoding='utf-8')
        assert 'FOO' not in content
        assert 'KEEP=ok' in content


# ----- atomic writes ------------------------------------------------------


class TestAtomicWrite:
    """Crash-safety regression gates for the .env writers.

    Both ``set_env_var`` and ``unset_env_var`` route through
    ``_atomic_write_text`` (.tmp + ``os.replace``). Simulating an
    ``os.replace`` failure (e.g. cross-filesystem rename, disk full,
    SIGKILL between the tmp-write and the rename) must leave the
    original file unchanged. Worktree creation calls ``set_env_var``
    5+ times to write tokens; a partial write would silently corrupt
    a user's ``.env``.
    """

    def test_set_env_var_writes_atomically(self, tmp_path: Path, mocker) -> None:
        """A crash mid-write must NOT leave a partial file."""
        env = tmp_path / '.env'
        env.write_text('EXISTING=value\n', encoding='utf-8')

        # Force os.replace to raise (simulating filesystem failure right
        # after the .tmp write). The .tmp file may remain; the original
        # MUST be preserved.
        mocker.patch(
            'myah.lib.cli.worktree_setup.os.replace',
            side_effect=OSError('boom'),
        )

        with pytest.raises(OSError):
            set_env_var(env, 'NEW_KEY', 'new_value')

        # Original is unchanged (the atomicity guarantee).
        assert env.read_text(encoding='utf-8') == 'EXISTING=value\n'

    def test_unset_env_var_writes_atomically(self, tmp_path: Path, mocker) -> None:
        """Same crash-safety guarantee on the unset path."""
        env = tmp_path / '.env'
        original = 'KEEP=alpha\nDROP=beta\n'
        env.write_text(original, encoding='utf-8')

        mocker.patch(
            'myah.lib.cli.worktree_setup.os.replace',
            side_effect=OSError('boom'),
        )

        with pytest.raises(OSError):
            unset_env_var(env, 'DROP')

        # Original is unchanged — neither line removed because the
        # rename failed before commit.
        assert env.read_text(encoding='utf-8') == original


# ----- write_worktree_platform_env ----------------------------------------


_FRESH_TOKENS_SAMPLE = {
    'MYAH_AGENT_BEARER_TOKEN': 'fresh-bearer-1',
    'MYAH_HERMES_WEB_SESSION_TOKEN': 'fresh-session-2',
    'MYAH_SECRET_KEY': 'fresh-secret-3',
}


def _make_platform_oss_dir(tmp_path: Path) -> Path:
    """Helper: create <worktree>/platform-oss/ so the .env target dir exists."""
    p = tmp_path / 'platform-oss'
    p.mkdir(parents=True, exist_ok=True)
    return p


def test_write_worktree_platform_env_writes_fresh_tokens(tmp_path: Path) -> None:
    _make_platform_oss_dir(tmp_path)
    write_worktree_platform_env(
        tmp_path, mode='hosted', copied_secrets={}, fresh_tokens=_FRESH_TOKENS_SAMPLE
    )
    content = (tmp_path / 'platform-oss' / '.env').read_text(encoding='utf-8')
    assert 'MYAH_AGENT_BEARER_TOKEN=fresh-bearer-1' in content
    assert 'MYAH_HERMES_WEB_SESSION_TOKEN=fresh-session-2' in content
    assert 'MYAH_SECRET_KEY=fresh-secret-3' in content


def test_write_worktree_platform_env_writes_copied_secrets(tmp_path: Path) -> None:
    _make_platform_oss_dir(tmp_path)
    copied = {
        'OPENROUTER_API_KEY': 'sk-or-test',
        'LANGFUSE_HOST': 'https://lf.example',
    }
    write_worktree_platform_env(
        tmp_path, mode='hosted', copied_secrets=copied, fresh_tokens=_FRESH_TOKENS_SAMPLE
    )
    content = (tmp_path / 'platform-oss' / '.env').read_text(encoding='utf-8')
    assert 'OPENROUTER_API_KEY=sk-or-test' in content
    assert 'LANGFUSE_HOST=https://lf.example' in content


def test_write_worktree_platform_env_oss_mode_writes_deployment_mode_and_auth_false(tmp_path: Path) -> None:
    _make_platform_oss_dir(tmp_path)
    write_worktree_platform_env(
        tmp_path, mode='oss', copied_secrets={}, fresh_tokens=_FRESH_TOKENS_SAMPLE
    )
    content = (tmp_path / 'platform-oss' / '.env').read_text(encoding='utf-8')
    assert 'MYAH_DEPLOYMENT_MODE=oss' in content
    assert 'MYAH_AUTH=false' in content


def test_write_worktree_platform_env_hosted_mode_writes_auth_true_no_deployment_mode(tmp_path: Path) -> None:
    _make_platform_oss_dir(tmp_path)
    write_worktree_platform_env(
        tmp_path, mode='hosted', copied_secrets={}, fresh_tokens=_FRESH_TOKENS_SAMPLE
    )
    content = (tmp_path / 'platform-oss' / '.env').read_text(encoding='utf-8')
    assert 'MYAH_AUTH=true' in content
    assert 'MYAH_DEPLOYMENT_MODE=' not in content


def test_write_worktree_platform_env_generates_oauth_key_when_not_in_copied(tmp_path: Path) -> None:
    _make_platform_oss_dir(tmp_path)
    write_worktree_platform_env(
        tmp_path, mode='hosted', copied_secrets={}, fresh_tokens=_FRESH_TOKENS_SAMPLE
    )
    content = (tmp_path / 'platform-oss' / '.env').read_text(encoding='utf-8')
    # The OAuth encryption key must appear with some non-empty value.
    lines = [ln for ln in content.splitlines() if ln.startswith('OAUTH_SESSION_TOKEN_ENCRYPTION_KEY=')]
    assert len(lines) == 1
    value = lines[0].split('=', 1)[1]
    assert value.strip(), 'OAUTH key must have a non-empty generated value'


def test_write_worktree_platform_env_uses_copied_oauth_key_when_present(tmp_path: Path) -> None:
    _make_platform_oss_dir(tmp_path)
    copied = {'OAUTH_SESSION_TOKEN_ENCRYPTION_KEY': 'copied-oauth-key-from-main'}
    write_worktree_platform_env(
        tmp_path, mode='hosted', copied_secrets=copied, fresh_tokens=_FRESH_TOKENS_SAMPLE
    )
    content = (tmp_path / 'platform-oss' / '.env').read_text(encoding='utf-8')
    assert 'OAUTH_SESSION_TOKEN_ENCRYPTION_KEY=copied-oauth-key-from-main' in content


def test_write_worktree_platform_env_writes_leading_comment_block(tmp_path: Path) -> None:
    _make_platform_oss_dir(tmp_path)
    write_worktree_platform_env(
        tmp_path,
        mode='oss',
        copied_secrets={'OPENROUTER_API_KEY': 'sk-or-x'},
        fresh_tokens=_FRESH_TOKENS_SAMPLE,
    )
    content = (tmp_path / 'platform-oss' / '.env').read_text(encoding='utf-8')
    assert '# Auto-generated by `myah dev worktree create`' in content
    assert '# Mode: oss' in content


# ----- align_hermes_env_tokens --------------------------------------------


def test_align_hermes_env_tokens_writes_all_four_slots(tmp_path: Path) -> None:
    hermes_env = tmp_path / '.hermes' / '.env'
    hermes_env.parent.mkdir(parents=True)
    hermes_env.write_text('MYAH_ADAPTER_AUTH_KEY=placeholder\n', encoding='utf-8')

    align_hermes_env_tokens(tmp_path, 'the-shared-bearer-token')

    content = hermes_env.read_text(encoding='utf-8')
    for key in ('MYAH_AGENT_BEARER_TOKEN', 'MYAH_ADAPTER_AUTH_KEY', 'API_SERVER_KEY', 'MYAH_PLATFORM_BEARER'):
        assert f'{key}=the-shared-bearer-token' in content, f'expected {key}= aligned'


def test_align_hermes_env_tokens_overwrites_existing_placeholder(tmp_path: Path) -> None:
    hermes_env = tmp_path / '.hermes' / '.env'
    hermes_env.parent.mkdir(parents=True)
    hermes_env.write_text('MYAH_ADAPTER_AUTH_KEY=placeholder-must-not-survive\n', encoding='utf-8')

    align_hermes_env_tokens(tmp_path, 'the-shared-bearer-token')

    content = hermes_env.read_text(encoding='utf-8')
    assert 'placeholder-must-not-survive' not in content
    assert 'MYAH_ADAPTER_AUTH_KEY=the-shared-bearer-token' in content


def test_align_hermes_env_tokens_raises_when_hermes_env_missing(tmp_path: Path) -> None:
    # No .hermes/.env exists.
    with pytest.raises(RuntimeError) as exc_info:
        align_hermes_env_tokens(tmp_path, 'token')
    assert 'setup_isolated_hermes' in str(exc_info.value)


# ----- WorktreeInfo + exception classes -----------------------------------


def test_worktree_info_dataclass_has_expected_fields() -> None:
    info = WorktreeInfo(
        path=Path('/tmp/worktree'),
        branch='feat/x',
        mode='hosted',
        ports={'backend_port': 8189, 'frontend_port': 5234},
    )
    assert info.path == Path('/tmp/worktree')
    assert info.branch == 'feat/x'
    assert info.mode == 'hosted'
    assert info.ports == {'backend_port': 8189, 'frontend_port': 5234}


def test_worktree_creation_error_carries_step_and_original() -> None:
    original = ValueError('something failed')
    err = WorktreeCreationError(step='install_hermes_into_venv', original=original)
    assert err.step == 'install_hermes_into_venv'
    assert err.original is original
    assert 'install_hermes_into_venv' in str(err)


def test_worktree_already_exists_error_is_runtime_error() -> None:
    err = WorktreeAlreadyExistsError('worktree already at /foo')
    assert isinstance(err, RuntimeError)


# ----- create_worktree (orchestrator) -------------------------------------


def _mock_all_primitives(mocker, *, hermes_sha: str = _VALID_HERMES_SHA, plugin_sha: str = _VALID_PLUGIN_SHA):
    """Patch every primitive + the SHA readers + the git invocation.

    Returns a SimpleNamespace-like dict with the mocks for easy inspection.
    """
    mocks = {
        '_read_hermes_sha': mocker.patch(
            'myah.lib.cli.worktree_setup._read_hermes_sha', return_value=hermes_sha
        ),
        '_read_plugin_sha': mocker.patch(
            'myah.lib.cli.worktree_setup._read_plugin_sha', return_value=plugin_sha
        ),
        'read_main_env_for_copy': mocker.patch(
            'myah.lib.cli.worktree_setup.read_main_env_for_copy', return_value={}
        ),
        'generate_fresh_tokens': mocker.patch(
            'myah.lib.cli.worktree_setup.generate_fresh_tokens',
            return_value={
                'MYAH_AGENT_BEARER_TOKEN': 'oracle-bearer',
                'MYAH_HERMES_WEB_SESSION_TOKEN': 'oracle-session',
                'MYAH_SECRET_KEY': 'oracle-secret',
            },
        ),
        'run': mocker.patch(
            'myah.lib.cli.worktree_setup.run',
            return_value=ShellResult(returncode=0, stdout='', stderr=''),
        ),
        'setup_isolated_hermes': mocker.patch('myah.lib.cli.worktree_setup.setup_isolated_hermes'),
        'setup_venv': mocker.patch('myah.lib.cli.worktree_setup.setup_venv'),
        'install_platform_into_venv': mocker.patch(
            'myah.lib.cli.worktree_setup.install_platform_into_venv'
        ),
        'install_hermes_into_venv': mocker.patch(
            'myah.lib.cli.worktree_setup.install_hermes_into_venv'
        ),
        'install_plugin_into_hermes': mocker.patch(
            'myah.lib.cli.worktree_setup.install_plugin_into_hermes'
        ),
        'materialize_dashboard_shim': mocker.patch(
            'myah.lib.cli.worktree_setup.materialize_dashboard_shim'
        ),
        'write_worktree_platform_env': mocker.patch(
            'myah.lib.cli.worktree_setup.write_worktree_platform_env'
        ),
        'align_hermes_env_tokens': mocker.patch(
            'myah.lib.cli.worktree_setup.align_hermes_env_tokens'
        ),
        'write_worktree_env': mocker.patch(
            'myah.lib.cli.worktree_setup.write_worktree_env',
            return_value={'backend_port': 8189, 'frontend_port': 5234},
        ),
    }
    return mocks


def test_create_worktree_raises_already_exists_when_dir_exists(tmp_path: Path, mocker) -> None:
    """If <main>/.worktrees/<branch> exists, raise WorktreeAlreadyExistsError. No primitives called."""
    main_root = tmp_path / 'main'
    (main_root / '.worktrees' / 'feat/x').mkdir(parents=True)
    mocks = _mock_all_primitives(mocker)

    with pytest.raises(WorktreeAlreadyExistsError) as exc_info:
        create_worktree('feat/x', mode='hosted', main_repo_root=main_root)
    assert 'destroy' in str(exc_info.value).lower()

    # No side effects allowed once the guard fires.
    for name, m in mocks.items():
        assert m.call_count == 0, f'{name} should not have been called when guard fires'


def test_create_worktree_calls_primitives_in_canonical_order(tmp_path: Path, mocker) -> None:
    main_root = tmp_path / 'main'
    main_root.mkdir()
    mocks = _mock_all_primitives(mocker)

    # Snoop on the order of method calls across mocks by giving them a shared parent mock.
    parent = mocker.MagicMock()
    parent.attach_mock(mocks['read_main_env_for_copy'], 'step1_read_env')
    parent.attach_mock(mocks['generate_fresh_tokens'], 'step2_gen_tokens')
    parent.attach_mock(mocks['run'], 'step3_git_worktree_add')
    parent.attach_mock(mocks['setup_isolated_hermes'], 'step4_isolated_hermes')
    parent.attach_mock(mocks['setup_venv'], 'step5_setup_venv')
    parent.attach_mock(mocks['install_platform_into_venv'], 'step6_install_platform')
    parent.attach_mock(mocks['install_hermes_into_venv'], 'step7_install_hermes')
    parent.attach_mock(mocks['install_plugin_into_hermes'], 'step8_install_plugin')
    parent.attach_mock(mocks['materialize_dashboard_shim'], 'step9_dashboard_shim')
    parent.attach_mock(mocks['write_worktree_platform_env'], 'step10_platform_env')
    parent.attach_mock(mocks['align_hermes_env_tokens'], 'step11_align_tokens')
    parent.attach_mock(mocks['write_worktree_env'], 'step12_worktree_env')

    create_worktree('feat/x', mode='hosted', main_repo_root=main_root)

    # Expected ordering of the first call of each.
    seen_names: list[str] = []
    seen_set: set[str] = set()
    for call in parent.method_calls:
        name = call[0]
        if name in seen_set:
            continue
        seen_set.add(name)
        seen_names.append(name)

    expected = [
        'step1_read_env',
        'step2_gen_tokens',
        'step3_git_worktree_add',
        'step4_isolated_hermes',
        'step5_setup_venv',
        'step6_install_platform',
        'step7_install_hermes',
        'step8_install_plugin',
        'step9_dashboard_shim',
        'step10_platform_env',
        'step11_align_tokens',
        'step12_worktree_env',
    ]
    assert seen_names == expected, f'expected canonical order, got {seen_names}'


def test_create_worktree_passes_hermes_sha_to_install_hermes(tmp_path: Path, mocker) -> None:
    main_root = tmp_path / 'main'
    main_root.mkdir()
    mocks = _mock_all_primitives(mocker, hermes_sha=_VALID_HERMES_SHA)

    create_worktree('feat/x', mode='hosted', main_repo_root=main_root)

    args, _ = mocks['install_hermes_into_venv'].call_args
    assert _VALID_HERMES_SHA in args


def test_create_worktree_passes_plugin_sha_to_install_plugin(tmp_path: Path, mocker) -> None:
    main_root = tmp_path / 'main'
    main_root.mkdir()
    mocks = _mock_all_primitives(mocker, plugin_sha=_VALID_PLUGIN_SHA)

    create_worktree('feat/x', mode='hosted', main_repo_root=main_root)

    args, _ = mocks['install_plugin_into_hermes'].call_args
    assert _VALID_PLUGIN_SHA in args


def test_create_worktree_aligns_bearer_across_platform_env_and_hermes_env(tmp_path: Path, mocker) -> None:
    """The SAME MYAH_AGENT_BEARER_TOKEN flows from generate_fresh_tokens to both env-writers."""
    main_root = tmp_path / 'main'
    main_root.mkdir()
    mocks = _mock_all_primitives(mocker)

    create_worktree('feat/x', mode='hosted', main_repo_root=main_root)

    _, platform_kwargs = mocks['write_worktree_platform_env'].call_args
    fresh_tokens_passed = platform_kwargs['fresh_tokens']
    assert fresh_tokens_passed['MYAH_AGENT_BEARER_TOKEN'] == 'oracle-bearer'

    align_args, _ = mocks['align_hermes_env_tokens'].call_args
    # bearer_token is the second positional arg.
    assert align_args[1] == 'oracle-bearer'


def test_create_worktree_rolls_back_on_install_failure(tmp_path: Path, mocker) -> None:
    """When install_hermes_into_venv raises, cleanup runs in REVERSE for steps that succeeded."""
    main_root = tmp_path / 'main'
    main_root.mkdir()
    mocks = _mock_all_primitives(mocker)
    mocks['install_hermes_into_venv'].side_effect = RuntimeError('pip blew up')

    # Force the steps to actually create the worktree path so cleanup has something to remove.
    # Since git worktree add is mocked, we materialize the directories the cleanups expect.
    worktree_path = main_root / '.worktrees' / 'feat/x'

    def _create_worktree_dir(cmd, **_kwargs):
        # First call: git worktree add — materialize the directory.
        if 'worktree' in cmd and 'add' in cmd:
            worktree_path.mkdir(parents=True, exist_ok=True)
            return ShellResult(returncode=0, stdout='', stderr='')
        # Cleanup git worktree remove — leave alone.
        return ShellResult(returncode=0, stdout='', stderr='')

    mocks['run'].side_effect = _create_worktree_dir

    def _materialize_hermes(p):
        (p / '.hermes').mkdir(parents=True, exist_ok=True)

    mocks['setup_isolated_hermes'].side_effect = _materialize_hermes

    def _materialize_venv(p):
        (p / '.venv').mkdir(parents=True, exist_ok=True)

    mocks['setup_venv'].side_effect = _materialize_venv

    with pytest.raises(WorktreeCreationError) as exc_info:
        create_worktree('feat/x', mode='hosted', main_repo_root=main_root)
    assert exc_info.value.step == 'install_hermes_into_venv'
    assert isinstance(exc_info.value.original, RuntimeError)
    assert 'pip blew up' in str(exc_info.value.original)

    # After rollback, the .venv and .hermes dirs should have been cleaned up.
    assert not (worktree_path / '.venv').exists(), '.venv must be removed by rollback'
    assert not (worktree_path / '.hermes').exists(), '.hermes must be removed by rollback'

    # The git worktree remove cleanup must have been called (via `run`).
    run_calls = mocks['run'].call_args_list
    remove_seen = any('remove' in str(c.args[0]) and 'worktree' in str(c.args[0]) for c in run_calls)
    assert remove_seen, 'git worktree remove cleanup must have been invoked'


def test_create_worktree_rollback_swallows_cleanup_exceptions(tmp_path: Path, mocker) -> None:
    """A failing cleanup must NOT prevent other cleanups from running."""
    main_root = tmp_path / 'main'
    main_root.mkdir()
    mocks = _mock_all_primitives(mocker)
    worktree_path = main_root / '.worktrees' / 'feat/x'

    def _shell_side_effect(cmd, **_kwargs):
        if 'add' in cmd:
            worktree_path.mkdir(parents=True, exist_ok=True)
            return ShellResult(returncode=0, stdout='', stderr='')
        # Make the git worktree remove cleanup FAIL.
        if 'remove' in cmd:
            raise ShellError(cmd, ShellResult(returncode=1, stdout='', stderr='boom'))
        return ShellResult(returncode=0, stdout='', stderr='')

    mocks['run'].side_effect = _shell_side_effect

    def _materialize_hermes(p):
        (p / '.hermes').mkdir(parents=True, exist_ok=True)

    mocks['setup_isolated_hermes'].side_effect = _materialize_hermes
    mocks['install_platform_into_venv'].side_effect = RuntimeError('platform install boom')

    # Cleanup for setup_venv (rmtree of .venv) MUST still run even though
    # the later git-remove cleanup raises.
    def _materialize_venv(p):
        (p / '.venv').mkdir(parents=True, exist_ok=True)

    mocks['setup_venv'].side_effect = _materialize_venv

    with pytest.raises(WorktreeCreationError):
        create_worktree('feat/x', mode='hosted', main_repo_root=main_root)

    # Despite the git-remove cleanup raising, the venv directory cleanup ran:
    assert not (worktree_path / '.venv').exists()
    # And so did the hermes overlay cleanup:
    assert not (worktree_path / '.hermes').exists()


def test_create_worktree_returns_worktree_info_on_success(tmp_path: Path, mocker) -> None:
    main_root = tmp_path / 'main'
    main_root.mkdir()
    _mock_all_primitives(mocker)

    info = create_worktree('feat/x', mode='hosted', main_repo_root=main_root)

    assert isinstance(info, WorktreeInfo)
    assert info.branch == 'feat/x'
    assert info.mode == 'hosted'
    assert info.path == main_root / '.worktrees' / 'feat/x'
    assert info.ports == {'backend_port': 8189, 'frontend_port': 5234}


def test_create_worktree_oss_mode_flows_to_platform_env(tmp_path: Path, mocker) -> None:
    main_root = tmp_path / 'main'
    main_root.mkdir()
    mocks = _mock_all_primitives(mocker)

    create_worktree('feat/x', mode='oss', main_repo_root=main_root)

    _, platform_kwargs = mocks['write_worktree_platform_env'].call_args
    assert platform_kwargs['mode'] == 'oss'
