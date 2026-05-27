"""`myah dev hermes {link-main,unlink-main,config {show,edit,validate}}`.

The escape hatch + worktree-scoped Hermes ops. Two surfaces:

- `link-main` / `unlink-main`: rewrite `<worktree>/.worktree-env` so the
  worktree's processes read from main `~/.hermes/` instead of the
  per-worktree `<worktree>/.hermes/`. Loud confirmation on the
  outbound direction (you're about to mutate the user's real Hermes
  install); silent on the inbound (safe).

- `config {show,edit,validate}`: thin wrappers around upstream
  `hermes config {show,edit,check}`. Always invoke
  `<worktree>/.venv/bin/hermes` by absolute path (Investigation C —
  bare `hermes` would PATH-resolve to whatever Hermes was installed
  globally). HERMES_HOME is injected via env-merge so PATH and the
  rest of the parent environment survive.

Heavy imports (Rich, the shell wrapper) live inside command bodies so
`myah --help` cold-start stays under the 200ms budget.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import typer

# Module-level aliases so tests patch at the consumer namespace
# (`myah.cli.dev.hermes.X`), never on source modules.
from myah.lib.cli.shell import run
from myah.lib.cli.worktree_paths import get_worktree_path

hermes_app = typer.Typer(
    name='hermes',
    help='Worktree-scoped Hermes ops + escape hatch.',
    no_args_is_help=True,
)
config_app = typer.Typer(
    name='config',
    help='Worktree-scoped Hermes config.',
    no_args_is_help=True,
)


# "The worktree keeps its own .hermes. Sometimes the work needs the main
#  one. Open the door loudly; close it quietly." — hermes.py


# ---------------------------------------------------------------------------
# Worktree resolver + running-process detection (mirrors mode.py)
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


def _is_port_listening(port: int) -> bool:
    """True if anything is listening on `port` on localhost.

    Duplicated from `cli/dev/server.py` + `cli/dev/mode.py` deliberately —
    keeping the consumer-namespace mock surface clean. Six lines is not
    worth a cross-module import dependency in the test patch target table.
    """
    import socket

    try:
        with socket.create_connection(('127.0.0.1', port), timeout=0.5):
            return True
    except OSError:
        return False


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
            f'restart with [bold]myah dev restart[/] to apply new HERMES_HOME'
        )
    if frontend_port and _is_port_listening(frontend_port):
        console.print(
            f'[yellow]![/] frontend running on :[cyan]{frontend_port}[/] — '
            f'restart with [bold]myah dev restart[/] to apply new HERMES_HOME'
        )


def _effective_hermes_home(worktree: Path) -> Path:
    """Compute HERMES_HOME for this worktree.

    Reads `.worktree-env`; if HERMES_HOME is set, expand `~` and return it.
    Otherwise default to `<worktree>/.hermes`. `parse_env_file` does NOT
    expand shell variables, so we call `os.path.expanduser` defensively.
    """
    from myah.lib.cli.env_loader import parse_env_file

    env = parse_env_file(worktree / '.worktree-env')
    raw = env.get('HERMES_HOME', '').strip()
    if raw:
        return Path(os.path.expanduser(raw))
    return worktree / '.hermes'


def _hermes_binary(worktree: Path) -> Path:
    """Absolute path to the worktree's venv hermes binary (no PATH lookup)."""
    return worktree / '.venv' / 'bin' / 'hermes'


def _require_hermes_binary(worktree: Path) -> Path:
    """Return the hermes binary path or exit 2 with a clear message."""
    from rich.console import Console

    bin_path = _hermes_binary(worktree)
    if not bin_path.is_file():
        Console().print(
            f"[red bold]Worktree's hermes binary not found[/] at [cyan]{bin_path}[/].\n"
            f'[dim]Was this worktree created with [bold]myah dev worktree create <branch>[/]? '
            f'Older worktrees made by the legacy [bold]scripts/setup-worktree.sh[/] use a '
            f'symlinked venv and do not have a per-worktree hermes binary.[/]'
        )
        raise typer.Exit(code=2)
    return bin_path


# ---------------------------------------------------------------------------
# link-main / unlink-main
# ---------------------------------------------------------------------------


