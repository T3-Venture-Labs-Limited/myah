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
#     - MYAH_ADAPTER_AUTH_KEY       same value — plugin's incoming-auth check
#     - API_SERVER_KEY              same value — for upstream Hermes api_server
#     - MYAH_PLATFORM_BEARER        same value — plugin's outbound attachment-fetch bearer
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

# PyYAML is required for the Hermes config.yaml merge in step 6 — which
# runs AFTER the MYAH_OSS_SETUP_ENV_ONLY escape hatch. Tests that only
# verify env-write behavior set that var to short-circuit before step 5,
# so PyYAML isn't actually needed in those runs. Skipping the check for
# them keeps the curated CI gate green on minimal Python environments.
# Most distros ship PyYAML in `python3-yaml` (apt) or `python3-pyyaml`
# (dnf). It's tiny.
if [[ -z "${MYAH_OSS_SETUP_ENV_ONLY:-}" ]] \
   && ! python3 -c 'import yaml' >/dev/null 2>&1; then
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

# Return "free" if the loopback TCP port is available, "in-use" otherwise.
# Uses /dev/tcp (bash built-in) so we don't depend on netcat/ss.
probe_loopback_port() {
  local port="$1"
  if (timeout 1 bash -c "</dev/tcp/127.0.0.1/$port") 2>/dev/null; then
    echo "in-use"
  else
    echo "free"
  fi
}

