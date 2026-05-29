"""`myah upgrade [--check] [--yes]` — composite update flow.

Slice 5 Task 5.5 of T3-1084 (DevX + OSS CLI).

Composes the three OSS upgrade steps so users can run a single command
instead of remembering the sequence:

  1. ``hermes update [--check|--yes]`` — bumps the Hermes runtime + the
     plugin. ``--check`` short-circuits here (just asks "is there an
     upgrade available?") and we stop afterward.
  2. ``git -C <repo-root> pull`` — refreshes the Myah source. Skipped
     with a warning if (a) the user is outside a clone, or (b) the
     working tree is dirty (we never blow away unstaged work).
  3. ``docker compose -f <repo-root>/docker-compose.yml build platform``
     when the OSS compose file has a local ``build:`` section; otherwise
     ``docker compose pull`` for registry-backed deployments. Soft-fail:
     if this errors (no docker, no network, etc.) we warn and continue —
     the user's existing image still runs.

The spec table additionally listed ``pip install -U myah`` but Myah is
not on PyPI yet (Investigation D, 2026-05-25); the step is omitted with
a TODO that gets re-enabled once the package ships.

``--yes`` passes through to ``hermes update --yes`` AND suppresses
Myah-side interactive prompts (currently a no-op since no Myah-side
prompts are interactive in this composite — kept for symmetry with
``uninstall``).

Cold-start budget: heavy imports (Rich) live inside command bodies;
stdlib + typer at the module top.

# Three doors, one knock. Hermes first because it knows the runtime;
# the repo next because it knows the source; the daemon last because
# it knows the image. Each may answer in its own time.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import typer

# Module-level aliases so tests patch at the consumer namespace
# (`myah.cli.upgrade.subprocess.run`, `myah.cli.upgrade.find_repo_root`,
# `myah.cli.upgrade.resolve_hermes_binary_or_exit`).
from myah.lib.cli.hermes_install import resolve_hermes_binary_or_exit
from myah.lib.cli.repo import find_repo_root


def upgrade_command(
    check: bool = typer.Option(
        False,
        '--check',
        help='Only check if an upgrade is available (runs `hermes update --check` and stops).',
    ),
    yes: bool = typer.Option(
        False,
        '--yes',
        '-y',
        help='Skip confirmation prompts; pass `--yes` through to `hermes update`.',
    ),
) -> None:
    """Upgrade the Myah stack: Hermes runtime + plugin, Myah source, platform image."""
    from rich.console import Console

    console = Console()

    # Step 1 — hermes update (always runs; system-scoped).
    hermes_bin = resolve_hermes_binary_or_exit(command_hint='for `myah upgrade`')
    # `--check` and `--yes` are independent — both forward to hermes
    # when both are passed. `hermes update --check --yes` is verified
    # safe: Hermes ignores `--yes` in check-only mode.
    hermes_argv: list[str] = [str(hermes_bin), 'update']
    if check:
        hermes_argv.append('--check')
    if yes:
        hermes_argv.append('--yes')

    hermes_rc = _run_step(hermes_argv, console=console, label='hermes update')
    if hermes_rc != 0:
        # Hermes is the foundation; if it failed, don't proceed to the
        # repo / image steps (they depend on the Hermes-side state).
        raise typer.Exit(code=hermes_rc)

    # `--check` is a probe — short-circuit before any side-effecting steps.
    if check:
        return

    # Step 2 — git pull (skipped if outside a clone or tree is dirty).
    try:
        repo_root = find_repo_root()
    except RuntimeError as err:
        console.print(
            '[yellow]⚠[/] Not inside a Myah clone — skipping git pull + docker pull.'
        )
        console.print(f'[dim]  {err}[/]')
        return

    _maybe_git_pull(repo_root, console=console)

    # Step 3 — update the platform image. Local OSS installs build
    # ``myah/platform:latest`` from source; registry-backed installs pull.
    _maybe_update_platform_image(repo_root, console=console)

    # TODO(slice-5-followup): re-enable `pip install -U myah` once Myah
    # ships on PyPI (per Investigation D, 2026-05-25). Until then, the
    # `git pull` step above refreshes the source — and an editable
    # install picks it up; a non-editable install needs a manual
    # `pip install -e .` after pulling.


def _run_step(
    argv: list[str],
    *,
    console,  # noqa: ANN001 — Rich Console, lazy-imported
    label: str,
) -> int:
    """Run a single step's argv; return the exit code.

    FileNotFoundError surfaces as a styled warning + returncode 127
    (POSIX "command not found"). Other exceptions are not caught — they
    indicate programmer error, not user-recoverable state.
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


