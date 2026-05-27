"""Per-worktree setup primitives for `myah dev worktree create`.

This module hosts the lib-level building blocks that the user-facing
`myah dev worktree create` command (Slice 2 Task 2.3) will compose into
a single orchestrated flow with rollback.

Commits A, B, and C scope: venv-side + hermes-side + env-composition
primitives. A: `setup_venv`, `install_platform_into_venv`. B:
`setup_isolated_hermes`, `install_hermes_into_venv`,
`install_plugin_into_hermes`, `materialize_dashboard_shim`. C (this
commit): `read_main_env_for_copy`, `generate_fresh_tokens`,
`write_worktree_env`. The remaining commit (D) wires A+B+C together
into the `create_worktree` orchestrator with rollback.

Design notes carried over from Slice 0 spike findings:

- All subprocess calls go through `myah.lib.cli.shell.run` so tests can
  mock at a single point (consumer-namespace, `myah.lib.cli.worktree_setup.run`).
- `shell.run`'s `env=` kwarg REPLACES the parent environment. Callers
  that need to override one var while preserving PATH/etc. MUST merge
  with `os.environ` explicitly. See `install_platform_into_venv` and
  `materialize_dashboard_shim`.
- Absolute venv-relative paths (`<worktree>/.venv/bin/{python,pip,
  myah-hermes-plugin}`) beat PATH-based resolution (Investigation C).
  PATH-based resolution would silently fall back to the main system's
  Python/pip/console-script when the worktree venv isn't activated, and
  the per-worktree isolation guarantee would silently break.
- `MYAH_SKIP_HATCH_NPM=1` skips the hatch frontend-build hook so the
  editable install can succeed inside a Node-less worktree venv. The
  env-var skip alone is insufficient — Slice 2 Task 2.1 also committed
  `platform-oss/build/.gitkeep` so the `force-include` validation passes
  during editable installs (Investigation B).
- The Hermes install path is git+SHA, not curl-bash or PyPI (Slice 0
  Decision 1, Path 2). PyPI's `hermes-agent` lags the production pin and
  ships no extras; the curl-bash installer drops a system-wide binary
  outside the worktree venv. Only git+SHA gives production parity with
  the full extras set inside a per-worktree-isolated venv.
"""

from __future__ import annotations

import json
import os
import re
import secrets
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Literal

from loguru import logger

from myah.lib.cli.shell import run

# Canonical Hermes extras set — kept in sync with agent/Dockerfile.stock.
# If you bump the production extras, bump this too (and the spec).
_DEFAULT_HERMES_EXTRAS: tuple[str, ...] = (
    'messaging',
    'cron',
    'honcho',
    'mcp',
    'voice',
    'pty',
    'web',
)

# H2 hosted-mode secret distribution decision (plan §2.2d): when a new
# worktree is materialized, COPY these non-bearer secrets from main's
# platform-oss/.env so the worktree can talk to the same external APIs
# (OpenRouter, Sentry, Langfuse) without re-typing keys. GENERATE FRESH
# values for the bearer/signing set (MYAH_AGENT_BEARER_TOKEN,
# MYAH_HERMES_WEB_SESSION_TOKEN, MYAH_SECRET_KEY) so that cross-worktree
# session bleed is structurally impossible. The two sets MUST be
# disjoint — locking that invariant is the job of the test cross-check.
_NON_BEARER_SECRET_KEYS: frozenset[str] = frozenset({
    'OPENROUTER_API_KEY',
    'SENTRY_DSN_PLATFORM',
    'LANGFUSE_PUBLIC_KEY',
    'LANGFUSE_SECRET_KEY',
    'LANGFUSE_HOST',
    'OAUTH_SESSION_TOKEN_ENCRYPTION_KEY',
})

# Keys that `generate_fresh_tokens` returns — explicitly NOT copied from
# main. Kept as a separate constant rather than re-deriving so the H2
# disjoint invariant can be asserted directly in tests.
_BEARER_TOKEN_KEYS: tuple[str, ...] = (
    'MYAH_AGENT_BEARER_TOKEN',
    'MYAH_HERMES_WEB_SESSION_TOKEN',
    'MYAH_SECRET_KEY',
)

# Dockerfile.stock is the single source of truth for the production-pinned
# Hermes + plugin SHAs (see AGENTS.md "Bumping Hermes / Plugin SHA Pins").
# `create_worktree` reads them at runtime so a Dockerfile bump propagates
# to all new worktrees without code changes.
_DOCKERFILE_PATH = Path('agent/Dockerfile.stock')

# 40-char hex SHA, anchored. Trailing whitespace / comment tolerated.
_ARG_SHA_RE = re.compile(r'^\s*ARG\s+(?P<name>[A-Z_]+)\s*=\s*(?P<sha>[0-9a-fA-F]{40})\s*(?:#.*)?$')

# The 4 Hermes-side .env slots that `align_hermes_env_tokens` writes.
# The 5th alignment slot — the platform .env's MYAH_AGENT_BEARER_TOKEN —
# is written separately by `write_worktree_platform_env` from the same
# `fresh_tokens` dict, so all five values agree by construction.
_HERMES_ENV_BEARER_SLOTS: tuple[str, ...] = (
    'MYAH_AGENT_BEARER_TOKEN',
    'MYAH_ADAPTER_AUTH_KEY',
    'API_SERVER_KEY',
    'MYAH_PLATFORM_BEARER',
)


# "Carry the SHA across the threshold, never invent it. The Dockerfile
#  is the canon; we only read." — single source of truth, made explicit.


