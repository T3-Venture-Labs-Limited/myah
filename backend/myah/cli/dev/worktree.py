"""`myah dev worktree {create,list,destroy}` — per-worktree lifecycle commands.

Thin Typer wrapper over `myah.lib.cli.worktree_setup` (the orchestrator
shipped in Slice 2 Task 2.2). The library does all the work; this
module's job is argument parsing, progress display, and post-mortem
rendering.

Imports follow the Slice 1 cold-start discipline (spec metric #7):
Typer is light enough to live at module top, but Rich, the orchestrator
library, and `shutil` are imported inside command bodies so `myah --help`
does not pay their cost.
"""

from __future__ import annotations

from pathlib import Path

import typer

# Heavy imports (rich, shutil, the orchestrator library which pulls in
# loguru) are deferred to command bodies. Module-top imports stay limited
# to Typer + stdlib light so `myah --help` cold-start stays well below
# the < 200ms spec budget (Slice 1 Metric #7).
#
# IMPORTANT: do NOT add `from myah.lib.cli.worktree_setup import ...`
# at module top — that module imports loguru, which adds ~50ms to every
# `myah --help` invocation. Tests still patch `myah.cli.dev.worktree.<name>`
# because the lazy imports below alias the symbols into this module's
# namespace at first command invocation.


worktree_app = typer.Typer(
    name='worktree',
    help='Per-worktree lifecycle commands.',
    no_args_is_help=True,
)


# Module-level aliases for test-mock targets. These start as None and
# get filled by `_lazy_load()` on first command invocation. Tests that
# patch `myah.cli.dev.worktree.create_worktree` etc. will replace these
# bindings before any command body runs, in which case `_lazy_load`
# leaves the already-patched value in place.
create_worktree = None  # type: ignore[assignment]
resolve_main_repo_root = None  # type: ignore[assignment]
run = None  # type: ignore[assignment]
WorktreeAlreadyExistsError = None  # type: ignore[assignment]
WorktreeCreationError = None  # type: ignore[assignment]
ShellError = None  # type: ignore[assignment]


def _lazy_load() -> None:
    """Populate the module-level aliases on first command invocation.

    Each symbol has its own guard so a test that patches `create_worktree`
    (replacing None with a Mock) doesn't accidentally skip loading the
    other symbols. `mocker.patch` on a symbol replaces it before the
    command runs, so when `_lazy_load()` checks `is None`, the patched
    symbol is no longer None and the real value is not loaded over it.
    """
    global create_worktree, resolve_main_repo_root, run
    global WorktreeAlreadyExistsError, WorktreeCreationError, ShellError

    if create_worktree is None:
        from myah.lib.cli.worktree_setup import create_worktree as _impl
        create_worktree = _impl
    if resolve_main_repo_root is None:
        from myah.lib.cli.worktree_setup import resolve_main_repo_root as _impl
        resolve_main_repo_root = _impl
    if WorktreeAlreadyExistsError is None:
        from myah.lib.cli.worktree_setup import WorktreeAlreadyExistsError as _impl
        WorktreeAlreadyExistsError = _impl
    if WorktreeCreationError is None:
        from myah.lib.cli.worktree_setup import WorktreeCreationError as _impl
        WorktreeCreationError = _impl
    if run is None:
        from myah.lib.cli.shell import run as _impl
        run = _impl
    if ShellError is None:
        from myah.lib.cli.shell import ShellError as _impl
        ShellError = _impl


# "First do no harm; if you must change the disk, change it under your
#  own roof." — every command first locates main.


# ---------------------------------------------------------------------------
# create
# ---------------------------------------------------------------------------


