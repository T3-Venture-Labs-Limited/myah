"""`myah doctor` — diagnose stack health.

Runs each check from `myah.lib.cli.doctor_checks`, renders results as
a Rich table, and exits with code 0 if all OK/WARN, code 1 if any FAIL.
"""

from __future__ import annotations

import typer
from rich.console import Console
from rich.table import Table

from myah.lib.cli.doctor_checks import (
    CheckResult,
    CheckStatus,
    check_agent_container_env_injection,
    check_hermes_binary_on_path,
    check_hermes_plugin_installed,
    check_platform_container_running,
    check_plugin_sha_drift,
    check_port_for_service,
)


# Ports the platform expects, paired with the service that should own them.
# Keep in sync with docker-compose.yml and dev-oss.sh defaults: platform (8080),
# hermes gateway (8642), gateway-myah-adapter (8643), hermes dashboard (9119).
_REQUIRED_PORTS: list[tuple[int, str]] = [
    (8080, 'myah-platform'),
    (8642, 'hermes-gateway'),
    (8643, 'gateway-myah-adapter'),
    (9119, 'hermes-dashboard'),
]


def doctor_command() -> None:
    """Diagnose stack health and print a status table."""
    results: list[CheckResult] = []

    # Run all checks; collect results
    results.append(check_hermes_binary_on_path())
    results.append(check_hermes_plugin_installed())
    for port, service in _REQUIRED_PORTS:
        results.append(check_port_for_service(port, service))
    results.append(check_platform_container_running())
    results.append(check_plugin_sha_drift())
    results.append(check_agent_container_env_injection())  # M3 — attachment pipeline invariant

    # Render table
    console = Console()
    table = Table(title='Myah Stack Health', show_header=True, header_style='bold')
    table.add_column('Check', style='cyan')
    table.add_column('Status', justify='center')
    table.add_column('Detail', style='dim')

    for r in results:
        status_color = {
            CheckStatus.OK: '[green]OK[/]',
            CheckStatus.WARN: '[yellow]WARN[/]',
            CheckStatus.FAIL: '[red]FAIL[/]',
        }[r.status]
        table.add_row(r.name, status_color, r.message)

    console.print(table)

    # Exit code: 1 if any FAIL, else 0
    if any(r.status == CheckStatus.FAIL for r in results):
        raise typer.Exit(code=1)
