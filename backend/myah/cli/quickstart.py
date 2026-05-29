"""`myah quickstart` — composite first-run for OSS users.

One command instead of four:

  - install (non-interactive, with platform default service)
  - platform up
  - doctor

Failure semantics:
  - install failure → short-circuit, exit 1
  - platform_up failure → still run doctor (diagnostic surface),
    propagate exit code
  - doctor exit code is the final exit code unless an earlier step failed

# A door for those who don't want to read the runbook. One command.
# If it doesn't work, doctor tells them why.
"""

from __future__ import annotations

import sys

import typer

from myah.cli.doctor import doctor_command
from myah.cli.install import install_command
from myah.cli.platform_ import platform_up


def _default_service_for_platform() -> str:
    if sys.platform.startswith('linux'):
        return 'systemd'
    if sys.platform == 'darwin':
        return 'launchd'
    return 'none'


def quickstart_command(
    non_interactive: bool = typer.Option(
        False,
        '--non-interactive',
        help='Skip TTY prompts. Required for CI / scripted runs.',
    ),
    service: str = typer.Option(
        None,
        '--service',
        help='systemd|launchd|none. Defaults to the OS-appropriate value.',
    ),
    openrouter_key: str = typer.Option(
        None,
        '--openrouter-key',
        help='Pre-set OPENROUTER_API_KEY in the Hermes .env during install.',
    ),
    rotate: bool = typer.Option(
        False,
        '--rotate',
        help='Regenerate all secrets during install. Mutex with --keep-data.',
    ),
) -> None:
    """Run install, bring up the platform, and verify with doctor.

    Equivalent to:
        myah install [...flags...] && myah platform up && myah doctor

    See `myah install --help` for the flag semantics that pass through.
    """
    from rich.console import Console

    console = Console()

    chosen_service = service or _default_service_for_platform()
    console.print(
        '[bold]What this does:[/] connect Myah to your existing Hermes install, '
        'start the Myah Docker container, then run health checks.'
    )
    console.print(
        f'[dim]Service manager: {chosen_service}; platform URL: http://localhost:8080[/]'
    )

    # ─── Step 1/3: install ────────────────────────────────────────────
    console.print('[bold cyan]Step 1/3:[/] myah install')
    try:
        install_command(
            non_interactive=non_interactive,
            service=chosen_service,
            openrouter_key=openrouter_key,
            rotate=rotate,
            keep_data=False,
            skip_start=False,
        )
    except typer.Exit as exit_err:
        if exit_err.exit_code:
            console.print(
                f'[red]✗[/] Install failed (exit {exit_err.exit_code}). '
                'Re-run `myah install` after addressing the error above, '
                'then `myah platform up` + `myah doctor`.'
            )
            raise

    # ─── Step 2/3: platform up ────────────────────────────────────────
    console.print('\n[bold cyan]Step 2/3:[/] myah platform up')
    platform_failure: typer.Exit | None = None
    try:
        # Explicit rm_orphans=True: this is a first-run flow, so silently
        # auto-removing a pre-A.2 orphan container is the right UX. Pass
        # the bool explicitly because Typer's default resolution only
        # fires on Typer-dispatched calls — direct calls (like this one)
        # otherwise receive the OptionInfo sentinel.
        platform_up(rm_orphans=True)
    except typer.Exit as exit_err:
        if exit_err.exit_code:
            platform_failure = exit_err
            console.print(
                f'[yellow]⚠[/] platform up failed (exit {exit_err.exit_code}). '
                'Running doctor to surface what went wrong.'
            )

    # ─── Step 3/3: doctor ─────────────────────────────────────────────
    console.print('\n[bold cyan]Step 3/3:[/] myah doctor')
    try:
        # Explicit fix=False: doctor_command's `fix` parameter is a
        # typer.Option, which means direct (non-Typer) callers receive
        # the OptionInfo sentinel by default (truthy under `if fix:`).
        # quickstart runs install + platform up in known-good states,
        # so doctor's role here is reporting, not healing. The C.3
        # platform_up signature has the same quirk; see its docstring.
        doctor_command(fix=False)
    except typer.Exit:
        if platform_failure is not None:
            raise platform_failure
        raise

    if platform_failure is not None:
        raise platform_failure
    console.print(
        '\n[green bold]✓[/] Quickstart complete. '
        'Open [cyan]http://localhost:8080[/] to start chatting.'
    )


__all__ = ['quickstart_command']