def _read_arg_sha(dockerfile_path: Path, arg_name: str) -> str:
    """Extract `ARG <arg_name>=<40-char-sha>` from a Dockerfile.

    Tolerates trailing whitespace and a `# comment` after the value.
    Raises RuntimeError with the arg name and path if the line is
    missing, malformed, or the SHA isn't a valid 40-char hex string.
    """
    if not dockerfile_path.is_file():
        raise RuntimeError(
            f'Dockerfile not found at {dockerfile_path}. Cannot read {arg_name}.'
        )

    for raw_line in dockerfile_path.read_text(encoding='utf-8').splitlines():
        match = _ARG_SHA_RE.match(raw_line)
        if match and match.group('name') == arg_name:
            return match.group('sha')

    raise RuntimeError(
        f'Could not find a valid `ARG {arg_name}=<40-char-sha>` line in {dockerfile_path}. '
        f'Either the arg is missing or the SHA is malformed (must be 40 hex chars).'
    )


def _read_hermes_sha(dockerfile_path: Path) -> str:
    """Return the 40-char `HERMES_SHA` pin from Dockerfile.stock (line ~13)."""
    return _read_arg_sha(dockerfile_path, 'HERMES_SHA')


def _read_plugin_sha(dockerfile_path: Path) -> str:
    """Return the 40-char `MYAH_PLUGIN_SHA` pin from Dockerfile.stock (line ~183)."""
    return _read_arg_sha(dockerfile_path, 'MYAH_PLUGIN_SHA')


def _require_venv_pip(worktree_path: Path) -> Path:
    """Return the worktree's venv pip path, or raise RuntimeError with a clear hint.

    Every subprocess that invokes pip in a worktree must go through this
    helper. The hint mentions `setup_venv` so a caller who skipped the
    venv-creation step gets immediate, actionable feedback (per
    Investigation C: bare `pip` would silently resolve to the system pip
    and break per-worktree isolation).
    """
    pip = worktree_path / '.venv' / 'bin' / 'pip'
    if not pip.exists():
        raise RuntimeError(
            f'venv pip not found at {pip}. Run `setup_venv({worktree_path})` first '
            f'(or `myah dev worktree create` for the full orchestrated path).'
        )
    return pip

# "May the venv we set down here be a home, not a cage —
#  isolation that protects, but a path back to the trunk."


def setup_venv(worktree_path: Path) -> None:
    """Create a per-worktree Python venv at `<worktree_path>/.venv`.

    Uses `sys.executable -m venv` so the worktree venv runs the exact
    same Python interpreter that's executing this CLI. PATH-based
    resolution (`python3 -m venv ...`) would risk picking a different
    Python on machines with multiple installs.

    Idempotent: if `<worktree_path>/.venv/bin/python` already exists,
    returns without re-invoking venv creation. Callers running a repair
    pass on a partially-built worktree won't double-create.

    Raises `ShellError` on a non-zero exit from `python -m venv` (the
    `create_worktree` orchestrator catches and triggers rollback).
    """
    venv_python = worktree_path / '.venv' / 'bin' / 'python'
    if venv_python.exists():
        return

    run([sys.executable, '-m', 'venv', str(worktree_path / '.venv')], check=True)


def install_platform_into_venv(worktree_path: Path, *, skip_hatch_npm: bool = True) -> None:
    """Editable-install the platform-oss package into the worktree venv.

    Invokes `<worktree>/.venv/bin/pip install -e <worktree>/platform-oss[dev]`.

    When `skip_hatch_npm=True` (default), passes `MYAH_SKIP_HATCH_NPM=1`
    in the subprocess environment so `platform-oss/hatch_build.py` short-
    circuits its frontend build step. The env is MERGED with
    `os.environ` rather than replacing it — `shell.run`'s `env=` kwarg
    fully replaces the subprocess env, so passing only `{'MYAH_SKIP_...': '1'}`
    would strip PATH and the pip subprocess would fail to resolve its
    own dependencies. See `doctor_checks.check_hermes_plugin_installed`
    for the canonical merge pattern.

    Validates the venv exists before calling pip. If
    `<worktree>/.venv/bin/pip` is missing, raises `RuntimeError` with a
    message telling the caller to run `setup_venv` first.

    Raises `ShellError` on a non-zero pip exit so the orchestrator can
    roll back partial state.
    """
    pip = _require_venv_pip(worktree_path)

    cmd = [str(pip), 'install', '-e', f'{worktree_path / "platform-oss"}[dev]']

    if skip_hatch_npm:
        # Merge — never replace — so PATH and the rest of the parent env survive.
        env = {**os.environ, 'MYAH_SKIP_HATCH_NPM': '1'}
        run(cmd, check=True, env=env)
    else:
        run(cmd, check=True)


# "Pour the foundation before the walls. Pour the walls before the roof.
#  Pour patience over all three." — order of operations, for the worktree.


