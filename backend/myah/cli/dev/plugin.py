"""`myah dev plugin {install-local,install-pinned}` — worktree-scoped plugin local-dev.

Two surfaces:

- `install-local PATH`: editable install of a local plugin checkout. The
  seven-step flow (Slice 3 Task 3.3):
    1. Validate PATH has a pyproject.toml with name="myah-hermes-plugin"
    2. `pip uninstall -y myah-hermes-plugin` (tolerate exit 1 — no-op if absent)
    3. `pip install -e <abspath>` (editable install)
    4. Verify upstream `myah-hermes-plugin install --dashboard-only` flag exists
       (M5 reviewer finding — could be removed by upstream plugin change)
    5. Re-materialize the dashboard shim. CRITICAL — without this, the shim's
       plugin_api.py points at the OLD package while sys.path resolves to the
       new editable source.
    6. Sanity-check the shim's import resolves to the editable source. Warn
       loudly if not, but do NOT abort.
    7. Print restart hint if backend/frontend ports are listening.

- `install-pinned`: reverts to the pinned-SHA install. Reuses Slice 2's
  `install_plugin_into_hermes` + `materialize_dashboard_shim` primitives.

Heavy imports (Rich, lib primitives) live inside command bodies so
`myah --help` cold-start stays under the 200ms budget.
"""

from __future__ import annotations

import os
import tomllib
from pathlib import Path

import typer

# Module-level aliases so tests patch at the consumer namespace
# (`myah.cli.dev.plugin.X`), never on source modules.
from myah.lib.cli.shell import run
from myah.lib.cli.worktree_paths import get_worktree_path
from myah.lib.cli.worktree_setup import (
    _read_plugin_sha,
    install_plugin_into_hermes,
    materialize_dashboard_shim,
    resolve_main_repo_root,
)

plugin_app = typer.Typer(
    name='plugin',
    help='Worktree-scoped plugin local-dev workflow.',
    no_args_is_help=True,
)


# "Two installs share one home: the pinned one, true to the canon, and
#  the editable one, open to the moment. Both need the shim re-laid
#  before the dashboard remembers where to look." — plugin.py


# ---------------------------------------------------------------------------
# Shared helpers (mirrored from mode.py / hermes.py — see PR 3.A/3.B for the
# deliberate-dup pattern; extraction to a runtime helper is a follow-up).
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
    """True if anything is listening on `port` on localhost. See mode.py / hermes.py."""
    import socket

    try:
        with socket.create_connection(('127.0.0.1', port), timeout=0.5):
            return True
    except OSError:
        return False


def _maybe_print_restart_hint(worktree: Path) -> None:
    """Print a restart hint if backend/frontend ports are listening."""
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
            f'restart with [bold]myah dev restart[/] to apply the new plugin install'
        )
    if frontend_port and _is_port_listening(frontend_port):
        console.print(
            f'[yellow]![/] frontend running on :[cyan]{frontend_port}[/] — '
            f'restart with [bold]myah dev restart[/] to apply the new plugin install'
        )


def _require_venv_pip_or_exit(worktree: Path) -> Path:
    """Return the worktree's venv pip path, or exit 2 with a clear hint."""
    from rich.console import Console

    pip = worktree / '.venv' / 'bin' / 'pip'
    if not pip.is_file():
        Console().print(
            f"[red bold]Worktree's venv pip not found[/] at [cyan]{pip}[/].\n"
            '[dim]Was this worktree created with [bold]myah dev worktree create <branch>[/]?[/]'
        )
        raise typer.Exit(code=2)
    return pip


# ---------------------------------------------------------------------------
# install-local — the seven-step editable-install flow
# ---------------------------------------------------------------------------


