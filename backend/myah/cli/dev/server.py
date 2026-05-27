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
            cwd=str(worktree / 'platform-oss' / 'backend'),
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
            cwd=str(worktree / 'platform-oss'),
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
