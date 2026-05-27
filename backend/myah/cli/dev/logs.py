"""`myah dev logs` — unified parallel tail of worktree-scoped log files.

The unified-log-surface goal of the DevX initiative. Tails up to five
sources in parallel with color-coded prefixes:

    backend    cyan     <worktree>/.worktree-logs/backend.log
    frontend   magenta  <worktree>/.worktree-logs/frontend.log
    gateway    yellow   <worktree>/.worktree-logs/gateway.log       (Slice 3+)
    dashboard  green    <worktree>/.worktree-logs/dashboard.log     (Slice 3+)
    plugin     blue     <worktree>/.worktree-logs/plugin.log        (Slice 3+)

Missing files are non-fatal — only the present subset is tailed. Ctrl+C
cleanly drains and exits 0.

Heavy imports (Rich, threading) live inside the command body so
`myah --help` cold-start stays under the 200 ms budget.
"""

from __future__ import annotations

from pathlib import Path

import typer

# Module-level alias for `tail_logs` so tests can patch
# `myah.cli.dev.logs.tail_logs` (consumer namespace).
from myah.lib.cli.log_multiplex import tail_logs


# "Many threads, one terminal. May the lines arrive together." — logs.


# The catalog drives both the default sweep and the validation of the
# `services` positional argument. Order is insertion order: the priority
# in which we list catalog entries. The names are stable identifiers
# exposed to end users (used both as the prefix and the filter token).
_CATALOG: dict[str, tuple[str, str]] = {
    'backend': ('backend.log', 'cyan'),
    'frontend': ('frontend.log', 'magenta'),
    'gateway': ('gateway.log', 'yellow'),
    'dashboard': ('dashboard.log', 'green'),
    'plugin': ('plugin.log', 'blue'),
}

# Width of the prefix column when rendering. Equal to the longest catalog
# name ('dashboard' = 9 chars). Visually aligns lines from all sources.
_PREFIX_WIDTH = 9


def _get_worktree_path() -> Path:
    """Local alias so tests can patch `myah.cli.dev.logs._get_worktree_path`.

    Wraps the library resolver and translates RuntimeError into a
    user-facing typer.Exit with a Rich-rendered error.
    """
    from rich.console import Console

    from myah.lib.cli.worktree_paths import get_worktree_path

    try:
        return get_worktree_path()
    except RuntimeError:
        Console().print(
            '[red bold]Not inside a worktree[/]: no [cyan].worktree-env[/] found '
            'walking up from CWD.\n'
            '[dim]Hint: cd into a worktree (e.g. .worktrees/<branch>) or create one with '
            '[bold]myah dev worktree create <branch>[/].[/]'
        )
        raise typer.Exit(code=2)


def logs_command(
    services: list[str] = typer.Argument(
        None,
        help=(
            'Filter to specific services (backend, frontend, gateway, dashboard, plugin). '
            'Default: tail all available services.'
        ),
    ),
    lines: int = typer.Option(50, '--lines', '-n', help='Initial backlog lines per service.'),
    no_follow: bool = typer.Option(
        False, '--no-follow', '-F', help='Print backlog then exit (no follow).'
    ),
) -> None:
    """Unified parallel tail across worktree-scoped log files."""
    import threading

    from rich.console import Console

    from myah.lib.cli.log_multiplex import LogSource

    console = Console()
    worktree = _get_worktree_path()
    log_dir = worktree / '.worktree-logs'

    # Build the LogSource list. If `services` is empty/None we walk the
    # whole catalog; otherwise we filter by user-supplied names (warning
    # on unknowns).
    if services:
        catalog_keys: list[str] = []
        for svc in services:
            if svc in _CATALOG:
                catalog_keys.append(svc)
            else:
                console.print(f'[yellow]![/] unknown service `{svc}` — skipping')
    else:
        catalog_keys = list(_CATALOG.keys())

    # Only include sources whose logfile actually exists on disk. The
    # library would skip-with-warning too, but we want a friendlier
    # message in the common "nothing started yet" case.
    sources: list[LogSource] = []
    for key in catalog_keys:
        filename, color = _CATALOG[key]
        path = log_dir / filename
        if path.is_file():
            sources.append(LogSource(name=key, path=path, color=color))

    if not sources:
        console.print(
            '[yellow]No log files found.[/] Start a service with '
            '[bold]myah dev backend[/] / [bold]myah dev frontend[/].'
        )
        raise typer.Exit(code=0)

    stop_event = threading.Event()
    follow = not no_follow

    try:
        for source, line in tail_logs(
            sources,
            lines=lines,
            follow=follow,
            stop_event=stop_event,
        ):
            # `_PREFIX_WIDTH` left-pads to the width of 'dashboard' so
            # output from all sources visually aligns.
            prefix = f'{source.name:<{_PREFIX_WIDTH}}'
            console.print(f'[{source.color}]{prefix}[/] {line}', highlight=False)
    except KeyboardInterrupt:
        # Clean shutdown: signal workers, drain briefly, no traceback.
        stop_event.set()
        console.print('[dim]· stopped[/]')
        raise typer.Exit(code=0)


__all__ = ['logs_command']
