"""Env-composition source-of-truth for the worktree dev-server commands.

The `myah dev backend/frontend/both` commands spawn uvicorn and vite with an
environment built by overlaying three sources, in this order:

    1. os.environ                  (parent shell — preserves PATH)
    2. <worktree>/platform-oss/.env  (shared secrets, copied from main)
    3. <worktree>/.worktree-env      (per-branch overrides — ports, mode)

The order is the H7 invariant. Reverse it and `MYAH_PLATFORM_PORT` silently
falls back to the baked default `8082` in `.env`, which the per-user agent
container reads to fetch attachments — and the attachment dispatch silently
breaks on every chat send.

Per AGENTS.md "Attachment Pipeline Invariants" #2 and the spec at
`docs/superpowers/specs/2026-05-22-devx-oss-cli-design.md` §"CLI Command
Surface".

This module also exposes `parse_env_file` — the shared parser for `.env`-style
files. The same parser previously lived as `_parse_env_line` in
`worktree_setup.py` and `_parse_env_file_subset` in `cli/dev/worktree.py`; both
are now thin wrappers around `parse_env_file`.
"""

from __future__ import annotations

import os
from pathlib import Path

from loguru import logger


# "Three sources, one well. Whichever drop falls last is the one you taste." — H7.


def parse_env_file(path: Path) -> dict[str, str]:
    """Parse a `.env`-style file into a dict.

    Recognized syntax:
        - Comments (`# ...`) and blank lines are skipped.
        - Optional `export ` prefix is stripped.
        - Lines without `=` are skipped (logged at debug level).
        - A matching pair of single or double quotes wrapping the value is
          stripped; mismatched or unbalanced quotes are preserved as-is.
        - Trailing whitespace on the value is stripped before quote handling.

    If `path` does not exist, returns `{}` — callers decide whether a missing
    file is a hard error. This mirrors the bash `. file.env` behavior of
    failing only on syntax, not on absence.

    Pure parser: no `python-dotenv` dependency, no shell expansion, no
    interpolation. The CLI does not need any of those.
    """
    if not path.is_file():
        return {}

    out: dict[str, str] = {}
    for raw_line in path.read_text(encoding='utf-8').splitlines():
        stripped = raw_line.strip()
        if not stripped or stripped.startswith('#'):
            continue
        if stripped.startswith('export '):
            stripped = stripped[len('export '):].lstrip()
        if '=' not in stripped:
            logger.debug(f'parse_env_file: skipping malformed line in {path}: {raw_line!r}')
            continue
        key, value = stripped.split('=', 1)
        key = key.strip()
        value = value.rstrip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
            value = value[1:-1]
        out[key] = value
    return out


def load_worktree_env_chain(worktree_path: Path) -> dict[str, str]:
    """Compose the env-var dict for spawning dev-server subprocesses.

    Source order (H7 invariant — must NOT be reversed):

        1. Start from os.environ (preserves PATH and parent-shell state).
        2. Overlay <worktree_path>/platform-oss/.env (shared secrets from main).
        3. Overlay <worktree_path>/.worktree-env (per-branch ports + overrides).

    Returns a merged dict suitable for `subprocess.Popen(env=...)`.

    Raises:
        RuntimeError: if .worktree-env is missing (worktree not set up — caller
            should hint at `myah dev worktree create <branch>`).

    The `platform-oss/.env` file is optional — if missing, this function logs a
    warning and proceeds. The bearer-fail-fast guard in the calling command
    catches the resulting empty `MYAH_AGENT_BEARER_TOKEN`.
    """
    worktree_env_path = worktree_path / '.worktree-env'
    if not worktree_env_path.is_file():
        raise RuntimeError(
            f'.worktree-env not found at {worktree_env_path}. '
            f'Run `myah dev worktree create <branch>` first to materialize the worktree.'
        )

    env: dict[str, str] = dict(os.environ)

    platform_env_path = worktree_path / 'platform-oss' / '.env'
    if platform_env_path.is_file():
        env.update(parse_env_file(platform_env_path))
    else:
        logger.warning(
            f'platform-oss/.env not found at {platform_env_path} — the bearer-fail-fast '
            f'guard will catch any resulting empty MYAH_AGENT_BEARER_TOKEN.'
        )

    env.update(parse_env_file(worktree_env_path))
    return env


__all__ = ['load_worktree_env_chain', 'parse_env_file']