# Locate the Python venv hermes-agent installed itself into. Returns
# the venv root path on stdout, or exits 1 with a clear error message.
#
# Override via MYAH_HERMES_VENV env var — used by CI (and other automated
# environments that don't follow Hermes's canonical install locations).
# The override skips all candidate detection and trusts the caller.
detect_hermes_venv() {
  if [[ -n "${MYAH_HERMES_VENV:-}" ]]; then
    if [[ -x "$MYAH_HERMES_VENV/bin/python" ]]; then
      echo "$MYAH_HERMES_VENV"
      return 0
    fi
    echo "✗ MYAH_HERMES_VENV=$MYAH_HERMES_VENV is set but $MYAH_HERMES_VENV/bin/python is not executable" >&2
    return 1
  fi
  # Resolution order matches how Hermes's own installer creates them.
  local candidates=(
    "$HOME/.hermes/hermes-agent/venv"            # per-user install (default)
    "/usr/local/lib/hermes-agent/venv"           # system install
    "/opt/hermes-agent/venv"                     # Homebrew tap install
  )
  local candidate
  for candidate in "${candidates[@]}"; do
    if [[ -x "$candidate/bin/python" ]]; then
      echo "$candidate"
      return 0
    fi
  done

  # Last resort: resolve the venv from the `hermes` binary's shebang.
  if command -v hermes >/dev/null 2>&1; then
    local hermes_bin
    hermes_bin="$(command -v hermes)"
    local shebang
    shebang="$(head -n1 "$hermes_bin" 2>/dev/null || true)"
    if [[ "$shebang" =~ ^#!(.+/python[0-9.]*)$ ]]; then
      local python_path="${BASH_REMATCH[1]}"
      local venv_root
      venv_root="$(dirname "$(dirname "$python_path")")"
      if [[ -x "$venv_root/bin/python" ]]; then
        echo "$venv_root"
        return 0
      fi
    fi
  fi

  echo "✗ Could not locate hermes-agent venv. Looked in:" >&2
  printf '    %s\n' "${candidates[@]}" >&2
  echo "  Make sure hermes is installed; see https://hermes-agent.nousresearch.com/docs/installation" >&2
  return 1
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
# The same value is written to five env-var slots. Two directions, three
# checks each direction. Mismatch any one and a different feature breaks:
#
#   Platform → Hermes (chat dispatch):
#     - MYAH_AGENT_BEARER_TOKEN  (platform .env — what the platform SENDS)
#     - MYAH_ADAPTER_AUTH_KEY    (hermes  .env — what _check_auth COMPARES)
#     - API_SERVER_KEY           (hermes  .env — Hermes upstream api_server)
#     - MYAH_AGENT_BEARER_TOKEN  (hermes  .env — legacy alias)
#
#   Hermes → Platform (attachment fetch, cron deliveries):
#     - MYAH_PLATFORM_BEARER     (hermes  .env — adapter.py reads at import,
#                                no alias fallback — omitting this surfaces
#                                as a 500 'Adapter missing
#                                MYAH_PLATFORM_BASE_URL / MYAH_PLATFORM_BEARER
#                                env' on the FIRST attachment a user sends)
#
# All five MUST hold the same value or a feature silently fails.

PLATFORM_TOKEN="$(get_var "$PLATFORM_ENV" MYAH_AGENT_BEARER_TOKEN)"
HERMES_BEARER="$(get_var "$HERMES_ENV" MYAH_AGENT_BEARER_TOKEN)"
HERMES_ADAPTER_KEY="$(get_var "$HERMES_ENV" MYAH_ADAPTER_AUTH_KEY)"
HERMES_API_KEY="$(get_var "$HERMES_ENV" API_SERVER_KEY)"
HERMES_PLATFORM_BEARER="$(get_var "$HERMES_ENV" MYAH_PLATFORM_BEARER)"

if [[ "$ROTATE" == 1 ]]; then
  TOKEN=""
elif [[ -n "$PLATFORM_TOKEN" \
     && "$PLATFORM_TOKEN" == "$HERMES_BEARER" \
     && "$PLATFORM_TOKEN" == "$HERMES_ADAPTER_KEY" \
     && "$PLATFORM_TOKEN" == "$HERMES_API_KEY" \
     && "$PLATFORM_TOKEN" == "$HERMES_PLATFORM_BEARER" ]]; then
  echo "✓ MYAH_AGENT_BEARER_TOKEN: already aligned across all five slots"
  TOKEN="$PLATFORM_TOKEN"
else
  TOKEN="${PLATFORM_TOKEN:-${HERMES_BEARER:-${HERMES_ADAPTER_KEY:-${HERMES_API_KEY:-${HERMES_PLATFORM_BEARER:-}}}}}"
fi

if [[ -z "$TOKEN" ]]; then
  TOKEN="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
  echo "✓ MYAH_AGENT_BEARER_TOKEN: generated (length=${#TOKEN})"
fi

set_var "$PLATFORM_ENV" MYAH_AGENT_BEARER_TOKEN "$TOKEN"
set_var "$HERMES_ENV"   MYAH_AGENT_BEARER_TOKEN "$TOKEN"
set_var "$HERMES_ENV"   MYAH_ADAPTER_AUTH_KEY   "$TOKEN"
set_var "$HERMES_ENV"   API_SERVER_KEY          "$TOKEN"
set_var "$HERMES_ENV"   MYAH_PLATFORM_BEARER    "$TOKEN"

# Enable Hermes's HTTP api_server adapter so it binds port 8642 for
# /v1/runs, /health, etc. — opt-in per gateway/config.py:1472-1494.
[[ -n "$(get_var "$HERMES_ENV" API_SERVER_ENABLED)" ]] || \
  set_var "$HERMES_ENV" API_SERVER_ENABLED true

# Bind the api_server to 0.0.0.0 so the platform docker container can
# reach it via host.docker.internal:host-gateway (which resolves to the
# host bridge IP, e.g. 172.17.0.1 — a service bound only to 127.0.0.1
# on the host is unreachable from the container).
#
# Same LAN-exposure trade-off as the dashboard's --host 0.0.0.0; see
# docs/gotchas/2026-05-17-oss-dashboard-lan-exposure.md. The api_server
# is bearer-token gated by API_SERVER_KEY (which equals
# MYAH_AGENT_BEARER_TOKEN, written above), so LAN attackers can't reach
# /v1/runs without the secret.
[[ -n "$(get_var "$HERMES_ENV" API_SERVER_HOST)" ]] || \
  set_var "$HERMES_ENV" API_SERVER_HOST 0.0.0.0

# Plugin (running on the host) needs to reach the platform (running in
# docker compose). The OSS compose file publishes the platform on
# 127.0.0.1:8080 (see docker-compose.yml ports stanza), so loopback
# is the universally correct value for the canonical install.
#
# Auto-migrate installs from before this fix: the previous default was
# 'http://host.docker.internal:8080', which only resolves from INSIDE
# a docker container — host-side hermes can't use it, so attachments
# would 500 with 'Adapter missing ... env' on the first send. If the
# user still has the broken legacy default, replace it; otherwise
# preserve whatever they've set (could be a remote platform URL).
#
# Per Task 3.3 (this PR): also migrates from the OBSOLETE port 8154
# default that older pre-0.1.0-beta.1 installs wrote. The migration
# block already supersedes Task 3.3's idempotent-overwrite intent.
LEGACY_BROKEN_URLS=(
  'http://host.docker.internal:8080'   # only resolved inside containers
  'http://localhost:8154'              # obsolete port from pre-launch installs
)
CURRENT_PLATFORM_URL="$(get_var "$HERMES_ENV" MYAH_PLATFORM_BASE_URL)"
if [[ -z "$CURRENT_PLATFORM_URL" ]] \
    || printf '%s\n' "${LEGACY_BROKEN_URLS[@]}" | grep -Fxq "$CURRENT_PLATFORM_URL"; then
  set_var "$HERMES_ENV" MYAH_PLATFORM_BASE_URL "http://127.0.0.1:8080"
fi

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

# ─── 4. HERMES_WEB_SESSION_TOKEN — dashboard auth ────────────────────
#
# The platform talks to `hermes dashboard` (port 9119 by default — see
# platform-oss/backend/myah/utils/hermes_web.py:97) for provider, toolset,
# and model catalog reads and for every Add/Remove/OAuth write. The
# dashboard requires Bearer auth via HERMES_WEB_SESSION_TOKEN.
#
# Two env-var names hold the same value:
#   - HERMES_WEB_SESSION_TOKEN       in ~/.hermes/.env (read by hermes
#                                    dashboard at startup)
#   - MYAH_HERMES_WEB_SESSION_TOKEN  in ./.env (read by the platform
#                                    via _oss_web_session_token() in
#                                    hermes_web.py:109)
#
# Token desync = 401 from every catalog read. We always set both at the
# same value so the welcome screen never reports false dashboard-down.

PLATFORM_WEB_TOKEN="$(get_var "$PLATFORM_ENV" MYAH_HERMES_WEB_SESSION_TOKEN)"
HERMES_WEB_TOKEN="$(get_var "$HERMES_ENV" HERMES_WEB_SESSION_TOKEN)"
WEB_TOKEN=""

if [[ "$ROTATE" == 1 ]]; then
  WEB_TOKEN=""
  # Will hit the "generated" branch below.
elif [[ -n "$PLATFORM_WEB_TOKEN" \
     && "$PLATFORM_WEB_TOKEN" == "$HERMES_WEB_TOKEN" ]]; then
  WEB_TOKEN="$PLATFORM_WEB_TOKEN"
  echo "✓ HERMES_WEB_SESSION_TOKEN: already aligned across both .env files"
elif [[ -n "$PLATFORM_WEB_TOKEN" && -n "$HERMES_WEB_TOKEN" ]]; then
  # Both sides set but different — desync. Adopt platform value (it's
  # the one the docker container reads at boot via MYAH_HERMES_WEB_SESSION_TOKEN)
  # so the running platform stays valid; ~/.hermes/.env rewrites below.
  WEB_TOKEN="$PLATFORM_WEB_TOKEN"
  echo "⚠ HERMES_WEB_SESSION_TOKEN: desync detected — realigning ~/.hermes/.env to platform value"
elif [[ -n "$PLATFORM_WEB_TOKEN" ]]; then
  # Platform set, hermes empty — common after fresh hermes install.
  WEB_TOKEN="$PLATFORM_WEB_TOKEN"
  echo "✓ HERMES_WEB_SESSION_TOKEN: copying existing platform value to ~/.hermes/.env"
elif [[ -n "$HERMES_WEB_TOKEN" ]]; then
  # Hermes set, platform empty — fresh platform repo.
  WEB_TOKEN="$HERMES_WEB_TOKEN"
  echo "✓ HERMES_WEB_SESSION_TOKEN: copying existing hermes value to platform .env"
fi

if [[ -z "$WEB_TOKEN" ]]; then
  WEB_TOKEN="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
  echo "✓ HERMES_WEB_SESSION_TOKEN: generated (length=${#WEB_TOKEN})"
fi

set_var "$PLATFORM_ENV" MYAH_HERMES_WEB_SESSION_TOKEN "$WEB_TOKEN"
set_var "$HERMES_ENV"   HERMES_WEB_SESSION_TOKEN       "$WEB_TOKEN"

# ─── Test-only escape hatch: env-file writes are done; everything below
#     touches a real Hermes venv / network. Tests that only verify env
#     output set MYAH_OSS_SETUP_ENV_ONLY=1 to exit here.
[[ -n "${MYAH_OSS_SETUP_ENV_ONLY:-}" ]] && exit 0

# ─── 5. Pip-install myah-hermes-plugin into Hermes's venv ────────────
#
# The platform calls `hermes dashboard` (a second Hermes process) for
# provider catalog + Add/Remove/OAuth flows. That dashboard process needs
# to import myah_hermes_plugin.myah_admin.dashboard.plugin_api at runtime,
# which is only on sys.path if the plugin is installed in Hermes's venv.
# `hermes plugins install` materializes the gateway-side plugin but does
# NOT pip-install the package — that's why this step exists.

HERMES_VENV="$(detect_hermes_venv)" || exit 1
HERMES_PY="$HERMES_VENV/bin/python"

# Hermes is typically installed via uv (or a uv-style installer) which
# DOES NOT include pip in the venv by default. Bootstrap pip via stdlib
# ensurepip before trying to pip-install anything. Idempotent — if pip
# is already present, ensurepip is a no-op.
if ! "$HERMES_PY" -m pip --version >/dev/null 2>&1; then
  echo "→ Bootstrapping pip in Hermes venv via ensurepip..."
  "$HERMES_PY" -m ensurepip --upgrade --quiet
  if ! "$HERMES_PY" -m pip --version >/dev/null 2>&1; then
    echo "✗ ensurepip ran but 'python -m pip' still fails. Check the venv at $HERMES_VENV" >&2
    exit 1
  fi
fi

# Resolve the plugin SHA from versions.env (single source of truth on the
# public mirror; the private monorepo equivalent lives in
# agent/Dockerfile.stock). Both the production agent image and the OSS
# install use the same pin so upgrades stay coordinated.
if [[ ! -f "$ROOT/versions.env" ]]; then
  echo "✗ versions.env not found at $ROOT/versions.env" >&2
  exit 1
fi
# shellcheck source=/dev/null
source "$ROOT/versions.env"
PLUGIN_SHA="${MYAH_PLUGIN_SHA:-}"
if [[ -z "$PLUGIN_SHA" ]]; then
  echo "✗ MYAH_PLUGIN_SHA not set in $ROOT/versions.env" >&2
  exit 1
fi

# Install from GitHub at the pinned SHA. The myah-hermes-plugin repo is
# public; the URL works unauthenticated. MYAH_PLUGIN_AUTH_TOKEN is honored
# for forks of the plugin that happen to be private — set the env var to
# a PAT or fine-grained token with read access if needed.
if [[ -n "${MYAH_PLUGIN_AUTH_TOKEN:-}" ]]; then
  PLUGIN_URL="git+https://${MYAH_PLUGIN_AUTH_TOKEN}@github.com/T3-Venture-Labs-Limited/myah-hermes-plugin@${PLUGIN_SHA}"
else
  PLUGIN_URL="git+https://github.com/T3-Venture-Labs-Limited/myah-hermes-plugin@${PLUGIN_SHA}"
fi

"$HERMES_PY" -m pip install --quiet --upgrade "myah-hermes-plugin @ ${PLUGIN_URL}"
echo "✓ myah-hermes-plugin@${PLUGIN_SHA:0:8} pip-installed into $HERMES_VENV"

# Materialize the dashboard shim at ~/.hermes/plugins/myah-admin/
# (where the dashboard's plugin-discovery scans). The shim's
# plugin_api.py imports from the package we just pip-installed.
#
# The console script is created by the pip install above as
# <venv>/bin/myah-hermes-plugin. Use the absolute path so we don't
# depend on PATH ordering.
"$HERMES_VENV/bin/myah-hermes-plugin" install \
  --dashboard-only \
  --target "$HERMES_HOME_DIR/plugins/"
echo "✓ Dashboard plugin shim materialized at $HERMES_HOME_DIR/plugins/myah-admin/"

# ─── 6. Hermes config.yaml — enable the Myah platform ────────────────
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

# ─── 7. Optional service-unit setup ─────────────────────────────────
#
# The user has three ways to keep `hermes gateway` and `hermes dashboard`
# running across reboots:
#   - systemd --user units (Linux)
#   - launchd plists (macOS)
#   - "none": run them manually via `scripts/dev-oss.sh up`
#
# We offer to install the service units if the platform supports them;
# the user can decline. Non-interactive (CI) usage: set
# SETUP_SERVICE_CHOICE=systemd|launchd|none before running.

OSS_SERVICE_CHOICE="${SETUP_SERVICE_CHOICE:-}"

# Stop any pre-existing hermes dashboard/gateway processes that this
# script is about to manage. A stale dashboard running from a prior
# Hermes setup can race with our launchctl bootstrap / systemctl
# enable below, ending in a state where the NEW dashboard process is
# the one bound to :9119 but its `myah-admin` plugin's FastAPI routes
# never get mounted. The user sees the welcome screen "Connect a
# provider" infinite-loading because every proxied request from the
# platform to `/api/plugins/myah-admin/*` returns 401.
#
# See: docs/troubleshooting.md "Dashboard plugin not mounted" section
# (and the gotcha doc in the internal monorepo at
# docs/gotchas/2026-05-18-dashboard-plugin-mount-stale-process.md).
#
# We SIGTERM first, give 1s, then SIGKILL anything still alive. Each
# `pgrep`/`kill` is guarded with `|| true` so `set -euo pipefail`
# doesn't trip when there's nothing to stop.
stop_stale_hermes_processes() {
  local killed=0
  local pids pattern pid
  for pattern in 'hermes dashboard' 'hermes gateway' 'hermes_cli\.main'; do
    pids="$(pgrep -f "$pattern" 2>/dev/null || true)"
    for pid in $pids; do
      [[ -z "$pid" || "$pid" == "$$" ]] && continue
      if kill -TERM "$pid" 2>/dev/null; then
        killed=$((killed + 1))
      fi
    done
  done
  if (( killed > 0 )); then
    sleep 1
    for pattern in 'hermes dashboard' 'hermes gateway' 'hermes_cli\.main'; do
      pids="$(pgrep -f "$pattern" 2>/dev/null || true)"
      for pid in $pids; do
        [[ -z "$pid" || "$pid" == "$$" ]] && continue
        kill -9 "$pid" 2>/dev/null || true
      done
    done
    echo "→ stopped $killed pre-existing hermes process(es) to ensure clean service start"
  fi
}

# Poll the dashboard's `myah-admin` plugin health endpoint until it
# returns 200, or fail after ~15s with a clear remediation pointer.
# Does NOT exit the script on failure — the install itself completed,
# the runtime check is just a sanity gate. The user may still need to
# `kickstart -k` the dashboard once, which is fine.
#
# Why this check: `_mount_plugin_api_routes` in upstream
# `hermes_cli/web_server.py` catches all exceptions and logs via a
# logger with no handler configured at module-load time. Plugin mount
# failures are otherwise completely invisible — `/api/dashboard/plugins`
# still lists the plugin (manifest is on disk), but FastAPI has zero
# routes under `/api/plugins/<name>/`.
verify_dashboard_plugin_mounted() {
  local token="${1:-}"
  local port="${MYAH_HERMES_WEB_PORT:-9119}"
  local url="http://127.0.0.1:${port}/api/plugins/myah-admin/health"
  local attempts=30
  local delay=0.5
  local i
  for ((i=1; i<=attempts; i++)); do
    if [[ -n "$token" ]]; then
      if curl -sf -m 2 -H "Authorization: Bearer $token" "$url" >/dev/null 2>&1; then
        echo "✓ Dashboard 'myah-admin' plugin mounted at :${port}"
        return 0
      fi
    else
      # No token configured — auth-exempt path, just check liveness.
      if curl -sf -m 2 "$url" >/dev/null 2>&1; then
        echo "✓ Dashboard 'myah-admin' plugin mounted at :${port}"
        return 0
      fi
    fi
    sleep "$delay"
  done
  echo "" >&2
  echo "⚠ Dashboard 'myah-admin' plugin did not respond at :${port} within ~15s." >&2
  echo "  The platform's 'Connect a provider' screen will infinite-load." >&2
  echo "  Restart the dashboard cleanly:" >&2
  echo "    launchctl kickstart -k gui/\$UID/dev.myah.hermes-dashboard      # macOS" >&2
  echo "    systemctl --user restart hermes-dashboard                       # Linux" >&2
  echo "  Then verify:" >&2
  echo "    curl -s -H \"Authorization: Bearer \$HERMES_WEB_SESSION_TOKEN\" \\" >&2
  echo "      http://localhost:${port}/api/plugins/myah-admin/health" >&2
  echo "    Expected: {\"status\":\"ok\",\"plugin\":\"myah-admin\"}" >&2
  return 1
}

prompt_service_choice() {
  if [[ -n "$OSS_SERVICE_CHOICE" ]]; then
    return
  fi
  if [[ ! -t 0 ]]; then
    # Non-interactive: skip silently. The user can re-run with
    # SETUP_SERVICE_CHOICE=systemd|launchd|none to opt in later.
    OSS_SERVICE_CHOICE="none"
    return
  fi
  local default
  case "$(uname -s)" in
    Linux)  default="systemd" ;;
    Darwin) default="launchd" ;;
    *)      default="none" ;;
  esac
  echo
  echo "Run hermes gateway + dashboard as a background service?"
  echo "  [1] $default (recommended for $(uname -s))"
  echo "  [2] none — start them yourself via scripts/dev-oss.sh"
  read -rp "Choose [1]: " choice
  case "$choice" in
    ""|1) OSS_SERVICE_CHOICE="$default" ;;
    2)    OSS_SERVICE_CHOICE="none" ;;
    *)    OSS_SERVICE_CHOICE="none" ;;
  esac
}

