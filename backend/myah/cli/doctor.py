"""`myah doctor` — diagnose stack health.

Runs each check from `myah.lib.cli.doctor_checks`, renders results as
a Rich table, and exits with code 0 if all OK/WARN, code 1 if any FAIL.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

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
    probe_required_ports,
)
from myah.lib.cli.doctor_fixes import attempt_fix


def _service_units_present() -> bool:
    """True if `myah install` has laid down service-supervision units.

    Reading the OS supervisor directly would require shelling out. We
    use the cheaper file-existence check — the units are laid down by
    `service_units.install_*` and removed by `service_units.remove_service_units`.
    """
    if sys.platform == 'darwin':
        la = Path(os.path.expanduser('~/Library/LaunchAgents'))
        return (la / 'dev.myah.hermes-gateway.plist').is_file() or (
            la / 'dev.myah.hermes-dashboard.plist'
        ).is_file()
    if sys.platform.startswith('linux'):
        su = Path(os.path.expanduser('~/.config/systemd/user'))
        return (su / 'hermes-gateway.service').is_file() or (
            su / 'hermes-dashboard.service'
        ).is_file()
    return False


def run_all_checks() -> list[CheckResult]:
    """Aggregate every doctor check into one ordered list.

    Extracted from `doctor_command` so `--fix` can re-run the checks
    after applying remediations without duplicating the call list.

    Replaces the prior per-port loop using `check_port_for_service`
    (which always returned OK) with `probe_required_ports`. The
    `services_started` kwarg toggles "free port → WARN" semantics
    when the install has laid down service units that should be
    binding the port; otherwise free → OK.
    """
    results: list[CheckResult] = [
        check_hermes_binary_on_path(),
        check_hermes_plugin_installed(),
    ]
    results.extend(probe_required_ports(services_started=_service_units_present()))
    results.extend([
        check_platform_container_running(),
        check_plugin_sha_drift(),
        check_agent_container_env_injection(),
    ])
    return results


def _render_results_table(results: list[CheckResult]) -> None:
    """Render the Rich health table. Factored so --fix can re-render."""
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


def doctor_command(
    fix: bool = typer.Option(
        False, '--fix',
        help=(
            'Opt-in: attempt to fix actionable findings (plugin not '
            'enabled, gateway/dashboard ports unbound). Re-runs the '
            'checks after each fix. See doctor_fixes.py for the '
            'remediation dispatch table.'
        ),
    ),
) -> None:
    """Diagnose stack health and print a status table."""
    results = run_all_checks()
    _render_results_table(results)

    if fix:
        console = Console()
        actionable = [
            r for r in results
            if r.status in {CheckStatus.FAIL, CheckStatus.WARN}
        ]
        if not actionable:
            console.print('\n[green]✓[/] no actionable findings — nothing to fix.')
        else:
            console.print(f'\n[bold]Attempting {len(actionable)} fix(es)…[/]')
            fixed_any = False
            for finding in actionable:
                try:
                    if attempt_fix(finding):
                        fixed_any = True
                except Exception as err:  # noqa: BLE001
                    console.print(f'  [red]✗[/] {finding.name}: fix raised {err!r}')

            if fixed_any:
                console.print('\n[bold cyan]Re-running checks after fixes…[/]')
                new_results = run_all_checks()
                _render_results_table(new_results)
        # --fix mode is non-fatal: the user explicitly opted into
        # self-healing and the post-fix output is what they're meant
        # to read. Exit 0 even if findings remain, so a quickstart /
        # script run doesn't trip its own error handler on a partial
        # heal. Without --fix (read-only mode) we preserve the
        # original exit-1-on-FAIL contract below.
        return

    if any(r.status == CheckStatus.FAIL for r in results):
        raise typer.Exit(code=1)
