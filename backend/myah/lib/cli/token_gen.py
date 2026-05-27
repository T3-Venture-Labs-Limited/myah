"""Token + .env primitives for `myah install` (Slice 4 sub-phase 4a).

Library-only — no CLI command yet. Sub-phase 4f wires `myah install`
end-to-end. This module replaces phases 1-4 of the 922-line bash at
`platform-oss/scripts/setup-myah-oss.sh` with pure-Python primitives
the install command (and other callers) can compose at will.

Phase mapping:

  bash lines 162-164   → `generate_fernet_key`, `generate_jwt_secret`
                         (both produce 64-char hex)
  bash line  278       → `generate_bearer_token`
  bash lines 282-286   → `write_token_to_all_slots`  (5-slot alignment)
  bash lines 321-329   → `migrate_legacy_url`        (LEGACY_BROKEN_URLS)
  bash lines 376-378   → `adopt_legacy_webui_key`    (WEBUI -> MYAH)

The remaining phase-1 logic (supplementary env vars, web session token
2-slot alignment, ROTATE flag handling, generate-or-reuse resolution)
belongs to sub-phase 4f orchestration — 4a stays pure primitives.

Cold-start budget: stdlib + the two Slice-2 .env helpers only. No Rich,
no PyYAML, no threading.
"""

from __future__ import annotations

import secrets
from pathlib import Path

from myah.lib.cli.env_loader import parse_env_file
from myah.lib.cli.worktree_setup import set_env_var


# The single canonical platform URL for OSS installs (loopback to the
# docker-compose-published platform). See setup-myah-oss.sh:306-329 for
# the full why-127.0.0.1-not-host.docker.internal rationale.
CANONICAL_PLATFORM_BASE_URL = 'http://127.0.0.1:8080'

# URLs from older installer revisions that were broken-by-default and
# get silently migrated to the canonical value. Exposed (not underscored)
# so the install orchestrator and tests can ask "was X a legacy URL?"
# when emitting migration-log messages. See
# docs/gotchas/2026-05-19-oss-cron-platform-base-url-drift.md.
LEGACY_BROKEN_URLS: frozenset[str] = frozenset({
    'http://host.docker.internal:8080',  # only resolves inside containers
    'http://localhost:8154',             # obsolete port from pre-launch installs
})


# "Five slots, one truth. Mismatch any one and a different feature
#  silently fails." — bash:238-256, distilled.


def generate_bearer_token() -> str:
    """Generate a fresh URL-safe bearer token (mirrors setup-myah-oss.sh:278)."""
    return secrets.token_urlsafe(32)


def generate_fernet_key() -> str:
    """Generate a 64-char hex string for the OAuth Fernet key.

    Mirrors setup-myah-oss.sh's `gen_key` (line 162-164: `openssl rand -hex 32`).
    Uses `secrets.token_hex(32)` — same output, no subprocess to openssl.

    The bash comment at lines 158-161 documents that OAuth's Fernet
    bootstrap (`oauth_sessions.py:75-77`) SHA256-hashes any non-44-byte
    value before handing it to Fernet, so 64-char hex is correct for
    this slot.
    """
    return secrets.token_hex(32)


def generate_jwt_secret() -> str:
    """Generate a 64-char hex string for the JWT/session HMAC secret.

    Mirrors setup-myah-oss.sh's `gen_key` (same as `generate_fernet_key`
    — also produces 64 hex chars). Kept as a separate function so callers
    express semantic intent (the two slots are conceptually distinct
    even though their current implementation is identical).
    """
    return secrets.token_hex(32)


# "Open the file, find the key, replace the line." — set_env_var, reused.

