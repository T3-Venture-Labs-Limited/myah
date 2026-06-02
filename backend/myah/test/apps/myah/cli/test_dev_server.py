"""Tests for `myah dev {backend,frontend,both,stop,restart,status}` (Slice 2 Task 2.4).

Replaces the bash `scripts/dev-worktree.sh` with native Python Typer commands.
The H7 env-composition invariant is locked in `test_env_composition_order.py`;
this file covers the command-shell contract: bearer fail-fast, idempotence,
PID-file/log-file plumbing, the SIGTERM → SIGKILL sequence, and Rich
rendering for `status`.

Mock targets follow the consumer-namespace rule: patch where the symbol is
*imported into* (`myah.cli.dev.server.Popen` etc.), not where it was
originally defined.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from myah import app


runner = CliRunner()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_worktree(tmp_path: Path, *, bearer: str = 'test-bearer-token', extra_env: str = '') -> Path:
    """Materialize a minimal worktree shape rooted at tmp_path."""
    (tmp_path / 'platform-oss').mkdir(exist_ok=True)
    (tmp_path / 'platform-oss' / '.env').write_text(
        f'MYAH_AGENT_BEARER_TOKEN={bearer}\n' if bearer else ''
    )
    (tmp_path / '.worktree-env').write_text(
        'export BACKEND_PORT=8189\n'
        'export FRONTEND_PORT=5234\n'
        'export WORKTREE_BRANCH=test/branch\n'
        'export CORS_ALLOW_ORIGIN=http://localhost:5234\n'
        + extra_env
    )
    # Pre-create .venv/bin/uvicorn as a sentinel so the absolute-path check finds it.
    (tmp_path / '.venv' / 'bin').mkdir(parents=True, exist_ok=True)
    (tmp_path / '.venv' / 'bin' / 'uvicorn').write_text('#!/bin/sh\n')
    return tmp_path


@pytest.fixture
def worktree(tmp_path: Path, mocker) -> Path:
    """Pre-built worktree shape with the resolver pointed at it."""
    wt = _make_worktree(tmp_path)
    mocker.patch('myah.cli.dev.server._get_worktree_path', return_value=wt)
    return wt


class _FakePopen:
    """Minimal stand-in for subprocess.Popen that records kwargs."""

    instances: list['_FakePopen'] = []

    def __init__(self, cmd: list[str], *, env: dict[str, str] | None = None, cwd: Any = None,
                 stdout: Any = None, stderr: Any = None, start_new_session: bool = False,
                 **kwargs: Any) -> None:
        self.cmd = cmd
        self.env = env
        self.cwd = cwd
        self.stdout = stdout
        self.stderr = stderr
        self.start_new_session = start_new_session
        self.kwargs = kwargs
        self.pid = 12345
        _FakePopen.instances.append(self)

    def poll(self) -> int | None:
        return None

    def terminate(self) -> None:
        pass

    def kill(self) -> None:
        pass


@pytest.fixture(autouse=True)
def _reset_popen_instances() -> None:
    _FakePopen.instances.clear()


# ---------------------------------------------------------------------------
# Worktree resolver
# ---------------------------------------------------------------------------


def test_worktree_path_resolved_from_cwd_with_worktree_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Resolver walks up from CWD looking for `.worktree-env`."""
    wt = _make_worktree(tmp_path)
    nested = wt / 'platform-oss' / 'backend'
    nested.mkdir(parents=True, exist_ok=True)
    monkeypatch.chdir(nested)

    from myah.cli.dev.server import _get_worktree_path
    resolved = _get_worktree_path()
    assert resolved.resolve() == wt.resolve()