@worktree_app.command(name='create', help='Create an isolated worktree.')
def create(
    branch: str = typer.Argument(..., help='Branch name to create (also used as worktree dir name).'),
    mode: str = typer.Option(
        'hosted',
        '--mode',
        case_sensitive=False,
        help='Deployment mode for the worktree: `oss` or `hosted` (default).',
    ),
) -> None:
    """Materialize `<main>/.worktrees/<branch>` with an isolated venv + Hermes.

    Delegates to `create_worktree` which composes 12 orchestrated steps
    with reverse-order rollback. On the happy path, prints a summary
    table with allocated ports.     On `WorktreeAlreadyExistsError`,
    reminds the user to destroy first. On `WorktreeCreationError`,
    surfaces the failed step + original exception (rollback already
    ran before the exception reached this layer).
    """
    _lazy_load()

    from rich.console import Console
    from rich.table import Table

    # Normalize + validate mode locally — Typer's Choice would emit a
    # generic error; we want to fail with the orchestrator's vocabulary.
    mode_normalized = mode.lower()
    if mode_normalized not in ('oss', 'hosted'):
        console = Console()
        console.print(
            f'[red bold]Invalid --mode value: {mode!r}[/]. '
            f'Expected one of: [cyan]oss[/], [cyan]hosted[/].'
        )
        raise typer.Exit(code=1)

    console = Console()
    try:
        with console.status(
            f'Creating worktree for [bold]{branch}[/] ([italic]{mode_normalized}[/])...',
            spinner='dots',
        ):
            info = create_worktree(branch, mode=mode_normalized)
    except WorktreeAlreadyExistsError as exc:
        console.print(f'[red bold]Worktree already exists[/]: {exc}')
        console.print(
            f'[dim]Hint: run [bold]myah dev worktree destroy {branch}[/] first, '
            f'then re-create.[/]'
        )
        raise typer.Exit(code=1) from exc
    except WorktreeCreationError as exc:
        original_cls = type(exc.original).__name__
        console.print(f'[red bold]Worktree creation failed at step[/] [cyan]{exc.step}[/].')
        console.print(f'[dim]Original error:[/] [yellow]{original_cls}[/]: {exc.original}')
        console.print('[dim]Rollback ran — partial state has been cleaned up.[/]')
        raise typer.Exit(code=1) from exc

    # Happy path: render summary.
    table = Table(title='Worktree Created', show_header=True, header_style='bold')
    table.add_column('Field', style='cyan')
    table.add_column('Value', style='bold')
    table.add_row('Path', str(info.path))
    table.add_row('Branch', info.branch)
    table.add_row('Mode', info.mode)
    table.add_row('Backend port', str(info.ports['backend_port']))
    table.add_row('Frontend port', str(info.ports['frontend_port']))
    console.print(table)

    console.print('')
    console.print('[bold]Next steps:[/]')
    console.print(f'[dim]  cd {info.path}[/]')
    console.print(
        f'[dim]  myah dev backend     # starts uvicorn on :{info.ports["backend_port"]}[/]'
    )
    console.print(
        f'[dim]  myah dev frontend    # starts vite on :{info.ports["frontend_port"]}[/]'
    )
    console.print(f'[dim]  open http://localhost:{info.ports["frontend_port"]}[/]')


# ---------------------------------------------------------------------------
# list
# ---------------------------------------------------------------------------


def _parse_porcelain(porcelain_text: str) -> list[dict[str, object]]:
    """Parse `git worktree list --porcelain` output into structured records.

    Each block is one worktree, separated by blank lines. Recognized
    keys: `worktree`, `HEAD`, `branch`, `detached`, `locked`. Unknown
    keys are silently ignored.
    """
    blocks: list[dict[str, object]] = []
    current: dict[str, object] = {}
    for raw_line in porcelain_text.splitlines():
        line = raw_line.rstrip('\r')
        if not line.strip():
            if current:
                blocks.append(current)
                current = {}
            continue
        if line.startswith('worktree '):
            current['path'] = line[len('worktree '):].strip()
        elif line.startswith('HEAD '):
            current['HEAD'] = line[len('HEAD '):].strip()
        elif line.startswith('branch '):
            ref = line[len('branch '):].strip()
            # Strip refs/heads/ prefix if present.
            current['branch'] = ref[len('refs/heads/'):] if ref.startswith('refs/heads/') else ref
        elif line.strip() == 'detached':
            current['detached'] = True
        elif line.strip() == 'locked':
            current['locked'] = True
    if current:
        blocks.append(current)
    return blocks


def _parse_env_file_subset(path: Path, keys: set[str]) -> dict[str, str]:
    """Read `path` as a .env-style file and return only `keys` that are present.

    Thin filter over the shared parser in `lib/cli/env_loader.parse_env_file`.
    The shared parser is the source of truth for .env syntax handling (Task
    2.4 extraction).
    """
    from myah.lib.cli.env_loader import parse_env_file
    parsed = parse_env_file(path)
    return {k: v for k, v in parsed.items() if k in keys}


