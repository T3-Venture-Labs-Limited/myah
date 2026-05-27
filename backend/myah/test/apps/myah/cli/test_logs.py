"""Tests for ``myah logs [LOG_NAME] [...flags]``.

Slice 5 Task 5.4 of T3-1084 (DevX + OSS CLI).

Thin wrapper of `hermes logs` with one special component name:
``platform`` resolves to ``docker compose -f <root>/docker-compose.yml
logs platform``. All other names (or absence) forward to the user's
system Hermes binary.

Mock target = consumer namespace (``myah.cli.logs.subprocess.run``,
``myah.cli.logs.resolve_hermes_binary_or_exit``,
``myah.cli.logs.find_repo_root``). Same discipline as Slices 2-4.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from myah import app
from typer.testing import CliRunner

runner = CliRunner()


# ── fixtures ───────────────────────────────────────────────────────────


@pytest.fixture
def fake_repo(mocker, tmp_path: Path) -> Path:
    """Pretend we're inside a Myah clone."""
    mocker.patch('myah.cli.logs.find_repo_root', return_value=tmp_path)
    return tmp_path


@pytest.fixture
def fake_hermes_bin(mocker, tmp_path: Path) -> Path:
    """Pretend the user has a system Hermes binary."""
    bin_path = tmp_path / 'hermes-venv' / 'bin' / 'hermes'
    mocker.patch(
        'myah.cli.logs.resolve_hermes_binary_or_exit', return_value=bin_path
    )
    return bin_path


def _ok() -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(args=[], returncode=0)


# ── platform routing ───────────────────────────────────────────────────


def test_logs_platform_invokes_docker_compose_logs(fake_repo: Path, mocker) -> None:
    """`myah logs platform` → `docker compose -f <root>/docker-compose.yml logs platform`."""
    run_mock = mocker.patch('myah.cli.logs.subprocess.run', return_value=_ok())

    result = runner.invoke(app, ['logs', 'platform'])

    assert result.exit_code == 0, f'stdout: {result.stdout}\nexc: {result.exception}'
    run_mock.assert_called_once()
    cmd = run_mock.call_args.args[0]
    assert cmd == [
        'docker',
        'compose',
        '-f',
        str(fake_repo / 'docker-compose.yml'),
        'logs',
        'platform',
    ]


def test_logs_platform_with_lines_adds_tail_flag(fake_repo: Path, mocker) -> None:
    """`myah logs platform -n 100` → adds `--tail 100` to the docker compose args."""
    run_mock = mocker.patch('myah.cli.logs.subprocess.run', return_value=_ok())

    result = runner.invoke(app, ['logs', 'platform', '-n', '100'])

    assert result.exit_code == 0
    cmd = run_mock.call_args.args[0]
    assert '--tail' in cmd
    assert '100' in cmd
    # And the tail value immediately follows the flag.
    assert cmd[cmd.index('--tail') + 1] == '100'


def test_logs_platform_with_follow_adds_follow_flag(fake_repo: Path, mocker) -> None:
    """`myah logs platform -f` → adds `--follow` to the docker compose args."""
    run_mock = mocker.patch('myah.cli.logs.subprocess.run', return_value=_ok())

    result = runner.invoke(app, ['logs', 'platform', '-f'])

    assert result.exit_code == 0
    cmd = run_mock.call_args.args[0]
    assert '--follow' in cmd


def test_logs_platform_exits_2_when_outside_clone(mocker) -> None:
    """`logs platform` outside a Myah clone → exit 2."""
    mocker.patch(
        'myah.cli.logs.find_repo_root',
        side_effect=RuntimeError('Could not locate repo root.'),
    )
    run_mock = mocker.patch('myah.cli.logs.subprocess.run')

    result = runner.invoke(app, ['logs', 'platform'])

    assert result.exit_code == 2, f'wanted 2, got {result.exit_code}; stdout: {result.stdout}'
    run_mock.assert_not_called()
    assert 'Not inside a Myah clone' in result.stdout


