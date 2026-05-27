"""Tests for ``myah agent {up,down,restart}`` + ``myah agent config {show,edit,validate}``.

Slice 5 Task 5.1 of T3-1084 (DevX + OSS CLI).

The lifecycle commands (`up/down/restart`) invoke the OS supervisor
directly (systemctl --user on Linux, launchctl on macOS) against the
Hermes service units installed by Slice 4d's ``service_units``:

    Linux:  hermes-gateway.service, hermes-dashboard.service
    macOS:  dev.myah.hermes-gateway, dev.myah.hermes-dashboard

The plan's spec table said "wrap ``hermes gateway start``" but that
resolves to ``hermes-gateway-<profile>.service`` (upstream Hermes's own
unit-name convention) which does NOT match the units Myah installs.
Wrapping the OS supervisor directly is the correct, minimal delegation.

The config commands (`show/edit/validate`) are pure wrappers around
``hermes config {show,edit,check}`` — the rename ``validate → check`` is
the Myah-level value-add.

Mock target = consumer namespace (``myah.cli.agent.run`` /
``myah.cli.agent.subprocess.run`` / ``myah.cli.agent.detect_hermes_venv``).
Never patch source modules. Mirrors Slices 2-4 patterns.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest
from myah import app
from myah.lib.cli.shell import ShellResult
from typer.testing import CliRunner

runner = CliRunner()


# ── lifecycle: Linux (systemctl --user) ────────────────────────────────


def _ok() -> ShellResult:
    return ShellResult(returncode=0, stdout='', stderr='')


@pytest.fixture
def linux_with_systemd(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pretend we're on Linux with systemctl on PATH."""
    monkeypatch.setattr('myah.cli.agent.sys.platform', 'linux')

    def fake_which(name: str) -> str | None:
        if name == 'systemctl':
            return '/usr/bin/systemctl'
        return None

    monkeypatch.setattr('myah.cli.agent.shutil.which', fake_which)


