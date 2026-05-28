"""`myah agent {up,down,restart}` + `myah agent config {show,edit,validate}`.

Slice 5 Task 5.1 of T3-1084 (DevX + OSS CLI).

Two surfaces, both system-scoped (not worktree-scoped — that's
``myah dev oss`` in Slice 3):

- **Lifecycle** (`up/down/restart`): drives the OS supervisor against
  the Hermes service units installed by ``myah install`` (Slice 4d):

      Linux (systemd-user): hermes-gateway.service, hermes-dashboard.service
      macOS (launchd):      dev.myah.hermes-gateway, dev.myah.hermes-dashboard

  The original spec table said to wrap ``hermes gateway start``, but
  that resolves to ``hermes-gateway-<profile>.service`` (upstream
  Hermes's own unit-name convention) which does NOT match the units
  Myah installs. Dashboard has no `start` subcommand at all — `hermes
  dashboard` foregrounds. We delegate to systemctl/launchctl directly:
  still a "wrapper", just a thinner one.

- **Config** (`show/edit/validate`): thin wrappers around upstream
  ``hermes config {show,edit,check}``. The verb rename
  ``validate → check`` is the Myah-level value-add (Myah uses
  "validate"; upstream Hermes calls it "check"). Invokes the user's
  system Hermes binary via ``detect_hermes_venv`` (Slice 4b). No
  HERMES_HOME override — inherits from ``os.environ`` so users who set
  it explicitly are honored.

Cold-start budget: heavy imports (Rich) live inside command bodies so
``myah --help`` stays under 200ms. ``shutil``, ``sys``, ``os``,
``subprocess`` are stdlib and cheap.

# Hermes wakes when the supervisor calls. We knock on the right door —
# systemd on Linux, launchd on Darwin — and let the OS do the rest.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from collections.abc import Callable

import typer

# Module-level aliases so tests patch at the consumer namespace
# (`myah.cli.agent.run`, `myah.cli.agent.resolve_hermes_binary_or_exit`),
# never on source modules. See Slices 2-4 for the same discipline.
from myah.lib.cli.hermes_install import resolve_hermes_binary_or_exit
from myah.lib.cli.output import emit_result_or_exit
from myah.lib.cli.shell import run

agent_app = typer.Typer(
    name='agent',
    help='Manage the Hermes agent runtime (gateway + dashboard).',
    no_args_is_help=True,
)
config_app = typer.Typer(
    name='config',
    help="Inspect and edit the Hermes agent's config.",
    no_args_is_help=True,
)


# Unit names installed by Slice 4d's `service_units.install_systemd_user_units` /
# `install_launchd_plists`. Single source of truth — if those change, change here.
_SYSTEMD_UNITS = ('hermes-gateway.service', 'hermes-dashboard.service')
_LAUNCHD_SERVICES = ('dev.myah.hermes-gateway', 'dev.myah.hermes-dashboard')


# ---------------------------------------------------------------------------
# lifecycle: up / down / restart
# ---------------------------------------------------------------------------


def _on_macos() -> bool:
    return sys.platform == 'darwin'


def _has_systemd() -> bool:
    return shutil.which('systemctl') is not None


def _no_supervisor_exit() -> None:
    """Exit 2 with a clear message when neither systemd nor launchd is present."""
    from rich.console import Console

    Console().print(
        '[red bold]No supported service supervisor found.[/]\n'
        '[dim]`myah agent {up,down,restart}` requires either:\n'
        '  - systemd-user (Linux; needs `systemctl` on PATH), or\n'
        '  - launchd (macOS).\n'
        'On unsupported platforms, start hermes manually via [bold]hermes gateway[/] '
        'and [bold]hermes dashboard[/].[/]'
    )
    raise typer.Exit(code=2)


# Past-tense → infinitive map. Avoids the `rstrip("ed")` footgun where
# "stopped".rstrip("ed") returns "stopp" (rstrip strips trailing chars
# in the set, not a suffix).
_INFINITIVE_FOR_VERB = {
    'started': 'start',
    'stopped': 'stop',
    'restarted': 'restart',
    'updated': 'update',  # generic fallback verb
}


def _print_service_result(service: str, verb: str, success: bool, stderr: str = '') -> None:
    """Emit a one-line Rich confirmation for a service lifecycle action.

    `verb` is the user-facing past-tense verb ('started', 'stopped',
    'restarted'). On failure, print the truncated stderr for context.
    Regression for PR #16 post-merge laptop test, Bug 2.
    """
    from rich.console import Console

    console = Console()
    if success:
        console.print(f'  [green]✓[/] {verb} [cyan]{service}[/]')
    else:
        infinitive = _INFINITIVE_FOR_VERB.get(verb, verb)
        msg = f'  [red]✗[/] failed to {infinitive} [cyan]{service}[/]'
        if stderr:
            tail = stderr.strip().splitlines()[-1] if stderr.strip() else ''
            if tail:
                msg += f' [dim]({tail[:120]})[/]'
        console.print(msg)


def _systemctl(verb: str, *, verb_label: str = 'updated') -> None:
    """Invoke `systemctl --user <verb>` against the Myah-installed units,
    then print a per-unit confirmation by re-checking `systemctl is-active`."""
    result = run(['systemctl', '--user', verb, *_SYSTEMD_UNITS])
    # Confirm per-unit state.
    for unit in _SYSTEMD_UNITS:
        active = run(['systemctl', '--user', 'is-active', unit])
        success = active.returncode == 0 and active.stdout.strip() == 'active'
        # 'stop' is a successful confirmation when is-active reports inactive.
        if verb == 'stop':
            success = active.returncode != 0 or active.stdout.strip() != 'active'
        _print_service_result(unit, verb_label, success=success, stderr=result.stderr)
    if result.returncode != 0:
        raise typer.Exit(code=result.returncode)


def _launchctl_each(
    make_argv: Callable[[str], list[str]],
    *,
    verb: str = 'updated',
) -> None:
    """Run a launchctl invocation per service. Prints confirmation per
    service; aggregates exit code (worst rc wins). Replaces the prior
    fail-fast `emit_result_or_exit` behavior to surface partial success.
    """
    worst_rc = 0
    for service in _LAUNCHD_SERVICES:
        result = run(make_argv(service))
        if result.returncode != 0:
            worst_rc = max(worst_rc, result.returncode)
            _print_service_result(service, verb, success=False, stderr=result.stderr)
        else:
            _print_service_result(service, verb, success=True)
    if worst_rc != 0:
        raise typer.Exit(code=worst_rc)


def _launchd_target(service: str) -> str:
    """Build the `gui/<uid>/<service>` target string for launchctl."""
    return f'gui/{os.getuid()}/{service}'


@agent_app.command('up')
def agent_up() -> None:
    """Start the Hermes gateway + dashboard via the OS supervisor."""
    if _on_macos():
        _launchctl_each(
            lambda s: ['launchctl', 'kickstart', _launchd_target(s)],
            verb='started',
        )
    elif _has_systemd():
        _systemctl('start', verb_label='started')
    else:
        _no_supervisor_exit()


@agent_app.command('down')
def agent_down() -> None:
    """Stop the Hermes gateway + dashboard via the OS supervisor."""
    if _on_macos():
        _launchctl_each(
            lambda s: ['launchctl', 'bootout', _launchd_target(s)],
            verb='stopped',
        )
    elif _has_systemd():
        _systemctl('stop', verb_label='stopped')
    else:
        _no_supervisor_exit()


@agent_app.command('restart')
def agent_restart() -> None:
    """Restart the Hermes gateway + dashboard via the OS supervisor."""
    if _on_macos():
        # `launchctl kickstart -k` forces a restart of an already-running service.
        _launchctl_each(
            lambda s: ['launchctl', 'kickstart', '-k', _launchd_target(s)],
            verb='restarted',
        )
    elif _has_systemd():
        _systemctl('restart', verb_label='restarted')
    else:
        _no_supervisor_exit()


# ---------------------------------------------------------------------------
# config: show / edit / validate
# ---------------------------------------------------------------------------


@config_app.command('show')
def config_show() -> None:
    """Print the user's effective Hermes config.yaml."""
    hermes_bin = resolve_hermes_binary_or_exit(command_hint='for `myah agent config show`')
    emit_result_or_exit(run([str(hermes_bin), 'config', 'show']))


@config_app.command('edit')
def config_edit() -> None:
    """Open the user's Hermes config.yaml in $EDITOR."""
    hermes_bin = resolve_hermes_binary_or_exit(command_hint='for `myah agent config edit`')
    # Interactive editor needs stdio passthrough; `shell.run` captures
    # output, which would break the editor. Use `subprocess.run` directly.
    completed = subprocess.run(  # noqa: S603 — args are not user-controlled
        [str(hermes_bin), 'config', 'edit'],
        check=False,
    )
    if completed.returncode != 0:
        raise typer.Exit(code=completed.returncode)


@config_app.command('validate')
def config_validate() -> None:
    """Validate the user's Hermes config.yaml (wraps `hermes config check`)."""
    hermes_bin = resolve_hermes_binary_or_exit(command_hint='for `myah agent config validate`')
    # Verb rename: Myah uses "validate"; upstream Hermes calls it "check".
    # This rename IS the value-add of the wrapper.
    emit_result_or_exit(run([str(hermes_bin), 'config', 'check']))


agent_app.add_typer(config_app, name='config')


__all__ = ['agent_app']