# Detect + retire pre-existing LaunchAgent plists from earlier Hermes /
# Myah installs that used different label conventions. These conflict
# with the canonical `dev.myah.hermes-{gateway,dashboard}` plists we
# write below — the OS will happily run two competing copies of the
# gateway against the same port, with the older one usually winning the
# bind race and the newer plist staying in a flapping
# spawn-fail-respawn loop.
#
# Glob patterns we treat as legacy:
#   com.nous-research.hermes.{gateway,dashboard}.plist
#   com.myah.*.plist  (any earlier Myah-labelled service)
# We deliberately do NOT touch dev.myah.* — that's the current label;
# overwriting is handled by install_launchd_plists itself.
migrate_legacy_launchagents() {
  local agents_dir="$HOME/Library/LaunchAgents"
  if [[ ! -d "$agents_dir" ]]; then
    return 0
  fi
  shopt -s nullglob
  local found_legacy=()
  for plist in "$agents_dir"/com.nous-research.hermes.*.plist "$agents_dir"/com.myah.*.plist; do
    if [[ -f "$plist" ]]; then
      found_legacy+=("$plist")
    fi
  done
  shopt -u nullglob
  if [[ "${#found_legacy[@]}" -eq 0 ]]; then
    return 0
  fi
  echo "Detected ${#found_legacy[@]} legacy LaunchAgent plist(s); migrating..."
  local ts
  ts=$(date +%Y%m%d_%H%M%S)
  for plist in "${found_legacy[@]}"; do
    local label
    label=$(basename "$plist" .plist)
    echo "  Unloading $label"
    # bootout is the modern equivalent; fall back to unload for older macOS.
    launchctl bootout "gui/$UID/$label" 2>/dev/null \
      || launchctl unload "$plist" 2>/dev/null \
      || true
    echo "  Renaming $plist → $plist.bak.$ts"
    mv "$plist" "$plist.bak.$ts"
  done
}

