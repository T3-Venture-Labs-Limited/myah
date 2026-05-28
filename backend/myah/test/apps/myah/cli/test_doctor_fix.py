"""Tests for `myah doctor --fix` — opt-in self-healing."""

from __future__ import annotations

from typer.testing import CliRunner

from myah import app
from myah.lib.cli.doctor_checks import CheckResult, CheckStatus


runner = CliRunner()


def test_doctor_without_fix_is_read_only(mocker):
    """No --fix → doctor doesn't invoke any remediation."""
    mock_fix = mocker.patch('myah.cli.doctor.attempt_fix')
    mocker.patch(
        'myah.cli.doctor.run_all_checks',
        return_value=[
            CheckResult(name='myah-hermes-plugin', status=CheckStatus.FAIL, message='not installed'),
        ],
    )

    runner.invoke(app, ['doctor'])
    mock_fix.assert_not_called()


def test_doctor_fix_invokes_attempt_fix_for_each_actionable_finding(mocker):
    """With --fix, every FAIL/WARN gets a remediation attempt."""
    findings = [
        CheckResult(name='myah-hermes-plugin', status=CheckStatus.FAIL, message='not installed'),
        CheckResult(name='port 8643', status=CheckStatus.WARN, message='not bound'),
        CheckResult(name='hermes binary', status=CheckStatus.OK, message='ok'),  # OK is skipped
    ]
    mocker.patch('myah.cli.doctor.run_all_checks', return_value=findings)
    # attempt_fix is imported into the doctor module's namespace via
    # `from myah.lib.cli.doctor_fixes import attempt_fix`, so patch
    # at the consumer namespace (myah.cli.doctor.attempt_fix).
    mock_fix = mocker.patch('myah.cli.doctor.attempt_fix')

    result = runner.invoke(app, ['doctor', '--fix'])

    assert result.exit_code == 0
    # 2 actionable findings (FAIL + WARN), 1 OK skipped.
    assert mock_fix.call_count == 2


def test_attempt_fix_plugin_not_enabled_runs_enable_and_restart(mocker, tmp_path):
    """The plugin-not-enabled remediation invokes both
    `hermes plugins enable myah` and `myah agent restart`."""
    from myah.lib.cli import doctor_fixes
    from myah.lib.cli.shell import ShellResult

    mock_run = mocker.patch.object(doctor_fixes, 'run')
    mock_run.return_value = ShellResult(returncode=0, stdout='', stderr='')
    mock_agent_restart = mocker.patch.object(doctor_fixes, 'agent_restart')
    mocker.patch.object(
        doctor_fixes,
        'resolve_hermes_binary_or_exit',
        return_value=tmp_path / 'venv' / 'bin' / 'hermes',
    )

    finding = CheckResult(
        name='myah-hermes-plugin',
        status=CheckStatus.FAIL,
        message='plugin not installed. Install via: hermes plugins install ...',
    )
    fixed = doctor_fixes.attempt_fix(finding)

    assert fixed is True
    argvs = [c.args[0] for c in mock_run.call_args_list]
    assert any(a[1:] == ['plugins', 'enable', 'myah'] for a in argvs)
    mock_agent_restart.assert_called_once()


def test_attempt_fix_port_unbound_runs_agent_restart(mocker):
    """Port-unbound WARN (which `probe_required_ports(services_started=True)`
    now produces, post-Step 1a refactor) is fixed by `myah agent restart`."""
    from myah.lib.cli import doctor_fixes
    mock_agent_restart = mocker.patch.object(doctor_fixes, 'agent_restart')

    finding = CheckResult(
        name='port 8643',
        status=CheckStatus.WARN,
        message='port 8643 is free but Hermes gateway adapter should be bound',
    )
    fixed = doctor_fixes.attempt_fix(finding)

    assert fixed is True
    mock_agent_restart.assert_called_once()