def test_worktree_path_error_when_outside_worktree(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Outside any worktree the resolver exits with a clear message."""
    monkeypatch.chdir(tmp_path)

    from myah.cli.dev.server import _get_worktree_path
    import typer
    with pytest.raises(typer.Exit):
        _get_worktree_path()


# ---------------------------------------------------------------------------
# backend
# ---------------------------------------------------------------------------


def test_backend_spawns_uvicorn_with_absolute_venv_path(worktree: Path, mocker) -> None:
    """Per Investigation C: must invoke <worktree>/.venv/bin/uvicorn, not PATH-resolved uvicorn."""
    mocker.patch('myah.cli.dev.server._is_port_listening', return_value=False)
    mocker.patch('myah.cli.dev.server._health_check', return_value=True)
    fake_popen = mocker.patch('myah.cli.dev.server.Popen', side_effect=_FakePopen)

    result = runner.invoke(app, ['dev', 'backend'])

    assert result.exit_code == 0, result.output
    assert fake_popen.called
    cmd = fake_popen.call_args.args[0]
    expected_uvicorn = str(worktree / '.venv' / 'bin' / 'uvicorn')
    assert cmd[0] == expected_uvicorn, f'expected {expected_uvicorn}, got {cmd[0]}'
    assert 'myah.main:app' in cmd
    assert '8189' in cmd  # backend port


def test_backend_passes_loaded_env_to_subprocess(worktree: Path, mocker) -> None:
    """The Popen env kwarg includes both platform-oss/.env and .worktree-env values."""
    mocker.patch('myah.cli.dev.server._is_port_listening', return_value=False)
    mocker.patch('myah.cli.dev.server._health_check', return_value=True)
    fake_popen = mocker.patch('myah.cli.dev.server.Popen', side_effect=_FakePopen)

    result = runner.invoke(app, ['dev', 'backend'])

    assert result.exit_code == 0, result.output
    env = fake_popen.call_args.kwargs['env']
    assert env['MYAH_AGENT_BEARER_TOKEN'] == 'test-bearer-token'
    assert env['BACKEND_PORT'] == '8189'


def test_backend_hosted_mode_materializes_hosted_overlay(worktree: Path, mocker) -> None:
    """Hosted worktrees run uvicorn from an OSS+hosted backend overlay."""
    (worktree / 'platform-oss' / 'backend' / 'myah').mkdir(parents=True)
    (worktree / 'platform-oss' / 'backend' / 'myah' / '__init__.py').write_text('')
    (worktree / 'platform-oss' / 'backend' / 'myah' / 'oss_only.py').write_text('OSS = True\n')
    (worktree / 'platform-hosted' / 'backend' / 'myah').mkdir(parents=True)
    (worktree / 'platform-hosted' / 'backend' / 'myah' / 'hosted_only.py').write_text('HOSTED = True\n')
    (worktree / 'platform-oss' / 'package.json').write_text('{"name":"myah","version":"0.0.0"}')
    (worktree / 'platform-oss' / 'shared' / 'contract').mkdir(parents=True)
    (worktree / 'platform-oss' / 'shared' / 'contract' / '__init__.py').write_text('')

    mocker.patch('myah.cli.dev.server._is_port_listening', return_value=False)
    mocker.patch('myah.cli.dev.server._health_check', return_value=True)
    fake_popen = mocker.patch('myah.cli.dev.server.Popen', side_effect=_FakePopen)

    result = runner.invoke(app, ['dev', 'backend'])

    assert result.exit_code == 0, result.output
    cwd = Path(fake_popen.call_args.kwargs['cwd'])
    assert cwd == worktree / '.worktree-logs' / 'hosted-backend-overlay' / 'backend'
    assert (cwd / 'myah' / 'oss_only.py').is_file()
    assert (cwd / 'myah' / 'hosted_only.py').is_file()
    assert (cwd.parent / 'package.json').is_file()
    assert (cwd.parent / 'shared' / 'contract' / '__init__.py').is_file()
    env = fake_popen.call_args.kwargs['env']
    python_path = env['PYTHONPATH'].split(':')
    assert str(cwd) in python_path
    assert str(cwd.parent) in python_path
    assert env['DATA_DIR'] == str(worktree / 'platform-oss' / 'backend' / 'data')


def test_backend_fails_fast_on_empty_bearer(tmp_path: Path, mocker) -> None:
    """Empty MYAH_AGENT_BEARER_TOKEN → exit 2, no Popen call."""
    wt = _make_worktree(tmp_path, bearer='')
    mocker.patch('myah.cli.dev.server._get_worktree_path', return_value=wt)
    mocker.patch('myah.cli.dev.server._is_port_listening', return_value=False)
    fake_popen = mocker.patch('myah.cli.dev.server.Popen', side_effect=_FakePopen)

    result = runner.invoke(app, ['dev', 'backend'])

    assert result.exit_code == 2, result.output
    assert 'MYAH_AGENT_BEARER_TOKEN' in result.output
    assert not fake_popen.called


def test_backend_fails_fast_when_only_worktree_env_exists(tmp_path: Path, mocker) -> None:
    """When platform-oss/.env is entirely missing, bearer is empty → exit 2.

    Mirrors the bash dev-worktree.sh:62-71 fail-fast guard. Without the env
    file the load_worktree_env_chain warns but proceeds; bearer-empty is
    then caught here BEFORE any Popen spawn.
    """
    # No platform-oss/.env at all
    (tmp_path / '.worktree-env').write_text(
        'export BACKEND_PORT=8189\n'
        'export FRONTEND_PORT=5234\n'
        'export WORKTREE_BRANCH=test/branch\n'
    )
    (tmp_path / '.venv' / 'bin').mkdir(parents=True, exist_ok=True)
    (tmp_path / '.venv' / 'bin' / 'uvicorn').write_text('#!/bin/sh\n')

    mocker.patch('myah.cli.dev.server._get_worktree_path', return_value=tmp_path)
    mocker.patch('myah.cli.dev.server._is_port_listening', return_value=False)
    fake_popen = mocker.patch('myah.cli.dev.server.Popen', side_effect=_FakePopen)

    result = runner.invoke(app, ['dev', 'backend'])

    assert result.exit_code == 2, result.output
    assert 'MYAH_AGENT_BEARER_TOKEN' in result.output
    assert not fake_popen.called


def test_backend_idempotent_when_already_listening(worktree: Path, mocker) -> None:
    """If port is already listening, print 'already running' and exit 0 without Popen."""
    mocker.patch('myah.cli.dev.server._is_port_listening', return_value=True)
    fake_popen = mocker.patch('myah.cli.dev.server.Popen', side_effect=_FakePopen)

    result = runner.invoke(app, ['dev', 'backend'])

    assert result.exit_code == 0, result.output
    assert 'already running' in result.output.lower()
    assert not fake_popen.called


def test_backend_writes_pidfile(worktree: Path, mocker) -> None:
    """The pidfile at .worktree-logs/backend.pid contains the spawned PID."""
    mocker.patch('myah.cli.dev.server._is_port_listening', return_value=False)
    mocker.patch('myah.cli.dev.server._health_check', return_value=True)
    mocker.patch('myah.cli.dev.server.Popen', side_effect=_FakePopen)

    result = runner.invoke(app, ['dev', 'backend'])

    assert result.exit_code == 0, result.output
    pidfile = worktree / '.worktree-logs' / 'backend.pid'
    assert pidfile.is_file()
    assert pidfile.read_text().strip() == '12345'


def test_backend_redirects_output_to_logfile(worktree: Path, mocker) -> None:
    """Popen stdout points at .worktree-logs/backend.log (file handle)."""
    mocker.patch('myah.cli.dev.server._is_port_listening', return_value=False)
    mocker.patch('myah.cli.dev.server._health_check', return_value=True)
    fake_popen = mocker.patch('myah.cli.dev.server.Popen', side_effect=_FakePopen)

    result = runner.invoke(app, ['dev', 'backend'])

    assert result.exit_code == 0, result.output
    stdout_arg = fake_popen.call_args.kwargs['stdout']
    # Should be a file handle (not None, not subprocess constant)
    assert hasattr(stdout_arg, 'write') or hasattr(stdout_arg, 'fileno')
    assert (worktree / '.worktree-logs' / 'backend.log').is_file()


def test_backend_health_check_timeout_reports_error(worktree: Path, mocker) -> None:
    """If /health doesn't respond, exit 1 with a hint pointing at the log file."""
    mocker.patch('myah.cli.dev.server._is_port_listening', return_value=False)
    mocker.patch('myah.cli.dev.server._health_check', return_value=False)
    mocker.patch('myah.cli.dev.server.Popen', side_effect=_FakePopen)

    result = runner.invoke(app, ['dev', 'backend'])

    assert result.exit_code == 1, result.output
    assert 'backend.log' in result.output or 'log' in result.output.lower()


# ---------------------------------------------------------------------------
# frontend
# ---------------------------------------------------------------------------


def test_frontend_spawns_npm_dev_with_port(worktree: Path, mocker) -> None:
    """Vite invocation: `npm run dev -- --port <FRONTEND_PORT>`."""
    mocker.patch('myah.cli.dev.server._is_port_listening', return_value=False)
    mocker.patch('myah.cli.dev.server._health_check', return_value=True)
    fake_popen = mocker.patch('myah.cli.dev.server.Popen', side_effect=_FakePopen)

    result = runner.invoke(app, ['dev', 'frontend'])

    assert result.exit_code == 0, result.output
    cmd = fake_popen.call_args.args[0]
    assert 'npm' in cmd[0]
    assert '5234' in cmd


def test_frontend_passes_backend_port_to_env(worktree: Path, mocker) -> None:
    """BACKEND_PORT must be in env so vite.config.ts proxies correctly."""
    mocker.patch('myah.cli.dev.server._is_port_listening', return_value=False)
    mocker.patch('myah.cli.dev.server._health_check', return_value=True)
    fake_popen = mocker.patch('myah.cli.dev.server.Popen', side_effect=_FakePopen)

    result = runner.invoke(app, ['dev', 'frontend'])

    assert result.exit_code == 0, result.output
    env = fake_popen.call_args.kwargs['env']
    assert env['BACKEND_PORT'] == '8189'


def test_frontend_forces_development_node_env(worktree: Path, mocker, monkeypatch: pytest.MonkeyPatch) -> None:
    """Parent NODE_ENV=production must not break SvelteKit dev boot."""
    monkeypatch.setenv('NODE_ENV', 'production')
    monkeypatch.setenv('ENV', 'prod')
    mocker.patch('myah.cli.dev.server._is_port_listening', return_value=False)
    mocker.patch('myah.cli.dev.server._health_check', return_value=True)
    fake_popen = mocker.patch('myah.cli.dev.server.Popen', side_effect=_FakePopen)

    result = runner.invoke(app, ['dev', 'frontend'])

    assert result.exit_code == 0, result.output
    env = fake_popen.call_args.kwargs['env']
    assert env['NODE_ENV'] == 'development'
    assert env['ENV'] == 'dev'


def test_frontend_idempotent_when_already_listening(worktree: Path, mocker) -> None:
    """Idempotence mirrors backend."""
    mocker.patch('myah.cli.dev.server._is_port_listening', return_value=True)
    fake_popen = mocker.patch('myah.cli.dev.server.Popen', side_effect=_FakePopen)

    result = runner.invoke(app, ['dev', 'frontend'])

    assert result.exit_code == 0, result.output
    assert 'already running' in result.output.lower()
    assert not fake_popen.called


def test_frontend_writes_pidfile(worktree: Path, mocker) -> None:
    """Frontend pidfile at .worktree-logs/frontend.pid."""
    mocker.patch('myah.cli.dev.server._is_port_listening', return_value=False)
    mocker.patch('myah.cli.dev.server._health_check', return_value=True)
    mocker.patch('myah.cli.dev.server.Popen', side_effect=_FakePopen)

    result = runner.invoke(app, ['dev', 'frontend'])

    assert result.exit_code == 0, result.output
    pidfile = worktree / '.worktree-logs' / 'frontend.pid'
    assert pidfile.is_file()


def test_frontend_health_check_timeout_reports_error(worktree: Path, mocker) -> None:
    """Frontend health-check failure → exit 1."""
    mocker.patch('myah.cli.dev.server._is_port_listening', return_value=False)
    mocker.patch('myah.cli.dev.server._health_check', return_value=False)
    mocker.patch('myah.cli.dev.server.Popen', side_effect=_FakePopen)

    result = runner.invoke(app, ['dev', 'frontend'])

    assert result.exit_code == 1, result.output


def test_frontend_cwd_is_platform_oss_without_hosted_overlay(worktree: Path, mocker) -> None:
    """npm run dev runs from <worktree>/platform-oss when no hosted frontend exists."""
    mocker.patch('myah.cli.dev.server._is_port_listening', return_value=False)
    mocker.patch('myah.cli.dev.server._health_check', return_value=True)
    fake_popen = mocker.patch('myah.cli.dev.server.Popen', side_effect=_FakePopen)

    result = runner.invoke(app, ['dev', 'frontend'])

    assert result.exit_code == 0, result.output
    cwd = fake_popen.call_args.kwargs['cwd']
    assert Path(cwd).resolve() == (worktree / 'platform-oss').resolve()


def test_frontend_hosted_mode_materializes_hosted_overlay(worktree: Path, mocker) -> None:
    """Hosted worktrees run Vite from an OSS+hosted frontend overlay."""
    (worktree / 'platform-oss' / 'src' / 'routes' / '(app)').mkdir(parents=True)
    (worktree / 'platform-oss' / 'src' / 'routes' / '(app)' / '+page.svelte').write_text('<p>OSS</p>')
    (worktree / 'platform-oss' / 'package.json').write_text('{"scripts":{"dev":"vite"}}')
    (worktree / 'platform-oss' / 'node_modules').mkdir()
    (worktree / 'platform-hosted' / 'src' / 'routes' / '(app)' / 'files').mkdir(parents=True)
    (worktree / 'platform-hosted' / 'src' / 'routes' / '(app)' / 'files' / '+page.svelte').write_text(
        '<p>Files</p>'
    )

    mocker.patch('myah.cli.dev.server._is_port_listening', return_value=False)
    mocker.patch('myah.cli.dev.server._health_check', return_value=True)
    fake_popen = mocker.patch('myah.cli.dev.server.Popen', side_effect=_FakePopen)

    result = runner.invoke(app, ['dev', 'frontend'])

    assert result.exit_code == 0, result.output
    cwd = Path(fake_popen.call_args.kwargs['cwd'])
    assert cwd == worktree / '.worktree-logs' / 'hosted-frontend-overlay'
    assert (cwd / 'src' / 'routes' / '(app)' / '+page.svelte').is_symlink()
    assert (cwd / 'src' / 'routes' / '(app)' / 'files' / '+page.svelte').is_symlink()
    assert (cwd / 'node_modules').is_symlink()
    assert (cwd / 'node_modules').resolve() == (worktree / 'platform-oss' / 'node_modules').resolve()
    assert not (cwd / '.env').exists()
    assert not (cwd / '.venv').exists()
    assert not (cwd / 'backend').exists()
    env = fake_popen.call_args.kwargs['env']
    assert env['MYAH_DEV_WORKTREE_ROOT'] == str(worktree.resolve())
    assert env['MYAH_DEV_VITE_FS_ALLOW_EXTRA'].split(os.pathsep) == [
        str((worktree / 'platform-oss' / 'node_modules').resolve()),
        str((worktree / 'platform-oss' / 'src').resolve()),
        str((worktree / 'platform-hosted' / 'src').resolve()),
    ]


# ---------------------------------------------------------------------------
# stop
# ---------------------------------------------------------------------------


def test_stop_reads_pidfile_and_sends_sigterm(worktree: Path, mocker) -> None:
    """A live pidfile triggers SIGTERM to its PID."""
    (worktree / '.worktree-logs').mkdir(exist_ok=True)
    (worktree / '.worktree-logs' / 'backend.pid').write_text('99999\n')

    mock_kill = mocker.patch('myah.cli.dev.server.os.kill')
    mocker.patch('myah.cli.dev.server._get_pid_by_port', return_value=None)
    mocker.patch('myah.cli.dev.server._is_port_listening', return_value=False)
    mocker.patch('myah.cli.dev.server.time.sleep')
    mocker.patch('myah.cli.dev.server.run')

    result = runner.invoke(app, ['dev', 'stop'])

    assert result.exit_code == 0, result.output
    import signal
    # Backend pid (99999) should have been SIGTERMed
    kill_calls = [c for c in mock_kill.call_args_list if c.args == (99999, signal.SIGTERM)]
    assert kill_calls, f'expected SIGTERM to 99999, calls were: {mock_kill.call_args_list}'


def test_stop_kills_orphan_by_lsof_when_no_pidfile(worktree: Path, mocker) -> None:
    """No pidfile but port-listening orphan → kill by lsof'd PID."""
    # No pidfile created
    mock_kill = mocker.patch('myah.cli.dev.server.os.kill')
    # First call: backend port has orphan 77777; second call: frontend none
    mocker.patch(
        'myah.cli.dev.server._get_pid_by_port',
        side_effect=lambda port: 77777 if port == 8189 else None,
    )
    mocker.patch('myah.cli.dev.server._is_port_listening', return_value=False)
    mocker.patch('myah.cli.dev.server.time.sleep')
    mocker.patch('myah.cli.dev.server.run')

    result = runner.invoke(app, ['dev', 'stop'])

    assert result.exit_code == 0, result.output
    import signal
    kill_calls = [c for c in mock_kill.call_args_list if c.args == (77777, signal.SIGTERM)]
    assert kill_calls, f'expected SIGTERM to orphan 77777, calls were: {mock_kill.call_args_list}'


def test_stop_sigkills_after_grace_period(worktree: Path, mocker) -> None:
    """If SIGTERM doesn't take, SIGKILL follows."""
    (worktree / '.worktree-logs').mkdir(exist_ok=True)
    (worktree / '.worktree-logs' / 'backend.pid').write_text('55555\n')

    mock_kill = mocker.patch('myah.cli.dev.server.os.kill')
    # After SIGTERM + sleep, port is still listening → escalation
    mocker.patch('myah.cli.dev.server._get_pid_by_port', return_value=55555)
    mocker.patch('myah.cli.dev.server._is_port_listening', return_value=True)
    mocker.patch('myah.cli.dev.server.time.sleep')
    mocker.patch('myah.cli.dev.server.run')

    result = runner.invoke(app, ['dev', 'stop'])

    assert result.exit_code == 0, result.output
    import signal
    sigkill_calls = [c for c in mock_kill.call_args_list if c.args[1] == signal.SIGKILL]
    assert sigkill_calls, f'expected SIGKILL escalation, calls were: {mock_kill.call_args_list}'


def test_stop_removes_pidfile_after_success(worktree: Path, mocker) -> None:
    """Pidfile is unlinked after a successful stop."""
    (worktree / '.worktree-logs').mkdir(exist_ok=True)
    pidfile = worktree / '.worktree-logs' / 'backend.pid'
    pidfile.write_text('44444\n')

    mocker.patch('myah.cli.dev.server.os.kill')
    mocker.patch('myah.cli.dev.server._get_pid_by_port', return_value=None)
    mocker.patch('myah.cli.dev.server._is_port_listening', return_value=False)
    mocker.patch('myah.cli.dev.server.time.sleep')
    mocker.patch('myah.cli.dev.server.run')

    result = runner.invoke(app, ['dev', 'stop'])

    assert result.exit_code == 0, result.output
    assert not pidfile.exists()


def test_stop_idempotent_when_nothing_running(worktree: Path, mocker) -> None:
    """`stop` with nothing running exits 0, no errors."""
    mocker.patch('myah.cli.dev.server.os.kill')
    mocker.patch('myah.cli.dev.server._get_pid_by_port', return_value=None)
    mocker.patch('myah.cli.dev.server._is_port_listening', return_value=False)
    mocker.patch('myah.cli.dev.server.time.sleep')
    mocker.patch('myah.cli.dev.server.run')

    result = runner.invoke(app, ['dev', 'stop'])

    assert result.exit_code == 0, result.output


# ---------------------------------------------------------------------------
# status
# ---------------------------------------------------------------------------


def test_status_renders_table_with_both_services(worktree: Path, mocker) -> None:
    """Status output mentions both backend and frontend."""
    mocker.patch('myah.cli.dev.server._is_port_listening', return_value=False)
    mocker.patch('myah.cli.dev.server._get_pid_by_port', return_value=None)
    mocker.patch('myah.cli.dev.server._http_get_ok', return_value=False)

    result = runner.invoke(app, ['dev', 'status'])

    assert result.exit_code == 0, result.output
    assert 'backend' in result.output.lower()
    assert 'frontend' in result.output.lower()


def test_status_shows_running_when_port_listening(worktree: Path, mocker) -> None:
    """Listening port → 'running' indicator in output."""
    mocker.patch('myah.cli.dev.server._is_port_listening', return_value=True)
    mocker.patch('myah.cli.dev.server._get_pid_by_port', return_value=11111)
    mocker.patch('myah.cli.dev.server._http_get_ok', return_value=True)

    result = runner.invoke(app, ['dev', 'status'])

    assert result.exit_code == 0, result.output
    assert 'running' in result.output.lower() or 'up' in result.output.lower()


def test_status_shows_down_when_port_not_listening(worktree: Path, mocker) -> None:
    """Down port → explicit 'down' or 'not running'."""
    mocker.patch('myah.cli.dev.server._is_port_listening', return_value=False)
    mocker.patch('myah.cli.dev.server._get_pid_by_port', return_value=None)
    mocker.patch('myah.cli.dev.server._http_get_ok', return_value=False)

    result = runner.invoke(app, ['dev', 'status'])

    assert result.exit_code == 0, result.output
    out_lower = result.output.lower()
    assert 'down' in out_lower or 'not running' in out_lower


def test_status_includes_health_endpoint_check(worktree: Path, mocker) -> None:
    """When backend is up, /health is probed and result rendered."""
    mocker.patch('myah.cli.dev.server._is_port_listening', return_value=True)
    mocker.patch('myah.cli.dev.server._get_pid_by_port', return_value=22222)
    mock_http = mocker.patch('myah.cli.dev.server._http_get_ok', return_value=True)

    result = runner.invoke(app, ['dev', 'status'])

    assert result.exit_code == 0, result.output
    # _http_get_ok was called for /health probe
    assert mock_http.called


def test_status_always_exits_zero_when_services_down(worktree: Path, mocker) -> None:
    """Status is observational; never fails."""
    mocker.patch('myah.cli.dev.server._is_port_listening', return_value=False)
    mocker.patch('myah.cli.dev.server._get_pid_by_port', return_value=None)
    mocker.patch('myah.cli.dev.server._http_get_ok', return_value=False)

    result = runner.invoke(app, ['dev', 'status'])

    assert result.exit_code == 0, result.output


# ---------------------------------------------------------------------------
# both
# ---------------------------------------------------------------------------


def test_both_starts_backend_then_frontend(worktree: Path, mocker) -> None:
    """`both` invokes backend first, then frontend."""
    mocker.patch('myah.cli.dev.server._is_port_listening', return_value=False)
    mocker.patch('myah.cli.dev.server._health_check', return_value=True)
    fake_popen = mocker.patch('myah.cli.dev.server.Popen', side_effect=_FakePopen)

    result = runner.invoke(app, ['dev', 'both'])

    assert result.exit_code == 0, result.output
    # Two Popen calls in order: uvicorn first, npm second.
    assert len(_FakePopen.instances) == 2
    assert 'uvicorn' in _FakePopen.instances[0].cmd[0]
    assert any('npm' in part for part in _FakePopen.instances[1].cmd)


def test_both_aborts_when_backend_fails(worktree: Path, mocker) -> None:
    """If backend's health-check fails, frontend is not started."""
    mocker.patch('myah.cli.dev.server._is_port_listening', return_value=False)
    # First call (backend) returns False; subsequent calls wouldn't matter
    mocker.patch('myah.cli.dev.server._health_check', return_value=False)
    fake_popen = mocker.patch('myah.cli.dev.server.Popen', side_effect=_FakePopen)

    result = runner.invoke(app, ['dev', 'both'])

    assert result.exit_code == 1, result.output
    # Only one Popen call (backend), no npm spawn.
    assert len(_FakePopen.instances) == 1


# ---------------------------------------------------------------------------
# restart
# ---------------------------------------------------------------------------


def test_restart_calls_stop_then_both(worktree: Path, mocker) -> None:
    """`restart` = stop, then both. Verify ordering via spy."""
    call_log: list[str] = []

    def _spy_stop(*a: Any, **kw: Any) -> int:
        call_log.append('stop')
        return 0

    def _spy_both(*a: Any, **kw: Any) -> int:
        call_log.append('both')
        return 0

    mocker.patch('myah.cli.dev.server._do_stop', side_effect=_spy_stop)
    mocker.patch('myah.cli.dev.server._do_both', side_effect=_spy_both)

    result = runner.invoke(app, ['dev', 'restart'])

    assert result.exit_code == 0, result.output
    assert call_log == ['stop', 'both'], f'expected [stop, both], got {call_log}'