# Linux counterpart: retire pre-existing systemd-user units from
# earlier installs that aren't part of the canonical Myah/Hermes set we
# install below. `mask` is the strongest form of "do not start this
# again" — equivalent to renaming the plist on macOS.
#
# Specifically we look for `myah-platform.service` (an older pattern
# where the platform itself was a systemd-user unit instead of docker
# compose). We do NOT mask `hermes-gateway` / `hermes-dashboard` here
# because install_systemd_units below installs units with those same
# names — they overwrite cleanly via daemon-reload, no migration needed.
migrate_legacy_systemd_units() {
  if ! command -v systemctl >/dev/null 2>&1; then
    return 0
  fi
  local found=()
  for unit in myah-platform; do
    if systemctl --user list-unit-files "${unit}.service" 2>/dev/null | grep -q "${unit}.service"; then
      found+=("$unit")
    fi
  done
  if [[ "${#found[@]}" -eq 0 ]]; then
    return 0
  fi
  echo "Detected ${#found[@]} legacy systemd unit(s); migrating..."
  for unit in "${found[@]}"; do
    echo "  Stopping + disabling + masking $unit"
    systemctl --user stop "${unit}.service" 2>/dev/null || true
    systemctl --user disable "${unit}.service" 2>/dev/null || true
    systemctl --user mask "${unit}.service" 2>/dev/null || true
  done
}

