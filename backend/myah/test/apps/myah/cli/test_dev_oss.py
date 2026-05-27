"""Tests for `myah dev oss {up,down,restart,status}` (Slice 3 Task 3.4).

Worktree-scoped lifecycle for hermes gateway + dashboard. Mirrors the
test shape used for `myah dev backend/frontend` in `test_dev_server.py`,
adapted for the two-service shape (gateway + dashboard).

Mock targets follow the consumer-namespace rule: patch
`myah.cli.dev.oss.X`, not where `X` was originally defined.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from myah import app


runner = CliRunner()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_worktree(
    tmp_path: Path,
    *,
    hermes_home: str | None = None,
    gateway_port: str = '8643',
    dashboard_port: str = '9119',
) -> Path:
    """Materialize a minimal worktree shape rooted at tmp_path."""
    (tmp_path / 'platform-oss').mkdir(exist_ok=True)
    (tmp_path / 'platform-oss' / '.env').write_text(
        'MYAH_AGENT_BEARER_TOKEN=test-bearer-token\n'
    )
    env_lines = [
        'export BACKEND_PORT=8189\n',
        'export FRONTEND_PORT=5234\n',
        'export WORKTREE_BRANCH=test/branch\n',
        f'export MYAH_GATEWAY_PORT={gateway_port}\n',
        f'export MYAH_HERMES_WEB_PORT={dashboard_port}\n',
    ]
    if hermes_home is not None:
        env_lines.append(f'export HERMES_HOME={hermes_home}\n')
    (tmp_path / '.worktree-env').write_text(''.join(env_lines))
    # Pre-create .venv/bin/hermes as a sentinel
    (tmp_path / '.venv' / 'bin').mkdir(parents=True, exist_ok=True)
    (tmp_path / '.venv' / 'bin' / 'hermes').write_text('#!/bin/sh\n')
    return tmp_path


class _FakePopen:
    """Minimal stand-in for subprocess.Popen that records kwargs."""

    instances: list['_FakePopen'] = []

    def __init__(
        self,
        cmd: list[str],
        *,
        env: dict[str, str] | None = None,
        cwd: Any = None,
        stdout: Any = None,
        stderr: Any = None,
        start_new_session: bool = False,
        **kwargs: Any,
    ) -> None:
        self.cmd = cmd
        self.env = env
        self.cwd = cwd
        self.stdout = stdout
        self.stderr = stderr
        self.start_new_session = start_new_session
        self.kwargs = kwargs
        self.pid = 31337
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


@pytest.fixture
def worktree(tmp_path: Path, mocker) -> Path:
    """Pre-built worktree shape with the resolver pointed at it."""
    wt = _make_worktree(tmp_path)
    mocker.patch('myah.cli.dev.oss._get_worktree_path', return_value=wt)
    return wt


# ---------------------------------------------------------------------------
# `oss up` — spawning, idempotence, env, paths
# ---------------------------------------------------------------------------


def test_oss_up_spawns_gateway_at_absolute_venv_path(worktree: Path, mocker) -> None:
    """Per Investigation C: must invoke <worktree>/.venv/bin/hermes (absolute), not PATH."""
    mocker.patch('myah.cli.dev.oss._is_port_listening', return_value=False)
    mocker.patch('myah.cli.dev.oss._is_process_dead', return_value=False)
    mocker.patch('myah.cli.dev.oss.time.sleep')
    fake_popen = mocker.patch('myah.cli.dev.oss.Popen', side_effect=_FakePopen)

    result = runner.invoke(app, ['dev', 'oss', 'up'])

    assert result.exit_code == 0, result.output
    expected_hermes = str(worktree / '.venv' / 'bin' / 'hermes')
    # Gateway is the first spawn; verify cmd[0] is the absolute path.
    assert _FakePopen.instances, 'expected at least one Popen call'
    gw = _FakePopen.instances[0]
    assert gw.cmd[0] == expected_hermes, f'expected {expected_hermes}, got {gw.cmd[0]}'
    assert 'gateway' in gw.cmd
    assert 'run' in gw.cmd


def test_oss_up_spawns_dashboard_with_insecure_host_flags(worktree: Path, mocker) -> None:
    """Dashboard must include --no-open --insecure --host 0.0.0.0 (per dev-oss.sh:16-20)."""
    mocker.patch('myah.cli.dev.oss._is_port_listening', return_value=False)
    mocker.patch('myah.cli.dev.oss._is_process_dead', return_value=False)
    mocker.patch('myah.cli.dev.oss.time.sleep')
    mocker.patch('myah.cli.dev.oss.Popen', side_effect=_FakePopen)

    result = runner.invoke(app, ['dev', 'oss', 'up'])

    assert result.exit_code == 0, result.output
    # Find the dashboard call (cmd contains 'dashboard').
    dashboard_calls = [i for i in _FakePopen.instances if 'dashboard' in i.cmd]
    assert dashboard_calls, f'expected dashboard spawn, got cmds: {[i.cmd for i in _FakePopen.instances]}'
    dash_cmd = dashboard_calls[0].cmd
    assert '--insecure' in dash_cmd
    assert '--host' in dash_cmd
    assert '0.0.0.0' in dash_cmd
    assert '--no-open' in dash_cmd


def test_oss_up_passes_hermes_home_in_env_merge(worktree: Path, mocker) -> None:
    """HERMES_HOME defaults to <worktree>/.hermes; PATH must survive env-merge."""
    mocker.patch('myah.cli.dev.oss._is_port_listening', return_value=False)
    mocker.patch('myah.cli.dev.oss._is_process_dead', return_value=False)
    mocker.patch('myah.cli.dev.oss.time.sleep')
    fake_popen = mocker.patch('myah.cli.dev.oss.Popen', side_effect=_FakePopen)

    result = runner.invoke(app, ['dev', 'oss', 'up'])

    assert result.exit_code == 0, result.output
    env = fake_popen.call_args_list[0].kwargs['env']
    assert env['HERMES_HOME'] == str(worktree / '.hermes')
    # PATH must have survived env-merge (would be stripped if env={'HERMES_HOME':...} alone).
    assert 'PATH' in env


def test_oss_up_respects_hermes_home_from_link_main(tmp_path: Path, mocker) -> None:
    """When `.worktree-env` sets HERMES_HOME=~/.hermes, expand it and pass through."""
    wt = _make_worktree(tmp_path, hermes_home='~/.hermes')
    mocker.patch('myah.cli.dev.oss._get_worktree_path', return_value=wt)
    mocker.patch('myah.cli.dev.oss._is_port_listening', return_value=False)
    mocker.patch('myah.cli.dev.oss._is_process_dead', return_value=False)
    mocker.patch('myah.cli.dev.oss.time.sleep')
    fake_popen = mocker.patch('myah.cli.dev.oss.Popen', side_effect=_FakePopen)

    result = runner.invoke(app, ['dev', 'oss', 'up'])

    assert result.exit_code == 0, result.output
    env = fake_popen.call_args_list[0].kwargs['env']
    expected_home = str(Path.home() / '.hermes')
    assert env['HERMES_HOME'] == expected_home, (
        f'expected expanded HERMES_HOME {expected_home}, got {env["HERMES_HOME"]}'
    )


def test_oss_up_idempotent_when_gateway_already_listening(worktree: Path, mocker) -> None:
    """If gateway port is listening, skip its Popen but still try dashboard."""
    # Gateway port (8643) listening; dashboard port (9119) not.
    def _listening(port: int) -> bool:
        return port == 8643
    mocker.patch('myah.cli.dev.oss._is_port_listening', side_effect=_listening)
    mocker.patch('myah.cli.dev.oss._is_process_dead', return_value=False)
    mocker.patch('myah.cli.dev.oss.time.sleep')
    mocker.patch('myah.cli.dev.oss.Popen', side_effect=_FakePopen)

    result = runner.invoke(app, ['dev', 'oss', 'up'])

    assert result.exit_code == 0, result.output
    # Only dashboard should have been spawned.
    assert len(_FakePopen.instances) == 1
    assert 'dashboard' in _FakePopen.instances[0].cmd
    assert 'already running' in result.output.lower()


def test_oss_up_skips_dashboard_when_already_listening_but_still_starts_gateway(
    worktree: Path, mocker,
) -> None:
    """Symmetric idempotence: dashboard up, gateway down → only gateway spawns."""
    def _listening(port: int) -> bool:
        return port == 9119
    mocker.patch('myah.cli.dev.oss._is_port_listening', side_effect=_listening)
    mocker.patch('myah.cli.dev.oss._is_process_dead', return_value=False)
    mocker.patch('myah.cli.dev.oss.time.sleep')
    mocker.patch('myah.cli.dev.oss.Popen', side_effect=_FakePopen)

    result = runner.invoke(app, ['dev', 'oss', 'up'])

    assert result.exit_code == 0, result.output
    # Only gateway should have been spawned.
    assert len(_FakePopen.instances) == 1
    assert 'gateway' in _FakePopen.instances[0].cmd


def test_oss_up_writes_pidfiles_for_both(worktree: Path, mocker) -> None:
    """Both .worktree-logs/gateway.pid and dashboard.pid materialized after success."""
    mocker.patch('myah.cli.dev.oss._is_port_listening', return_value=False)
    mocker.patch('myah.cli.dev.oss._is_process_dead', return_value=False)
    mocker.patch('myah.cli.dev.oss.time.sleep')
    mocker.patch('myah.cli.dev.oss.Popen', side_effect=_FakePopen)

    result = runner.invoke(app, ['dev', 'oss', 'up'])

    assert result.exit_code == 0, result.output
    gateway_pid = worktree / '.worktree-logs' / 'gateway.pid'
    dashboard_pid = worktree / '.worktree-logs' / 'dashboard.pid'
    assert gateway_pid.is_file(), 'gateway.pid not written'
    assert dashboard_pid.is_file(), 'dashboard.pid not written'
    assert gateway_pid.read_text().strip() == '31337'
    assert dashboard_pid.read_text().strip() == '31337'


def test_oss_up_aborts_when_venv_hermes_missing(tmp_path: Path, mocker) -> None:
    """Missing <worktree>/.venv/bin/hermes → exit 2, no Popen."""
    wt = _make_worktree(tmp_path)
    # Remove the sentinel hermes binary.
    (wt / '.venv' / 'bin' / 'hermes').unlink()
    mocker.patch('myah.cli.dev.oss._get_worktree_path', return_value=wt)
    mocker.patch('myah.cli.dev.oss._is_port_listening', return_value=False)
    fake_popen = mocker.patch('myah.cli.dev.oss.Popen', side_effect=_FakePopen)

    result = runner.invoke(app, ['dev', 'oss', 'up'])

    assert result.exit_code == 2, result.output
    assert not fake_popen.called
    assert 'hermes' in result.output.lower()


def test_oss_up_outside_worktree_exits_code_2(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Outside any worktree → exit 2."""
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(app, ['dev', 'oss', 'up'])

    assert result.exit_code == 2, result.output


