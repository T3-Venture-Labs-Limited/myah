"""Tests for `myah quickstart` — composite install + platform up + doctor.

Task C.2 of the OSS install-flow followups plan. The `quickstart` command
is a thin composite that reduces the OSS first-run from 4 commands to 1.

Test strategy: mock the 3 underlying phases at the consumer namespace
(``myah.cli.quickstart.<callable>``) so we exercise the orchestration
contract (ordering, short-circuit, doctor-always-runs-on-platform-failure)
without spinning up the real install / docker / doctor surfaces.
"""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

from myah import app


runner = CliRunner()


@pytest.fixture
def all_quickstart_mocks(mocker):
    """Mock the 3 phases the composite invokes."""
    return {
        'install': mocker.patch('myah.cli.quickstart.install_command'),
        'platform_up': mocker.patch('myah.cli.quickstart.platform_up'),
        'doctor': mocker.patch('myah.cli.quickstart.doctor_command'),
    }


def test_quickstart_runs_install_then_platform_up_then_doctor(all_quickstart_mocks):
    result = runner.invoke(app, ['quickstart', '--non-interactive', '--service', 'systemd'])

    assert result.exit_code == 0, result.stdout
    all_quickstart_mocks['install'].assert_called_once()
    all_quickstart_mocks['platform_up'].assert_called_once()
    all_quickstart_mocks['doctor'].assert_called_once()


def test_quickstart_forwards_openrouter_key_to_install(all_quickstart_mocks):
    result = runner.invoke(
        app,
        [
            'quickstart',
            '--non-interactive',
            '--service',
            'systemd',
            '--openrouter-key',
            'sk-or-v1-test',
        ],
    )
    assert result.exit_code == 0
    install_kwargs = all_quickstart_mocks['install'].call_args.kwargs
    assert install_kwargs.get('openrouter_key') == 'sk-or-v1-test'


def test_quickstart_install_failure_short_circuits(all_quickstart_mocks):
    """If install fails, don't run platform_up or doctor."""
    import typer

    all_quickstart_mocks['install'].side_effect = typer.Exit(code=1)

    result = runner.invoke(app, ['quickstart', '--non-interactive', '--service', 'systemd'])

    assert result.exit_code == 1
    all_quickstart_mocks['platform_up'].assert_not_called()
    all_quickstart_mocks['doctor'].assert_not_called()


def test_quickstart_platform_up_failure_still_runs_doctor(all_quickstart_mocks):
    """Doctor is the diagnostic surface — run it even when platform fails
    so the user gets a Rich table of what's wrong."""
    import typer

    all_quickstart_mocks['platform_up'].side_effect = typer.Exit(code=1)

    result = runner.invoke(app, ['quickstart', '--non-interactive', '--service', 'systemd'])

    all_quickstart_mocks['doctor'].assert_called_once()
    # Exit code reflects platform_up failure even though doctor ran.
    assert result.exit_code != 0