def test_logs_platform_rejects_hermes_specific_flags(fake_repo: Path, mocker) -> None:
    """Hermes-only flags (`--level`, `--session`, `--component`, `--since`) error out."""
    run_mock = mocker.patch('myah.cli.logs.subprocess.run')

    result = runner.invoke(app, ['logs', 'platform', '--level', 'WARNING'])

    assert result.exit_code != 0
    run_mock.assert_not_called()
    assert '--level' in result.stdout or 'not supported' in result.stdout.lower()


# ── hermes routing ─────────────────────────────────────────────────────


def test_logs_no_args_forwards_to_hermes(fake_hermes_bin: Path, mocker) -> None:
    """`myah logs` → `<hermes-bin> logs`."""
    run_mock = mocker.patch('myah.cli.logs.subprocess.run', return_value=_ok())

    result = runner.invoke(app, ['logs'])

    assert result.exit_code == 0, f'stdout: {result.stdout}\nexc: {result.exception}'
    cmd = run_mock.call_args.args[0]
    assert cmd == [str(fake_hermes_bin), 'logs']


def test_logs_with_log_name_forwards_to_hermes(fake_hermes_bin: Path, mocker) -> None:
    """`myah logs agent` → `<hermes-bin> logs agent`."""
    run_mock = mocker.patch('myah.cli.logs.subprocess.run', return_value=_ok())

    result = runner.invoke(app, ['logs', 'agent'])

    assert result.exit_code == 0
    cmd = run_mock.call_args.args[0]
    assert cmd == [str(fake_hermes_bin), 'logs', 'agent']


def test_logs_with_lines_and_follow_forwards_to_hermes(fake_hermes_bin: Path, mocker) -> None:
    """`myah logs gateway -n 100 -f` → forwards lines + follow as hermes flags."""
    run_mock = mocker.patch('myah.cli.logs.subprocess.run', return_value=_ok())

    result = runner.invoke(app, ['logs', 'gateway', '-n', '100', '-f'])

    assert result.exit_code == 0
    cmd = run_mock.call_args.args[0]
    assert cmd[0] == str(fake_hermes_bin)
    assert 'logs' in cmd
    assert 'gateway' in cmd
    # Lines + follow surface on the hermes argv too.
    assert '-n' in cmd or '--tail' in cmd
    assert '-f' in cmd or '--follow' in cmd


def test_logs_with_component_flag_forwards_to_hermes(fake_hermes_bin: Path, mocker) -> None:
    """`myah logs --component tools` → forwards --component to hermes."""
    run_mock = mocker.patch('myah.cli.logs.subprocess.run', return_value=_ok())

    result = runner.invoke(app, ['logs', '--component', 'tools'])

    assert result.exit_code == 0
    cmd = run_mock.call_args.args[0]
    assert '--component' in cmd
    assert 'tools' in cmd


def test_logs_with_level_flag_forwards_to_hermes(fake_hermes_bin: Path, mocker) -> None:
    """`myah logs --level WARNING` → forwards to hermes."""
    run_mock = mocker.patch('myah.cli.logs.subprocess.run', return_value=_ok())

    result = runner.invoke(app, ['logs', '--level', 'WARNING'])

    assert result.exit_code == 0
    cmd = run_mock.call_args.args[0]
    assert '--level' in cmd
    assert 'WARNING' in cmd


def test_logs_with_since_flag_forwards_to_hermes(fake_hermes_bin: Path, mocker) -> None:
    """`myah logs --since 1h` → forwards to hermes."""
    run_mock = mocker.patch('myah.cli.logs.subprocess.run', return_value=_ok())

    result = runner.invoke(app, ['logs', '--since', '1h'])

    assert result.exit_code == 0
    cmd = run_mock.call_args.args[0]
    assert '--since' in cmd
    assert '1h' in cmd


