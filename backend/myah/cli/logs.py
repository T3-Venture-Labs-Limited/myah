"""`myah logs [LOG_NAME] [...flags]` — pass-through wrapper of `hermes logs`.

Slice 5 Task 5.4 of T3-1084 (DevX + OSS CLI).

Thin wrapper: most invocations forward verbatim to the user's system
``hermes logs`` binary. One special LOG_NAME — ``platform`` — resolves
to ``docker compose -f <repo-root>/docker-compose.yml logs platform``
because the FastAPI platform isn't a Hermes component and has no
Hermes-side log file.

Flag map:

  -n, --lines N    → docker: ``--tail N``;  hermes: ``-n N``
  -f, --follow     → docker: ``--follow``;  hermes: ``-f``
  --level LEVEL    → hermes only (rejected for platform)
  --session ID     → hermes only (rejected for platform)
  --since DUR      → hermes only (rejected for platform)
  --component NAME → hermes only (rejected for platform)

stdio passes through to the user's terminal (no capture), so ``-f``
follows live without buffering. The subprocess exit code propagates
verbatim via ``typer.Exit``.

Cold-start budget: ``typer`` + stdlib only at the module top. Rich is
lazy inside command bodies. Hermes binary resolution is also lazy so
``myah --help`` doesn't pay the venv-detection cost.

# One door, two hallways: most logs come from Hermes, but the platform
# speaks docker-compose. We pick the right hallway based on the name
# and let stdio carry the rest unchanged.
"""

from __future__ import annotations

import subprocess
from typing import Optional

import typer

# Module-level aliases so tests patch at the consumer namespace
# (`myah.cli.logs.subprocess.run`, `myah.cli.logs.find_repo_root`,
# `myah.cli.logs.resolve_hermes_binary_or_exit`). Same discipline as
# Slices 2-4 — never patch source modules.
from myah.lib.cli.hermes_install import resolve_hermes_binary_or_exit
from myah.lib.cli.repo import find_repo_root


def logs_command(
    log_name: Optional[str] = typer.Argument(  # noqa: UP007 — typer needs Optional
        None,
        help="Log component name. 'platform' → docker compose; "
        'anything else (or omitted) → forwarded to `hermes logs`.',
    ),
    lines: Optional[int] = typer.Option(  # noqa: UP007
        None,
        '-n',
        '--lines',
        help='Number of tail lines to show.',
    ),
    follow: bool = typer.Option(
        False,
        '-f',
        '--follow',
        help='Follow log output (live tail).',
    ),
    level: Optional[str] = typer.Option(  # noqa: UP007
        None,
        '--level',
        help='Minimum log level (hermes only — rejected for platform).',
    ),
    session: Optional[str] = typer.Option(  # noqa: UP007
        None,
        '--session',
        help='Filter by session id (hermes only — rejected for platform).',
    ),
    since: Optional[str] = typer.Option(  # noqa: UP007
        None,
        '--since',
        help='Show entries newer than the given duration (hermes only — rejected for platform).',
    ),
    component: Optional[str] = typer.Option(  # noqa: UP007
        None,
        '--component',
        help='Hermes component name (hermes only — rejected for platform).',
    ),
) -> None:
    """Tail Hermes or platform logs (see help for the platform special-case)."""
    if log_name == 'platform':
        _run_platform_logs(lines=lines, follow=follow, level=level, session=session,
                           since=since, component=component)
    else:
        _run_hermes_logs(
            log_name=log_name,
            lines=lines,
            follow=follow,
            level=level,
            session=session,
            since=since,
            component=component,
        )


