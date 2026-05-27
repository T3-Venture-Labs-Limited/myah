"""`myah platform {up,down,restart}` — manage the FastAPI platform container.

Slice 5 Task 5.3 of T3-1084 (DevX + OSS CLI).

Native — no Hermes equivalent. The "platform" here is the FastAPI
platform container declared in the repo-root ``docker-compose.yml``,
NOT the Hermes agent (use ``myah agent`` for that) and NOT the
per-worktree dev stack (use ``myah dev oss`` for that).

Each subcommand is a thin wrapper around ``docker compose -f
<repo-root>/docker-compose.yml <verb>`` with two pre-flights:

  1. ``shutil.which('docker')`` — fail fast with an install hint if
     docker isn't on PATH.
  2. ``find_repo_root()`` — fail fast if the user is outside a Myah
     clone (no ``agent/Dockerfile.stock`` or ``versions.env`` sentinel).

Both pre-flight failures exit 2 (distinct from docker compose's own
non-zero exits, which propagate verbatim).

The ``up`` form always passes ``-d`` (detached); ``down`` does NOT
remove volumes (footgun guard — the SQLite DB lives in a named volume).
Users who want the full docker-compose API can still invoke
``docker compose ...`` directly.

Cold-start budget: Rich lives lazily inside command bodies; ``shutil``
and ``typer`` at the top are stdlib-cheap. The Typer subgroup variable
is intentionally named ``platform_app`` to avoid colliding with stdlib
``platform``.

# Platform up. The compose file already knows what to build, what to
# bind, what to remember. We just speak its dialect to the daemon.
"""

from __future__ import annotations

import shutil

import typer

# Module-level aliases so tests patch at the consumer namespace
# (`myah.cli.platform_.run`, `myah.cli.platform_.find_repo_root`,
# `myah.cli.platform_.shutil.which`). Mirrors Slices 2-4 mocking
# discipline; never patch source modules.
from myah.lib.cli.output import emit_result_or_exit
from myah.lib.cli.repo import find_repo_root
from myah.lib.cli.shell import run

platform_app = typer.Typer(
    name='platform',
    help='Manage the Myah FastAPI platform container (docker compose wrapper).',
    no_args_is_help=True,
)


def _preflight_or_exit() -> list[str]:
    """Run docker + repo-root pre-flight and return the base argv prefix.

    Returns ``['docker', 'compose', '-f', '<root>/docker-compose.yml']``
    on success; raises ``typer.Exit(2)`` with a Rich-styled message on
    either pre-flight failure. Heavy Rich import stays lazy.
    """
    if shutil.which('docker') is None:
        from rich.console import Console

        Console().print(
            '[red bold]docker is not installed or not in PATH.[/]\n'
            '[dim]Install Docker Desktop (macOS / Windows) or your distro\'s docker '
            'package (Linux), then re-run.[/]'
        )
        raise typer.Exit(code=2)

    try:
        repo_root = find_repo_root()
    except RuntimeError as err:
        from rich.console import Console

        console = Console()
        console.print(
            '[red bold]✗[/] Not inside a Myah clone — '
            '`docker compose` cannot find docker-compose.yml.'
        )
        # Surface find_repo_root's diagnostic verbatim — it enumerates
        # the sentinels searched (agent/Dockerfile.stock, versions.env)
        # and the directory walk start, which is the actionable hint.
        console.print(f'[dim]  {err}[/]')
        console.print(
            '[dim]  Hint: cd into the directory where you cloned the repo or '
            'ran `myah install`.[/]'
        )
        raise typer.Exit(code=2) from None

    compose_file = repo_root / 'docker-compose.yml'
    # Bare 'docker' in argv: subprocess does PATH resolution, and we
    # already verified docker is on PATH via shutil.which() above.
    # Same idiom every docker-compose script in the repo uses.
    return ['docker', 'compose', '-f', str(compose_file)]


@platform_app.command('up')
def platform_up() -> None:
    """Start the platform container (detached)."""
    base = _preflight_or_exit()
    emit_result_or_exit(run([*base, 'up', '-d']))


@platform_app.command('down')
def platform_down() -> None:
    """Stop the platform container.

    Does NOT remove volumes — the SQLite DB lives in a named volume,
    and `down -v` would silently destroy user data. To remove volumes
    explicitly, run `docker compose down -v` yourself.
    """
    base = _preflight_or_exit()
    emit_result_or_exit(run([*base, 'down']))


@platform_app.command('restart')
def platform_restart() -> None:
    """Restart the platform container."""
    base = _preflight_or_exit()
    emit_result_or_exit(run([*base, 'restart']))


__all__ = ['platform_app']
