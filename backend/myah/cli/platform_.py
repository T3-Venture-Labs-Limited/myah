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

import os
import shutil
from pathlib import Path

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

    # Defensive Path() wrap — find_repo_root returns Path in production,
    # but tests for the orphan pre-flight (S3) mock it to return a str.
    compose_file = Path(repo_root) / 'docker-compose.yml'
    # Bare 'docker' in argv: subprocess does PATH resolution, and we
    # already verified docker is on PATH via shutil.which() above.
    # Same idiom every docker-compose script in the repo uses.
    return ['docker', 'compose', '-f', str(compose_file)]


def _check_for_orphan_container() -> str | None:
    """Return the orphan container ID if a stale `myah-platform`
    container exists outside the current compose project, else None.

    Detects the pre-A.2 hard-coded-container-name case. Docker's
    `name=` filter is a regex; anchor with `^...$` so we match the
    EXACT pre-A.2 name and not the new compose-generated names like
    `myah-platform-1` or `myah_platform_1` (which would have been
    created by THIS compose project and are not "orphans").
    """
    result = run([
        'docker', 'ps', '-a',
        '--filter', 'name=^myah-platform$',  # anchored — exact pre-A.2 name only
        '--format', '{{.ID}}\t{{.Names}}',
    ])
    if result.returncode != 0 or not result.stdout.strip():
        return None
    # Iterate lines defensively: filter regex anchors should guarantee a
    # single match, but be tolerant of edge cases.
    for line in result.stdout.strip().splitlines():
        parts = line.split('\t')
        if len(parts) >= 2 and parts[1] == 'myah-platform':
            return parts[0]
    return None


@platform_app.command('up')
def platform_up(
    rm_orphans: bool = typer.Option(
        False, '--rm-orphans',
        help=(
            'If a stale `myah-platform` container from a previous '
            'install layout exists, force-remove it before starting. '
            'Symptom: `Conflict. The container name "/myah-platform" '
            'is already in use`. See PR #16 post-merge laptop test, '
            'simplification S3.'
        ),
    ),
    bind: str = typer.Option(
        None,
        '--bind',
        help=(
            'Host interface for the platform port binding. Default is '
            '127.0.0.1 for local-only access. Use 0.0.0.0 for '
            'Tailscale/LAN access; enable auth first on untrusted networks.'
        ),
    ),
    expose: bool = typer.Option(
        False,
        '--expose',
        help='Shortcut for --bind 0.0.0.0 so Myah is reachable over Tailscale/LAN.',
    ),
) -> None:
    """Start the platform container (detached).

    Note for direct (non-Typer) callers: when invoking this function
    directly from Python (e.g. ``quickstart_command``), pass
    ``rm_orphans=True`` explicitly. Typer's default-resolution happens
    only when the function is dispatched through the Typer app; direct
    calls receive the raw ``OptionInfo`` sentinel (which is truthy under
    ``if rm_orphans:`` — yes, this is a subtle quirk).
    """
    base = _preflight_or_exit()
    bind_host = '0.0.0.0' if expose else bind
    compose_env = None
    if bind_host:
        if bind_host not in {'127.0.0.1', 'localhost', '0.0.0.0'}:
            from rich.console import Console

            Console().print(
                '[red]✗[/] unsupported --bind value. Use '
                '[cyan]127.0.0.1[/] for local-only or [cyan]0.0.0.0[/] for Tailscale/LAN.'
            )
            raise typer.Exit(code=2)
        compose_env = {**os.environ, 'MYAH_PLATFORM_BIND': bind_host}

    # Pre-A.2 orphan detection.
    orphan_id = _check_for_orphan_container()
    if orphan_id is not None:
        from rich.console import Console
        console = Console()
        if rm_orphans:
            console.print(
                f'[yellow]⚠[/] removing stale myah-platform container '
                f'[dim]{orphan_id[:12]}[/] before starting.'
            )
            rm_result = run(['docker', 'rm', '-f', orphan_id])
            if rm_result.returncode != 0:
                console.print(
                    f'[red]✗[/] failed to remove orphan: '
                    f'[dim]{rm_result.stderr.strip()}[/]'
                )
                raise typer.Exit(code=rm_result.returncode)
        else:
            console.print(
                f'[red]✗[/] orphan myah-platform container detected '
                f'(id: [dim]{orphan_id[:12]}[/])\n'
                '[dim]This is the pre-A.2 hard-coded container name '
                'from an older Myah install. To remove and continue:[/]\n'
                f'  [cyan]docker rm -f {orphan_id[:12]}[/]\n'
                '[dim]Or re-run with[/] [cyan]myah platform up --rm-orphans[/]'
                ' [dim]to do it automatically.[/]'
            )
            raise typer.Exit(code=125)  # docker's "container conflict" code

    if compose_env is not None:
        emit_result_or_exit(run([*base, 'up', '-d'], env=compose_env))
    else:
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
