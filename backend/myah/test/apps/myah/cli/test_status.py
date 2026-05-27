"""Tests for myah status command."""

from typer.testing import CliRunner

from myah import app


runner = CliRunner()


def test_status_lists_known_services(mocker) -> None:
    """`myah status` shows rows for platform, gateway, dashboard."""
    from myah.lib.cli.shell import ShellResult

    # Mock docker ps to show platform running. Mock at the CONSUMER namespace
    # (`myah.cli.status.run`) — not the source (`myah.lib.cli.shell.run`) —
    # because status.py does `from myah.lib.cli.shell import run` at import
    # time, which binds `run` into status.py's own namespace. Patching the
    # source after import has no effect on status.py's local binding.
    mocker.patch(
        'myah.cli.status.run',
        return_value=ShellResult(returncode=0, stdout='myah-platform Up 5 min  0.0.0.0:8080->8080/tcp', stderr=''),
    )

    result = runner.invoke(app, ['status'])

    assert result.exit_code == 0
    assert 'platform' in result.stdout.lower()
    assert 'gateway' in result.stdout.lower()
    assert 'dashboard' in result.stdout.lower()


def test_status_shows_ports(mocker) -> None:
    """Status output includes the port numbers for each service."""
    from myah.lib.cli.shell import ShellResult

    mocker.patch(
        'myah.cli.status.run',
        return_value=ShellResult(returncode=0, stdout='', stderr=''),
    )

    result = runner.invoke(app, ['status'])

    assert '8080' in result.stdout  # platform
    assert '8642' in result.stdout  # gateway
    assert '9119' in result.stdout  # dashboard


def test_status_exit_code_always_zero() -> None:
    """Status is informational; always exits 0 even when services are down."""
    result = runner.invoke(app, ['status'])
    assert result.exit_code == 0