def test_oss_up_logs_to_worktree_log_files(worktree: Path, mocker) -> None:
    """Popen stdout/stderr point at gateway.log and dashboard.log."""
    mocker.patch('myah.cli.dev.oss._is_port_listening', return_value=False)
    mocker.patch('myah.cli.dev.oss._is_process_dead', return_value=False)
    mocker.patch('myah.cli.dev.oss.time.sleep')
    mocker.patch('myah.cli.dev.oss.Popen', side_effect=_FakePopen)

    result = runner.invoke(app, ['dev', 'oss', 'up'])

    assert result.exit_code == 0, result.output
    assert (worktree / '.worktree-logs' / 'gateway.log').is_file()
    assert (worktree / '.worktree-logs' / 'dashboard.log').is_file()


def test_oss_up_reports_when_gateway_exits_immediately(worktree: Path, mocker) -> None:
    """Process-dead immediately after spawn → exit 1, with log tail in output."""
    mocker.patch('myah.cli.dev.oss._is_port_listening', return_value=False)
    # Process is dead immediately (synchronous exit).
    mocker.patch('myah.cli.dev.oss._is_process_dead', return_value=True)
    mocker.patch('myah.cli.dev.oss.time.sleep')
    mocker.patch('myah.cli.dev.oss.Popen', side_effect=_FakePopen)

    result = runner.invoke(app, ['dev', 'oss', 'up'])

    assert result.exit_code == 1, result.output
    # Pidfile should be cleaned up.
    assert not (worktree / '.worktree-logs' / 'gateway.pid').is_file()


