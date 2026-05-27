"""Pure file-I/O helpers for switching a worktree between oss and hosted mode.

Lives under `myah.lib.cli` so the Typer command layer at `myah.cli.dev.mode`
stays thin (it's just argument parsing + Rich rendering on top of these
functions). Testable in isolation from CLI plumbing — `test_dev_mode.py`
exercises each helper directly via tmp_path.

Mode-switch contract (per spec §"Mode switching mechanics"):

- `switch_to_oss(worktree_path)`:
    1. Set `MYAH_DEPLOYMENT_MODE=oss`
    2. Set `MYAH_AUTH=false`
    3. Comment out (prefix `# `) any uncommented `COMPOSIO_API_KEY`,
       `HONCHO_ADMIN_KEY`, `HONCHO_BASE_URL`, `HONCHO_WORKSPACE_ID` lines.
    4. Preserve every other env var unchanged — in particular the three
       fresh bearer/signing tokens written at worktree-create time.

- `switch_to_hosted(worktree_path, main_repo_root)`:
    1. Set `MYAH_AUTH=true`
    2. Comment out `MYAH_DEPLOYMENT_MODE` (hosted is the implicit default).
    3. For each of `COMPOSIO_API_KEY`, `HONCHO_ADMIN_KEY`, `HONCHO_BASE_URL`,
       `HONCHO_WORKSPACE_ID`: if main's `platform-oss/.env` defines it,
       copy the value into the worktree's `.env`. If main is silent the
       worktree is left untouched (so a previously-commented value
       survives as commented).
    4. Ensure `OAUTH_SESSION_TOKEN_ENCRYPTION_KEY` exists — preserve any
       existing value (commented or live), otherwise generate a fresh
       token via `secrets.token_urlsafe(32)`.

- `get_current_mode(worktree_path) -> Literal['oss', 'hosted']`:
    Returns 'oss' iff an uncommented `MYAH_DEPLOYMENT_MODE=oss` line is
    present in `<worktree>/platform-oss/.env`. Otherwise 'hosted'.
"""

from __future__ import annotations

import secrets
from pathlib import Path
from typing import Literal

from loguru import logger

from myah.lib.cli.env_loader import parse_env_file
from myah.lib.cli.worktree_setup import set_env_var

# "Flip the sign at the door. Comment out what the other tenant left.
#  The walls don't change — only which keys still open the lock." — mode_switch.


HOSTED_ONLY_KEYS: tuple[str, ...] = (
    'COMPOSIO_API_KEY',
    'HONCHO_ADMIN_KEY',
    'HONCHO_BASE_URL',
    'HONCHO_WORKSPACE_ID',
)


def _worktree_env_path(worktree_path: Path) -> Path:
    return worktree_path / 'platform-oss' / '.env'


def _main_env_path(main_repo_root: Path) -> Path:
    return main_repo_root / 'platform-oss' / '.env'


def comment_out_env_var(path: Path, key: str) -> None:
    """Prefix `# ` onto any uncommented `KEY=...` (or `export KEY=...`) line.

    No-op if `path` does not exist, if the key is absent, or if every
    matching line is already commented. Preserves the `export ` prefix
    (the `# ` goes BEFORE `export `, so a re-uncomment yields the
    original line shape).

    This is the OSS-mode equivalent of removing a key: we keep the value
    around so a later `mode hosted` switch could uncomment it cheaply,
    even though the hosted path actually re-copies from main's .env.
    """
    if not path.is_file():
        return

    lines = path.read_text(encoding='utf-8').splitlines(keepends=True)
    changed = False
    out: list[str] = []
    for line in lines:
        stripped = line.lstrip()
        if stripped.startswith('#'):
            out.append(line)
            continue
        candidate = stripped
        if candidate.startswith('export '):
            candidate = candidate[len('export '):].lstrip()
        eq_idx = candidate.find('=')
        if eq_idx > 0 and candidate[:eq_idx].strip() == key:
            # Insert `# ` at the start of the line (preserving original indent).
            indent_len = len(line) - len(stripped)
            indent = line[:indent_len]
            out.append(f'{indent}# {stripped}')
            changed = True
        else:
            out.append(line)

    if changed:
        path.write_text(''.join(out), encoding='utf-8')


