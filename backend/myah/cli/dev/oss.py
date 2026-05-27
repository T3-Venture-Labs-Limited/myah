"""`myah dev oss {up,down,restart,status}` — worktree-scoped Hermes lifecycle.

Spawns `hermes gateway` and `hermes dashboard` in background processes scoped
to the worktree's isolated `<worktree>/.hermes/` (NOT main's `~/.hermes/`).
State (pidfiles, logs) lives in `<worktree>/.worktree-logs/` so multiple
worktrees can run isolated OSS stacks in parallel.

Mirrors the shape of `server.py` (backend/frontend lifecycle) adapted to the
two-service shape. Key invariants:

- Absolute venv-relative hermes path (Investigation C — bare `hermes` would
  PATH-resolve to whatever Hermes was installed globally).
- HERMES_HOME injected via env-merge so PATH (and the rest of os.environ)
  survive. Respects any HERMES_HOME the user pre-set via `dev hermes link-main`.
- Dashboard launches with `--insecure --host 0.0.0.0 --no-open` (per
  dev-oss.sh:16-20 — required so the platform docker container can reach
  via host.docker.internal).

Heavy imports (Rich, time, signal, urllib, subprocess.Popen, socket) live
inside command bodies so `myah --help` cold-start stays under the 200ms
budget (spec Metric #7).
"""

from __future__ import annotations

import os
import signal
import time
from pathlib import Path
from subprocess import Popen
from typing import Any

import typer

# Module-level alias for `run` so tests patch
# `myah.cli.dev.oss.run` (consumer namespace).
from myah.lib.cli.shell import run


# "Two services, one worktree. Wake the gateway; light the dashboard; let
#  the chat that follows belong to this branch alone." — oss.py


oss_app = typer.Typer(
    name='oss',
    help='Worktree-scoped Hermes gateway + dashboard lifecycle.',
    no_args_is_help=True,
)


# ---------------------------------------------------------------------------
# Worktree resolution + low-level helpers (mirrored from server.py / hermes.py)
# ---------------------------------------------------------------------------


def _get_worktree_path() -> Path:
    """Back-compat wrapper around `get_worktree_path`; raises typer.Exit(2)."""
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