def setup_isolated_hermes(worktree_path: Path) -> None:
    """Materialize the per-worktree Hermes overlay at `<worktree>/.hermes/`.

    Creates the directory tree (plugins/, data/, skills/, models/, cache/,
    logs/) and writes two initial files:

    1. `.env` with a pre-populated `MYAH_ADAPTER_AUTH_KEY`. Per Slice 0
       Investigation A, `hermes plugins install` and the plugin's own
       install flow trigger an interactive `getpass` prompt for this
       value. The prompt hangs forever on non-TTY callers (CI, the
       `myah dev worktree create` orchestrator). Pre-writing a value
       here is what makes the subsequent `install_plugin_into_hermes`
       call complete non-interactively. The placeholder token is
       generated with `secrets.token_urlsafe(32)`; Commit C will
       overwrite it with the canonical token aligned across all five
       slots (see `setup-myah-oss.sh:282–286`).

    2. `config.yaml` enabling `gateway.platforms.myah`. Without
       `enabled: true`, the gateway loads the plugin but never spins
       up the platform adapter, and the OSS probe reports
       `plugin_installed=false` (see `setup-myah-oss.sh:503–525` for
       the canonical same-shape template).

    Idempotent: if either file already exists, it is preserved
    untouched. The user may have hand-edited tokens or platform
    configuration between worktree creates; we must not stomp those
    edits on a repair-pass invocation.

    No subprocess calls. Pure file I/O. Filesystem exceptions propagate
    so the Commit D orchestrator can catch them and roll back the
    partially-built worktree.
    """
    hermes_root = worktree_path / '.hermes'
    for sub in ('', 'plugins', 'data', 'skills', 'models', 'cache', 'logs'):
        (hermes_root / sub).mkdir(parents=True, exist_ok=True)

    env_file = hermes_root / '.env'
    if not env_file.exists():
        token = secrets.token_urlsafe(32)
        env_file.write_text(f'MYAH_ADAPTER_AUTH_KEY={token}\n', encoding='utf-8')

    config_path = hermes_root / 'config.yaml'
    if not config_path.exists():
        # Mirrors setup-myah-oss.sh:519–525. Hand-written literal rather
        # than yaml.safe_dump so the leading comment survives intact
        # (yaml.safe_dump strips comments and re-orders keys).
        config_path.write_text(
            '# Auto-generated by myah dev worktree create — safe to edit by hand.\n'
            'gateway:\n'
            '  platforms:\n'
            '    myah:\n'
            '      enabled: true\n',
            encoding='utf-8',
        )


def install_hermes_into_venv(
    worktree_path: Path,
    hermes_sha: str,
    *,
    extras: tuple[str, ...] = _DEFAULT_HERMES_EXTRAS,
) -> None:
    """Pip-install upstream Hermes into the worktree venv at the pinned SHA.

    Uses git+SHA per Slice 0 Decision 1 (Path 2). Rationale: PyPI's
    `hermes-agent` (Path 1) lags the production pin in `Dockerfile.stock`
    and ships no extras; the curl-bash installer (Path 3) drops a
    system-wide binary outside the worktree's venv and defeats per-
    worktree isolation. Only git+SHA into the local venv gives both
    production parity (same SHA as the prod agent image) and isolation
    (lives at `<worktree>/.venv`, no impact on the main `~/.hermes/`).

    `extras` defaults to the canonical set mirrored from
    `agent/Dockerfile.stock` so a per-worktree dev install matches what
    the prod agent ships. Override only when a slice or test explicitly
    needs a subset.

    Invokes the absolute `<worktree>/.venv/bin/pip` path
    (Investigation C). PATH-based resolution would silently fall back
    to the system pip on machines where the worktree venv isn't
    activated, and the install would land in the wrong place.

    Raises `RuntimeError` if the venv pip doesn't exist (caller must
    run `setup_venv` first) and `ShellError` on a non-zero pip exit
    (caught by the Commit D orchestrator for rollback).
    """
    pip = _require_venv_pip(worktree_path)

    extras_joined = ','.join(extras)
    pip_arg = (
        f'hermes-agent[{extras_joined}] @ '
        f'git+https://github.com/NousResearch/Hermes-Agent@{hermes_sha}'
    )
    run([str(pip), 'install', '--upgrade', pip_arg], check=True)


def install_plugin_into_hermes(worktree_path: Path, plugin_sha: str) -> None:
    """Pip-install the myah-hermes-plugin into the worktree venv.

    Per `setup-myah-oss.sh:472–489`: pip-installing the plugin into the
    same venv as Hermes is what makes `myah_hermes_plugin.myah_admin.
    dashboard.plugin_api` importable from the dashboard process at
    runtime. `hermes plugins install` only materializes the gateway-
    side shim under `~/.hermes/plugins/`; it does NOT pip-install the
    package. That's why this step exists as a separate primitive.

    Per-worktree variant: uses `<worktree>/.venv/bin/pip` (not the main
    Hermes venv) and assumes `setup_isolated_hermes` already ran and
    pre-populated `<worktree>/.hermes/.env` with
    `MYAH_ADAPTER_AUTH_KEY`. Without that pre-population, the plugin's
    own setup hooks would trigger an interactive `getpass` prompt
    (Investigation A) and hang the orchestrator.

    The plugin repo is public, so no auth is needed for the git+SHA
    clone — pip pulls it unauthenticated. (The production install
    script supports `MYAH_PLUGIN_AUTH_TOKEN` for private forks; the
    dev-loop case here doesn't need it.)

    Raises `RuntimeError` on missing prerequisites with hints at the
    function the caller should run first; `ShellError` on pip failure.
    """
    pip = _require_venv_pip(worktree_path)

    hermes_env = worktree_path / '.hermes' / '.env'
    if not hermes_env.exists():
        raise RuntimeError(
            f'Hermes overlay .env not found at {hermes_env}. '
            f'Run `setup_isolated_hermes({worktree_path})` first — it pre-populates '
            'MYAH_ADAPTER_AUTH_KEY so the plugin install does not hang on the '
            'interactive getpass prompt (Slice 0 Investigation A).'
        )

    pip_arg = (
        f'myah-hermes-plugin @ '
        f'git+https://github.com/T3-Venture-Labs-Limited/myah-hermes-plugin@{plugin_sha}'
    )
    run([str(pip), 'install', '--upgrade', pip_arg], check=True)