def install_local(
    path: Path = typer.Argument(..., help='Path to a local myah-hermes-plugin checkout'),
) -> None:
    """Install a local plugin checkout in editable mode + re-materialize the shim."""
    from rich.console import Console

    console = Console()
    worktree = _resolve_worktree_or_exit()
    abs_path = path.resolve()  # editable install demands an absolute path

    # Step 1: validate pyproject.toml exists and has name="myah-hermes-plugin"
    pyproject = abs_path / 'pyproject.toml'
    if not pyproject.is_file():
        console.print(f'[red bold]error[/]: no [cyan]pyproject.toml[/] at {pyproject}')
        raise typer.Exit(code=2)

    try:
        parsed = tomllib.loads(pyproject.read_text(encoding='utf-8'))
    except tomllib.TOMLDecodeError as exc:
        console.print(f'[red bold]error[/]: could not parse {pyproject}: {exc}')
        raise typer.Exit(code=2)

    project_name = parsed.get('project', {}).get('name', '')
    if project_name != 'myah-hermes-plugin':
        console.print(
            f'[red bold]error[/]: pyproject.toml at {pyproject} has '
            f'name=[yellow]{project_name!r}[/], expected [cyan]"myah-hermes-plugin"[/].'
        )
        raise typer.Exit(code=2)

    pip = _require_venv_pip_or_exit(worktree)

    # Step 2: uninstall any existing install. `pip uninstall` of a missing
    # package returns 1 — tolerate it; the install we are about to do
    # would fail anyway if there is a real conflict.
    console.print('[bold]→[/] Uninstalling previously-installed [cyan]myah-hermes-plugin[/] (if any)')
    run([str(pip), 'uninstall', '-y', 'myah-hermes-plugin'])

    # Step 3: editable install.
    console.print(f'[bold]→[/] Editable install from [cyan]{abs_path}[/]')
    install_result = run([str(pip), 'install', '-e', str(abs_path)])
    if install_result.returncode != 0:
        console.print(
            f'[red bold]editable install failed[/] (exit {install_result.returncode}):\n'
            f'{install_result.stderr}'
        )
        raise typer.Exit(code=install_result.returncode)

    # Step 4: verify upstream `myah-hermes-plugin install --dashboard-only` still exists.
    plugin_bin = worktree / '.venv' / 'bin' / 'myah-hermes-plugin'
    if not plugin_bin.is_file():
        console.print(
            f'[red bold]error[/]: [cyan]myah-hermes-plugin[/] binary not found at '
            f'{plugin_bin}.\n[dim]The editable install should have created this '
            'entry point — check the pyproject.toml [project.scripts] table.[/]'
        )
        raise typer.Exit(code=2)

    help_result = run([str(plugin_bin), 'install', '--help'])
    if 'dashboard-only' not in help_result.stdout:
        console.print(
            '[red bold]error[/]: [cyan]myah-hermes-plugin install --dashboard-only[/] '
            'flag missing.\n'
            '[dim]Plugin version compatibility issue. The flag must exist for shim '
            're-materialization to work. Bump or pin a plugin checkout that still '
            'ships --dashboard-only.[/]'
        )
        raise typer.Exit(code=2)

    # Step 5: re-materialize the dashboard shim.
    # CRITICAL — per spec audit: without this, the shim's plugin_api.py points
    # at the OLD package while sys.path resolves to the new editable source.
    plugins_dir = worktree / '.hermes' / 'plugins'
    console.print(f'[bold]→[/] Re-materializing dashboard shim at [cyan]{plugins_dir}[/]')
    # env-merge — never replace — so PATH (and the rest of os.environ) survive.
    env = {**os.environ, 'HERMES_HOME': str(worktree / '.hermes')}
    materialize_result = run(
        [str(plugin_bin), 'install', '--dashboard-only', '--target', str(plugins_dir)],
        env=env,
    )
    if materialize_result.returncode != 0:
        console.print(
            f'[red bold]shim re-materialization failed[/] (exit '
            f'{materialize_result.returncode}):\n{materialize_result.stderr}'
        )
        raise typer.Exit(code=materialize_result.returncode)

    # Step 6: sanity-check that `python -c "import myah_hermes_plugin; print(__file__)"`
    # resolves to the editable source. Warn loudly on mismatch — do NOT abort,
    # because the user may still want to ship the editable install and the
    # mismatch may be a sys.path quirk we can't fix from here.
    venv_python = worktree / '.venv' / 'bin' / 'python'
    verify_result = run([
        str(venv_python),
        '-c',
        'import myah_hermes_plugin; print(myah_hermes_plugin.__file__)',
    ])
    if verify_result.returncode == 0:
        resolved = verify_result.stdout.strip()
        if str(abs_path) in resolved:
            console.print(f'[green]✓[/] shim resolves to editable source at [cyan]{abs_path}[/]')
        else:
            console.print(
                f'[yellow]warning[/]: dashboard shim materialized but '
                f'`import myah_hermes_plugin` resolves to [cyan]{resolved}[/], not the '
                f'editable install at [cyan]{abs_path}[/].\n'
                '[dim]Plugin local-dev may not behave as expected. Inspect sys.path '
                f'with `{venv_python} -c "import sys; print(sys.path)"`.[/]'
            )
    else:
        console.print(
            '[yellow]warning[/]: could not verify shim import resolves to editable '
            f'source — `python -c "import myah_hermes_plugin"` exited '
            f'{verify_result.returncode}.\n[dim]{verify_result.stderr.strip() or "(no stderr)"}[/]'
        )

    # Step 7: hint to restart any running processes.
    _maybe_print_restart_hint(worktree)

    console.print(f'[green]✓[/] Plugin installed in editable mode from [cyan]{abs_path}[/]')