def _run_platform_logs(
    *,
    lines: Optional[int],  # noqa: UP007
    follow: bool,
    level: Optional[str],  # noqa: UP007
    session: Optional[str],  # noqa: UP007
    since: Optional[str],  # noqa: UP007
    component: Optional[str],  # noqa: UP007
) -> None:
    """Forward to `docker compose -f <root>/docker-compose.yml logs platform`."""
    from rich.console import Console

    console = Console()

    # Reject Hermes-only flags with a clear error — they have no
    # equivalent on docker compose logs.
    bad_flags: list[str] = []
    if level is not None:
        bad_flags.append('--level')
    if session is not None:
        bad_flags.append('--session')
    if since is not None:
        bad_flags.append('--since')
    if component is not None:
        bad_flags.append('--component')
    if bad_flags:
        console.print(
            f'[red bold]✗[/] These flags are not supported with `myah logs platform`: '
            f"{', '.join(bad_flags)}.\n"
            "[dim]They're Hermes-specific. Use `-n N` / `-f` only for the platform log.[/]"
        )
        raise typer.Exit(code=2)

    try:
        repo_root = find_repo_root()
    except RuntimeError as err:
        console.print(
            '[red bold]✗[/] Not inside a Myah clone — '
            '`docker compose` cannot find docker-compose.yml.'
        )
        console.print(f'[dim]  {err}[/]')
        console.print(
            '[dim]  Hint: cd into the directory where you cloned the repo or '
            'ran `myah install`.[/]'
        )
        raise typer.Exit(code=2) from None

    compose_file = repo_root / 'docker-compose.yml'
    argv = [
        'docker',
        'compose',
        '-f',
        str(compose_file),
        'logs',
        'platform',
    ]
    if lines is not None:
        argv.extend(['--tail', str(lines)])
    if follow:
        argv.append('--follow')

    # stdio passes through to the user's terminal (no capture); `-f`
    # tails live without buffering and the subprocess exit code
    # propagates verbatim.
    _run_or_exit(
        argv,
        not_found_hint=(
            "Install Docker Desktop (macOS/Windows) or your distro's docker "
            'package, then re-run.'
        ),
    )


def _run_hermes_logs(
    *,
    log_name: Optional[str],  # noqa: UP007
    lines: Optional[int],  # noqa: UP007
    follow: bool,
    level: Optional[str],  # noqa: UP007
    session: Optional[str],  # noqa: UP007
    since: Optional[str],  # noqa: UP007
    component: Optional[str],  # noqa: UP007
) -> None:
    """Forward to `<hermes-bin> logs [LOG_NAME] [flags...]`."""
    hermes_bin = resolve_hermes_binary_or_exit(command_hint='for `myah logs`')

    argv: list[str] = [str(hermes_bin), 'logs']
    if log_name is not None:
        argv.append(log_name)
    if lines is not None:
        argv.extend(['-n', str(lines)])
    if follow:
        argv.append('-f')
    if level is not None:
        argv.extend(['--level', level])
    if session is not None:
        argv.extend(['--session', session])
    if since is not None:
        argv.extend(['--since', since])
    if component is not None:
        argv.extend(['--component', component])

    # Hermes binary was resolved by `resolve_hermes_binary_or_exit`
    # moments ago; FileNotFoundError here means a TOCTOU race
    # (binary disappeared between resolution and run). Rare but real
    # — surface a clear hint instead of a Python traceback.
    _run_or_exit(
        argv,
        not_found_hint='Re-run `myah install` to reinstall the Hermes binary.',
    )


def _run_or_exit(argv: list[str], *, not_found_hint: str) -> None:
    """Run ``argv`` with stdio passthrough; propagate exit code.

    Wraps ``subprocess.run`` so that a missing binary (``FileNotFoundError``,
    raised by the OS when ``argv[0]`` isn't on PATH or has vanished) is
    reported as a Rich-styled error with ``not_found_hint`` and exit
    code 2 — never a raw Python traceback to the user.

    On any other return path: a non-zero ``returncode`` raises
    ``typer.Exit`` with the same code; a zero return falls through
    silently.
    """
    try:
        completed = subprocess.run(argv, check=False)  # noqa: S603 — args are not user-controlled
    except FileNotFoundError as err:
        from rich.console import Console

        Console().print(
            f'[red bold]✗[/] Binary not found: [cyan]{argv[0]}[/]\n'
            f'[dim]  {err}[/]\n'
            f'[dim]  Hint: {not_found_hint}[/]'
        )
        raise typer.Exit(code=2) from None
    if completed.returncode != 0:
        raise typer.Exit(code=completed.returncode)


__all__ = ['logs_command']
