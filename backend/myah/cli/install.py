"""`myah install` — orchestrate the OSS install end-to-end.

Sub-phase 4f of Slice 4. This command wires sub-phases 4a-4e into a
single end-to-end installer that replaces the 922-line bash at
``platform-oss/scripts/setup-myah-oss.sh``. The 8 phases mirror the
bash exactly:

  1. Pre-flight (hermes on PATH; repo root detection)
  2. Bearer token 5-slot alignment + OSS-default Hermes env vars
  3. OAuth Fernet key (generate if unset or --rotate)
  4. MYAH_SECRET_KEY (adopt WEBUI_SECRET_KEY → generate fallback)
  5. HERMES_WEB_SESSION_TOKEN 2-slot alignment
  6. Plugin install (detect venv → pip install at SHA → dashboard shim)
  7. Hermes config.yaml merge (gateway.platforms.myah.enabled = true)
  8. Service units + post-install verification

Cold-start: this module is loaded LAZILY via `_register_install` in
`cli/__init__.py`. Rich, typer.prompt, and typer.confirm imports stay
inside the function body so the cold-start budget holds.

PyYAML is NOT a hard prerequisite for this command — it's lazy-imported
inside `config_merge.enable_myah_platform` so phases that don't touch
the config don't pay for it.
"""

from __future__ import annotations

import os
import re
import shutil
import sys
from pathlib import Path

import typer

from myah.lib.cli.config_merge import enable_myah_platform
from myah.lib.cli.doctor_checks import CheckResult, CheckStatus, post_install_doctor_run
from myah.lib.cli.hermes_install import (
    bootstrap_pip,
    detect_hermes_venv,
    materialize_dashboard_shim,
    pip_install_plugin_at_sha,
    read_pinned_plugin_sha_from_dockerfile,
    verify_dashboard_plugin_mounted,
)
from myah.lib.cli.repo import find_repo_root
from myah.lib.cli.service_units import install_launchd_plists, install_systemd_user_units
from myah.lib.cli.token_gen import (
    adopt_legacy_webui_key,
    generate_bearer_token,
    generate_fernet_key,
    generate_jwt_secret,
    migrate_legacy_url,
    write_token_to_all_slots,
)
from myah.lib.cli.env_loader import parse_env_file
from myah.lib.cli.worktree_setup import set_env_var


# ─── Repo-root detection ────────────────────────────────────────────────
#
# Two layouts are supported. The private monorepo (this repo) has
# `agent/Dockerfile.stock` and pins the plugin SHA there. The public
# OSS mirror (T3-Venture-Labs-Limited/myah) has `versions.env` instead
# and pins the SHA via a `MYAH_PLUGIN_SHA=<40hex>` line.
_DOCKERFILE_REL = Path('agent') / 'Dockerfile.stock'
_VERSIONS_ENV_REL = Path('versions.env')

# A 40-char-hex MYAH_PLUGIN_SHA line in versions.env. Tolerates
# `export ` prefix and `# comment` suffix. Mirrors the public OSS
# repo's setup-myah-oss.sh which sources versions.env directly.
_VERSIONS_ENV_SHA_RE = re.compile(
    r'^\s*(?:export\s+)?MYAH_PLUGIN_SHA\s*=\s*([0-9a-fA-F]{40})\s*(?:#.*)?$'
)


# Seeded single-user OSS admin (matches oss_seed_user migration).
# Also appears in platform-oss/backend/myah/internal/db.py and the
# OSS auth bootstrap. Searchable; do NOT inline-duplicate.
_SEEDED_ADMIN_USER_ID = '00000000-0000-0000-0000-000000000001'


# The six OSS-default Hermes env vars from bash:303-319. Each is
# conditionally written only if currently empty. The list-of-tuples form
# preserves write order for test determinism.
_OSS_DEFAULT_HERMES_ENV: tuple[tuple[str, str], ...] = (
    ('API_SERVER_ENABLED', 'true'),
    ('API_SERVER_HOST', '0.0.0.0'),
    ('MYAH_USER_ID', _SEEDED_ADMIN_USER_ID),
    ('MYAH_ALLOW_ALL_USERS', 'true'),
    ('MYAH_HOME_CHAT', 'disabled'),
    ('MYAH_HOME_CHANNEL', 'disabled'),
)