# ---------------------------------------------------------------------------
# install-pinned — reuse Slice 2 primitives
# ---------------------------------------------------------------------------


def install_pinned() -> None:
    """Reinstall the plugin at the SHA pinned in agent/Dockerfile.stock."""
    from rich.console import Console

    console = Console()
    worktree = _resolve_worktree_or_exit()

    # Locate main repo root via the shared library helper, then read the SHA pin.
    try:
        main_root = resolve_main_repo_root(worktree)
    except Exception as exc:  # noqa: BLE001 — surface the failure clearly
        console.print(f'[red bold]error[/]: could not locate main repo root: {exc}')
        raise typer.Exit(code=2) from exc

    dockerfile = main_root / 'agent' / 'Dockerfile.stock'
    if not dockerfile.is_file():
        console.print(
            f'[red bold]error[/]: [cyan]{dockerfile}[/] not found — cannot read pinned SHA.'
        )
        raise typer.Exit(code=2)

    try:
        plugin_sha = _read_plugin_sha(dockerfile)
    except RuntimeError as exc:
        console.print(f'[red bold]error[/]: {exc}')
        raise typer.Exit(code=2) from exc

    console.print(
        f'[bold]→[/] Reinstalling plugin at pinned SHA [cyan]{plugin_sha[:12]}...[/]'
    )

    # Uninstall any existing install first (mirrors install-local step 2).
    pip = _require_venv_pip_or_exit(worktree)
    run([str(pip), 'uninstall', '-y', 'myah-hermes-plugin'])

    # Reuse Slice 2 primitives — they already do the right thing.
    try:
        install_plugin_into_hermes(worktree, plugin_sha)
    except Exception as exc:  # noqa: BLE001 — surface the failure clearly
        console.print(f'[red bold]plugin reinstall failed[/]: {exc}')
        raise typer.Exit(code=1) from exc

    try:
        materialize_dashboard_shim(worktree)
    except Exception as exc:  # noqa: BLE001 — surface the failure clearly
        console.print(f'[red bold]dashboard shim re-materialization failed[/]: {exc}')
        raise typer.Exit(code=1) from exc

    _maybe_print_restart_hint(worktree)
    console.print(f'[green]✓[/] Plugin reinstalled at SHA [cyan]{plugin_sha[:12]}[/].')


plugin_app.command('install-local', help='Editable install of a local plugin checkout')(install_local)
plugin_app.command('install-pinned', help='Reinstall plugin at the SHA pinned in Dockerfile.stock')(
    install_pinned
)


__all__ = ['plugin_app']