def get_current_mode(worktree_path: Path) -> Literal['oss', 'hosted']:
    """Return 'oss' if MYAH_DEPLOYMENT_MODE=oss is live in the worktree .env, else 'hosted'.

    `parse_env_file` already skips comment lines, so a commented-out
    `# MYAH_DEPLOYMENT_MODE=oss` correctly resolves to hosted.
    """
    env = parse_env_file(_worktree_env_path(worktree_path))
    mode_value = env.get('MYAH_DEPLOYMENT_MODE', '').strip().lower()
    if mode_value == 'oss':
        return 'oss'
    return 'hosted'


def switch_to_oss(worktree_path: Path) -> None:
    """Rewrite `<worktree>/platform-oss/.env` so the worktree boots in OSS mode.

    The bearer/signing tokens written at worktree-create time MUST survive —
    only the mode flags + hosted-only secrets are touched.
    """
    env_path = _worktree_env_path(worktree_path)

    # Mode flags first — set_env_var upserts in place (preserving export prefix).
    set_env_var(env_path, 'MYAH_DEPLOYMENT_MODE', 'oss')
    set_env_var(env_path, 'MYAH_AUTH', 'false')

    # Hosted-only keys: comment-out (not delete) so a later flip can reason
    # about previous state if needed.
    for key in HOSTED_ONLY_KEYS:
        comment_out_env_var(env_path, key)

    logger.debug(f'switch_to_oss: rewrote {env_path}')


def switch_to_hosted(worktree_path: Path, main_repo_root: Path) -> None:
    """Rewrite `<worktree>/platform-oss/.env` so the worktree boots in hosted mode.

    Pulls COMPOSIO/HONCHO secrets from main's `.env` if present. If main
    has nothing for a given key, the worktree's `.env` is left untouched
    for that key (a previously-commented stub survives as commented; an
    absent key stays absent). Always ensures OAUTH_SESSION_TOKEN_
    ENCRYPTION_KEY exists, generating a fresh one if neither the worktree
    nor main supplied one.
    """
    env_path = _worktree_env_path(worktree_path)

    # MYAH_AUTH=true; comment out MYAH_DEPLOYMENT_MODE (hosted is the
    # implicit default — no need for an explicit value).
    set_env_var(env_path, 'MYAH_AUTH', 'true')
    comment_out_env_var(env_path, 'MYAH_DEPLOYMENT_MODE')

    # Pull COMPOSIO + HONCHO_* from main's .env if main has them.
    main_env = parse_env_file(_main_env_path(main_repo_root))
    for key in HOSTED_ONLY_KEYS:
        value = main_env.get(key, '').strip()
        if value:
            set_env_var(env_path, key, value)
        # else: deliberately leave the worktree's .env alone for this key.

    # OAuth session-token encryption key — required by hosted OAuth flows.
    worktree_env = parse_env_file(env_path)
    existing_oauth = worktree_env.get('OAUTH_SESSION_TOKEN_ENCRYPTION_KEY', '').strip()
    if not existing_oauth:
        main_oauth = main_env.get('OAUTH_SESSION_TOKEN_ENCRYPTION_KEY', '').strip()
        oauth_value = main_oauth or secrets.token_urlsafe(32)
        set_env_var(env_path, 'OAUTH_SESSION_TOKEN_ENCRYPTION_KEY', oauth_value)

    logger.debug(f'switch_to_hosted: rewrote {env_path}')


__all__ = [
    'HOSTED_ONLY_KEYS',
    'comment_out_env_var',
    'get_current_mode',
    'switch_to_hosted',
    'switch_to_oss',
]
