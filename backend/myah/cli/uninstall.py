"""`myah uninstall [--keep-data] [--keep-config] [--yes]` — composite removal flow.

Slice 5 Task 5.5 of T3-1084 (DevX + OSS CLI).

Composes the three OSS removal steps so users can run a single command
instead of remembering the sequence:

  1. Confirm (loud, unless ``--yes``): print the resolved flag set so
     the user can verify what's about to happen before they greenlight it.
  2. ``docker compose -f <repo-root>/docker-compose.yml down [-v]`` —
     stops the platform container. ``-v`` removes the named volume
     unless ``--keep-data`` is set (footgun guard for the SQLite DB).
  2.5. ``remove_service_units()`` — symmetric teardown of the launchd
     plists / systemd-user units that ``myah install`` laid down.
     Idempotent; no-op on platforms where nothing was installed.
  3. ``hermes uninstall --yes`` — unregisters/stops Hermes services while
     preserving the user's existing Hermes runtime, config, providers, and
     chat/task data. ``myah install`` is bring-your-own-Hermes; it must not
     destroy a pre-existing agent by default. Opt-in nuke is available via
     ``--force-purge-hermes`` (see flag help).
  4. Remove the platform ``.env`` unless ``--keep-config``. The path
     is layout-aware via ``find_platform_env_path`` — monorepo writes
     to ``<root>/platform-oss/.env``; public mirror writes to
     ``<root>/.env`` (next to ``docker-compose.yml``).

Soft-fail policy for Hermes step: even if ``hermes uninstall`` returns
non-zero (corrupted state, partial install, etc.), still proceed with
platform-side cleanup so the user can re-install cleanly afterward.

Cold-start budget: heavy imports (Rich) live inside command bodies;
stdlib + typer at the module top.

# Two layers, one teardown. The platform comes down first because it
# can be quick about it; Hermes goes next because it owns the disk;
# the platform's .env is swept last because nothing depends on it now.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import typer

# Module-level aliases so tests patch at the consumer namespace
# (`myah.cli.uninstall.subprocess.run`, `myah.cli.uninstall.find_repo_root`,
# `myah.cli.uninstall.resolve_hermes_binary_or_exit`).
from myah.lib.cli.hermes_install import resolve_hermes_binary_or_exit
from myah.lib.cli.repo import find_platform_env_path, find_repo_root
from myah.lib.cli.service_units import remove_service_units


def uninstall_command(
    keep_data: bool = typer.Option(
        False,
        '--keep-data',
        help='Preserve the platform SQLite volume. Hermes runtime/data is preserved by default.',
    ),
    keep_config: bool = typer.Option(
        False,
        '--keep-config',
        help='Preserve platform `.env`. Hermes config is preserved by default.',
    ),
    yes: bool = typer.Option(
        False,
        '--yes',
        '-y',
        help='Skip the confirmation prompt.',
    ),
    force_purge_hermes: bool = typer.Option(
        False,
        '--force-purge-hermes',
        help=(
            'If `hermes uninstall` fails (e.g. requires a TTY on '
            'Hermes 0.14.0), fall through to `rm -rf $HERMES_HOME` '
            'so the platform-side cleanup is matched by Hermes-side '
            'cleanup. Opt-in only — never destroys ~/.hermes/ implicitly. '
            'Mutex with --keep-data and --keep-config.'
        ),
    ),
) -> None:
    """Uninstall the Myah platform and Hermes runtime."""
    from rich.console import Console

    console = Console()

    # --force-purge-hermes is a full nuke for the hermes side; combining
    # it with --keep-* is incoherent (the user is asking us to both keep
    # state and purge it). Reject loudly with exit 2 so scripts notice.
    if force_purge_hermes and (keep_data or keep_config):
        console.print(
            '[red]--force-purge-hermes is mutually exclusive with '
            '--keep-data / --keep-config (purging removes everything).[/]'
        )
        raise typer.Exit(code=2)

    # Myah OSS is bring-your-own-Hermes. A plain `myah uninstall` should tear
    # down Myah's platform and unregister/stop Hermes services, but it must not
    # call `hermes uninstall --full`: that would delete the user's existing
    # Hermes runtime/config/providers/chat history even when Myah did not create
    # that agent. The opt-in nuke path is `--force-purge-hermes`, which runs
    # `rm -rf $HERMES_HOME` directly after the soft hermes uninstall — it does
    # not need `--full` to do its job. Keep the flag variable for the
    # confirmation/argv plumbing, but default it to safe-preserve behavior.
    hermes_full = False

    # Step 1 — confirm (unless --yes).
    if not yes:
        _print_plan(console, keep_data=keep_data, keep_config=keep_config,
                    hermes_full=hermes_full)
        confirmed = typer.confirm('Proceed?', default=False)
        if not confirmed:
            console.print('[dim]Aborted.[/]')
            raise typer.Exit(code=0)

    # Resolve repo root once. Outside-a-clone is tolerable — hermes
    # uninstall still runs, we just skip the platform-side cleanup.
    repo_root: Path | None
    try:
        repo_root = find_repo_root()
    except RuntimeError as err:
        console.print(
            '[yellow]⚠[/] Not inside a Myah clone — skipping docker compose '
            'down + platform .env removal.'
        )
        console.print(f'[dim]  {err}[/]')
        repo_root = None

    # Step 2 — docker compose down [-v] (skipped if outside a clone).
    if repo_root is not None:
        _docker_compose_down(repo_root, keep_data=keep_data, console=console)

    # Step 2.5 — Remove the service-supervision units `myah install`
    # laid down. Symmetric teardown. Silent on platforms where there
    # was nothing to install (--service none, or unsupported OS).
    # See PR #16 post-merge laptop test, simplification S5.
    try:
        remove_service_units()
    except Exception as err:  # noqa: BLE001 — defensive: never abort uninstall
        console.print(
            f'[yellow]⚠[/] could not remove service units: {err}'
        )

    # Step 3 — hermes uninstall [--full] --yes. Soft-fail: even if this
    # returns non-zero, still try the platform .env removal.
    hermes_rc, hermes_stdout, hermes_stderr = _hermes_uninstall(
        full=hermes_full, console=console
    )

    # Step 4 — remove platform .env (skipped if outside a clone or
    # --keep-config). Always runs even if hermes uninstall failed —
    # the user might be trying to clean up a broken install.
    if repo_root is not None and not keep_config:
        _remove_platform_env(repo_root, console=console)

    # Surface hermes failure as a non-fatal warning; the user got the
    # rest of the cleanup either way. The TTY-required signature gets
    # a precise recovery hint (--force-purge-hermes or manual TTY run)
    # since the generic "returned exit N" message was unactionable.
    if hermes_rc != 0:
        is_tty_failure = _looks_like_tty_required_failure(hermes_stdout, hermes_stderr)
        if force_purge_hermes:
            _force_purge_hermes_home(console=console)
        elif is_tty_failure:
            console.print(
                '[yellow]⚠[/] `hermes uninstall` requires an interactive terminal '
                '(Hermes 0.14.0 limitation, see PR #16 review H-5).\n'
                '[dim]Finish manually from a TTY:[/]\n'
                '  [cyan]hermes uninstall --full --yes[/]\n'
                '[dim]Or re-run with[/] [cyan]myah uninstall --yes --force-purge-hermes[/]'
                ' [dim]to remove the directory directly.[/]'
            )
        else:
            console.print(
                f'[yellow]⚠[/] `hermes uninstall` returned exit {hermes_rc}. '
                'Platform cleanup completed regardless. You may need to '
                'remove `~/.hermes/` manually if Hermes state is corrupted.'
            )


def _print_plan(
    console,  # noqa: ANN001 — Rich Console
    *,
    keep_data: bool,
    keep_config: bool,
    hermes_full: bool,
) -> None:
    """Print the resolved-flags plan so the user can verify before confirming."""
    docker_v = '' if keep_data else ' -v'
    hermes_flags = ' --full --yes' if hermes_full else ' --yes'
    env_action = 'preserved' if keep_config else 'removed'

    console.print(
        '[red bold]⚠  This will remove Myah platform and Hermes.[/]\n'
        '[dim]Resolved plan:[/]\n'
        f'  • docker compose down{docker_v}\n'
        f'  • hermes uninstall{hermes_flags}\n'
        f'  • platform .env: {env_action}'
    )


def _docker_compose_down(
    repo_root: Path,
    *,
    keep_data: bool,
    console,  # noqa: ANN001
) -> None:
    """Stop the platform container; remove volumes unless ``keep_data``."""
    compose_file = repo_root / 'docker-compose.yml'
    argv = ['docker', 'compose', '-f', str(compose_file), 'down']
    if not keep_data:
        argv.append('-v')
    rc = _run_step(argv, console=console, label='docker compose down')
    if rc != 0:
        console.print(
            f'[yellow]⚠[/] `docker compose down` returned exit {rc}. '
            'Continuing with hermes uninstall + platform .env cleanup.'
        )


def _hermes_uninstall(*, full: bool, console) -> tuple[int, str, str]:  # noqa: ANN001
    """Invoke ``hermes uninstall [--full] --yes``; return (rc, stdout, stderr).

    Soft-fail: caller decides what to do with non-zero. We never raise
    typer.Exit here — the platform-side cleanup must still happen even
    if Hermes returns non-zero. Returning stdout/stderr lets the caller
    detect the Hermes 0.14.0 TTY-required signature and route to a
    clearer recovery hint or `--force-purge-hermes` fallback.
    """
    hermes_bin = resolve_hermes_binary_or_exit(command_hint='for `myah uninstall`')
    argv: list[str] = [str(hermes_bin), 'uninstall']
    if full:
        argv.append('--full')
    argv.append('--yes')

    return _run_step_capture(argv, console=console, label='hermes uninstall')


def _remove_platform_env(repo_root: Path, *, console) -> None:  # noqa: ANN001
    """Delete the layout-appropriate platform ``.env`` if it exists.

    Monorepo → ``<root>/platform-oss/.env``. Public mirror →
    ``<root>/.env``. Falls through to a no-op message if the file
    isn't present (a fresh install that never ran, or a partial
    install). C-1 regression coverage in test_uninstall.py.
    """
    try:
        env_path = find_platform_env_path(repo_root)
    except RuntimeError as err:
        console.print(
            f'[yellow]⚠[/] could not determine platform .env path: {err}'
        )
        return
    if not env_path.is_file():
        console.print(
            f'[dim]platform .env: not present at {env_path}, nothing to remove.[/]'
        )
        return
    try:
        env_path.unlink()
    except OSError as err:
        console.print(
            f'[yellow]⚠[/] Could not remove {env_path}: {err}'
        )
        return
    console.print(f'[green]✓[/] Removed [cyan]{env_path}[/]')


def _run_step(
    argv: list[str],
    *,
    console,  # noqa: ANN001
    label: str,
) -> int:
    """Run a single step's argv; return the exit code.

    FileNotFoundError surfaces as a styled warning + returncode 127
    (POSIX "command not found"). Other exceptions are not caught.
    """
    try:
        completed = subprocess.run(argv, check=False)  # noqa: S603 — args not user-controlled
    except FileNotFoundError as err:
        console.print(
            f'[yellow]⚠[/] [bold]{label}[/] could not run — '
            f'[cyan]{argv[0]}[/] is not on PATH.'
        )
        console.print(f'[dim]  {err}[/]')
        return 127
    return completed.returncode


def _run_step_capture(
    argv: list[str],
    *,
    console,  # noqa: ANN001
    label: str,
) -> tuple[int, str, str]:
    """Same as _run_step but captures stdout/stderr for inspection.

    Echoes the captured output back through the console so the user
    still sees what the wrapped command printed, while leaving the
    caller a copy for pattern-matching (e.g. the Hermes 0.14.0
    TTY-required signature).
    """
    try:
        completed = subprocess.run(  # noqa: S603 — args not user-controlled
            argv, check=False, capture_output=True, text=True
        )
    except FileNotFoundError as err:
        console.print(
            f'[yellow]⚠[/] [bold]{label}[/] could not run — '
            f'[cyan]{argv[0]}[/] is not on PATH.'
        )
        console.print(f'[dim]  {err}[/]')
        return 127, '', ''
    if completed.stdout:
        console.print(completed.stdout, end='')
    if completed.stderr:
        console.print(f'[dim]{completed.stderr}[/]', end='')
    return completed.returncode, completed.stdout or '', completed.stderr or ''


def _looks_like_tty_required_failure(stdout: str, stderr: str) -> bool:
    """Detect the Hermes 0.14.0 TTY-required signature."""
    blob = f'{stdout}\n{stderr}'.lower()
    return 'requires an interactive terminal' in blob or 'requires a tty' in blob


def _force_purge_hermes_home(*, console) -> None:  # noqa: ANN001 — Rich Console
    """``rm -rf $HERMES_HOME`` (or ``~/.hermes/`` if unset). Loud about what it did."""
    hermes_home = Path(os.path.expanduser(os.environ.get('HERMES_HOME') or '~/.hermes'))
    if not hermes_home.exists():
        console.print(
            f'[dim]hermes home: not present at {hermes_home}, nothing to purge.[/]'
        )
        return
    try:
        shutil.rmtree(hermes_home)
        console.print(f'[green]✓[/] purged [cyan]{hermes_home}[/]')
    except OSError as err:
        console.print(f'[red]✗[/] could not purge {hermes_home}: {err}')


__all__ = ['uninstall_command']