def _is_process_dead(pid: int) -> bool:
    """True if `pid` is not currently a running process. ESRCH-tolerant."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return True
    except PermissionError:
        # PermissionError means process exists but we can't signal — alive.
        return False
    return False


# ---------------------------------------------------------------------------
# Env-chain loading + HERMES_HOME resolution
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


def _effective_hermes_home(worktree: Path, env: dict[str, str]) -> Path:
    """Compute HERMES_HOME for this worktree.

    Reads from the already-merged env (which includes os.environ +
    platform-oss/.env + .worktree-env). If HERMES_HOME is set, expand `~`
    and return it (e.g. `dev hermes link-main` writes `~/.hermes`).
    Otherwise default to `<worktree>/.hermes`.
    """
    raw = env.get('HERMES_HOME', '').strip()
    if raw:
        return Path(os.path.expanduser(raw))
    return worktree / '.hermes'


def _build_subprocess_env(env: dict[str, str], hermes_home: Path) -> dict[str, str]:
    """Compose the subprocess env: merged env-chain + HERMES_HOME override.

    The env-merge invariant: passing only `{'HERMES_HOME': ...}` would
    strip PATH and break the subprocess. `load_worktree_env_chain` already
    merges os.environ + .env files, so we just overlay the resolved
    HERMES_HOME on top.
    """
    return {**env, 'HERMES_HOME': str(hermes_home)}


def _require_hermes_binary(worktree: Path) -> Path:
    """Return the venv hermes binary path or exit 2 with a clear message."""
    from rich.console import Console

    bin_path = worktree / '.venv' / 'bin' / 'hermes'
    if not bin_path.is_file():
        Console().print(
            f"[red bold]Worktree's hermes binary not found[/] at [cyan]{bin_path}[/].\n"
            '[dim]Was this worktree created with [bold]myah dev worktree create <branch>[/]?[/]'
        )
        raise typer.Exit(code=2)
    return bin_path


def _port_or_default(env: dict[str, str], key: str, default: int) -> int:
    """Parse a port env-var; fall back to `default` on missing / malformed."""
    raw = env.get(key, '').strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


# ---------------------------------------------------------------------------
# Spawn helpers
# ---------------------------------------------------------------------------


def _spawn_service(
    worktree: Path,
    *,
    label: str,
    cmd: list[str],
    port: int,
    subprocess_env: dict[str, str],
) -> int:
    """Spawn a service in the background; return 0 on success, 1 on failure.

    Idempotent: if `port` is already listening, log a 'already running'
    message and return 0 without spawning. Writes pidfile + log file at
    `<worktree>/.worktree-logs/<label>.{pid,log}`.

    After spawn, sleeps briefly and checks that the process is still alive
    (matches dev-oss.sh:89-95). If it exited immediately, prints the tail
    of the log file and returns 1.
    """
    from rich.console import Console
    console = Console()

    if _is_port_listening(port):
        console.print(f'[dim]· {label} already running on :{port}[/]')
        return 0

    log_dir = worktree / '.worktree-logs'
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / f'{label}.log'
    pid_file = log_dir / f'{label}.pid'

    console.print(f'[bold]→[/] Starting {label} on :[cyan]{port}[/]')

    log_handle = log_file.open('a', buffering=1, encoding='utf-8')
    try:
        proc = Popen(
            cmd,
            env=subprocess_env,
            cwd=str(worktree),
            stdout=log_handle,
            stderr=log_handle,
            start_new_session=True,
        )
    except OSError as exc:
        console.print(f'[red bold]Failed to spawn {label}[/]: {exc}')
        log_handle.close()
        return 1

    _write_pidfile(pid_file, proc.pid)

    # Brief startup verification — matches dev-oss.sh:89-95 pattern.
    time.sleep(0.5)
    if _is_process_dead(proc.pid):
        console.print(f'[red bold]{label} exited immediately[/]')
        try:
            tail = log_file.read_text(encoding='utf-8').splitlines()[-10:]
            for line in tail:
                console.print(f'  [dim]{line}[/]')
        except OSError:
            pass
        pid_file.unlink(missing_ok=True)
        return 1

    console.print(f'[green]✓[/] {label} started (pid {proc.pid}, port {port})')
    return 0


# ---------------------------------------------------------------------------
# `up` orchestrator
# ---------------------------------------------------------------------------


def _do_up(worktree: Path) -> int:
    """Start gateway + dashboard. Returns 0 on full success, non-zero otherwise."""
    env = _load_env_or_exit(worktree)
    hermes_bin = _require_hermes_binary(worktree)
    hermes_home = _effective_hermes_home(worktree, env)
    subprocess_env = _build_subprocess_env(env, hermes_home)

    gateway_port = _port_or_default(env, 'MYAH_GATEWAY_PORT', 8643)
    dashboard_port = _port_or_default(env, 'MYAH_HERMES_WEB_PORT', 9119)

    rc_gateway = _spawn_service(
        worktree,
        label='gateway',
        cmd=[str(hermes_bin), 'gateway', 'run'],
        port=gateway_port,
        subprocess_env=subprocess_env,
    )
    if rc_gateway != 0:
        return rc_gateway

    # Dashboard --insecure --host 0.0.0.0 required so the platform docker
    # container can reach via host.docker.internal (dev-oss.sh:16-20).
    rc_dashboard = _spawn_service(
        worktree,
        label='dashboard',
        cmd=[
            str(hermes_bin), 'dashboard',
            '--no-open',
            '--insecure',
            '--host', '0.0.0.0',
        ],
        port=dashboard_port,
        subprocess_env=subprocess_env,
    )
    return rc_dashboard


# ---------------------------------------------------------------------------
# Stop helper + `down` orchestrator
# ---------------------------------------------------------------------------


def _stop_service(worktree: Path, label: str, port: int, pidfile: Path) -> None:
    """Stop a service: SIGTERM → wait → SIGKILL → cleanup pidfile."""
    from rich.console import Console
    console = Console()

    pid = _read_pidfile(pidfile)
    if pid is None:
        pid = _get_pid_by_port(port)

    if pid is None:
        # Nothing to do; tidy any stale pidfile and return.
        if pidfile.is_file():
            pidfile.unlink()
        return

    console.print(f'[bold]→[/] Stopping {label} (pid [cyan]{pid}[/], port [cyan]{port}[/])')

    _kill_pid(pid, signal.SIGTERM)

    # Grace period.
    time.sleep(2)

    if _is_port_listening(port):
        remaining = _get_pid_by_port(port) or pid
        console.print(f'[yellow]  ! force-killing stale process: {remaining}[/]')
        _kill_pid(remaining, signal.SIGKILL)

    if pidfile.is_file():
        pidfile.unlink()

    console.print(f'[green]✓[/] {label} stopped')


def _do_down(worktree: Path) -> int:
    """Stop gateway + dashboard. Always returns 0 (idempotent)."""
    log_dir = worktree / '.worktree-logs'
    env = _load_env_or_exit(worktree)
    gateway_port = _port_or_default(env, 'MYAH_GATEWAY_PORT', 8643)
    dashboard_port = _port_or_default(env, 'MYAH_HERMES_WEB_PORT', 9119)

    # Dashboard first — it's a client of the gateway; tearing it down
    # first avoids reconnection noise during gateway shutdown.
    _stop_service(worktree, 'dashboard', dashboard_port, log_dir / 'dashboard.pid')
    _stop_service(worktree, 'gateway', gateway_port, log_dir / 'gateway.pid')
    return 0


# ---------------------------------------------------------------------------
# Typer commands
# ---------------------------------------------------------------------------


@oss_app.command('up')
def up() -> None:
    """Start gateway + dashboard in background, scoped to this worktree."""
    worktree = _get_worktree_path()
    rc = _do_up(worktree)
    if rc != 0:
        raise typer.Exit(code=rc)


@oss_app.command('down')
def down() -> None:
    """Stop gateway + dashboard (SIGTERM → SIGKILL after grace)."""
    worktree = _get_worktree_path()
    _do_down(worktree)


@oss_app.command('restart')
def restart() -> None:
    """Stop both, then start them again."""
    worktree = _get_worktree_path()
    _do_down(worktree)
    rc = _do_up(worktree)
    if rc != 0:
        raise typer.Exit(code=rc)


@oss_app.command('status')
def status() -> None:
    """Show gateway + dashboard status (PID/port/health) in a Rich table."""
    from rich.console import Console
    from rich.table import Table

    console = Console()
    worktree = _get_worktree_path()
    env = _load_env_or_exit(worktree)

    gateway_port = _port_or_default(env, 'MYAH_GATEWAY_PORT', 8643)
    dashboard_port = _port_or_default(env, 'MYAH_HERMES_WEB_PORT', 9119)

    hermes_home = _effective_hermes_home(worktree, env)

    table = Table(title='Worktree Hermes Status', show_header=True, header_style='bold')
    table.add_column('Service', style='cyan')
    table.add_column('Port', justify='right')
    table.add_column('PID', justify='right')
    table.add_column('Status', justify='center')
    table.add_column('Health', justify='center')

    def _row(
        label: str, port: int, pidfile_name: str, health_url: str,
    ) -> tuple[str, str, str, str, str]:
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

    table.add_row(*_row(
        'gateway', gateway_port, 'gateway.pid',
        f'http://127.0.0.1:{gateway_port}/health',
    ))
    table.add_row(*_row(
        'dashboard', dashboard_port, 'dashboard.pid',
        f'http://127.0.0.1:{dashboard_port}/',
    ))

    console.print(table)
    console.print(f'[dim]HERMES_HOME:[/] [cyan]{hermes_home}[/]')
    console.print(
        f'[dim]logs:        [/] {worktree}/.worktree-logs/{{gateway,dashboard}}.log'
    )


__all__: list[str] = ['oss_app']