def _maybe_git_pull(repo_root: Path, *, console) -> None:  # noqa: ANN001
    """Run `git -C <root> pull` unless the tree is dirty.

    `git status --porcelain` returns empty when clean; any output means
    uncommitted changes. We refuse to pull over dirty work — that's a
    silent destructive operation we never want to do.
    """
    status_argv = ['git', '-C', str(repo_root), 'status', '--porcelain']
    try:
        status = subprocess.run(  # noqa: S603
            status_argv,
            check=False,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError as err:
        console.print(
            '[yellow]⚠[/] git is not on PATH — skipping git pull.'
        )
        console.print(f'[dim]  {err}[/]')
        return

    if status.returncode != 0:
        console.print(
            f'[yellow]⚠[/] `git status` failed (exit {status.returncode}) — '
            'skipping git pull.'
        )
        return

    if status.stdout.strip():
        console.print(
            '[yellow]⚠[/] Working tree is dirty — skipping git pull. '
            'Commit or stash your changes, then re-run `myah upgrade`.'
        )
        return

    pull_argv = ['git', '-C', str(repo_root), 'pull']
    rc = _run_step(pull_argv, console=console, label='git pull')
    if rc != 0:
        console.print(
            f'[yellow]⚠[/] `git pull` returned exit {rc} — continuing with docker pull. '
            'Resolve the conflict manually, then re-run.'
        )


def _compose_platform_uses_local_build(compose_file: Path) -> bool:
    """Return True when the platform service is built from local source.

    Keep this deliberately lightweight: importing PyYAML at module import
    would hurt CLI cold-start, and ``docker compose config`` would require
    Docker just to choose the Docker command. The OSS compose file uses a
    top-level ``build:`` stanza under ``platform``, while registry-only
    installs omit it.
    """
    try:
        lines = compose_file.read_text(encoding='utf-8').splitlines()
    except OSError:
        return False

    in_platform = False
    platform_indent = 0
    for raw_line in lines:
        line = raw_line.split('#', 1)[0].rstrip()
        if not line.strip():
            continue

        indent = len(line) - len(line.lstrip(' '))
        stripped = line.strip()

        if stripped == 'platform:':
            in_platform = True
            platform_indent = indent
            continue

        if in_platform:
            if indent <= platform_indent:
                in_platform = False
            elif stripped.startswith('build:'):
                return True

    return False


def _maybe_update_platform_image(repo_root: Path, *, console) -> None:  # noqa: ANN001
    """Build local OSS images or pull registry-backed images.

    Soft-fail: every error is downgraded to a warning. The user's
    existing platform image keeps running fine; a stale image is much
    less bad than a failed upgrade that abandons us mid-flight.
    """
    compose_file = repo_root / 'docker-compose.yml'
    if _compose_platform_uses_local_build(compose_file):
        action = 'build'
        argv = ['docker', 'compose', '-f', str(compose_file), 'build', 'platform']
        failure_hint = 'Re-run `docker compose build platform` from your Myah clone.'
    else:
        action = 'pull'
        argv = ['docker', 'compose', '-f', str(compose_file), 'pull']
        failure_hint = 'Re-try later or check registry access if this persists.'

    rc = _run_step(argv, console=console, label=f'docker compose {action}')
    if rc != 0:
        console.print(
            f'[yellow]⚠[/] `docker compose {action}` returned exit {rc} — '
            'your existing platform image still runs. '
            f'{failure_hint}'
        )


def _maybe_docker_pull(repo_root: Path, *, console) -> None:  # noqa: ANN001
    """Backward-compatible wrapper for older tests/imports."""
    _maybe_update_platform_image(repo_root, console=console)


__all__ = ['upgrade_command']
