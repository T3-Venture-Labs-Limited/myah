#!/usr/bin/env bash
# scripts/setup-myah-oss.sh — one-shot OSS-mode bootstrap helper.
#
# Generates all shared secrets and writes them to the right places so a
# fresh OSS install just works once Hermes is started + Myah platform
# is brought up. This script is idempotent — re-runs only fill values
# that are unset. Pass --rotate to force fresh values for all secrets.
#
# What it writes:
#
#   Platform .env (./.env):
#     - MYAH_AGENT_BEARER_TOKEN              shared bearer
#     - OAUTH_SESSION_TOKEN_ENCRYPTION_KEY   Fernet key for oauth_session table
#     - MYAH_SECRET_KEY                      HMAC key for session cookies
#
#   Hermes .env (~/.hermes/.env):
#     - MYAH_AGENT_BEARER_TOKEN     mirrors platform value (legacy compat)
#     - MYAH_ADAPTER_AUTH_KEY       same value — what the plugin actually reads
#     - API_SERVER_KEY              same value — for upstream Hermes api_server
#     - API_SERVER_ENABLED=true     opt-in to the /v1/runs, /health HTTP API
#     - MYAH_PLATFORM_BASE_URL      platform URL the plugin can call back to
#     - MYAH_USER_ID                seeded single-user UUID (from oss_seed_user
#                                   migration) so plugin cron→platform deliveries
#                                   resolve without needing /whoami discovery
#     - MYAH_ALLOW_ALL_USERS=true   plugin accepts any user_id (single-user OSS)
#     - MYAH_HOME_CHAT=disabled     suppress "no home channel" warning
#     - MYAH_HOME_CHANNEL=disabled  forward-compat for the legacy name
#
#   Hermes config (~/.hermes/config.yaml):
#     - gateway.platforms.myah.enabled = true   without this, `hermes plugins
#                                               install <plugin>` registers
#                                               the plugin but the gateway
#                                               never instantiates its adapter
#                                               and /myah/* routes never bind
#
# Usage:
#   ./scripts/setup-myah-oss.sh
#   ./scripts/setup-myah-oss.sh --rotate    # force new keys
set -euo pipefail

# ─── 0. Prerequisite checks ─────────────────────────────────────────
# Fail early and loudly so the user knows exactly what's missing before
# any partial writes happen.
missing=()
for cmd in openssl python3 grep awk; do
  command -v "$cmd" >/dev/null 2>&1 || missing+=("$cmd")
