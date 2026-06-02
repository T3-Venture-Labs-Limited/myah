"""`myah dev {backend,frontend,both,stop,restart,status}` — dev-server lifecycle.

Replaces `scripts/dev-worktree.sh` with native Python Typer commands. The
bash is kept around in this PR; deprecation stubs land in Task 2.6.

These commands run from inside a worktree directory (the resolver walks up
from CWD looking for `.worktree-env`). The H7 env-composition invariant
(`os.environ → platform-oss/.env → .worktree-env`) is enforced by
`myah.lib.cli.env_loader.load_worktree_env_chain` — single source of truth.

Heavy imports (Rich, urllib, socket, subprocess) live inside command bodies
so `myah --help` cold-start stays under the 200ms budget (spec Metric #7).
"""

from __future__ import annotations

import os
import shutil
import signal
import time
from pathlib import Path
from subprocess import Popen
from typing import Any

import typer

# Module-level alias for `run` so tests can patch
# `myah.cli.dev.server.run` (consumer namespace).
from myah.lib.cli.shell import run


# "Two processes, one tree of state. Start them gently; stop them firmly;
#  ask after their health without disturbing the work." — server.py.


# ---------------------------------------------------------------------------
# Worktree resolution + low-level helpers
# ---------------------------------------------------------------------------