def test_logs_exits_2_when_hermes_venv_missing(mocker) -> None:
    """No Hermes venv → exit 2 from `resolve_hermes_binary_or_exit`."""
    import typer as _typer

    mocker.patch(
        'myah.cli.logs.resolve_hermes_binary_or_exit',
        side_effect=_typer.Exit(code=2),
    )
    run_mock = mocker.patch('myah.cli.logs.subprocess.run')

    result = runner.invoke(app, ['logs', 'agent'])

    assert result.exit_code == 2
    run_mock.assert_not_called()


# ── cross-cutting ──────────────────────────────────────────────────────


def test_logs_propagates_subprocess_exit_code(fake_hermes_bin: Path, mocker) -> None:
    """A non-zero subprocess returncode propagates verbatim to the CLI exit."""
    mocker.patch(
        'myah.cli.logs.subprocess.run',
        return_value=subprocess.CompletedProcess(args=[], returncode=125),
    )

    result = runner.invoke(app, ['logs', 'agent'])

    assert result.exit_code == 125


def test_logs_platform_propagates_subprocess_exit_code(fake_repo: Path, mocker) -> None:
    """Same propagation behavior for the docker-compose path."""
    mocker.patch(
        'myah.cli.logs.subprocess.run',
        return_value=subprocess.CompletedProcess(args=[], returncode=7),
    )

    result = runner.invoke(app, ['logs', 'platform'])

    assert result.exit_code == 7


def test_logs_platform_handles_docker_not_in_path(fake_repo: Path, mocker) -> None:
    """FileNotFoundError on `docker` → Rich error, exit 2, not a traceback."""
    mocker.patch(
        'myah.cli.logs.subprocess.run',
        side_effect=FileNotFoundError("[Errno 2] No such file or directory: 'docker'"),
    )

    result = runner.invoke(app, ['logs', 'platform'])

    assert result.exit_code == 2, f'wanted 2, got {result.exit_code}; stdout: {result.stdout}'
    assert 'Binary not found' in result.stdout
    assert 'docker' in result.stdout
    # Hint surfaces.
    assert 'Docker Desktop' in result.stdout or 'docker package' in result.stdout


def test_logs_hermes_handles_binary_missing_at_runtime(fake_hermes_bin: Path, mocker) -> None:
    """If the resolved hermes binary vanishes between resolution and run (TOCTOU)."""
    mocker.patch(
        'myah.cli.logs.subprocess.run',
        side_effect=FileNotFoundError("[Errno 2] No such file or directory: 'hermes'"),
    )

    result = runner.invoke(app, ['logs', 'agent'])

    assert result.exit_code == 2, f'wanted 2, got {result.exit_code}; stdout: {result.stdout}'
    assert 'Binary not found' in result.stdout
    # The resolved path surfaces (helps the user spot which binary is missing).
    assert 'hermes' in result.stdout
    # TOCTOU hint.
    assert 'myah install' in result.stdout


def test_logs_help_mentions_platform_special_case() -> None:
    """`myah logs --help` documents the LOG_NAME=platform branch."""
    result = runner.invoke(app, ['logs', '--help'])

    assert result.exit_code == 0
    assert 'platform' in result.stdout.lower()


def test_top_level_help_lists_logs() -> None:
    """`myah --help` surfaces the `logs` command for OSS users."""
    result = runner.invoke(app, ['--help'])

    assert result.exit_code == 0
    assert 'logs' in result.stdout


# ── cold-start sentinel ────────────────────────────────────────────────


def test_logs_module_does_not_import_heavy_libs_at_top_level() -> None:
    """Rich / yaml / time / socket must stay out of the module top so
    `myah --help` cold-start holds under 200ms.
    """
    from myah.cli import logs as mod

    source = Path(mod.__file__).read_text(encoding='utf-8')
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
        assert offender not in head, f'cli/logs.py top-level imports {offender!r}'
