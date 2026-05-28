"""Opt-in self-healing for `myah doctor --fix`.

Each remediation is a small, idempotent function keyed off a
`CheckResult.name`. Returns True if a fix was attempted (caller
re-runs the check), False if the finding isn't actionable.

Out of scope: anything destructive (e.g. wiping ~/.hermes). Fixes that
might modify user data require an explicit subcommand, not --fix.

See PR #16 post-merge laptop test, simplification S4.
"""

from __future__ import annotations

from myah.lib.cli.doctor_checks import CheckResult, CheckStatus
from myah.lib.cli.hermes_install import resolve_hermes_binary_or_exit
from myah.lib.cli.shell import run


def attempt_fix(finding: CheckResult) -> bool:
    """Dispatch a remediation by check name. Returns True if fix ran."""
    if finding.status == CheckStatus.OK:
        return False
    handler = _FIX_DISPATCH.get(finding.name)
    if handler is None:
        return False
    return handler(finding)


def _fix_plugin_not_enabled(finding: CheckResult) -> bool:
    """Run `hermes plugins enable myah` + `myah agent restart`."""
    from rich.console import Console
    console = Console()

    hermes_bin = resolve_hermes_binary_or_exit(command_hint='for `myah doctor --fix`')
    console.print(f'[cyan]fix[/] {finding.name}: hermes plugins enable myah')
    result = run([str(hermes_bin), 'plugins', 'enable', 'myah'])
    if result.returncode != 0:
        console.print(f'  [red]✗[/] enable failed: {result.stderr.strip()!r}')
        return True  # we did try; caller re-checks
    console.print('  [green]✓[/] plugin enabled, restarting agent…')
    try:
        agent_restart()
    except Exception as err:  # noqa: BLE001 — best-effort
        console.print(f'  [yellow]⚠[/] agent restart failed: {err}')
    return True


def _fix_port_unbound(finding: CheckResult) -> bool:
    """Port should be bound but isn't → `myah agent restart`."""
    from rich.console import Console
    console = Console()
    console.print(f'[cyan]fix[/] {finding.name}: restarting agent to bind the port')
    try:
        agent_restart()
        return True
    except Exception as err:  # noqa: BLE001
        console.print(f'  [yellow]⚠[/] agent restart failed: {err}')
        return True


def _fix_platform_down(finding: CheckResult) -> bool:
    """Platform container not running → `myah platform up`. Idempotent.

    Separate handler from `_fix_port_unbound` because the platform is
    a docker-compose container, not a launchd/systemd service.
    """
    from rich.console import Console
    console = Console()
    console.print(f'[cyan]fix[/] {finding.name}: running `myah platform up`')
    try:
        platform_up(rm_orphans=False)
        return True
    except Exception as err:  # noqa: BLE001
        console.print(f'  [yellow]⚠[/] platform up failed: {err}')
        return True


# Dispatch table: CheckResult.name → remediation function.
#
# Port coverage rationale:
#   8642  — Hermes api_server. Reuses _fix_port_unbound (agent restart
#           re-binds both 8642 and 8643 in the same hermes-gateway
#           process; listing it explicitly avoids depending on the
#           side-effect).
#   8643  — gateway-myah-adapter. agent restart binds it.
#   9119  — hermes-dashboard. agent restart binds it.
#   8080  — myah-platform (Docker). NOT in this dispatch because the
#           platform is a docker-compose-managed container, not a
#           launchd/systemd service. The myah-platform-container WARN
#           is handled by the separate `myah-platform container` row
#           (whose dispatch entry below calls platform_up).
#
# Any future port added to doctor_checks._REQUIRED_PORTS that should
# be auto-fixable MUST be added here too; otherwise --fix silently
# skips it.
_FIX_DISPATCH = {
    'myah-hermes-plugin': _fix_plugin_not_enabled,
    'port 8642': _fix_port_unbound,
    'port 8643': _fix_port_unbound,
    'port 9119': _fix_port_unbound,
    'myah-platform container': _fix_platform_down,
}


# Module-level imports for things the dispatch handlers call. Top-level
# (not lazy) so test code can patch via mocker.patch.object(doctor_fixes, ...).
from myah.cli.agent import agent_restart  # noqa: E402
from myah.cli.platform_ import platform_up  # noqa: E402


__all__ = ['attempt_fix']