def write_token_to_all_slots(
    token: str,
    hermes_env_path: Path,
    platform_env_path: Path,
) -> None:
    """Write `token` to all five slots that MUST hold the same value.

    Mirrors setup-myah-oss.sh:282-286. The five slots:

      - platform_env_path: ``MYAH_AGENT_BEARER_TOKEN``
      - hermes_env_path:   ``MYAH_AGENT_BEARER_TOKEN``
      - hermes_env_path:   ``MYAH_ADAPTER_AUTH_KEY``
      - hermes_env_path:   ``API_SERVER_KEY``
      - hermes_env_path:   ``MYAH_PLATFORM_BEARER``

    Any mismatch breaks a different feature silently — see the comment
    block at setup-myah-oss.sh:238-256 for the full direction-by-direction
    breakdown (platform→hermes chat dispatch vs hermes→platform
    attachment fetch / cron deliveries).

    Both files are upserted via `set_env_var` (preserves `export `
    prefix, atomic write). Creates files + parent dirs if missing.
    """
    set_env_var(platform_env_path, 'MYAH_AGENT_BEARER_TOKEN', token)
    set_env_var(hermes_env_path, 'MYAH_AGENT_BEARER_TOKEN', token)
    set_env_var(hermes_env_path, 'MYAH_ADAPTER_AUTH_KEY', token)
    set_env_var(hermes_env_path, 'API_SERVER_KEY', token)
    set_env_var(hermes_env_path, 'MYAH_PLATFORM_BEARER', token)


# "If your URL still points at the broken default, we fix it for you.
#  If you've customized it, we leave it alone." — bash:321-329.

def migrate_legacy_url(env_path: Path) -> bool:
    """Migrate `MYAH_PLATFORM_BASE_URL` to the canonical value if broken.

    Mirrors setup-myah-oss.sh:321-329. Preserves the bug-class behavior
    documented in `docs/gotchas/2026-05-19-oss-cron-platform-base-url-drift.md`.

    Behavior:

      - If the value is empty/unset: write the canonical value, return ``True``.
      - If the value matches one of ``LEGACY_BROKEN_URLS``: overwrite with
        the canonical value, return ``True``.
      - If the value is anything else (including the canonical value
        itself or a user-customized URL like a remote platform):
        leave it alone, return ``False``.

    Returns ``True`` if a write happened, ``False`` if the value was preserved.
    """
    current = parse_env_file(env_path).get('MYAH_PLATFORM_BASE_URL', '')
    if current and current not in LEGACY_BROKEN_URLS:
        return False
    set_env_var(env_path, 'MYAH_PLATFORM_BASE_URL', CANONICAL_PLATFORM_BASE_URL)
    return True


# "If they had a key under the old name, give it the new name too —
#  but don't take the old one away." — bash:376-378.

def adopt_legacy_webui_key(env_path: Path) -> bool:
    """Adopt ``WEBUI_SECRET_KEY`` into ``MYAH_SECRET_KEY`` if applicable.

    Mirrors setup-myah-oss.sh:376-378 (the ``elif`` branch of phase 3).

    Behavior:

      - If ``MYAH_SECRET_KEY`` is already set (non-empty): do nothing,
        return ``False``.
      - If ``MYAH_SECRET_KEY`` is unset/empty AND ``WEBUI_SECRET_KEY`` is
        set (non-empty): copy the ``WEBUI_SECRET_KEY`` value to
        ``MYAH_SECRET_KEY``, return ``True``.
      - If both are unset/empty: do nothing, return ``False`` (caller is
        expected to generate a fresh secret via `generate_jwt_secret`).
      - If the file does not exist: do nothing, return ``False`` — the
        caller will then call `generate_jwt_secret` + write the result,
        so there is no "stale" state to clean up here.

    Returns ``True`` if a write happened, ``False`` otherwise.

    Note: does NOT remove or modify ``WEBUI_SECRET_KEY`` — the legacy
    key stays in place for backwards compat (matching the bash behavior).
    """
    if not env_path.is_file():
        return False
    parsed = parse_env_file(env_path)
    if parsed.get('MYAH_SECRET_KEY'):
        return False
    legacy = parsed.get('WEBUI_SECRET_KEY', '')
    if not legacy:
        return False
    set_env_var(env_path, 'MYAH_SECRET_KEY', legacy)
    return True


__all__ = [
    'CANONICAL_PLATFORM_BASE_URL',
    'LEGACY_BROKEN_URLS',
    'adopt_legacy_webui_key',
    'generate_bearer_token',
    'generate_fernet_key',
    'generate_jwt_secret',
    'migrate_legacy_url',
    'write_token_to_all_slots',
]