# ---------------------------------------------------------------------------
# `oss down`
# ---------------------------------------------------------------------------


def test_oss_down_sigterms_pid_from_pidfile(worktree: Path, mocker) -> None:
    """A live pidfile triggers SIGTERM to its PID."""
    (worktree / '.worktree-logs').mkdir(exist_ok=True)
    (worktree / '.worktree-logs' / 'gateway.pid').write_text('77777\n')

    mock_kill = mocker.patch('myah.cli.dev.oss.os.kill')
    mocker.patch('myah.cli.dev.oss._is_port_listening', return_value=False)
    mocker.patch('myah.cli.dev.oss._get_pid_by_port', return_value=None)
    mocker.patch('myah.cli.dev.oss.time.sleep')
    mocker.patch('myah.cli.dev.oss.run')

    result = runner.invoke(app, ['dev', 'oss', 'down'])

    assert result.exit_code == 0, result.output
    import signal
    kill_calls = [c for c in mock_kill.call_args_list if c.args == (77777, signal.SIGTERM)]
    assert kill_calls, f'expected SIGTERM to 77777, calls were: {mock_kill.call_args_list}'


def test_oss_down_tolerates_missing_pidfile(worktree: Path, mocker) -> None:
    """No pidfile → no-op, exit 0."""
    mocker.patch('myah.cli.dev.oss.os.kill')
    mocker.patch('myah.cli.dev.oss._is_port_listening', return_value=False)
    mocker.patch('myah.cli.dev.oss._get_pid_by_port', return_value=None)
    mocker.patch('myah.cli.dev.oss.time.sleep')
    mocker.patch('myah.cli.dev.oss.run')

    result = runner.invoke(app, ['dev', 'oss', 'down'])

    assert result.exit_code == 0, result.output