def materialize_dashboard_shim(worktree_path: Path) -> None:
    """Materialize the dashboard shim under `<worktree>/.hermes/plugins/myah-admin/`.

    Per `setup-myah-oss.sh:491–501`: pip-installing the plugin into the
    venv (the previous step) does NOT place the dashboard shim at the
    location where Hermes's dashboard process scans for plugins. The
    console script `myah-hermes-plugin install --dashboard-only
    --target <plugins/>` is what writes the shim files. The shim's
    `plugin_api.py` does `from myah_hermes_plugin... import ...`, so
    both the pip install (previous primitive) and this materialization
    are required — they are NOT redundant.

    Invokes the absolute `<worktree>/.venv/bin/myah-hermes-plugin`
    path (Investigation C). PATH-based resolution would silently pick
    up a console script from another venv (the main repo's `.venv`,
    for instance) and write the shim referencing a different package
    install, breaking imports at dashboard-start time.

    Sets `HERMES_HOME=<worktree>/.hermes` in the subprocess env. The
    `--target` flag already pins the output location, but the shim's
    own bootstrap code may also read `HERMES_HOME` for related paths
    (sessions, logs). Defensive merging with `os.environ` so PATH and
    other parent env vars survive.

    Raises `RuntimeError` if the console script doesn't exist (caller
    must run `install_plugin_into_hermes` first); `ShellError` on
    non-zero exit.
    """
    script = worktree_path / '.venv' / 'bin' / 'myah-hermes-plugin'
    if not script.exists():
        raise RuntimeError(
            f'myah-hermes-plugin console script not found at {script}. '
            f'Run `install_plugin_into_hermes({worktree_path}, ...)` first — '
            'pip install of the plugin is what creates this entry point.'
        )

    plugins_dir = worktree_path / '.hermes' / 'plugins'
    cmd = [
        str(script),
        'install',
        '--dashboard-only',
        '--target',
        str(plugins_dir),
    ]
    # Merge — never replace — so PATH/HOME/etc. survive into the subprocess.
    env = {**os.environ, 'HERMES_HOME': str(worktree_path / '.hermes')}
    run(cmd, check=True, env=env)


# "What you carry across the threshold matters less than what you leave
#  behind. Copy the keys that open doors. Forge new locks for the rooms
#  that must stay private to this branch alone." — H2, made concrete.


def read_main_env_for_copy(main_env_path: Path) -> dict[str, str]:
    """Parse main's platform-oss/.env and return the non-bearer subset.

    Implements the H2 hosted-mode secret distribution decision (plan
    §2.2d): copy non-bearer secrets so a new worktree can talk to the
    same external APIs (OpenRouter / Sentry / Langfuse / OAuth-session
    encryption) as main, but DO NOT copy bearer/signing tokens — those
    must be freshly generated per worktree to prevent cross-worktree
    session bleed.

    Returns a dict containing only keys in `_NON_BEARER_SECRET_KEYS`
    that are present AND non-empty in `main_env_path`. Missing keys are
    silently skipped (caller gets a smaller dict). If `main_env_path`
    does not exist, returns `{}` — a fresh main checkout may not have
    a `.env` yet, and the orchestrator may warn but should not fatal-
    exit on that case.

    Pure parser: no python-dotenv dependency (heavy + side-effecty),
    no subprocess calls, no mutation of the source file.
    """
    # Parser shared with `cli/dev/server.load_worktree_env_chain` and the H7
    # regression suite — single source of truth in lib/cli/env_loader.
    from myah.lib.cli.env_loader import parse_env_file

    parsed = parse_env_file(main_env_path)
    result: dict[str, str] = {}
    for key, value in parsed.items():
        if key not in _NON_BEARER_SECRET_KEYS:
            continue
        # Empty (or whitespace-only after quote stripping) values are skipped:
        # they would otherwise overwrite a real value at the destination with
        # a blank, which is worse than just leaving the slot unset.
        if not value.strip():
            continue
        result[key] = value
    return result


def generate_fresh_tokens() -> dict[str, str]:
    """Return three distinct `secrets.token_urlsafe(32)` values per worktree.

    Returns a dict keyed by `_BEARER_TOKEN_KEYS`:

    - `MYAH_AGENT_BEARER_TOKEN` — platform↔Hermes auth.
    - `MYAH_HERMES_WEB_SESSION_TOKEN` — Hermes-web cookie signing.
    - `MYAH_SECRET_KEY` — platform session signing.

    Three distinct `secrets.token_urlsafe(32)` calls so the values
    differ. Per the H2 decision (plan §2.2d), these are the "bearer /
    signing" set — generated fresh per worktree to prevent cross-
    worktree session bleed. The orchestrator (Commit D) is responsible
    for aligning `MYAH_AGENT_BEARER_TOKEN` across the platform `.env`
    and the Hermes `.env` slots (mirrors the 5-way fill in
    `setup-myah-oss.sh:282–286`).
    """
    return {key: secrets.token_urlsafe(32) for key in _BEARER_TOKEN_KEYS}


