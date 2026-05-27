"""`myah status` — compact snapshot of what is running.

A one-shot informational read of the host. Walks a small set of known
services, asks the kernel "is anything listening on this port", and
prints a Rich table. Always exits 0 — status is observed, not enforced;
shell pipelines that follow `myah status` should not be aborted just
because a service happens to be down.
"""

from __future__ import annotations

import socket

from rich.console import Console
from rich.table import Table

from myah.lib.cli.shell import run


# Services we know about and the ports they should occupy.
# Tuple shape: (display name, port, free-form notes column).
_SERVICES = [
    ('platform', 8080, 'docker compose myah-platform'),
    ('gateway', 8642, 'hermes gateway'),
    ('gateway-myah-adapter', 8643, 'myah-hermes-plugin adapter'),
    ('dashboard', 9119, 'hermes dashboard'),
]


def _port_listening(port: int) -> bool:
    """Quick check: is anything listening on `port` on localhost?

    Returns True iff a TCP connect to 127.0.0.1:`port` succeeds within
    half a second. False on any OSError (refused, timeout, unreachable).
    """
    try:
        with socket.create_connection(('127.0.0.1', port), timeout=0.5):
            return True
    except OSError:
        return False


def _platform_container_running() -> bool:
    """Is the myah-platform docker container running?

    Distinguishes 'container alive but port not yet bound' (yellow) from
    'nothing here at all' (red). Tolerant of docker absence — a failed
    `docker ps` simply means we cannot prove the container is up.
    """
    result = run(['docker', 'ps', '--filter', 'name=myah-platform', '-q'])
    return result.returncode == 0 and bool(result.stdout.strip())


def status_command() -> None:
    """Show a compact table of running services + ports.

    Informational only. Never raises, never exits non-zero.
    """
    console = Console()
    table = Table(title='Myah Status', show_header=True, header_style='bold')
    table.add_column('Service', style='cyan')
    table.add_column('Port', justify='right')
    table.add_column('Status', justify='center')
    table.add_column('Notes', style='dim')

    for name, port, notes in _SERVICES:
        listening = _port_listening(port)
        if listening:
            status = '[green]up[/]'
        else:
            # For platform specifically, also check the container — the
            # docker container may be alive but not yet bound to the port.
            if name == 'platform' and _platform_container_running():
                status = '[yellow]container up; port not bound[/]'
            else:
                status = '[red]down[/]'
        table.add_row(name, str(port), status, notes)

    console.print(table)