install_systemd_units() {
  migrate_legacy_systemd_units
  local hermes_bin
  hermes_bin="$(command -v hermes)" || {
    echo "⚠ hermes not on PATH — skipping systemd unit install"
    return
  }
  local unit_dir="$HOME/.config/systemd/user"
  mkdir -p "$unit_dir"

  # Defensive: kill any stale hermes processes BEFORE systemctl takes
  # over. `systemctl --user enable --now` doesn't touch processes
  # started outside of systemd (e.g. an old `hermes gateway run` left
  # over in a tmux window), so we'd race with them otherwise.
  stop_stale_hermes_processes

  for unit in hermes-gateway hermes-dashboard; do
    sed -e "s|__HERMES_BIN__|$hermes_bin|g" \
        -e "s|__HERMES_HOME__|$HERMES_HOME_DIR|g" \
        "$ROOT/scripts/oss-service-templates/${unit}.service.in" \
        > "$unit_dir/${unit}.service"
    systemctl --user enable --now "${unit}.service"
  done
  echo "✓ systemd-user units installed: hermes-gateway, hermes-dashboard"
  echo "  Manage with: systemctl --user {start|stop|restart|status} hermes-{gateway,dashboard}"

  # Sanity-check the dashboard plugin actually mounted — the most
  # common silent failure mode after a fresh pip-install.
  local web_token
  web_token="$(get_var "$HERMES_ENV" HERMES_WEB_SESSION_TOKEN)"
  verify_dashboard_plugin_mounted "$web_token" || true
}