def _read_plugin_sha_from_versions_env(path: Path) -> str:
    """Extract ``MYAH_PLUGIN_SHA=<40hex>`` from a versions.env file.

    Public OSS repo convention — the bash `setup-myah-oss.sh` in that
    repo sources this file directly. Raises ``RuntimeError`` if the
    line is missing or malformed.
    """
    if not path.is_file():
        raise RuntimeError(f'versions.env not found at {path}')
    for raw_line in path.read_text(encoding='utf-8').splitlines():
        match = _VERSIONS_ENV_SHA_RE.match(raw_line)
        if match:
            return match.group(1)
    raise RuntimeError(
        f'Could not find a valid `MYAH_PLUGIN_SHA=<40-char-sha>` line in {path}. '
        f'Either the var is missing or the SHA is malformed (must be 40 hex chars).'
    )


def _resolve_plugin_sha(repo_root: Path) -> str:
    """Read the pinned plugin SHA from whichever sentinel exists.

    Prefers ``agent/Dockerfile.stock`` (monorepo canonical source);
    falls back to ``versions.env`` (public OSS mirror).
    """
    dockerfile = repo_root / _DOCKERFILE_REL
    if dockerfile.is_file():
        return read_pinned_plugin_sha_from_dockerfile(dockerfile)
    versions_env = repo_root / _VERSIONS_ENV_REL
    if versions_env.is_file():
        return _read_plugin_sha_from_versions_env(versions_env)
    raise RuntimeError(
        f'Cannot resolve plugin SHA — neither {dockerfile} nor {versions_env} exists.'
    )


def _hermes_home() -> Path:
    """Return the Hermes home directory (HERMES_HOME env or ~/.hermes).

    Always passes the value through ``os.path.expanduser`` because
    Python does NOT auto-expand tildes in env-var values — a user who
    sets ``HERMES_HOME=~/.hermes`` would otherwise get a literal
    ``~/.hermes`` directory relative to CWD.
    """
    override = os.environ.get('HERMES_HOME')
    if override:
        return Path(os.path.expanduser(override))
    return Path(os.path.expanduser('~/.hermes'))


def _default_service_for_platform() -> str:
    """Best-guess service framework for the current OS."""
    if sys.platform.startswith('linux'):
        return 'systemd'
    if sys.platform == 'darwin':
        return 'launchd'
    return 'none'


def _stdin_is_tty() -> bool:
    """Factored out so tests can monkeypatch it deterministically.

    `sys.stdin.isatty()` is awkward to patch because stdin is a global
    file object shared across modules. Wrapping in a function lets the
    test suite swap the predicate at the consumer namespace.
    """
    return sys.stdin.isatty()


def _resolve_bearer_token(
    hermes_env_path: Path,
    platform_env_path: Path,
    *,
    rotate: bool,
) -> str:
    """Pick the bearer token to write across all 5 slots.

    Mirrors bash lines 261-281. If rotate=True OR any slot is empty OR
    slots disagree, picks the first non-empty value or generates fresh.
    """
    hermes_parsed = parse_env_file(hermes_env_path)
    platform_parsed = parse_env_file(platform_env_path)

    slots = [
        platform_parsed.get('MYAH_AGENT_BEARER_TOKEN', ''),
        hermes_parsed.get('MYAH_AGENT_BEARER_TOKEN', ''),
        hermes_parsed.get('MYAH_ADAPTER_AUTH_KEY', ''),
        hermes_parsed.get('API_SERVER_KEY', ''),
        hermes_parsed.get('MYAH_PLATFORM_BEARER', ''),
    ]
    if not rotate and all(slots) and len(set(slots)) == 1:
        return slots[0]
    if rotate:
        return generate_bearer_token()
    # Reuse first non-empty; else generate.
    for slot in slots:
        if slot:
            return slot
    return generate_bearer_token()