@pytest.fixture
def macos(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pretend we're on macOS with a fixed UID."""
    monkeypatch.setattr('myah.cli.agent.sys.platform', 'darwin')
    monkeypatch.setattr('myah.cli.agent.os.getuid', lambda: 501, raising=False)


def test_agent_up_invokes_systemctl_on_linux_when_systemd_present(linux_with_systemd, mocker) -> None:
    """`myah agent up` on Linux invokes `systemctl --user start` for both units."""
    run_mock = mocker.patch('myah.cli.agent.run', return_value=_ok())

    result = runner.invoke(app, ['agent', 'up'])

    assert result.exit_code == 0, f'stdout: {result.stdout}\nexc: {result.exception}'
    run_mock.assert_called_once()
    cmd = run_mock.call_args.args[0]
    assert cmd == [
        'systemctl',
        '--user',
        'start',
        'hermes-gateway.service',
        'hermes-dashboard.service',
    ]


def test_agent_down_invokes_systemctl_on_linux(linux_with_systemd, mocker) -> None:
    run_mock = mocker.patch('myah.cli.agent.run', return_value=_ok())

    result = runner.invoke(app, ['agent', 'down'])

    assert result.exit_code == 0, result.stdout
    cmd = run_mock.call_args.args[0]
    assert cmd == [
        'systemctl',
        '--user',
        'stop',
        'hermes-gateway.service',
        'hermes-dashboard.service',
    ]


def test_agent_restart_invokes_systemctl_on_linux(linux_with_systemd, mocker) -> None:
    run_mock = mocker.patch('myah.cli.agent.run', return_value=_ok())

    result = runner.invoke(app, ['agent', 'restart'])

    assert result.exit_code == 0, result.stdout
    cmd = run_mock.call_args.args[0]
    assert cmd == [
        'systemctl',
        '--user',
        'restart',
        'hermes-gateway.service',
        'hermes-dashboard.service',
    ]


# ── lifecycle: macOS (launchctl) ───────────────────────────────────────


def test_agent_up_invokes_launchctl_kickstart_on_macos(macos, mocker) -> None:
    """`myah agent up` on macOS kickstarts both gateway + dashboard services."""
    run_mock = mocker.patch('myah.cli.agent.run', return_value=_ok())

    result = runner.invoke(app, ['agent', 'up'])

    assert result.exit_code == 0, f'stdout: {result.stdout}\nexc: {result.exception}'
    # Two calls — one per service.
    assert run_mock.call_count == 2
    commands = [c.args[0] for c in run_mock.call_args_list]
    assert commands[0] == ['launchctl', 'kickstart', 'gui/501/dev.myah.hermes-gateway']
    assert commands[1] == ['launchctl', 'kickstart', 'gui/501/dev.myah.hermes-dashboard']


def test_agent_down_invokes_launchctl_bootout_on_macos(macos, mocker) -> None:
    run_mock = mocker.patch('myah.cli.agent.run', return_value=_ok())

    result = runner.invoke(app, ['agent', 'down'])

    assert result.exit_code == 0, result.stdout
    assert run_mock.call_count == 2
    commands = [c.args[0] for c in run_mock.call_args_list]
    assert commands[0] == ['launchctl', 'bootout', 'gui/501/dev.myah.hermes-gateway']
    assert commands[1] == ['launchctl', 'bootout', 'gui/501/dev.myah.hermes-dashboard']


def test_agent_restart_invokes_launchctl_kickstart_dash_k_on_macos(macos, mocker) -> None:
    """`launchctl kickstart -k` forces restart of an already-running service."""
    run_mock = mocker.patch('myah.cli.agent.run', return_value=_ok())

    result = runner.invoke(app, ['agent', 'restart'])

    assert result.exit_code == 0, result.stdout
    assert run_mock.call_count == 2
    commands = [c.args[0] for c in run_mock.call_args_list]
    assert commands[0] == ['launchctl', 'kickstart', '-k', 'gui/501/dev.myah.hermes-gateway']
    assert commands[1] == ['launchctl', 'kickstart', '-k', 'gui/501/dev.myah.hermes-dashboard']


# ── lifecycle: unsupported topology ────────────────────────────────────


def test_agent_up_exits_2_when_neither_systemd_nor_macos(monkeypatch: pytest.MonkeyPatch, mocker) -> None:
    """Linux without systemctl: exit 2 with a clear error message."""
    monkeypatch.setattr('myah.cli.agent.sys.platform', 'linux')
    monkeypatch.setattr('myah.cli.agent.shutil.which', lambda name: None)
    run_mock = mocker.patch('myah.cli.agent.run', return_value=_ok())

    result = runner.invoke(app, ['agent', 'up'])

    assert result.exit_code == 2
    # Should NOT have invoked the supervisor.
    run_mock.assert_not_called()
    # Error message should mention the supported topologies.
    output = result.stdout + (str(result.exception) if result.exception else '')
    assert 'systemd' in output.lower() or 'launchd' in output.lower() or 'supervisor' in output.lower()


def test_agent_up_surfaces_failing_returncode_from_systemctl(linux_with_systemd, mocker) -> None:
    """When systemctl returns non-zero, the CLI must propagate non-zero exit."""
    mocker.patch(
        'myah.cli.agent.run',
        return_value=ShellResult(returncode=1, stdout='', stderr='unit not found'),
    )

    result = runner.invoke(app, ['agent', 'up'])

    assert result.exit_code != 0


def test_agent_up_dry_run_mocks_at_consumer_namespace(linux_with_systemd, mocker) -> None:
    """Sanity check: patching `myah.cli.agent.run` actually intercepts the call.

    If a future refactor changes the import to `from ... import run as _run`
    or `import shell` + `shell.run`, this test catches the regression.
    """
    run_mock = mocker.patch('myah.cli.agent.run', return_value=_ok())

    result = runner.invoke(app, ['agent', 'up'])

    assert result.exit_code == 0, result.stdout
    assert run_mock.called, 'patching myah.cli.agent.run did NOT intercept the lifecycle call'


# ── config: show / edit / validate ─────────────────────────────────────


@pytest.fixture
def fake_hermes_venv(tmp_path: Path, mocker) -> Path:
    """A fake hermes venv with bin/hermes; detect_hermes_venv returns it."""
    venv = tmp_path / 'fake-hermes-venv'
    (venv / 'bin').mkdir(parents=True)
    hermes_bin = venv / 'bin' / 'hermes'
    hermes_bin.write_text('#!/bin/sh\necho fake-hermes\n', encoding='utf-8')
    hermes_bin.chmod(0o755)
    mocker.patch('myah.lib.cli.hermes_install.detect_hermes_venv', return_value=venv)
    return venv


def test_config_show_invokes_hermes_binary_via_detect_hermes_venv(fake_hermes_venv: Path, mocker) -> None:
    """`myah agent config show` invokes `<hermes-venv>/bin/hermes config show`."""
    run_mock = mocker.patch(
        'myah.cli.agent.run',
        return_value=ShellResult(returncode=0, stdout='cfg-yaml', stderr=''),
    )

    result = runner.invoke(app, ['agent', 'config', 'show'])

    assert result.exit_code == 0, f'stdout: {result.stdout}\nexc: {result.exception}'
    cmd = run_mock.call_args.args[0]
    assert cmd == [str(fake_hermes_venv / 'bin' / 'hermes'), 'config', 'show']
    # stdout from hermes should reach the user
    assert 'cfg-yaml' in result.stdout


def test_config_validate_maps_to_hermes_config_check(fake_hermes_venv: Path, mocker) -> None:
    """Verb rename: `myah agent config validate` ↔ `hermes config check`."""
    run_mock = mocker.patch(
        'myah.cli.agent.run',
        return_value=ShellResult(returncode=0, stdout='ok', stderr=''),
    )

    result = runner.invoke(app, ['agent', 'config', 'validate'])

    assert result.exit_code == 0, result.stdout
    cmd = run_mock.call_args.args[0]
    assert cmd[-2:] == ['config', 'check'], f'validate must map to upstream `hermes config check`, got {cmd!r}'


def test_config_edit_uses_subprocess_run_for_stdio_passthrough(fake_hermes_venv: Path, mocker) -> None:
    """`myah agent config edit` must use subprocess.run (not shell.run),
    so the interactive editor inherits stdio. This mirrors Slice 3's
    cli/dev/hermes.py:config_edit invariant.
    """
    completed = MagicMock(returncode=0)
    sp_run_mock = mocker.patch('myah.cli.agent.subprocess.run', return_value=completed)
    # shell.run should NOT be called for `edit` — guard against accidental misuse.
    shell_run_mock = mocker.patch('myah.cli.agent.run')

    result = runner.invoke(app, ['agent', 'config', 'edit'])

    assert result.exit_code == 0, result.stdout
    sp_run_mock.assert_called_once()
    shell_run_mock.assert_not_called()
    cmd = sp_run_mock.call_args.args[0]
    assert cmd == [str(fake_hermes_venv / 'bin' / 'hermes'), 'config', 'edit']


def test_config_show_when_no_hermes_venv_exits_with_clear_error(monkeypatch: pytest.MonkeyPatch, mocker) -> None:
    """When detect_hermes_venv raises, surface a clear error and exit 2."""
    mocker.patch(
        'myah.lib.cli.hermes_install.detect_hermes_venv',
        side_effect=RuntimeError('Could not locate hermes-agent venv'),
    )
    run_mock = mocker.patch('myah.cli.agent.run')

    result = runner.invoke(app, ['agent', 'config', 'show'])

    assert result.exit_code == 2
    run_mock.assert_not_called()
    output = result.stdout + (str(result.exception) if result.exception else '')
    assert 'hermes' in output.lower()


def test_config_show_does_not_pass_env_kwarg(fake_hermes_venv: Path, monkeypatch: pytest.MonkeyPatch, mocker) -> None:
    """Validate the design promise: `agent config show` inherits os.environ
    rather than overriding it.

    The system-scoped `agent config *` surface deliberately does NOT
    override HERMES_HOME (unlike Slice 3's worktree-scoped `dev hermes
    config *`, which DOES override via env-merge). Passing `env=` here
    would shadow whatever HERMES_HOME the user has set in their shell.
    Subprocess inheritance is the correct mechanism — assert that no
    explicit env= is supplied to the shell wrapper.
    """
    monkeypatch.setenv('HERMES_HOME', '/custom/hermes-home')
    run_mock = mocker.patch(
        'myah.cli.agent.run',
        return_value=ShellResult(returncode=0, stdout='', stderr=''),
    )

    result = runner.invoke(app, ['agent', 'config', 'show'])

    assert result.exit_code == 0, result.stdout
    assert run_mock.call_args.kwargs.get('env') is None, (
        'agent config show must inherit os.environ; passing env= would shadow '
        'user-set HERMES_HOME (this is the system-scoped surface, not '
        "Slice 3's worktree-scoped `dev hermes config`)"
    )


def test_config_show_surfaces_non_zero_exit(fake_hermes_venv: Path, mocker) -> None:
    """A non-zero `hermes config show` should propagate to the CLI exit code."""
    mocker.patch(
        'myah.cli.agent.run',
        return_value=ShellResult(returncode=5, stdout='', stderr='bad config'),
    )

    result = runner.invoke(app, ['agent', 'config', 'show'])

    assert result.exit_code == 5


# ── cold-start sentinel ────────────────────────────────────────────────


def test_module_does_not_import_heavy_libs_at_top_level() -> None:
    """Mirrors the 4a/4c/4d pattern — Rich, Typer (other than the
    subgroup definition itself), socket, time must stay out of the
    module top so `myah --help` cold-start stays under 200ms.
    """
    from myah.cli import agent as mod

    source = Path(mod.__file__).read_text(encoding='utf-8')
    # Walk only the head (before the first `def `) — everything below is
    # function-body territory where lazy imports live.
    head = source.split('\ndef ', 1)[0]

    offenders = (
        'import rich',
        'from rich',
        'import time',
        'import socket',
        'import yaml',
        'from yaml',
    )
    for offender in offenders:
        assert offender not in head, f'cli/agent.py top-level imports {offender!r}'


# ── help text ──────────────────────────────────────────────────────────


def test_agent_help_lists_subcommands() -> None:
    result = runner.invoke(app, ['agent', '--help'])
    assert result.exit_code == 0
    assert 'up' in result.stdout
    assert 'down' in result.stdout
    assert 'restart' in result.stdout
    assert 'config' in result.stdout


def test_agent_config_help_lists_subcommands() -> None:
    result = runner.invoke(app, ['agent', 'config', '--help'])
    assert result.exit_code == 0
    assert 'show' in result.stdout
    assert 'edit' in result.stdout
    assert 'validate' in result.stdout


def test_top_level_help_lists_agent_group() -> None:
    """`myah --help` must surface the `agent` subgroup for OSS users."""
    result = runner.invoke(app, ['--help'])
    assert result.exit_code == 0
    assert 'agent' in result.stdout