install_launchd_plists() {
  migrate_legacy_launchagents
  local hermes_bin
  hermes_bin="$(command -v hermes)" || {
    echo "⚠ hermes not on PATH — skipping launchd plist install"
    return
  }
  local plist_dir="$HOME/Library/LaunchAgents"
  mkdir -p "$plist_dir"
  mkdir -p "$HERMES_HOME_DIR/logs"

  # Defensive: kill any stale hermes processes BEFORE launchctl takes
  # over. Otherwise the new dashboard can race the old for :9119 and
  # end up running with the `myah-admin` plugin's routes unmounted.
  # The whole point of this gate is that the failure is silent — the
  # OpenAPI is just missing 32 routes that should be there.
  stop_stale_hermes_processes

  for service in dev.myah.hermes-gateway dev.myah.hermes-dashboard; do
    sed -e "s|__HERMES_BIN__|$hermes_bin|g" \
        -e "s|__HERMES_HOME__|$HERMES_HOME_DIR|g" \
        "$ROOT/scripts/oss-service-templates/${service}.plist.in" \
        > "$plist_dir/${service}.plist"
    # Bootout any existing registration first so we ALWAYS re-bootstrap
    # against the latest plist + venv state (the script just pip-installed
    # the plugin, the previously-loaded dashboard may not have seen it).
    # Both bootout failures (service wasn't loaded) and bootstrap fallbacks
    # to `load` are tolerated for backward compat with older launchctl.
    launchctl bootout "gui/$UID/${service}" 2>/dev/null || true
    launchctl bootstrap "gui/$UID" "$plist_dir/${service}.plist" 2>/dev/null || \
      launchctl load "$plist_dir/${service}.plist"
  done
  echo "✓ launchd plists installed: dev.myah.hermes-{gateway,dashboard}"
  echo "  Manage with: launchctl {kickstart -k|stop|print} gui/\$UID/dev.myah.hermes-{gateway,dashboard}"

  # Sanity-check the dashboard plugin actually mounted — the most
  # common silent failure mode after a fresh pip-install.
  local web_token
  web_token="$(get_var "$HERMES_ENV" HERMES_WEB_SESSION_TOKEN)"
  verify_dashboard_plugin_mounted "$web_token" || true
}