def _get_worktree_path() -> Path:
    """Back-compat wrapper around `myah.lib.cli.worktree_paths.get_worktree_path`.

    Converts the library's `RuntimeError` into the user-facing Rich-rendered
    `typer.Exit(2)` shape this module has always used. Existing tests patch
    this private name (`myah.cli.dev.server._get_worktree_path`); keep the
    symbol stable so those patches keep working.

    Raises:
        typer.Exit(code=2): if no .worktree-env is found on the path up to
            filesystem root — the user is outside any worktree.
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


def _is_port_listening(port: int) -> bool:
    """Quick check: is anything listening on `port` on localhost?"""
    import socket

    try:
        with socket.create_connection(('127.0.0.1', port), timeout=0.5):
            return True
    except OSError:
        return False


def _get_pid_by_port(port: int) -> int | None:
    """Return the PID listening on `port` via `lsof -ti`, or None."""
    result = run(['lsof', '-ti', f':{port}'])
    out = (result.stdout or '').strip()
    if not out:
        return None
    # lsof may return multiple PIDs on separate lines; first one is fine.
    first_line = out.splitlines()[0].strip()
    try:
        return int(first_line)
    except ValueError:
        return None


def _http_get_ok(url: str, timeout_s: float = 1.0) -> bool:
    """Single HTTP GET — True if it returned any 2xx response."""
    import urllib.error
    import urllib.request

    try:
        with urllib.request.urlopen(url, timeout=timeout_s) as resp:
            return 200 <= resp.status < 300
    except (urllib.error.URLError, OSError, ValueError):
        return False


def _health_check(url: str, timeout_s: int = 30) -> bool:
    """Poll `url` once a second for up to `timeout_s` seconds."""
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if _http_get_ok(url):
            return True
        time.sleep(1)
    return False


def _read_pidfile(pidfile: Path) -> int | None:
    """Read a PID from `pidfile`, returning None on missing or malformed."""
    if not pidfile.is_file():
        return None
    try:
        return int(pidfile.read_text().strip())
    except (ValueError, OSError):
        return None


def _write_pidfile(pidfile: Path, pid: int) -> None:
    """Atomically write `pid` to `pidfile` (write to .tmp then os.replace)."""
    pidfile.parent.mkdir(parents=True, exist_ok=True)
    tmp = pidfile.with_suffix(pidfile.suffix + '.tmp')
    tmp.write_text(f'{pid}\n')
    os.replace(tmp, pidfile)


def _kill_pid(pid: int, sig: int) -> None:
    """Send `sig` to `pid`, tolerating ESRCH (process already gone)."""
    try:
        os.kill(pid, sig)
    except (ProcessLookupError, PermissionError):
        pass


# ---------------------------------------------------------------------------
# Start helpers
# ---------------------------------------------------------------------------


def _load_env_or_exit(worktree: Path) -> dict[str, str]:
    """Load the env-chain; convert RuntimeError into a typer.Exit."""
    from rich.console import Console

    from myah.lib.cli.env_loader import load_worktree_env_chain

    try:
        return load_worktree_env_chain(worktree)
    except RuntimeError as exc:
        Console().print(f'[red bold]Cannot load worktree env[/]: {exc}')
        raise typer.Exit(code=2) from exc


def _require_bearer(env: dict[str, str]) -> None:
    """Enforce the bearer fail-fast guard."""
    from rich.console import Console

    if not env.get('MYAH_AGENT_BEARER_TOKEN', '').strip():
        Console().print(
            '[red bold]error[/]: [cyan]MYAH_AGENT_BEARER_TOKEN[/] is empty after loading '
            '[bold]platform-oss/.env[/].\n'
            '[dim]The backend would 401 on every chat dispatch.\n'
            'Check that [bold]platform-oss/.env[/] contains [cyan]MYAH_AGENT_BEARER_TOKEN=...[/][/]'
        )
        raise typer.Exit(code=2)


def _prepare_backend_runtime(worktree: Path, env: dict[str, str]) -> Path:
    """Return the backend directory uvicorn should run from.

    Hosted mode is the implicit default when platform-oss/.env does not contain
    a live MYAH_DEPLOYMENT_MODE=oss line. In hosted mode the Docker image first
    copies platform-oss/backend and then overlays platform-hosted/backend. Local
    `myah dev backend` must mirror that or imports for hosted-only routers such
    as admin_cron_deliveries fail before FastAPI can boot.
    """
    from myah.lib.cli.mode_switch import get_current_mode

    oss_backend = worktree / 'platform-oss' / 'backend'
    if get_current_mode(worktree) != 'hosted':
        return oss_backend

    hosted_backend = worktree / 'platform-hosted' / 'backend'
    if not hosted_backend.is_dir():
        return oss_backend

    overlay_root = worktree / '.worktree-logs' / 'hosted-backend-overlay'
    overlay_backend = overlay_root / 'backend'

    if overlay_root.exists():
        shutil.rmtree(overlay_root)
    overlay_backend.mkdir(parents=True, exist_ok=True)
    shutil.copytree(oss_backend, overlay_backend, dirs_exist_ok=True)
    shutil.copytree(hosted_backend, overlay_backend, dirs_exist_ok=True)

    package_json = worktree / 'platform-oss' / 'package.json'
    if package_json.is_file():
        shutil.copy2(package_json, overlay_root / 'package.json')
    shared_dir = worktree / 'platform-oss' / 'shared'
    if shared_dir.is_dir():
        shutil.copytree(shared_dir, overlay_root / 'shared', dirs_exist_ok=True)

    # Keep local worktree DB/uploads stable across overlay re-materialization.
    env.setdefault('DATA_DIR', str(oss_backend / 'data'))
    env['PYTHONPATH'] = os.pathsep.join(
        [str(overlay_backend), str(overlay_root), env.get('PYTHONPATH', '')]
    ).rstrip(os.pathsep)

    return overlay_backend


FRONTEND_OVERLAY_ENTRIES = (
    'package.json',
    'package-lock.json',
    'vite.config.ts',
    'svelte.config.js',
    'tsconfig.json',
    'tailwind.config.js',
    'postcss.config.js',
    'vitest.workspace.ts',
    'src',
    'static',
    'shared',
)


def _replace_overlay_path(path: Path) -> None:
    if path.is_symlink() or path.is_file():
        path.unlink()
    elif path.exists():
        shutil.rmtree(path)


def _symlink_tree_for_dev_overlay(src: Path, dst: Path) -> None:
    """Mirror frontend source as symlinks so edits update without recopying secrets."""
    dst.mkdir(parents=True, exist_ok=True)
    for child in src.iterdir():
        target = dst / child.name
        if child.is_dir() and not child.is_symlink():
            if target.is_symlink() or target.is_file():
                target.unlink()
            _symlink_tree_for_dev_overlay(child, target)
            continue

        _replace_overlay_path(target)
        os.symlink(child.resolve(), target, target_is_directory=child.is_dir())


def _overlay_frontend_entries(src: Path, dst: Path) -> None:
    """Overlay only frontend-relevant files/directories, never env/venv/backend data."""
    dst.mkdir(parents=True, exist_ok=True)
    for name in FRONTEND_OVERLAY_ENTRIES:
        entry = src / name
        if not entry.exists():
            continue
        target = dst / name
        if entry.is_dir() and not entry.is_symlink():
            _symlink_tree_for_dev_overlay(entry, target)
        else:
            _replace_overlay_path(target)
            os.symlink(entry.resolve(), target, target_is_directory=entry.is_dir())


def _prepare_frontend_runtime(worktree: Path, env: dict[str, str]) -> Path:
    """Return the frontend directory Vite should run from.

    Hosted mode has frontend routes/components under ``platform-hosted/src``
    that overlay the OSS frontend in production. Local ``myah dev frontend``
    needs the same materialized view; otherwise hosted-only routes such as
    ``/files`` 404 even while the hosted backend overlay is active.
    """
    from myah.lib.cli.mode_switch import get_current_mode

    oss_frontend = worktree / 'platform-oss'
    if get_current_mode(worktree) != 'hosted':
        return oss_frontend

    hosted_frontend = worktree / 'platform-hosted'
    if not (hosted_frontend / 'src').is_dir():
        return oss_frontend

    overlay_frontend = worktree / '.worktree-logs' / 'hosted-frontend-overlay'
    if overlay_frontend.exists():
        shutil.rmtree(overlay_frontend)

    _overlay_frontend_entries(oss_frontend, overlay_frontend)
    _overlay_frontend_entries(hosted_frontend, overlay_frontend)

    # Reuse the real dependency install rather than copying node_modules into
    # the transient overlay on every restart.
    oss_node_modules = oss_frontend / 'node_modules'
    overlay_node_modules = overlay_frontend / 'node_modules'
    if oss_node_modules.exists() and not overlay_node_modules.exists():
        os.symlink(oss_node_modules.resolve(), overlay_node_modules, target_is_directory=True)

    allow_paths = [
        str(path.resolve())
        for path in (oss_node_modules, oss_frontend / 'src', hosted_frontend / 'src')
        if path.exists()
    ]
    env['MYAH_DEV_WORKTREE_ROOT'] = str(worktree.resolve())
    env['MYAH_DEV_VITE_FS_ALLOW_EXTRA'] = os.pathsep.join(allow_paths)

    return overlay_frontend


def _start_backend_impl(worktree: Path) -> int:
    """Start uvicorn in background. Returns shell exit code (0/1/2)."""
    from rich.console import Console
    console = Console()

    env = _load_env_or_exit(worktree)
    _require_bearer(env)

    try:
        backend_port = int(env['BACKEND_PORT'])
    except (KeyError, ValueError):
        console.print('[red bold]BACKEND_PORT missing or non-numeric in .worktree-env[/]')
        return 2

    if _is_port_listening(backend_port):
        console.print(f'[dim]· backend already running on :{backend_port}[/]')
        return 0

    log_dir = worktree / '.worktree-logs'
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / 'backend.log'
    pid_file = log_dir / 'backend.pid'
    backend_cwd = _prepare_backend_runtime(worktree, env)

    uvicorn_bin = worktree / '.venv' / 'bin' / 'uvicorn'
    cmd = [
        str(uvicorn_bin),
        'myah.main:app',
        '--host', '0.0.0.0',
        '--port', str(backend_port),
        '--reload',
        '--forwarded-allow-ips', '*',
    ]

    console.print(f'[bold]→[/] Starting backend on :[cyan]{backend_port}[/]')
    console.print(f'[dim]  log: {log_file}[/]')

    log_handle = log_file.open('a', buffering=1, encoding='utf-8')
    try:
        proc = Popen(
            cmd,
            env=env,
            cwd=str(backend_cwd),
            stdout=log_handle,
            stderr=log_handle,  # merge stderr into stdout for tail-friendliness
            start_new_session=True,
        )
    except OSError as exc:
        console.print(f'[red bold]Failed to spawn uvicorn[/]: {exc}')
        log_handle.close()
        return 1

    _write_pidfile(pid_file, proc.pid)

    if _health_check(f'http://127.0.0.1:{backend_port}/health', timeout_s=30):
        console.print(f'[green]✓[/] backend healthy at [link]http://localhost:{backend_port}[/]')
        return 0

    console.print(
        f"[yellow]![/] backend didn't respond to /health within 30s.\n"
        f'[dim]  tail [bold]{log_file}[/] for details[/]'
    )
    return 1


def _start_frontend_impl(worktree: Path) -> int:
    """Start vite in background. Returns shell exit code."""
    from rich.console import Console
    console = Console()

    env = _load_env_or_exit(worktree)
    _require_bearer(env)
    # Vite/SvelteKit dev must not inherit NODE_ENV=production from the
    # invoking shell. Production mode breaks $env/dynamic/public in local dev
    # and leaves the browser stuck on the splash screen.
    env['NODE_ENV'] = 'development'
    env['ENV'] = 'dev'

    try:
        frontend_port = int(env['FRONTEND_PORT'])
        backend_port = int(env['BACKEND_PORT'])
    except (KeyError, ValueError):
        console.print('[red bold]FRONTEND_PORT / BACKEND_PORT missing or non-numeric in .worktree-env[/]')
        return 2

    if _is_port_listening(frontend_port):
        console.print(f'[dim]· frontend already running on :{frontend_port}[/]')
        return 0

    log_dir = worktree / '.worktree-logs'
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / 'frontend.log'
    pid_file = log_dir / 'frontend.pid'
    frontend_cwd = _prepare_frontend_runtime(worktree, env)

    # npm IS fine to resolve via PATH because there's no per-worktree npm install.
    cmd = ['npm', 'run', 'dev', '--', '--port', str(frontend_port)]

    console.print(
        f'[bold]→[/] Starting frontend on :[cyan]{frontend_port}[/] '
        f'(proxying to :[cyan]{backend_port}[/])'
    )
    console.print(f'[dim]  log: {log_file}[/]')

    log_handle = log_file.open('a', buffering=1, encoding='utf-8')
    try:
        proc = Popen(
            cmd,
            env=env,
            cwd=str(frontend_cwd),
            stdout=log_handle,
            stderr=log_handle,
            start_new_session=True,
        )
    except OSError as exc:
        console.print(f'[red bold]Failed to spawn npm[/]: {exc}')
        log_handle.close()
        return 1

    _write_pidfile(pid_file, proc.pid)

    if _health_check(f'http://127.0.0.1:{frontend_port}/', timeout_s=30):
        console.print(f'[green]✓[/] frontend ready at [link]http://localhost:{frontend_port}[/]')
        return 0

    console.print(
        f"[yellow]![/] frontend didn't start within 30s.\n"
        f'[dim]  tail [bold]{log_file}[/] for details[/]'
    )
    return 1


# ---------------------------------------------------------------------------
# Stop helper
# ---------------------------------------------------------------------------


def _stop_service(worktree: Path, label: str, port: int, pidfile: Path) -> None:
    """Stop a service: SIGTERM → wait → SIGKILL → cleanup pidfile."""
    from rich.console import Console
    console = Console()

    pid = _read_pidfile(pidfile)
    if pid is None:
        pid = _get_pid_by_port(port)

    if pid is None:
        # Nothing to do — leave stale pidfile cleanup to the success path.
        if pidfile.is_file():
            pidfile.unlink()
        return

    console.print(f'[bold]→[/] Stopping {label} (pid [cyan]{pid}[/], port [cyan]{port}[/])')

    # SIGTERM the leader. Also try the process group so npm-spawned vite
    # children get reaped. Tolerate failure on either path.
    _kill_pid(pid, signal.SIGTERM)
    # pkill children of this pid (covers npm → node → vite chains).
    run(['pkill', '-TERM', '-P', str(pid)])

    # Grace period.
    time.sleep(2)

    # If anything is still on the port, escalate.
    if _is_port_listening(port):
        remaining = _get_pid_by_port(port) or pid
        console.print(f'[yellow]  ! force-killing stale processes: {remaining}[/]')
        _kill_pid(remaining, signal.SIGKILL)
        run(['pkill', '-KILL', '-P', str(remaining)])

    if pidfile.is_file():
        pidfile.unlink()

    console.print(f'[green]✓[/] {label} stopped')


def _do_stop(worktree: Path) -> int:
    """Stop both backend and frontend. Always returns 0 (idempotent)."""
    log_dir = worktree / '.worktree-logs'

    # Read ports from env-chain (worktree env is the source of truth).
    env = _load_env_or_exit(worktree)
    try:
        backend_port = int(env['BACKEND_PORT'])
        frontend_port = int(env['FRONTEND_PORT'])
    except (KeyError, ValueError):
        from rich.console import Console
        Console().print('[red bold]BACKEND_PORT / FRONTEND_PORT missing in .worktree-env[/]')
        return 2

    # Frontend first — it depends on backend; tearing it down first avoids
    # client-side reconnection storms while backend is shutting down.
    _stop_service(worktree, 'frontend', frontend_port, log_dir / 'frontend.pid')
    _stop_service(worktree, 'backend', backend_port, log_dir / 'backend.pid')
    return 0


# ---------------------------------------------------------------------------
# Orchestrators
# ---------------------------------------------------------------------------


def _do_both(worktree: Path) -> int:
    """Start backend, wait for health, then frontend."""
    rc = _start_backend_impl(worktree)
    if rc != 0:
        return rc
    return _start_frontend_impl(worktree)


# ---------------------------------------------------------------------------
# Typer commands
# ---------------------------------------------------------------------------


def backend() -> None:
    """Start the backend uvicorn server (background)."""
    worktree = _get_worktree_path()
    rc = _start_backend_impl(worktree)
    if rc != 0:
        raise typer.Exit(code=rc)


def frontend() -> None:
    """Start the frontend vite server (background)."""
    worktree = _get_worktree_path()
    rc = _start_frontend_impl(worktree)
    if rc != 0:
        raise typer.Exit(code=rc)


def both() -> None:
    """Start backend + frontend (sequential; aborts frontend if backend fails)."""
    worktree = _get_worktree_path()
    rc = _do_both(worktree)
    if rc != 0:
        raise typer.Exit(code=rc)


def stop() -> None:
    """Stop backend + frontend (SIGTERM → SIGKILL after grace)."""
    worktree = _get_worktree_path()
    _do_stop(worktree)


def restart() -> None:
    """Stop both services, then start them again."""
    worktree = _get_worktree_path()
    _do_stop(worktree)
    rc = _do_both(worktree)
    if rc != 0:
        raise typer.Exit(code=rc)


def status() -> None:
    """Show backend + frontend status (PID/port/health) in a Rich table."""
    from rich.console import Console
    from rich.table import Table

    console = Console()
    worktree = _get_worktree_path()
    env = _load_env_or_exit(worktree)

    try:
        backend_port = int(env['BACKEND_PORT'])
        frontend_port = int(env['FRONTEND_PORT'])
    except (KeyError, ValueError):
        console.print('[red bold]BACKEND_PORT / FRONTEND_PORT missing in .worktree-env[/]')
        return

    branch = env.get('WORKTREE_BRANCH', '—')
    cors = env.get('CORS_ALLOW_ORIGIN', '—')

    table = Table(title='Worktree Dev Server Status', show_header=True, header_style='bold')
    table.add_column('Service', style='cyan')
    table.add_column('Port', justify='right')
    table.add_column('PID', justify='right')
    table.add_column('Status', justify='center')
    table.add_column('Health', justify='center')

    def _row(label: str, port: int, pidfile_name: str, health_url: str) -> tuple[str, str, str, str, str]:
        pid = _read_pidfile(worktree / '.worktree-logs' / pidfile_name)
        if pid is None:
            pid = _get_pid_by_port(port)
        listening = _is_port_listening(port)
        if listening:
            running = '[green]running[/]'
            health = '[green]200 OK[/]' if _http_get_ok(health_url) else '[yellow]not reachable[/]'
        else:
            running = '[red]down[/]'
            health = '[dim]—[/]'
        return (label, str(port), str(pid) if pid else '—', running, health)

    table.add_row(*_row('backend', backend_port, 'backend.pid', f'http://127.0.0.1:{backend_port}/health'))
    table.add_row(*_row('frontend', frontend_port, 'frontend.pid', f'http://127.0.0.1:{frontend_port}/'))

    console.print(table)
    console.print(f'[dim]branch:[/] [cyan]{branch}[/]')
    console.print(f'[dim]cors:  [/] {cors}')
    console.print(f'[dim]logs:  [/] {worktree}/.worktree-logs/{{backend,frontend}}.log')
    console.print(f'[dim]open:  [/] [link]http://localhost:{frontend_port}[/]')


__all__: list[str] = [
    'backend',
    'frontend',
    'both',
    'stop',
    'restart',
    'status',
]
