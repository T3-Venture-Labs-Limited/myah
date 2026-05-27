"""The `myah dev *` developer-only command group.

Subcommands land in subsequent slices:
- Slice 2: worktree, server (backend/frontend/both/stop/restart/status), logs
- Slice 3: mode, hermes (link-main/unlink-main/config), plugin, oss

`myah dev --help` shows the registered subcommands.
"""

from __future__ import annotations

import typer

dev_app = typer.Typer(
    name='dev',
    help='Developer-only commands.',
    no_args_is_help=True,  # `myah dev` (no subcommand) shows help instead of erroring
)


def _register_worktree_group() -> None:
    """Register `myah dev worktree {create,list,destroy}` as a subgroup.

    The import is module-top inside the helper rather than the top of
    this file so the cold-start budget stays close to the Slice 1
    measurement — `typer` itself is already imported here. The
    orchestrator library + Rich are deferred inside the command
    bodies in `worktree.py`.
    """
    from myah.cli.dev.worktree import worktree_app

    dev_app.add_typer(
        worktree_app,
        name='worktree',
        help='Per-worktree lifecycle (create / list / destroy).',
    )


def _register_server_commands() -> None:
    """Register the flat-under-dev server commands.

    These are NOT a subgroup — per spec, `myah dev backend`, not
    `myah dev server backend`. The imports stay inside this helper so
    `server.py`'s lazy Rich/Popen/socket imports don't run at
    `myah --help` time; only the command functions themselves are
    pulled in here (they're tiny).
    """
    from myah.cli.dev.server import (
        backend as backend_cmd,
    )
    from myah.cli.dev.server import (
        both as both_cmd,
    )
    from myah.cli.dev.server import (
        frontend as frontend_cmd,
    )
    from myah.cli.dev.server import (
        restart as restart_cmd,
    )
    from myah.cli.dev.server import (
        status as status_cmd,
    )
    from myah.cli.dev.server import (
        stop as stop_cmd,
    )
    dev_app.command(name='backend', help='Start backend uvicorn server (background)')(backend_cmd)
    dev_app.command(name='frontend', help='Start frontend vite server (background)')(frontend_cmd)
    dev_app.command(name='both', help='Start backend + frontend')(both_cmd)
    dev_app.command(name='stop', help='Stop backend + frontend')(stop_cmd)
    dev_app.command(name='restart', help='Stop then start both')(restart_cmd)
    dev_app.command(name='status', help='Show backend + frontend status')(status_cmd)


def _register_logs_command() -> None:
    """Register `myah dev logs` — unified parallel tail of worktree logs.

    Lazy import keeps the cold-start budget intact: the heavy Rich/threading
    imports live inside `logs_command`'s body, not at module load.
    """
    from myah.cli.dev.logs import logs_command

    dev_app.command(name='logs', help='Unified parallel tail of worktree log files')(logs_command)


def _register_mode_commands() -> None:
    """Register `myah dev mode {oss,hosted,show}` as a subgroup.

    Lazy import keeps cold-start under 200ms — the mode module pulls in
    Rich + lib.cli.mode_switch only at first invocation, not at
    `myah --help` time.
    """
    from myah.cli.dev.mode import mode_app

    dev_app.add_typer(
        mode_app,
        name='mode',
        help='Switch worktree mode between oss and hosted.',
    )


def _register_hermes_group() -> None:
    """Register `myah dev hermes {link-main,unlink-main,config {show,edit,validate}}`.

    Lazy import — `hermes.py` defers Rich + subprocess wiring to command
    bodies, so module load here is typer-only and cheap.
    """
    from myah.cli.dev.hermes import hermes_app

    dev_app.add_typer(
        hermes_app,
        name='hermes',
        help='Worktree-scoped Hermes ops + escape hatch.',
    )


def _register_plugin_group() -> None:
    """Register `myah dev plugin {install-local,install-pinned}`.

    Lazy import — `plugin.py` defers Rich + subprocess wiring to command
    bodies, so module load here is typer-only and cheap.
    """
    from myah.cli.dev.plugin import plugin_app

    dev_app.add_typer(
        plugin_app,
        name='plugin',
        help='Worktree-scoped plugin local-dev workflow.',
    )


def _register_oss_group() -> None:
    """Register `myah dev oss {up,down,restart,status}`.

    Lazy import — `oss.py` defers Rich + Popen + socket + urllib to
    command bodies, so module load here is typer-only and cheap.
    """
    from myah.cli.dev.oss import oss_app

    dev_app.add_typer(
        oss_app,
        name='oss',
        help='Worktree-scoped Hermes gateway + dashboard lifecycle.',
    )


_register_worktree_group()
_register_server_commands()
_register_logs_command()
_register_mode_commands()
_register_hermes_group()
_register_plugin_group()
_register_oss_group()
