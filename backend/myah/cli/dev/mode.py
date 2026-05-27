"""`myah dev mode {oss,hosted,show}` — flip a worktree between deployment modes.

A thin Typer wrapper around `myah.lib.cli.mode_switch` plus a Rich-rendered
`show` table. Heavy imports (Rich, the lib helper) live inside command bodies
so `myah --help` cold-start stays under the 200ms budget.

Restart behavior: if backend/frontend are running when a switch happens we
print a hint pointing at `myah dev restart` — we do NOT auto-restart in this
PR. The hint is sufficient and keeps the test surface small.
"""

from __future__ import annotations

from pathlib import Path

import typer

# Module-level aliases so tests patch at the consumer namespace
# (`myah.cli.dev.mode.X`), never on the source modules.
from myah.lib.cli.worktree_paths import get_worktree_path
from myah.lib.cli.worktree_setup import resolve_main_repo_root

mode_app = typer.Typer(
    name='mode',
    help='Switch worktree mode between oss and hosted (or show current state).',
    no_args_is_help=True,
)


# "Two doors, one room. Choose which sign hangs on the door —
#  the room remembers nothing else." — mode.py


# ---------------------------------------------------------------------------
# Worktree resolver — Rich-styled error path
# ---------------------------------------------------------------------------


def _resolve_worktree_or_exit() -> Path:
    from rich.console import Console

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


# ---------------------------------------------------------------------------
# Running-process detection (for the restart hint)
# ---------------------------------------------------------------------------


def _is_port_listening(port: int) -> bool:
    """True if anything is listening on `port` on localhost.

    Duplicated from `cli/dev/server.py` deliberately — keeping the
    consumer-namespace mock surface clean. The function is six lines;
    DRY is not worth a cross-module import dependency in the test patch
    target table.
    """
    import socket

    try:
        with socket.create_connection(('127.0.0.1', port), timeout=0.5):
            return True
    except OSError:
        return False


# TODO(post-cli-cleanup): auto-restart backend/frontend when mode switches.
# Today we only print a hint pointing at `myah dev restart`. Auto-restart
# adds test surface area (race between stop + new uvicorn binding the
# same port) so it's deferred. See T3-1084 initiative-complete summary
# for the post-CLI follow-up backlog.
def _maybe_print_restart_hint(worktree: Path) -> None:
    """If backend/frontend are running, print a hint to restart them."""
    from rich.console import Console

    from myah.lib.cli.env_loader import parse_env_file

    worktree_env = parse_env_file(worktree / '.worktree-env')
    try:
        backend_port = int(worktree_env.get('BACKEND_PORT', '0'))
        frontend_port = int(worktree_env.get('FRONTEND_PORT', '0'))
    except ValueError:
        return

    console = Console()
    if backend_port and _is_port_listening(backend_port):
        console.print(
            f'[yellow]![/] backend running on :[cyan]{backend_port}[/] — '
            f'restart with [bold]myah dev restart[/] to apply new mode'
        )
    if frontend_port and _is_port_listening(frontend_port):
        console.print(
            f'[yellow]![/] frontend running on :[cyan]{frontend_port}[/] — '
            f'restart with [bold]myah dev restart[/] to apply new mode'
        )


# ---------------------------------------------------------------------------
# Subcommands
# ---------------------------------------------------------------------------


@mode_app.command('oss')
def mode_oss() -> None:
    """Switch the current worktree to OSS mode."""
    from rich.console import Console

    from myah.lib.cli.mode_switch import switch_to_oss

    worktree = _resolve_worktree_or_exit()
    switch_to_oss(worktree)

    console = Console()
    console.print('[green]✓[/] worktree switched to [bold]oss[/] mode')
    console.print(f'[dim]  edited:[/] {worktree / "platform-oss" / ".env"}')

    _maybe_print_restart_hint(worktree)


@mode_app.command('hosted')
def mode_hosted() -> None:
    """Switch the current worktree to hosted mode."""
    from rich.console import Console

    from myah.lib.cli.mode_switch import switch_to_hosted

    worktree = _resolve_worktree_or_exit()

    try:
        main_repo_root = resolve_main_repo_root(worktree)
    except Exception as exc:  # noqa: BLE001 — surface the failure clearly
        Console().print(f'[red bold]Could not locate main repo root[/]: {exc}')
        raise typer.Exit(code=2) from exc

    switch_to_hosted(worktree, main_repo_root)

    console = Console()
    console.print('[green]✓[/] worktree switched to [bold]hosted[/] mode')
    console.print(f'[dim]  edited:[/] {worktree / "platform-oss" / ".env"}')
    # TODO(post-cli-cleanup): auto-install composio + honcho-ai into
    # <worktree>/.venv when switching to hosted mode. Today we only print a
    # hint and let the user run `pip install` themselves; doing it inline
    # here means we need pip-install-while-running logic + failure handling,
    # which deserves its own PR. See T3-1084 initiative-complete summary.
    console.print(
        '[dim]  hint: hosted mode needs [cyan]composio[/] + [cyan]honcho-ai[/] in the '
        'worktree venv (auto-install is a follow-up PR — install manually for now).[/]'
    )

    _maybe_print_restart_hint(worktree)


@mode_app.command('show')
def mode_show() -> None:
    """Print the current mode plus a Rich table of mode-relevant env state."""
    from rich.console import Console
    from rich.table import Table

    from myah.lib.cli.env_loader import parse_env_file
    from myah.lib.cli.mode_switch import get_current_mode

    worktree = _resolve_worktree_or_exit()
    env_path = worktree / 'platform-oss' / '.env'
    env = parse_env_file(env_path)
    mode = get_current_mode(worktree)

    console = Console()
    console.print(f'[bold]current mode:[/] [cyan]{mode}[/]')
    console.print(f'[dim]source:[/] {env_path}')

    def _redacted(key: str) -> str:
        value = env.get(key, '').strip()
        return '[green]set[/]' if value else '[dim]unset[/]'

    def _literal(key: str) -> str:
        value = env.get(key, '').strip()
        return f'[cyan]{value}[/]' if value else '[dim]unset[/]'

    table = Table(title='Mode-relevant env', show_header=True, header_style='bold')
    table.add_column('Key', style='cyan')
    table.add_column('Value')

    # Literals (these are flags, not secrets).
    table.add_row('MYAH_DEPLOYMENT_MODE', _literal('MYAH_DEPLOYMENT_MODE'))
    table.add_row('MYAH_AUTH', _literal('MYAH_AUTH'))
    # Redacted (real secrets — never echo to the terminal).
    table.add_row('COMPOSIO_API_KEY', _redacted('COMPOSIO_API_KEY'))
    table.add_row('HONCHO_ADMIN_KEY', _redacted('HONCHO_ADMIN_KEY'))
    table.add_row('HONCHO_BASE_URL', _literal('HONCHO_BASE_URL'))
    table.add_row('HONCHO_WORKSPACE_ID', _literal('HONCHO_WORKSPACE_ID'))
    table.add_row('OAUTH_SESSION_TOKEN_ENCRYPTION_KEY', _redacted('OAUTH_SESSION_TOKEN_ENCRYPTION_KEY'))

    console.print(table)


__all__ = ['mode_app']