def test_oss_down_force_kills_when_still_listening_after_grace(worktree: Path, mocker) -> None:
    """If port still listening after SIGTERM, escalate to SIGKILL."""
    (worktree / '.worktree-logs').mkdir(exist_ok=True)
    (worktree / '.worktree-logs' / 'gateway.pid').write_text('55555\n')

    mock_kill = mocker.patch('myah.cli.dev.oss.os.kill')
    # After SIGTERM + sleep, port is still listening → escalation
    mocker.patch('myah.cli.dev.oss._get_pid_by_port', return_value=55555)
    mocker.patch('myah.cli.dev.oss._is_port_listening', return_value=True)
    mocker.patch('myah.cli.dev.oss.time.sleep')
    mocker.patch('myah.cli.dev.oss.run')

    result = runner.invoke(app, ['dev', 'oss', 'down'])

    assert result.exit_code == 0, result.output
    import signal
    sigkill_calls = [c for c in mock_kill.call_args_list if c.args[1] == signal.SIGKILL]
    assert sigkill_calls, f'expected SIGKILL escalation, calls were: {mock_kill.call_args_list}'


def test_oss_down_removes_pidfiles_after_success(worktree: Path, mocker) -> None:
    """Both pidfiles are unlinked after a successful down."""
    (worktree / '.worktree-logs').mkdir(exist_ok=True)
    gw_pid = worktree / '.worktree-logs' / 'gateway.pid'
    dash_pid = worktree / '.worktree-logs' / 'dashboard.pid'
    gw_pid.write_text('11111\n')
    dash_pid.write_text('22222\n')

    mocker.patch('myah.cli.dev.oss.os.kill')
    mocker.patch('myah.cli.dev.oss._get_pid_by_port', return_value=None)
    mocker.patch('myah.cli.dev.oss._is_port_listening', return_value=False)
    mocker.patch('myah.cli.dev.oss.time.sleep')
    mocker.patch('myah.cli.dev.oss.run')

    result = runner.invoke(app, ['dev', 'oss', 'down'])

    assert result.exit_code == 0, result.output
    assert not gw_pid.exists()
    assert not dash_pid.exists()