def _resolve_web_session_token(
    hermes_env_path: Path,
    platform_env_path: Path,
    *,
    rotate: bool,
) -> str:
    """Pick the HERMES_WEB_SESSION_TOKEN. Mirrors bash phase 4 (385-435).

    Two slots: platform's MYAH_HERMES_WEB_SESSION_TOKEN, hermes's
    HERMES_WEB_SESSION_TOKEN. Resolution:

      - --rotate → generate fresh
      - Both set + equal → reuse
      - Both set + desync → adopt platform value (log warning at caller)
      - One set, one empty → copy the set value
      - Both empty → generate fresh
    """
    platform_parsed = parse_env_file(platform_env_path)
    hermes_parsed = parse_env_file(hermes_env_path)
    platform_token = platform_parsed.get('MYAH_HERMES_WEB_SESSION_TOKEN', '')
    hermes_token = hermes_parsed.get('HERMES_WEB_SESSION_TOKEN', '')

    if rotate:
        return generate_bearer_token()
    if platform_token and platform_token == hermes_token:
        return platform_token
    if platform_token and hermes_token:
        # Desync — adopt platform.
        return platform_token
    if platform_token:
        return platform_token
    if hermes_token:
        return hermes_token
    return generate_bearer_token()


def install_command(
    *,
    non_interactive: bool = False,
    service: str | None = None,
    openrouter_key: str | None = None,
    rotate: bool = False,
    keep_data: bool = False,
) -> None:
    """Install the Myah OSS stack: tokens, Hermes plugin, config, services, doctor.

    PyYAML is not a hard prerequisite — it's lazy-loaded inside the
    config-merge phase, so other phases work without it.

    Args:
      non_interactive: Skip all prompts. Required for CI. Fails fast if
        interactive-only values are missing.
      service: Service framework — one of ``systemd``, ``launchd``, or
        ``none``. If None and stdin is a TTY, prompts the user with a
        platform-appropriate default.
      openrouter_key: Pre-set ``OPENROUTER_API_KEY`` in the Hermes .env.
        Avoids interactive prompting.
      rotate: Regenerate all generated tokens/keys (bearer, web session,
        OAuth, JWT secret). Mutually exclusive with ``keep_data``.
      keep_data: Documented intent flag preserving existing tokens/keys
        (the default behavior). Mutually exclusive with ``rotate``.
    """
    # Lazy-import Rich so cold-start budget holds.
    from rich.console import Console
    from rich.table import Table

    console = Console()

    # ─── Mutual exclusion gate ────────────────────────────────────────
    if rotate and keep_data:
        console.print(
            '[red]--rotate and --keep-data are mutually exclusive.[/]\n'
            '  --keep-data preserves existing tokens (default behavior).\n'
            '  --rotate regenerates them.'
        )
        raise typer.Exit(code=2)

    # ─── Service choice resolution (early, before any writes) ────────
    if service is not None:
        if service not in ('systemd', 'launchd', 'none'):
            console.print(
                f'[red]Invalid --service value {service!r}.[/] '
                f'Must be one of: systemd, launchd, none.'
            )
            raise typer.Exit(code=2)
        chosen_service = service
    elif non_interactive or not _stdin_is_tty():
        console.print(
            '[red]--service is required in non-interactive mode.[/]\n'
            '  Pass one of: --service systemd | --service launchd | --service none'
        )
        raise typer.Exit(code=2)
    else:
        default = _default_service_for_platform()
        chosen_service = typer.prompt(
            'Service framework (systemd|launchd|none)',
            default=default,
        )
        if chosen_service not in ('systemd', 'launchd', 'none'):
            console.print(
                f'[red]Invalid service choice {chosen_service!r}.[/] '
                f'Must be one of: systemd, launchd, none.'
            )
            raise typer.Exit(code=2)

    # ─── Phase 0 — Pre-flight ─────────────────────────────────────────
    console.print('[bold cyan]Phase 0:[/] pre-flight checks')

    if not shutil.which('hermes'):
        console.print(
            '[red]hermes binary not found on PATH.[/]\n'
            '  Install via: curl -fsSL '
            'https://raw.githubusercontent.com/NousResearch/hermes-agent/main/scripts/install.sh | bash'
        )
        raise typer.Exit(code=1)

    try:
        repo_root = find_repo_root()
    except RuntimeError as err:
        # Surface as a Rich-styled error rather than a Python traceback.
        # find_repo_root's message lists both expected sentinel paths;
        # printing it verbatim gives the user an actionable hint.
        console.print(f'[red]✗ {err}[/]')
        raise typer.Exit(code=1) from err
    console.print(f'  repo root: {repo_root}')

    hermes_home = _hermes_home()
    hermes_home.mkdir(parents=True, exist_ok=True)
    hermes_env = hermes_home / '.env'
    platform_env = repo_root / 'platform-oss' / '.env'
    platform_env.parent.mkdir(parents=True, exist_ok=True)

    # ─── Phase 1 — Bearer token alignment + OSS defaults ──────────────
    console.print('[bold cyan]Phase 1:[/] bearer token + OSS defaults')

    token = _resolve_bearer_token(hermes_env, platform_env, rotate=rotate)
    write_token_to_all_slots(token, hermes_env, platform_env)

    hermes_parsed = parse_env_file(hermes_env)
    for key, default_value in _OSS_DEFAULT_HERMES_ENV:
        if not hermes_parsed.get(key):
            set_env_var(hermes_env, key, default_value)

    migrate_legacy_url(hermes_env)

    if openrouter_key:
        set_env_var(hermes_env, 'OPENROUTER_API_KEY', openrouter_key)
        console.print('  [green]OPENROUTER_API_KEY set in Hermes .env[/]')

    # ─── Phase 2 — OAuth Fernet key ───────────────────────────────────
    console.print('[bold cyan]Phase 2:[/] OAuth Fernet key')

    platform_parsed = parse_env_file(platform_env)
    if rotate or not platform_parsed.get('OAUTH_SESSION_TOKEN_ENCRYPTION_KEY'):
        set_env_var(platform_env, 'OAUTH_SESSION_TOKEN_ENCRYPTION_KEY', generate_fernet_key())

    # ─── Phase 3 — MYAH_SECRET_KEY ────────────────────────────────────
    console.print('[bold cyan]Phase 3:[/] MYAH_SECRET_KEY')

    # --rotate must always generate a fresh JWT secret, even when the legacy
    # WEBUI_SECRET_KEY is present. Adopting the legacy value on --rotate would
    # silently make rotate a no-op for the common Open WebUI migration audience.
    platform_parsed = parse_env_file(platform_env)
    if rotate:
        set_env_var(platform_env, 'MYAH_SECRET_KEY', generate_jwt_secret())
    elif not platform_parsed.get('MYAH_SECRET_KEY'):
        adopted = adopt_legacy_webui_key(platform_env)
        if not adopted:
            set_env_var(platform_env, 'MYAH_SECRET_KEY', generate_jwt_secret())

    # ─── Phase 4 — HERMES_WEB_SESSION_TOKEN 2-slot alignment ──────────
    console.print('[bold cyan]Phase 4:[/] HERMES_WEB_SESSION_TOKEN')

    # Detect desync BEFORE resolving so we can warn the user.
    pre = parse_env_file(platform_env), parse_env_file(hermes_env)
    pre_plat = pre[0].get('MYAH_HERMES_WEB_SESSION_TOKEN', '')
    pre_herm = pre[1].get('HERMES_WEB_SESSION_TOKEN', '')
    if not rotate and pre_plat and pre_herm and pre_plat != pre_herm:
        # Loguru is the structured-log surface Sentry consumes via the
        # LoggingIntegration bridge — emit alongside the user-facing Rich
        # print. Truncate the token values to a 6-char prefix; never dump
        # full bearer tokens to logs.
        from loguru import logger  # lazy — keep cold-start lean
        logger.warning(
            f'web-session token desync detected: platform={pre_plat[:6]}…, '
            f'hermes={pre_herm[:6]}… — realigning Hermes .env to platform value'
        )
        console.print(
            '  [yellow]desync detected — realigning Hermes .env to platform value[/]'
        )

    web_token = _resolve_web_session_token(hermes_env, platform_env, rotate=rotate)
    set_env_var(platform_env, 'MYAH_HERMES_WEB_SESSION_TOKEN', web_token)
    set_env_var(hermes_env, 'HERMES_WEB_SESSION_TOKEN', web_token)

    # ─── Phase 5 — Plugin install ─────────────────────────────────────
    console.print('[bold cyan]Phase 5:[/] plugin install')

    try:
        venv_path = detect_hermes_venv()
    except RuntimeError as err:
        console.print(f'[red]✗ {err}[/]')
        raise typer.Exit(code=1) from err
    venv_python = venv_path / 'bin' / 'python'

    # bootstrap_pip resolves pip from PyPI (public, no auth needed); the
    # plugin install below uses MYAH_PLUGIN_AUTH_TOKEN for private forks.
    bootstrap_pip(venv_python)

    try:
        plugin_sha = _resolve_plugin_sha(repo_root)
    except RuntimeError as err:
        console.print(f'[red]✗ {err}[/]')
        raise typer.Exit(code=1) from err

    pip_install_plugin_at_sha(
        plugin_sha,
        venv_python,
        auth_token=os.environ.get('MYAH_PLUGIN_AUTH_TOKEN'),
    )
    materialize_dashboard_shim(venv_path, hermes_home)

    # ─── Phase 6 — Hermes config merge ────────────────────────────────
    console.print('[bold cyan]Phase 6:[/] Hermes config.yaml merge')

    config_path = hermes_home / 'config.yaml'
    enable_myah_platform(config_path)

    # ─── Phase 7 — Service units + dashboard verification ─────────────
    console.print(f'[bold cyan]Phase 7:[/] service units ({chosen_service})')

    hermes_bin = shutil.which('hermes') or ''
    if chosen_service == 'systemd':
        install_systemd_user_units(hermes_bin, hermes_home)
    elif chosen_service == 'launchd':
        install_launchd_plists(hermes_bin, hermes_home)
    else:  # 'none'
        console.print('  [dim]service install skipped (--service none)[/]')

    # Dashboard mount verification (best-effort poll). Skipped when no
    # service was installed — there's nothing listening.
    if chosen_service in ('systemd', 'launchd'):
        mounted = verify_dashboard_plugin_mounted(web_token, port=9119, timeout_s=15.0)
        if mounted:
            console.print('  [green]dashboard plugin mount verified[/]')
        else:
            console.print(
                '  [yellow]dashboard plugin mount not verified within 15s — '
                'check `hermes dashboard` logs[/]'
            )

    # ─── Phase 8 — Post-install verification ──────────────────────────
    console.print('[bold cyan]Phase 8:[/] post-install verification')

    results: list[CheckResult] = post_install_doctor_run()

    table = Table(title='Post-install verification', show_header=True, header_style='bold')
    table.add_column('Check', style='cyan')
    table.add_column('Status', justify='center')
    table.add_column('Detail', style='dim')
    for r in results:
        status_cell = {
            CheckStatus.OK: '[green]✓ OK[/]',
            CheckStatus.WARN: '[yellow]⚠ WARN[/]',
            CheckStatus.FAIL: '[red]✗ FAIL[/]',
        }[r.status]
        table.add_row(r.name, status_cell, r.message)
    console.print(table)

    # Exit code: any FAIL → 1, else 0. WARN does NOT fail (bash semantics).
    if any(r.status == CheckStatus.FAIL for r in results):
        raise typer.Exit(code=1)

    # TODO(slice-4-followup): port bash's "Next steps" 5-message block
    # from setup-myah-oss.sh:885-921. The verification table is enough
    # for now (users can run `myah doctor` for guidance), but a Rich-
    # rendered numbered list of post-install actions would improve UX.


__all__ = ['install_command']