def write_worktree_env(
    worktree_path: Path,
    *,
    branch: str,
    main_repo_root: Path,
) -> dict[str, int]:
    """Write `<worktree>/.worktree-env` and return the allocated ports.

    Python port of `scripts/setup-worktree.sh:159–184`. Subprocess-
    invokes the canonical port allocator at
    `<main>/platform-oss/scripts/e2e_ports.py --format json --branch <branch>`
    via `<main>/platform-oss/.venv/bin/python` (absolute paths per
    Slice 0 Investigation C — bare `python` could resolve to a
    different interpreter when the dev-worktree shell isn't sourced).

    Writes the canonical comment block byte-for-byte alongside the four
    export lines: WORKTREE_BRANCH, BACKEND_PORT, FRONTEND_PORT,
    CORS_ALLOW_ORIGIN, MYAH_PLATFORM_PORT. The comments are non-
    trivial documentation that `dev-worktree.sh` users rely on (they
    explain WHY MYAH_PLATFORM_PORT exists separately from BACKEND_PORT)
    and they survive verbatim from the bash source.

    **H7 invariant (plan §2.2c):** the written file MUST contain
    `export MYAH_PLATFORM_PORT=<BACKEND_PORT>`. The agent container
    code in `platform-oss/backend/myah/routers/containers.py` reads
    `MYAH_PLATFORM_PORT` to decide which host port the agent reaches
    the platform on for attachment fetches. `platform-oss/.env`
    (symlinked from main) hardcodes `MYAH_PLATFORM_PORT=8082`; without
    the export here that value wins and the worktree's chat flow
    silently fetches attachments from main. `.worktree-env` is sourced
    AFTER `platform-oss/.env` by all dev commands so this export wins.
    A dedicated test gates the invariant.

    Returns `{'backend_port': int, 'frontend_port': int}` so the
    orchestrator (Commit D) can use the values without re-parsing the
    file it just wrote.

    Not idempotent: the file is regenerated every time. If the branch
    name's hash changed (it shouldn't, but defensively), or the allocator
    is bumped to a new range, the new ports take effect immediately.
    """
    cmd = [
        str(main_repo_root / 'platform-oss' / '.venv' / 'bin' / 'python'),
        str(main_repo_root / 'platform-oss' / 'scripts' / 'e2e_ports.py'),
        '--format',
        'json',
        '--branch',
        branch,
    ]
    result = run(cmd, check=True)
    ports = json.loads(result.stdout)
    backend_port = int(ports['backend_port'])
    frontend_port = int(ports['frontend_port'])

    content = (
        '# Auto-generated by myah dev worktree create — do NOT commit.\n'
        '# This file is gitignored. Source it in every shell that runs the backend or\n'
        '# frontend from a worktree. `myah dev backend/frontend` does this for you.\n'
        f'export WORKTREE_BRANCH={branch}\n'
        f'export BACKEND_PORT={backend_port}\n'
        f'export FRONTEND_PORT={frontend_port}\n'
        f"export CORS_ALLOW_ORIGIN='http://localhost:{frontend_port};http://localhost:5173'\n"
        '# MYAH_PLATFORM_PORT is read by platform-oss/backend/myah/routers/containers.py\n'
        '# to decide which host port per-user agent containers reach the platform at.\n'
        '# platform-oss/.env (symlinked from main) hardcodes MYAH_PLATFORM_PORT=8082, which\n'
        '# makes the agent container fetch file attachments from the main workspace\n'
        '# instead of this worktree. .worktree-env is sourced AFTER platform-oss/.env by\n'
        '# dev commands, so this export wins.\n'
        f'export MYAH_PLATFORM_PORT={backend_port}\n'
    )
    (worktree_path / '.worktree-env').write_text(content, encoding='utf-8')

    return {'backend_port': backend_port, 'frontend_port': frontend_port}


# "Write to the side first. Only when the new page is whole, swap it for
#  the old. A crash mid-stroke leaves the original untouched." — atomic write.


def _atomic_write_text(path: Path, content: str, encoding: str = 'utf-8') -> None:
    """Write `content` to `path` atomically via `.tmp + os.replace`.

    Crash-safe: a SIGKILL between any two bytes either leaves the original
    file unchanged OR commits the full new content. Never a partial write.

    Uses `path.with_suffix(path.suffix + '.tmp')` for the tmp path so the
    rename target sits on the same filesystem as the destination
    (``os.replace`` is atomic only within a filesystem).
    """
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(content, encoding=encoding)
    os.replace(tmp, path)


# "Open the file. Find the key. Replace one line, leave the rest in peace."
# — set_env_var, the small surgery that composes everything below.


def set_env_var(path: Path, key: str, value: str) -> None:
    """Upsert `key=value` in a .env file, preserving surrounding lines.

    Mirrors `scripts/setup-myah-oss.sh`'s `set_var` helper. Reads `path`
    if it exists; finds an existing `KEY=...` line and replaces it in
    place; otherwise appends `KEY=value` to the end. Preserves an
    optional `export ` prefix on the existing line.

    Creates the file if it does not exist (and any missing parent
    directories). Writes are atomic via ``_atomic_write_text`` (.tmp +
    ``os.replace``) so a crash mid-write either leaves the original
    intact or commits the full new content — never a partial. This is
    a strengthening for existing callers, who previously used a plain
    ``path.write_text`` and could be SIGKILL'd mid-write during
    worktree creation.

    Used by ``write_worktree_platform_env`` and ``align_hermes_env_tokens``.
    """
    path.parent.mkdir(parents=True, exist_ok=True)

    if not path.is_file():
        _atomic_write_text(path, f'{key}={value}\n')
        return

    existing = path.read_text(encoding='utf-8')
    lines = existing.splitlines(keepends=True)
    updated_lines: list[str] = []
    replaced = False

    for line in lines:
        stripped = line.lstrip()
        # Match `KEY=...` or `export KEY=...`.
        candidate = stripped
        had_export = False
        if candidate.startswith('export '):
            candidate = candidate[len('export '):].lstrip()
            had_export = True
        eq_idx = candidate.find('=')
        if eq_idx > 0 and candidate[:eq_idx].strip() == key:
            prefix = 'export ' if had_export else ''
            # Preserve trailing newline if the original had one.
            newline = '\n' if line.endswith('\n') else ''
            updated_lines.append(f'{prefix}{key}={value}{newline}')
            replaced = True
        else:
            updated_lines.append(line)

    if not replaced:
        # Ensure a trailing newline before appending.
        if updated_lines and not updated_lines[-1].endswith('\n'):
            updated_lines[-1] = updated_lines[-1] + '\n'
        updated_lines.append(f'{key}={value}\n')

    _atomic_write_text(path, ''.join(updated_lines))