# ---------------------------------------------------------------------------
# `oss status`
# ---------------------------------------------------------------------------


def test_oss_status_renders_table_with_both_services(worktree: Path, mocker) -> None:
    """Status output mentions both gateway and dashboard."""
    mocker.patch('myah.cli.dev.oss._is_port_listening', return_value=False)
    mocker.patch('myah.cli.dev.oss._get_pid_by_port', return_value=None)
    mocker.patch('myah.cli.dev.oss._http_get_ok', return_value=False)

    result = runner.invoke(app, ['dev', 'oss', 'status'])

    assert result.exit_code == 0, result.output
    assert 'gateway' in result.output.lower()
    assert 'dashboard' in result.output.lower()


def test_oss_status_shows_running_when_port_listening(worktree: Path, mocker) -> None:
    """Listening port → 'running' indicator."""
    mocker.patch('myah.cli.dev.oss._is_port_listening', return_value=True)
    mocker.patch('myah.cli.dev.oss._get_pid_by_port', return_value=42424)
    mocker.patch('myah.cli.dev.oss._http_get_ok', return_value=True)

    result = runner.invoke(app, ['dev', 'oss', 'status'])

    assert result.exit_code == 0, result.output
    assert 'running' in result.output.lower() or 'up' in result.output.lower()


def test_oss_status_shows_down_when_port_not_listening(worktree: Path, mocker) -> None:
    """Down port → explicit 'down' indicator."""
    mocker.patch('myah.cli.dev.oss._is_port_listening', return_value=False)
    mocker.patch('myah.cli.dev.oss._get_pid_by_port', return_value=None)
    mocker.patch('myah.cli.dev.oss._http_get_ok', return_value=False)

    result = runner.invoke(app, ['dev', 'oss', 'status'])

    assert result.exit_code == 0, result.output
    out_lower = result.output.lower()
    assert 'down' in out_lower or 'not running' in out_lower


# ---------------------------------------------------------------------------
# `oss restart`
# ---------------------------------------------------------------------------


def test_oss_restart_calls_down_then_up(worktree: Path, mocker) -> None:
    """`restart` = down, then up. Verify ordering via spy."""
    call_log: list[str] = []

    def _spy_down(*a: Any, **kw: Any) -> int:
        call_log.append('down')
        return 0

    def _spy_up(*a: Any, **kw: Any) -> int:
        call_log.append('up')
        return 0

    mocker.patch('myah.cli.dev.oss._do_down', side_effect=_spy_down)
    mocker.patch('myah.cli.dev.oss._do_up', side_effect=_spy_up)

    result = runner.invoke(app, ['dev', 'oss', 'restart'])

    assert result.exit_code == 0, result.output
    assert call_log == ['down', 'up'], f'expected [down, up], got {call_log}'