done
if (( ${#missing[@]} > 0 )); then
  echo "✗ Missing required commands: ${missing[*]}" >&2
  echo "  On Debian/Ubuntu: sudo apt-get install -y ${missing[*]}" >&2
  exit 1
fi

# PyYAML is required for the Hermes config.yaml merge. Most distros ship
# it in `python3-yaml` (apt) or `python3-pyyaml` (dnf). It's tiny.
if ! python3 -c 'import yaml' >/dev/null 2>&1; then
  echo "✗ Python 'yaml' module not installed (PyYAML)." >&2
  echo "  Install one of:" >&2
  echo "    sudo apt-get install -y python3-yaml      # Debian/Ubuntu" >&2
  echo "    sudo dnf install -y python3-pyyaml        # Fedora/RHEL" >&2
  echo "    python3 -m pip install --user pyyaml      # any distro with pip" >&2
  exit 1
fi

# Docker/Compose checks are advisory at this stage — the user might be
# running this script BEFORE installing Docker (e.g. to generate keys
# in advance). Just warn.
if ! command -v docker >/dev/null 2>&1; then
  echo "⚠ docker not on PATH — you'll need it before 'docker compose up -d'"
fi
if command -v docker >/dev/null 2>&1 && ! docker compose version >/dev/null 2>&1; then
  echo "⚠ 'docker compose' subcommand unavailable — install Docker Compose v2"
fi

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PLATFORM_ENV="$ROOT/.env"
HERMES_HOME_DIR="${HERMES_HOME:-$HOME/.hermes}"
HERMES_ENV="$HERMES_HOME_DIR/.env"
HERMES_CONFIG="$HERMES_HOME_DIR/config.yaml"
ROTATE=0
[[ "${1:-}" == "--rotate" ]] && ROTATE=1

mkdir -p "$HERMES_HOME_DIR"

# ─── Helpers ────────────────────────────────────────────────────────

# Read the value of an env var from a .env-style file (or empty).
get_var() {
  local file="$1" var="$2"
  [[ -f "$file" ]] || { echo ""; return; }
  grep -E "^${var}=" "$file" 2>/dev/null | tail -n1 | cut -d= -f2- || true
}

# Set or update an env var in a .env-style file. Portable: uses awk
# + atomic mv instead of sed -i (which is GNU/BSD-incompatible).
set_var() {
  local file="$1" var="$2" val="$3"
  if [[ -f "$file" ]] && grep -qE "^${var}=" "$file"; then
    awk -v v="$var" -v val="$val" '
      $0 ~ "^"v"=" { print v"="val; next } { print }
    ' "$file" > "$file.tmp" && mv "$file.tmp" "$file"
  else
    echo "${var}=${val}" >> "$file"
  fi
}

# 32 bytes of cryptographically secure random, hex-encoded (64 chars).
# Hex is portable across `openssl rand`, doesn't require Python, and
# OAuth's Fernet bootstrap (oauth_sessions.py:75-77) SHA256-hashes any
# non-44-byte value before handing it to Fernet — so hex works for both
# the OAuth encryption key AND the JWT HMAC secret.
gen_key() {
  openssl rand -hex 32
}

# Ensure platform .env exists (copy from .env.example if not)
if [[ ! -f "$PLATFORM_ENV" ]]; then
  if [[ -f "$ROOT/.env.example" ]]; then
    cp "$ROOT/.env.example" "$PLATFORM_ENV"
  else
    touch "$PLATFORM_ENV"
  fi
fi

# ─── 1. Shared bearer token ─────────────────────────────────────────
#
# The same value is written to four env-var names because three layers
# all check Bearer auth independently:
#
#   - MYAH_AGENT_BEARER_TOKEN  (platform side — what the platform SENDS)
#   - MYAH_ADAPTER_AUTH_KEY    (plugin side — what _check_auth COMPARES)
#   - API_SERVER_KEY           (Hermes upstream api_server adapter)
#   - MYAH_AGENT_BEARER_TOKEN  (also in hermes .env — legacy compat for
#                              code paths that still read the old name)
#
# All four MUST hold the same value or chat requests get 401.

PLATFORM_TOKEN="$(get_var "$PLATFORM_ENV" MYAH_AGENT_BEARER_TOKEN)"
HERMES_BEARER="$(get_var "$HERMES_ENV" MYAH_AGENT_BEARER_TOKEN)"
HERMES_ADAPTER_KEY="$(get_var "$HERMES_ENV" MYAH_ADAPTER_AUTH_KEY)"
HERMES_API_KEY="$(get_var "$HERMES_ENV" API_SERVER_KEY)"

if [[ "$ROTATE" == 1 ]]; then
  TOKEN=""
elif [[ -n "$PLATFORM_TOKEN" \
     && "$PLATFORM_TOKEN" == "$HERMES_BEARER" \
     && "$PLATFORM_TOKEN" == "$HERMES_ADAPTER_KEY" \
     && "$PLATFORM_TOKEN" == "$HERMES_API_KEY" ]]; then
  echo "✓ MYAH_AGENT_BEARER_TOKEN: already aligned across all four slots"
  TOKEN="$PLATFORM_TOKEN"
else
  TOKEN="${PLATFORM_TOKEN:-${HERMES_BEARER:-${HERMES_ADAPTER_KEY:-${HERMES_API_KEY:-}}}}"
fi

if [[ -z "$TOKEN" ]]; then
  TOKEN="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
  echo "✓ MYAH_AGENT_BEARER_TOKEN: generated (length=${#TOKEN})"
fi

set_var "$PLATFORM_ENV" MYAH_AGENT_BEARER_TOKEN "$TOKEN"
set_var "$HERMES_ENV"   MYAH_AGENT_BEARER_TOKEN "$TOKEN"
set_var "$HERMES_ENV"   MYAH_ADAPTER_AUTH_KEY   "$TOKEN"
set_var "$HERMES_ENV"   API_SERVER_KEY          "$TOKEN"

# Enable Hermes's HTTP api_server adapter so it binds port 8642 for
# /v1/runs, /health, etc. — opt-in per gateway/config.py:1472-1494.
[[ -n "$(get_var "$HERMES_ENV" API_SERVER_ENABLED)" ]] || \
  set_var "$HERMES_ENV" API_SERVER_ENABLED true

# Plugin needs to know where to call the platform back from (cron
# delivery, attachment fetch). Default to host.docker.internal:8080
# which works on Linux + macOS + Windows when the platform container's
# compose stanza maps the host gateway via extra_hosts.
[[ -n "$(get_var "$HERMES_ENV" MYAH_PLATFORM_BASE_URL)" ]] || \
  set_var "$HERMES_ENV" MYAH_PLATFORM_BASE_URL "http://host.docker.internal:8080"

# Seeded single-user UUID (see oss_seed_user migration).  Without this
# the plugin's _bootstrap_user_id falls back to /whoami discovery which
# adds a startup race and one extra HTTP roundtrip per process start.
[[ -n "$(get_var "$HERMES_ENV" MYAH_USER_ID)" ]] || \
  set_var "$HERMES_ENV" MYAH_USER_ID "00000000-0000-0000-0000-000000000001"

# Single-user OSS — plugin accepts any user_id from the platform.
[[ -n "$(get_var "$HERMES_ENV" MYAH_ALLOW_ALL_USERS)" ]] || \
  set_var "$HERMES_ENV" MYAH_ALLOW_ALL_USERS true

# Suppress the "📬 No home channel is set for Myah" warning emitted on
# every session creation. MYAH_HOME_CHAT is the canonical name the
# plugin registers; MYAH_HOME_CHANNEL is the legacy fallback derived
# from upstream's <PLATFORM>_HOME_CHANNEL pattern.
[[ -n "$(get_var "$HERMES_ENV" MYAH_HOME_CHAT)" ]] || \
  set_var "$HERMES_ENV" MYAH_HOME_CHAT disabled
[[ -n "$(get_var "$HERMES_ENV" MYAH_HOME_CHANNEL)" ]] || \
  set_var "$HERMES_ENV" MYAH_HOME_CHANNEL disabled

# ─── 2. OAUTH_SESSION_TOKEN_ENCRYPTION_KEY — platform-side Fernet key ─
#
# oauth_sessions.py raises Exception at module import time if this is
# unset (currently — H6 in the OSS audit will defer this to first use,
# but the script still seeds it so we don't depend on that fix).

OAUTH_KEY="$(get_var "$PLATFORM_ENV" OAUTH_SESSION_TOKEN_ENCRYPTION_KEY)"
if [[ "$ROTATE" == 1 || -z "$OAUTH_KEY" ]]; then
  OAUTH_KEY="$(gen_key)"
  set_var "$PLATFORM_ENV" OAUTH_SESSION_TOKEN_ENCRYPTION_KEY "$OAUTH_KEY"
  echo "✓ OAUTH_SESSION_TOKEN_ENCRYPTION_KEY: generated"
else
  echo "✓ OAUTH_SESSION_TOKEN_ENCRYPTION_KEY: already set"
fi

# ─── 3. MYAH_SECRET_KEY — JWT/session HMAC key ────────────────────────

SECRET_KEY="$(get_var "$PLATFORM_ENV" MYAH_SECRET_KEY)"
LEGACY_WEBUI_KEY="$(get_var "$PLATFORM_ENV" WEBUI_SECRET_KEY)"

if [[ "$ROTATE" == 1 ]]; then
  SECRET_KEY="$(gen_key)"
  set_var "$PLATFORM_ENV" MYAH_SECRET_KEY "$SECRET_KEY"
  echo "✓ MYAH_SECRET_KEY: rotated"
elif [[ -n "$SECRET_KEY" ]]; then
  echo "✓ MYAH_SECRET_KEY: already set"
elif [[ -n "$LEGACY_WEBUI_KEY" ]]; then
  set_var "$PLATFORM_ENV" MYAH_SECRET_KEY "$LEGACY_WEBUI_KEY"
  echo "✓ MYAH_SECRET_KEY: adopted from legacy WEBUI_SECRET_KEY"
else
  SECRET_KEY="$(gen_key)"
  set_var "$PLATFORM_ENV" MYAH_SECRET_KEY "$SECRET_KEY"
  echo "✓ MYAH_SECRET_KEY: generated"
fi

# ─── 4. Hermes config.yaml — enable the Myah platform ────────────────
#
# `hermes plugins install T3-Venture-Labs-Limited/myah-hermes-plugin`
# materializes the plugin to ~/.hermes/plugins/myah-hermes-plugin/ and
# adds it to plugin.disabled_list = []. BUT the gateway only spins up
# platform adapters whose config.platforms[name].enabled = True
# (gateway/run.py:3554). The plugin registers the platform name but
# does NOT auto-enable it in the user's config.
#
# Without this step the plugin loads, `hermes plugins list` shows it
# as enabled, but port 8643 never binds and the platform's OSS probe
# reports plugin_installed=false. This is the single most non-obvious
# failure mode in the install chain.

ensure_myah_platform_enabled_in_config() {
  if [[ ! -f "$HERMES_CONFIG" ]]; then
    cat > "$HERMES_CONFIG" <<'EOF'
# Auto-generated by scripts/setup-myah-oss.sh — safe to edit by hand.
gateway:
  platforms:
    myah:
      enabled: true
EOF
    echo "✓ Hermes config: created with gateway.platforms.myah.enabled=true"
    return
  fi

  # Existing file — proper YAML merge via PyYAML (asserted available
  # in the prereq block above). Preserves whatever else the user has
  # in their config; only flips one boolean (or adds the path if
  # missing).
  python3 - "$HERMES_CONFIG" <<'PY'
import pathlib
import sys

import yaml

path = pathlib.Path(sys.argv[1])
text = path.read_text()
cfg = yaml.safe_load(text) or {}
if not isinstance(cfg, dict):
    print(f"⚠ {path}: top-level is not a mapping; rewriting as fresh config")
    cfg = {}
gateway = cfg.setdefault('gateway', {})
if not isinstance(gateway, dict):
    print(f"⚠ {path}: 'gateway' is not a mapping; replacing it")
    gateway = {}
    cfg['gateway'] = gateway
platforms = gateway.setdefault('platforms', {})
if not isinstance(platforms, dict):
    platforms = {}
    gateway['platforms'] = platforms
myah = platforms.setdefault('myah', {})
if not isinstance(myah, dict):
    myah = {}
    platforms['myah'] = myah
already = myah.get('enabled') is True
myah['enabled'] = True
path.write_text(yaml.safe_dump(cfg, sort_keys=False))
status = 'already set' if already else 'updated'
print(f"✓ Hermes config: gateway.platforms.myah.enabled=true ({status})")
PY
}

ensure_myah_platform_enabled_in_config

# ─── Final output ────────────────────────────────────────────────────

echo
echo "✓ Platform .env:    $PLATFORM_ENV"
echo "✓ Hermes  .env:     $HERMES_ENV"
echo "✓ Hermes  config:   $HERMES_CONFIG"
echo
echo "Next steps (in order):"
echo
echo "  1. Add an LLM provider key to your Hermes .env. Pick one:"
echo "     echo 'OPENROUTER_API_KEY=sk-or-...'   >> $HERMES_ENV"
echo "     echo 'OPENAI_API_KEY=sk-...'          >> $HERMES_ENV"
echo "     echo 'ANTHROPIC_API_KEY=sk-ant-...'   >> $HERMES_ENV"
echo "     echo 'KIMI_API_KEY=...'               >> $HERMES_ENV"
echo "     (see Hermes docs for the full provider list)"
echo
echo "  2. Install the Myah plugin into Hermes (if you haven't yet):"
echo "       hermes plugins install T3-Venture-Labs-Limited/myah-hermes-plugin"
echo "     When prompted for MYAH_ADAPTER_AUTH_KEY, press Enter to skip —"
echo "     this script already wrote that value to $HERMES_ENV."
echo
echo "  3. Start the Hermes gateway. Two options:"
echo "       hermes gateway run                            # foreground"
echo "       hermes gateway install && hermes gateway start # systemd background"
echo "     Verify it's reachable:"
echo "       curl -s http://localhost:8642/health         # Hermes core"
echo "       curl -s http://localhost:8643/myah/health    # Myah plugin"
echo "     Both should return JSON. If 8643 returns connection-refused,"
echo "     the platform isn't enabled in $HERMES_CONFIG — check that"
echo "     gateway.platforms.myah.enabled is set to true."
echo
echo "  4. Bring up the Myah platform:"
echo "       docker compose up -d"
echo
echo "  5. Open http://localhost:8080 — single-user OSS, no sign-up needed."
echo
echo "If something doesn't work, see docs/troubleshooting.md or run"
echo "this script again with --rotate to regenerate every secret."