# "When the petition is withdrawn, the page remembers only what stayed."
# — unset_env_var, the small subtraction dual to set_env_var.


def unset_env_var(path: Path, key: str) -> bool:
    """Remove every line in `path` whose key matches `key`.

    Walks the file, drops any line whose KEY (with optional `export `
    prefix) matches. Atomic write via ``_atomic_write_text`` — same
    idiom as ``set_env_var``.

    Returns:
        True if at least one line was removed, False if no match found
        (so callers can emit "not found" notes). Also returns False
        when `path` does not exist (no error — symmetric with set_env_var's
        create-on-missing semantics, just absent on the unset side).

    Preserves comments, blank lines, and the order of other entries.
    """
    if not path.is_file():
        return False

    existing = path.read_text(encoding='utf-8')
    lines = existing.splitlines(keepends=True)
    kept: list[str] = []
    removed = False

    for line in lines:
        stripped = line.lstrip()
        # Match `KEY=...` or `export KEY=...`.
        candidate = stripped
        if candidate.startswith('export '):
            candidate = candidate[len('export '):].lstrip()
        eq_idx = candidate.find('=')
        if eq_idx > 0 and candidate[:eq_idx].strip() == key:
            removed = True
            continue
        kept.append(line)

    if not removed:
        return False

    _atomic_write_text(path, ''.join(kept))
    return True


# "Three fresh tokens at the door, plus the keys you brought from home —
#  enough to sign every petition this worktree will send." — H2 composed.


def write_worktree_platform_env(
    worktree_path: Path,
    *,
    mode: Literal['oss', 'hosted'],
    copied_secrets: dict[str, str],
    fresh_tokens: dict[str, str],
) -> None:
    """Compose `<worktree>/platform-oss/.env` from fresh tokens + copied secrets + mode flags.

    Overwrites any existing file — this is per-worktree-create, not a
    repeat. The H2 hosted-mode secret distribution decision (plan
    §2.2d) drives the content: bearer/signing tokens come fresh per
    worktree, non-bearer secrets are copied from main, and mode-
    specific deployment flags lock the worktree into oss or hosted
    behavior. The OAuth session-token encryption key gets a freshly
    generated value if main didn't have one — without it, hosted-mode
    OAuth flows fail silently.

    Layout:

    1. Comment block documenting auto-generation + mode + copied keys.
    2. Mode flag(s): `MYAH_DEPLOYMENT_MODE=oss` + `MYAH_AUTH=false` in
       oss mode; `MYAH_AUTH=true` in hosted mode.
    3. The three fresh bearer/signing tokens.
    4. Each copied non-bearer secret.
    5. `OAUTH_SESSION_TOKEN_ENCRYPTION_KEY` (from copied if present,
       generated otherwise).
    """
    target = worktree_path / 'platform-oss' / '.env'
    target.parent.mkdir(parents=True, exist_ok=True)

    copied_keys_list = ', '.join(sorted(copied_secrets.keys())) if copied_secrets else '(none)'
    header = (
        '# Auto-generated by `myah dev worktree create` — do NOT commit.\n'
        '# Per-worktree platform env (gitignored).\n'
        f'# Mode: {mode}\n'
        f'# Secrets copied from main: {copied_keys_list}\n'
        '# Fresh per-worktree tokens: MYAH_AGENT_BEARER_TOKEN, MYAH_HERMES_WEB_SESSION_TOKEN, MYAH_SECRET_KEY\n'
    )
    target.write_text(header, encoding='utf-8')

    # Mode flags. OSS pins MYAH_DEPLOYMENT_MODE so is_oss_mode() returns
    # True; hosted leaves it unset (hosted is the implicit default).
    if mode == 'oss':
        set_env_var(target, 'MYAH_DEPLOYMENT_MODE', 'oss')
        set_env_var(target, 'MYAH_AUTH', 'false')
    else:
        set_env_var(target, 'MYAH_AUTH', 'true')

    # The three fresh bearer/signing tokens.
    for key in _BEARER_TOKEN_KEYS:
        set_env_var(target, key, fresh_tokens[key])

    # Copied non-bearer secrets (excluding OAUTH — handled below to
    # branch on copied-vs-generated).
    for key in sorted(copied_secrets.keys()):
        if key == 'OAUTH_SESSION_TOKEN_ENCRYPTION_KEY':
            continue
        set_env_var(target, key, copied_secrets[key])

    # OAuth session-token encryption key: prefer copied, generate fresh otherwise.
    oauth_key = copied_secrets.get('OAUTH_SESSION_TOKEN_ENCRYPTION_KEY') or secrets.token_urlsafe(32)
    set_env_var(target, 'OAUTH_SESSION_TOKEN_ENCRYPTION_KEY', oauth_key)