@hermes_app.command('link-main')
def link_main() -> None:
    """Point this worktree at main ~/.hermes/ (escape hatch)."""
    from rich.console import Console

    from myah.lib.cli.worktree_setup import set_env_var

    console = Console()
    worktree = _resolve_worktree_or_exit()

    console.print(
        "[yellow bold]⚠  This will point this worktree's processes at your main "
        '[cyan]~/.hermes/[/].[/]\n'
        '[dim]   Changes made during this session — config edits, plugin installs,\n'
        '   env-var writes, accumulated conversations — will affect your real\n'
        '   Hermes install.[/]\n'
    )
    confirmed = typer.confirm('Proceed?', default=False, abort=False)
    if not confirmed:
        console.print('[dim]Aborted.[/]')
        raise typer.Exit(code=0)

    # parse_env_file does not expand shell variables — write the absolute path.
    main_hermes = Path.home() / '.hermes'
    set_env_var(worktree / '.worktree-env', 'HERMES_HOME', str(main_hermes))

    own_hermes = worktree / '.hermes'
    console.print(
        f'[green]✓[/] Linked to main [cyan]{main_hermes}[/]. '
        f"The worktree's own [cyan]{own_hermes}[/] is preserved but bypassed."
    )
    _maybe_print_restart_hint(worktree)


@hermes_app.command('unlink-main')
def unlink_main() -> None:
    """Restore HERMES_HOME=<worktree>/.hermes (safe direction)."""
    from rich.console import Console

    from myah.lib.cli.worktree_setup import set_env_var

    worktree = _resolve_worktree_or_exit()
    own_hermes = worktree / '.hermes'
    set_env_var(worktree / '.worktree-env', 'HERMES_HOME', str(own_hermes))

    console = Console()
    console.print(f'[green]✓[/] Unlinked. HERMES_HOME=[cyan]{own_hermes}[/]')
    _maybe_print_restart_hint(worktree)


# ---------------------------------------------------------------------------
# config show / edit / validate
# ---------------------------------------------------------------------------


def _build_hermes_env(hermes_home: Path) -> dict[str, str]:
    """Compose the subprocess env: parent os.environ + HERMES_HOME override.

    The env-merge invariant: we MUST preserve PATH (and the rest of the
    parent environment). Passing only `{'HERMES_HOME': ...}` strips PATH
    and breaks the subprocess. Verified by
    `test_config_show_passes_hermes_home_via_env_merge`.
    """
    return {**os.environ, 'HERMES_HOME': str(hermes_home)}


@config_app.command('show')
def config_show() -> None:
    """Print the worktree's effective Hermes config.yaml."""
    from rich.console import Console

    worktree = _resolve_worktree_or_exit()
    hermes_bin = _require_hermes_binary(worktree)
    hermes_home = _effective_hermes_home(worktree)

    result = run(
        [str(hermes_bin), 'config', 'show'],
        env=_build_hermes_env(hermes_home),
    )
    # Surface stdout (and any stderr noise) to the user, then propagate exit.
    console = Console()
    if result.stdout:
        console.print(result.stdout, end='')
    if result.stderr:
        console.print(result.stderr, end='')
    if result.returncode != 0:
        raise typer.Exit(code=result.returncode)


@config_app.command('edit')
def config_edit() -> None:
    """Open the worktree's Hermes config.yaml in $EDITOR."""
    worktree = _resolve_worktree_or_exit()
    hermes_bin = _require_hermes_binary(worktree)
    hermes_home = _effective_hermes_home(worktree)

    # Interactive editor needs stdio passthrough; `shell.run` captures
    # output, which would break the editor. Use `subprocess.run` directly
    # here. HERMES_HOME is still injected via env-merge.
    completed = subprocess.run(  # noqa: S603 — args are not user-controlled
        [str(hermes_bin), 'config', 'edit'],
        env=_build_hermes_env(hermes_home),
        check=False,
    )
    if completed.returncode != 0:
        raise typer.Exit(code=completed.returncode)


@config_app.command('validate')
def config_validate() -> None:
    """Validate the worktree's Hermes config.yaml (wraps `hermes config check`)."""
    from rich.console import Console

    worktree = _resolve_worktree_or_exit()
    hermes_bin = _require_hermes_binary(worktree)
    hermes_home = _effective_hermes_home(worktree)

    result = run(
        [str(hermes_bin), 'config', 'check'],
        env=_build_hermes_env(hermes_home),
    )
    console = Console()
    if result.stdout:
        console.print(result.stdout, end='')
    if result.stderr:
        console.print(result.stderr, end='')
    if result.returncode != 0:
        raise typer.Exit(code=result.returncode)


hermes_app.add_typer(config_app, name='config')


__all__ = ['hermes_app']