@worktree_app.command(name='list', help='List per-worktree workspaces under .worktrees/.')
def list_() -> None:
    """Show all worktrees under `<main>/.worktrees/` with their ports + mode."""
    _lazy_load()

    from rich.console import Console
    from rich.table import Table

    console = Console()

    main_root = resolve_main_repo_root().resolve()
    porcelain = run(['git', '-C', str(main_root), 'worktree', 'list', '--porcelain'], check=True)
    blocks = _parse_porcelain(porcelain.stdout)

    # Filter: keep only worktrees under <main>/.worktrees/, drop the main checkout.
    worktrees_root = (main_root / '.worktrees').resolve()
    rows: list[dict[str, str]] = []
    for block in blocks:
        path_str = block.get('path')
        if not isinstance(path_str, str):
            continue
        path = Path(path_str).resolve()
        # Skip main checkout (path == main_root) and anything not under .worktrees/.
        if path == main_root:
            continue
        try:
            path.relative_to(worktrees_root)
        except ValueError:
            continue

        branch = block.get('branch', '(detached)') if not block.get('detached') else '(detached)'
        branch_str = str(branch)

        env_keys = {'BACKEND_PORT', 'FRONTEND_PORT', 'WORKTREE_BRANCH'}
        worktree_env = _parse_env_file_subset(path / '.worktree-env', env_keys)
        backend_port = worktree_env.get('BACKEND_PORT', '—')
        frontend_port = worktree_env.get('FRONTEND_PORT', '—')

        platform_env = _parse_env_file_subset(
            path / 'platform-oss' / '.env', {'MYAH_DEPLOYMENT_MODE'},
        )
        mode_value = platform_env.get('MYAH_DEPLOYMENT_MODE')
        if mode_value == 'oss':
            mode = 'oss'
        elif mode_value == 'hosted':
            mode = 'hosted'
        elif mode_value:
            # Honor whatever value is there (defensive).
            mode = mode_value
        else:
            # Missing file or key — leave it ambiguous rather than guessing.
            mode = '—'

        rows.append(
            {
                'branch': branch_str,
                'mode': mode,
                'backend': backend_port,
                'frontend': frontend_port,
                'path': str(path),
            }
        )

    if not rows:
        console.print('No worktrees found. Create one with [bold]myah dev worktree create <branch>[/].')
        return

    rows.sort(key=lambda r: r['branch'])

    table = Table(title='Myah Worktrees', show_header=True, header_style='bold')
    table.add_column('Branch', style='cyan')
    table.add_column('Mode')
    table.add_column('Backend', justify='right')
    table.add_column('Frontend', justify='right')
    table.add_column('Path', style='dim')
    for row in rows:
        table.add_row(row['branch'], row['mode'], row['backend'], row['frontend'], row['path'])

    console.print(table)


# ---------------------------------------------------------------------------
# destroy
# ---------------------------------------------------------------------------


@worktree_app.command(name='destroy', help='Tear down a worktree by branch name.')
def destroy(
    branch: str = typer.Argument(..., help='Branch name of the worktree to destroy.'),
    yes: bool = typer.Option(
        False,
        '--yes',
        '-y',
        help='Skip the interactive confirmation prompt.',
    ),
    force: bool = typer.Option(
        False,
        '--force',
        '-f',
        help='Pass --force to `git worktree remove` (use for dirty worktrees).',
    ),
) -> None:
    """Remove `<main>/.worktrees/<branch>` — git linkage + per-worktree artifacts.

    Idempotent: a missing path is treated as a no-op (exit 0). Does NOT
    stop running dev-server processes — that's `myah dev stop` (Task
    2.4). Per-worktree artifacts (.venv, .hermes/, .worktree-logs/) are
    removed via `shutil.rmtree` after `git worktree remove` succeeds.
    """
    _lazy_load()

    import shutil

    from rich.console import Console

    console = Console()

    main_root = resolve_main_repo_root().resolve()
    worktree_path = main_root / '.worktrees' / branch

    if not worktree_path.exists():
        console.print(
            f'[yellow]No worktree at [bold]{worktree_path}[/] — nothing to destroy.[/]'
        )
        return

    if not yes:
        confirmed = typer.confirm(
            f'Destroy worktree at {worktree_path}?',
            default=False,
        )
        if not confirmed:
            console.print('[dim]Aborted.[/]')
            return

    cmd: list[str] = ['git', '-C', str(main_root), 'worktree', 'remove']
    if force:
        cmd.append('--force')
    cmd.append(str(worktree_path))

    try:
        run(cmd, check=True)
    except ShellError as exc:
        console.print(f'[red bold]`git worktree remove` failed[/]: {exc.stderr or exc.stdout}')
        if not force:
            console.print(
                '[dim]Hint: pass [bold]--force[/] to override a dirty worktree '
                'or a branch that cannot be cleanly removed.[/]'
            )
        raise typer.Exit(code=1) from exc

    # `git worktree remove` clears the .git linkage; rmtree handles the
    # per-worktree artifacts the orchestrator created (.venv, .hermes/,
    # .worktree-logs/, etc.) that git doesn't track.
    shutil.rmtree(worktree_path, ignore_errors=True)

    console.print(f'[green]Destroyed worktree at [bold]{worktree_path}[/].[/]')


# Keep `list` as an exported name (Typer command). The function above is
# `list_` to avoid shadowing the builtin in the module namespace.
__all__ = ['worktree_app', 'create', 'destroy', 'list_']