def align_hermes_env_tokens(worktree_path: Path, bearer_token: str) -> None:
    """Write the same `bearer_token` to four slots in `<worktree>/.hermes/.env`.

    Per `setup-myah-oss.sh:282–286` — plugin auth (`MYAH_ADAPTER_AUTH_KEY`),
    gateway auth (`API_SERVER_KEY`), platform→plugin auth
    (`MYAH_PLATFORM_BEARER`), and the agent's own bearer
    (`MYAH_AGENT_BEARER_TOKEN`) must all agree on a single value. The
    platform's `MYAH_AGENT_BEARER_TOKEN` (the 5th alignment slot) is
    written separately by `write_worktree_platform_env` from the same
    source dict — so all five values agree by construction.

    Requires `<worktree>/.hermes/.env` to already exist (placeholder
    `MYAH_ADAPTER_AUTH_KEY=...` written by `setup_isolated_hermes`).
    Raises RuntimeError with a hint pointing at `setup_isolated_hermes`
    if missing.
    """
    hermes_env = worktree_path / '.hermes' / '.env'
    if not hermes_env.is_file():
        raise RuntimeError(
            f'Hermes overlay .env not found at {hermes_env}. '
            f'Run `setup_isolated_hermes({worktree_path})` first — it writes '
            'the placeholder MYAH_ADAPTER_AUTH_KEY that this function overwrites.'
        )

    for key in _HERMES_ENV_BEARER_SLOTS:
        set_env_var(hermes_env, key, bearer_token)


# "The orchestrator: twelve steps, twelve cleanups, one ledger. When the
#  road breaks, walk it backwards until you reach the place where you
#  could still see home." — create_worktree.


class WorktreeAlreadyExistsError(RuntimeError):
    """Raised by the idempotence guard when `<main>/.worktrees/<branch>` already exists.

    Per plan §2.2.2 option (a) and Q-DX7: the policy is restart-from-
    scratch via `myah dev worktree destroy <branch>`, not auto-resume.
    """


class WorktreeCreationError(RuntimeError):
    """Raised after rollback has run when any orchestrator step fails.

    Carries the failed step's name and the original exception so the
    user-facing CLI command can render a clear post-mortem.
    """

    def __init__(self, *, step: str, original: BaseException) -> None:
        super().__init__(f'worktree creation failed at step `{step}`: {original!r}')
        self.step = step
        self.original = original


@dataclass(frozen=True, slots=True)
class WorktreeInfo:
    """The orchestrator's return value on success.

    Carries enough to drive a follow-up `myah dev backend/frontend`
    invocation without re-parsing `.worktree-env`.
    """

    path: Path
    branch: str
    mode: str
    ports: dict[str, int]


def resolve_main_repo_root(start: Path | None = None) -> Path:
    """Walk up from `start` (or CWD) until we find the main checkout's root.

    Uses `git rev-parse --git-common-dir` to find the .git dir shared by
    main + all its worktrees, then returns its parent.
    """
    cwd = start or Path.cwd()
    result = run(
        ['git', '-C', str(cwd), 'rev-parse', '--git-common-dir'],
        check=True,
    )
    common_dir = Path(result.stdout.strip())
    if not common_dir.is_absolute():
        common_dir = (cwd / common_dir).resolve()
    # `git-common-dir` is `<main>/.git` — parent is the main repo root.
    return common_dir.parent


# Back-compat alias: pre-Task 2.3 callers (and the orchestrator's own
# default-resolution branch below) referenced the underscore-prefixed
# name. Task 2.3 promoted it to public so the CLI layer can use it
# without re-importing private symbols. Keep the alias for one release
# in case any out-of-tree caller pinned the private name.
_resolve_main_repo_root = resolve_main_repo_root


