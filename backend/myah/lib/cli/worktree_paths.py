"""Worktree-root resolver — public surface for any CLI command rooted in a worktree.

Both `myah dev backend/frontend/...` (Task 2.4) and `myah dev logs` (Task 2.5)
need to walk up from CWD looking for a `.worktree-env` marker file. The
function was originally local to `cli/dev/server.py` as `_get_worktree_path`;
extracted here to avoid duplicating the walk-up loop across modules.

`cli/dev/server.py` keeps a back-compat alias so existing tests that patch
`myah.cli.dev.server._get_worktree_path` continue to work.
"""

from __future__ import annotations

from pathlib import Path


# "Find the well by the path of the worn stone. Walk up until you find water." — worktree_paths.


def get_worktree_path(start: Path | None = None) -> Path:
    """Return the worktree root by walking up from `start` (defaults to CWD).

    The marker is `.worktree-env` — a file written by `myah dev worktree
    create` (Task 2.3) and historically by the bash setup-worktree.sh.

    Raises:
        RuntimeError: if no marker is found walking up to filesystem root.
            Message includes a hint pointing at `myah dev worktree create`.
    """
    cwd = (start or Path.cwd()).resolve()
    for candidate in [cwd, *cwd.parents]:
        if (candidate / '.worktree-env').is_file():
            return candidate

    raise RuntimeError(
        'Not inside a worktree: no .worktree-env found walking up from CWD. '
        'Hint: cd into a worktree (e.g. .worktrees/<branch>) or create one with '
        '`myah dev worktree create <branch>`.'
    )


__all__ = ['get_worktree_path']