prompt_service_choice
case "$OSS_SERVICE_CHOICE" in
  systemd) install_systemd_units ;;
  launchd) install_launchd_plists ;;
  none)    echo "✓ Service install skipped — start manually via ./scripts/dev-oss.sh up" ;;
esac

# ─── 8. Port-conflict detection ─────────────────────────────────────
#
# Spec §4 promises this. We probe each port the OSS stack expects to
# bind and surface conflicts as warnings (NOT hard errors — the user
# may have a legitimate reason, e.g. the dashboard's already running
# under systemd from a previous setup run).

echo
echo "Probing default ports..."
for entry in \
    "8642:Hermes api_server" \
    "8643:Hermes gateway adapter" \
    "9119:Hermes dashboard" \
    "8080:Myah platform"; do
  port="${entry%%:*}"
  label="${entry#*:}"
  status="$(probe_loopback_port "$port")"
  if [[ "$status" = "free" ]]; then
    echo "  ✓ port $port ($label): free"
  else
    echo "  ⚠ port $port ($label): IN USE"
  fi
done
echo "If a port shows IN USE but you expected it free, run 'lsof -i:<port>'"
echo "to find the process. Override via env vars (MYAH_GATEWAY_PORT,"
echo "MYAH_HERMES_WEB_PORT, MYAH_HERMES_CHAT_PORT) in both .env files."

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
echo "       hermes gateway run --replace                  # foreground (replaces any existing gateway)"
echo "       ./scripts/dev-oss.sh up                       # systemd/launchd background (uses the unit installed above)"
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
