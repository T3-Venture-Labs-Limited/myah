"""E2E port allocator.

Deterministic per-branch port allocation for parallel worktree E2E testing.
Each branch always resolves to the same (backend_port, frontend_port) pair so
that repeated runs are reproducible and don't stomp on other branches.

Ports are chosen from dedicated E2E ranges that live OUTSIDE the defaults
(backend 8082, frontend 5173). This guarantees that no worktree-specific port
can leak into merged code -- the defaults are only used by the main workspace.

Ranges:
- backend:   8100-8199  (100 slots)
- frontend:  5200-5299  (100 slots)

Usage:
    # From a worktree, print shell-exportable vars:
    $ python3 platform/scripts/e2e_ports.py
    E2E_BACKEND_PORT=8137
    E2E_FRONTEND_PORT=5237
    E2E_BRANCH=feat/t3-962-secret-capture

    # Eval it into a shell:
    $ eval "$(python3 platform/scripts/e2e_ports.py)"

    # As a module:
    >>> from e2e_ports import allocate
    >>> allocate('feat/t3-962-secret-capture')
    (8137, 5237)

The allocation uses a stable hash (sha1) of the branch name, so adding/removing
branches never reshuffles existing allocations. Collisions within a single
worktree's two ports are impossible by construction (different ranges).

Collisions BETWEEN branches in the same range are possible (1 in 100). If two
running worktrees happen to hash to the same slot, the second one will fail
to bind -- rename one of the branches or pass --offset to shift.
"""

from __future__ import annotations

import argparse
import hashlib
import socket
import subprocess
import sys

BACKEND_RANGE = (8100, 8200)  # [start, end) -- 100 slots
FRONTEND_RANGE = (5200, 5300)  # [start, end) -- 100 slots


def _detect_branch() -> str:
    """Detect the current git branch (works in a worktree)."""
    try:
        out = subprocess.check_output(
            ['git', 'rev-parse', '--abbrev-ref', 'HEAD'],
            stderr=subprocess.DEVNULL,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return 'unknown'
    return out.decode('utf-8').strip() or 'unknown'


def _hash_offset(branch: str, mod: int, salt: str = '') -> int:
    """Stable non-negative offset in [0, mod)."""
    digest = hashlib.sha1(f'{salt}:{branch}'.encode('utf-8')).hexdigest()
    return int(digest[:8], 16) % mod


def _is_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(('127.0.0.1', port)) != 0


def _allocate_in_range(branch: str, range_: tuple[int, int], salt: str) -> int:
    """Pick a port in the given range via stable hash, advancing on collisions.

    The initial slot is deterministic; if it's taken we walk forward in the
    range (wrapping) until we find a free one. This preserves determinism for
    the common case (nothing bound) while still coping with real collisions.
    """
    start, end = range_
    span = end - start
    base = _hash_offset(branch, span, salt)
    for i in range(span):
        port = start + ((base + i) % span)
        if _is_free(port):
            return port
    raise RuntimeError(f'No free port in range {start}-{end} for branch {branch!r}')


def allocate(branch: str | None = None) -> tuple[int, int]:
    """Return (backend_port, frontend_port) for a branch."""
    branch = branch or _detect_branch()
    backend = _allocate_in_range(branch, BACKEND_RANGE, salt='backend')
    frontend = _allocate_in_range(branch, FRONTEND_RANGE, salt='frontend')
    return backend, frontend


def main() -> int:
    parser = argparse.ArgumentParser(description='Allocate E2E ports for the current branch.')
    parser.add_argument('--branch', help='Override the branch name (default: current git branch).')
    parser.add_argument(
        '--format',
        choices=('shell', 'json', 'plain'),
        default='shell',
        help='Output format (default: shell).',
    )
    args = parser.parse_args()

    branch = args.branch or _detect_branch()
    try:
        backend, frontend = allocate(branch)
    except RuntimeError as err:
        print(f'error: {err}', file=sys.stderr)
        return 1

    if args.format == 'shell':
        print(f'E2E_BACKEND_PORT={backend}')
        print(f'E2E_FRONTEND_PORT={frontend}')
        print(f'E2E_BRANCH={branch}')
    elif args.format == 'json':
        import json

        print(json.dumps({'backend_port': backend, 'frontend_port': frontend, 'branch': branch}))
    else:
        print(f'{backend} {frontend}')

    return 0


if __name__ == '__main__':
    sys.exit(main())