def create_worktree(
    branch: str,
    *,
    mode: Literal['oss', 'hosted'] = 'hosted',
    main_repo_root: Path | None = None,
) -> WorktreeInfo:
    """Orchestrate end-to-end worktree creation with reverse-order rollback.

    Composes the primitives from Commits A, B, and C into a single
    flow. Each successful step appends a cleanup callable to an
    in-memory rollback list; on exception, the list is walked in
    reverse, cleanups run with exceptions swallowed, and a
    `WorktreeCreationError` is raised carrying the failed step name +
    original exception.

    The idempotence guard fires first: if `<main>/.worktrees/<branch>`
    exists, raises `WorktreeAlreadyExistsError` with a hint pointing at
    `myah dev worktree destroy`. No state file is written — restart-
    from-scratch is the policy per plan §Q-DX7.

    Per plan §2.2c the H7 invariant (MYAH_PLATFORM_PORT === BACKEND_PORT)
    is enforced inside `write_worktree_env`. Per plan §2.2d the H2
    secret distribution decision lives in `read_main_env_for_copy` +
    `write_worktree_platform_env`. Per plan §2.2.1 the rollback ledger
    runs in reverse order with exception-swallowing cleanups.
    """
    if main_repo_root is None:
        main_repo_root = _resolve_main_repo_root()
    main_repo_root = main_repo_root.resolve() if main_repo_root.is_absolute() else main_repo_root

    worktree_path = main_repo_root / '.worktrees' / branch

    # Step 0: idempotence guard. Must run before any side effect.
    if worktree_path.exists():
        raise WorktreeAlreadyExistsError(
            f'Worktree already exists at {worktree_path}. '
            f'Use `myah dev worktree destroy {branch}` first.'
        )

    # In-memory cleanup ledger. Appended on each step's success.
    cleanups: list[tuple[str, Callable[[], None]]] = []

    def _safe_cleanup(name: str, fn: Callable[[], None]) -> None:
        try:
            fn()
        except Exception as cleanup_exc:  # noqa: BLE001 — swallow per plan §2.2.1
            logger.warning(f'cleanup `{name}` raised (ignored): {cleanup_exc!r}')

    def _rollback() -> None:
        for name, fn in reversed(cleanups):
            _safe_cleanup(name, fn)

    current_step = '<not-started>'
    total = 12
    try:
        # Step 1: read main's .env for the non-bearer copy set (H2).
        current_step = 'read_main_env_for_copy'
        logger.info(f'Step 1/{total}: reading main .env for non-bearer secret copy')
        copied_secrets = read_main_env_for_copy(main_repo_root / 'platform-oss' / '.env')

        # Step 2: generate fresh bearer/signing tokens (H2).
        current_step = 'generate_fresh_tokens'
        logger.info(f'Step 2/{total}: generating fresh per-worktree tokens')
        fresh_tokens = generate_fresh_tokens()

        # Step 3: git worktree add.
        current_step = 'git_worktree_add'
        logger.info(f'Step 3/{total}: git worktree add {worktree_path} -b {branch}')
        run(
            ['git', '-C', str(main_repo_root), 'worktree', 'add', str(worktree_path), '-b', branch],
            check=True,
        )

        def _cleanup_git_worktree() -> None:
            run(
                ['git', '-C', str(main_repo_root), 'worktree', 'remove', '--force', str(worktree_path)],
                check=True,
            )

        cleanups.append(('git_worktree_add', _cleanup_git_worktree))

        # Step 4: materialize <worktree>/.hermes/ with placeholder env + config.
        current_step = 'setup_isolated_hermes'
        logger.info(f'Step 4/{total}: setup_isolated_hermes')
        setup_isolated_hermes(worktree_path)
        cleanups.append(
            (
                'setup_isolated_hermes',
                lambda: shutil.rmtree(worktree_path / '.hermes', ignore_errors=True),
            )
        )

        # Step 5: create the per-worktree venv.
        current_step = 'setup_venv'
        logger.info(f'Step 5/{total}: setup_venv')
        setup_venv(worktree_path)
        cleanups.append(
            (
                'setup_venv',
                lambda: shutil.rmtree(worktree_path / '.venv', ignore_errors=True),
            )
        )

        # Step 6: editable install of platform-oss into the venv.
        current_step = 'install_platform_into_venv'
        logger.info(f'Step 6/{total}: install_platform_into_venv')
        install_platform_into_venv(worktree_path)
        # No individual cleanup — .venv rmtree from step 5 covers it.

        # Step 7: pip-install upstream Hermes at the pinned SHA.
        current_step = 'install_hermes_into_venv'
        logger.info(f'Step 7/{total}: install_hermes_into_venv')
        hermes_sha = _read_hermes_sha(main_repo_root / _DOCKERFILE_PATH)
        install_hermes_into_venv(worktree_path, hermes_sha)

        # Step 8: pip-install the Myah plugin at the pinned SHA.
        current_step = 'install_plugin_into_hermes'
        logger.info(f'Step 8/{total}: install_plugin_into_hermes')
        plugin_sha = _read_plugin_sha(main_repo_root / _DOCKERFILE_PATH)
        install_plugin_into_hermes(worktree_path, plugin_sha)

        # Step 9: materialize the dashboard shim.
        current_step = 'materialize_dashboard_shim'
        logger.info(f'Step 9/{total}: materialize_dashboard_shim')
        materialize_dashboard_shim(worktree_path)
        cleanups.append(
            (
                'materialize_dashboard_shim',
                lambda: shutil.rmtree(
                    worktree_path / '.hermes' / 'plugins' / 'myah-admin', ignore_errors=True
                ),
            )
        )

        # Step 10: compose <worktree>/platform-oss/.env from copied + fresh.
        current_step = 'write_worktree_platform_env'
        logger.info(f'Step 10/{total}: write_worktree_platform_env')
        write_worktree_platform_env(
            worktree_path,
            mode=mode,
            copied_secrets=copied_secrets,
            fresh_tokens=fresh_tokens,
        )
        cleanups.append(
            (
                'write_worktree_platform_env',
                lambda: (worktree_path / 'platform-oss' / '.env').unlink(missing_ok=True),
            )
        )

        # Step 11: align the bearer token across 4 Hermes-side .env slots.
        current_step = 'align_hermes_env_tokens'
        logger.info(f'Step 11/{total}: align_hermes_env_tokens (4 Hermes slots)')
        align_hermes_env_tokens(worktree_path, fresh_tokens['MYAH_AGENT_BEARER_TOKEN'])
        # No separate cleanup — step 4's .hermes rmtree covers this.

        # Step 12: write .worktree-env (ports + H7).
        current_step = 'write_worktree_env'
        logger.info(f'Step 12/{total}: write_worktree_env (ports + H7)')
        ports = write_worktree_env(worktree_path, branch=branch, main_repo_root=main_repo_root)
        cleanups.append(
            (
                'write_worktree_env',
                lambda: (worktree_path / '.worktree-env').unlink(missing_ok=True),
            )
        )

    except Exception as exc:
        logger.warning(f'worktree creation failed at step `{current_step}`; rolling back')
        _rollback()
        raise WorktreeCreationError(step=current_step, original=exc) from exc

    return WorktreeInfo(path=worktree_path, branch=branch, mode=mode, ports=ports)
