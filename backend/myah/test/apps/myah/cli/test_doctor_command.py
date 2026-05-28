"""Tests for the composed `myah doctor` command (uses individual checks from doctor_checks)."""

import pytest
from typer.testing import CliRunner

from myah import app


runner = CliRunner()


def test_doctor_invokes_without_crash(mocker) -> None:
    """`myah doctor` runs all checks and exits cleanly (0 if all OK; non-zero if any FAIL)."""
    # Mock all check functions to return OK so we don't depend on real environment
    from myah.lib.cli.doctor_checks import CheckResult, CheckStatus
    ok = lambda name: CheckResult(name=name, status=CheckStatus.OK, message='all good')
    mocker.patch('myah.cli.doctor.check_hermes_binary_on_path', return_value=ok('hermes binary'))
    mocker.patch('myah.cli.doctor.check_hermes_plugin_installed', return_value=ok('plugin'))
    # probe_required_ports now drives port checks (replaces check_port_for_service)
    mocker.patch('myah.cli.doctor.probe_required_ports', return_value=[ok('port 8642'), ok('port 8643')])
    mocker.patch('myah.cli.doctor.check_platform_container_running', return_value=ok('container'))
    mocker.patch('myah.cli.doctor.check_plugin_sha_drift', return_value=ok('sha'))
    mocker.patch('myah.cli.doctor.check_agent_container_env_injection', return_value=ok('agent env'))

    result = runner.invoke(app, ['doctor'])

    assert result.exit_code == 0


def test_doctor_renders_table(mocker) -> None:
    """Doctor output is a table with check names + status."""
    from myah.lib.cli.doctor_checks import CheckResult, CheckStatus
    mocker.patch(
        'myah.cli.doctor.check_hermes_binary_on_path',
        return_value=CheckResult(name='hermes binary', status=CheckStatus.OK, message='found at /usr/local/bin/hermes'),
    )
    mocker.patch(
        'myah.cli.doctor.probe_required_ports',
        return_value=[CheckResult(name='port 8642', status=CheckStatus.OK, message='ok')],
    )
    # Mock the others to OK too
    for name in [
        'check_hermes_plugin_installed',
        'check_platform_container_running',
        'check_plugin_sha_drift',
        'check_agent_container_env_injection',
    ]:
        mocker.patch(
            f'myah.cli.doctor.{name}',
            return_value=CheckResult(name='x', status=CheckStatus.OK, message='ok'),
        )

    result = runner.invoke(app, ['doctor'])

    assert 'hermes binary' in result.stdout
    assert 'OK' in result.stdout or 'ok' in result.stdout.lower()


def test_doctor_exit_code_1_on_any_fail(mocker) -> None:
    """If any check returns FAIL, the command exits with code 1."""
    from myah.lib.cli.doctor_checks import CheckResult, CheckStatus
    mocker.patch(
        'myah.cli.doctor.check_hermes_binary_on_path',
        return_value=CheckResult(name='hermes binary', status=CheckStatus.FAIL, message='not found'),
    )
    mocker.patch(
        'myah.cli.doctor.probe_required_ports',
        return_value=[CheckResult(name='port 8642', status=CheckStatus.OK, message='ok')],
    )
    for name in [
        'check_hermes_plugin_installed',
        'check_platform_container_running',
        'check_plugin_sha_drift',
        'check_agent_container_env_injection',
    ]:
        mocker.patch(
            f'myah.cli.doctor.{name}',
            return_value=CheckResult(name='x', status=CheckStatus.OK, message='ok'),
        )

    result = runner.invoke(app, ['doctor'])

    assert result.exit_code == 1


def test_doctor_exit_code_0_when_only_warns(mocker) -> None:
    """WARNs do not fail the doctor command — they're informational."""
    from myah.lib.cli.doctor_checks import CheckResult, CheckStatus
    mocker.patch(
        'myah.cli.doctor.check_platform_container_running',
        return_value=CheckResult(name='container', status=CheckStatus.WARN, message='not running'),
    )
    mocker.patch(
        'myah.cli.doctor.probe_required_ports',
        return_value=[CheckResult(name='port 8642', status=CheckStatus.OK, message='ok')],
    )
    for name in [
        'check_hermes_binary_on_path',
        'check_hermes_plugin_installed',
        'check_plugin_sha_drift',
        'check_agent_container_env_injection',
    ]:
        mocker.patch(
            f'myah.cli.doctor.{name}',
            return_value=CheckResult(name='x', status=CheckStatus.OK, message='ok'),
        )

    result = runner.invoke(app, ['doctor'])

    assert result.exit_code == 0


@pytest.mark.slow
def test_doctor_runs_end_to_end_against_real_environment() -> None:
    """Integration test: myah doctor must run without crashing in a real shell.

    Asserts only that the command exits cleanly (0 or 1) and produces table-shaped
    output. Does NOT assert specific check results — those depend on the
    invoking machine's state (hermes installed, container running, etc.).

    Catches the failure mode "the doctor command passes its unit tests but
    crashes the moment it runs against real subprocess output."
    """
    import os
    import subprocess

    # Use PYTHONPATH=backend so we exercise THIS worktree's code, not main's myah
    env = os.environ.copy()
    env['PYTHONPATH'] = 'backend' + os.pathsep + env.get('PYTHONPATH', '')
    result = subprocess.run(
        ['python', '-c', 'from myah import app; app(["doctor"])'],
        capture_output=True,
        text=True,
        env=env,
    )
    assert result.returncode in (0, 1), (
        f'doctor crashed (exit {result.returncode}). stderr: {result.stderr[:500]}'
    )
    # Rich table renders with these chars; sanity-check we got table output
    assert '─' in result.stdout or '|' in result.stdout, (
        f'doctor produced no table output. stdout: {result.stdout[:500]}'
    )
    # At least one of the well-known check names must appear
    assert any(name in result.stdout for name in ['hermes binary', 'plugin', 'port', 'platform']), (
        f'doctor table missing expected check rows. stdout: {result.stdout[:500]}'
    )
