#!/usr/bin/env bash
# scripts/setup-myah-oss.sh — one-shot OSS-mode bootstrap helper.
#
# Generates three shared secrets and writes them to the right .env file(s):
#
#   1. MYAH_AGENT_BEARER_TOKEN — agent ↔ platform shared bearer (both .envs)
#   2. OAUTH_SESSION_TOKEN_ENCRYPTION_KEY — Fernet-compatible encryption key
#      for the oauth_session table (platform .env; the backend crashes at
#      import time without it — oauth_sessions.py:72)
#   3. MYAH_SECRET_KEY — HMAC key for JWT session-cookie signing
#      (platform .env; an empty key triggers InsecureKeyLengthWarning from
#      python-jose and falls back to a zero-byte HMAC)
#
# Idempotent: a key that's already set keeps its value across re-runs;
# only missing keys are filled. The shared bearer is mirrored across both
# files when a value exists in only one. Pass --rotate to force fresh
# values for all three keys.
#
# Usage:  ./scripts/setup-myah-oss.sh
#         ./scripts/setup-myah-oss.sh --rotate    # force new keys
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PLATFORM_ENV="$ROOT/.env"
HERMES_ENV="${HERMES_HOME:-$HOME/.hermes}/.env"
ROTATE=0
[[ "${1:-}" == "--rotate" ]] && ROTATE=1

mkdir -p "$(dirname "$HERMES_ENV")"

# Read existing tokens (or empty) from both files
get_var() {
  local file="$1" var="$2"
  [[ -f "$file" ]] || { echo ""; return; }
  grep -E "^${var}=" "$file" 2>/dev/null | tail -n1 | cut -d= -f2- || true
}

set_var() {
  local file="$1" var="$2" val="$3"
  if [[ -f "$file" ]] && grep -qE "^${var}=" "$file"; then
    # Use a portable sed in-place: write to tmp + mv
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

# ─── 1. MYAH_AGENT_BEARER_TOKEN — shared bearer (both files) ──────────

PLATFORM_TOKEN="$(get_var "$PLATFORM_ENV" MYAH_AGENT_BEARER_TOKEN)"
HERMES_BEARER="$(get_var "$HERMES_ENV" MYAH_AGENT_BEARER_TOKEN)"
HERMES_API_KEY="$(get_var "$HERMES_ENV" API_SERVER_KEY)"

if [[ "$ROTATE" == 1 ]]; then
  TOKEN=""
elif [[ -n "$PLATFORM_TOKEN" && "$PLATFORM_TOKEN" == "$HERMES_BEARER" && "$PLATFORM_TOKEN" == "$HERMES_API_KEY" ]]; then
  echo "✓ MYAH_AGENT_BEARER_TOKEN: already aligned across both files"
  TOKEN="$PLATFORM_TOKEN"
else
  TOKEN="${PLATFORM_TOKEN:-${HERMES_BEARER:-${HERMES_API_KEY:-}}}"
fi

if [[ -z "$TOKEN" ]]; then
  TOKEN="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
  echo "✓ MYAH_AGENT_BEARER_TOKEN: generated (length=${#TOKEN})"
fi

set_var "$PLATFORM_ENV" MYAH_AGENT_BEARER_TOKEN "$TOKEN"
set_var "$HERMES_ENV"   MYAH_AGENT_BEARER_TOKEN "$TOKEN"
set_var "$HERMES_ENV"   API_SERVER_KEY          "$TOKEN"

# Set the suppressor vars on the hermes side (idempotent — only writes
# if missing).
#
# MYAH_HOME_CHAT is the canonical env var the gateway checks for the
# Myah platform's home channel (the plugin registers this as its
# cron_deliver_env_var in myah_platform/__init__.py:344). Without it,
# every new chat session emits a "📬 No home channel is set for Myah"
# warning. The legacy MYAH_HOME_CHANNEL name is also written for
# forward-compat — upstream's _home_target_env_var falls back to
# "<PLATFORM>_HOME_CHANNEL" if the plugin ever drops its registration.
# See docs/superpowers/plans/2026-05-11-no-fork-vendoring-respec.md (B1).
[[ -n "$(get_var "$HERMES_ENV" MYAH_ALLOW_ALL_USERS)" ]] || set_var "$HERMES_ENV" MYAH_ALLOW_ALL_USERS true
[[ -n "$(get_var "$HERMES_ENV" MYAH_HOME_CHAT)" ]]       || set_var "$HERMES_ENV" MYAH_HOME_CHAT       disabled
[[ -n "$(get_var "$HERMES_ENV" MYAH_HOME_CHANNEL)" ]]    || set_var "$HERMES_ENV" MYAH_HOME_CHANNEL    disabled

# ─── 2. OAUTH_SESSION_TOKEN_ENCRYPTION_KEY — platform-side Fernet key ─
#
# oauth_sessions.py raises Exception at module import time if this is
# unset (oauth_sessions.py:72), so a fresh OSS install crashes on first
# boot without it. Phase D finding D2 (docs/oss-launch/vm-testing-followups.md).

OAUTH_KEY="$(get_var "$PLATFORM_ENV" OAUTH_SESSION_TOKEN_ENCRYPTION_KEY)"
if [[ "$ROTATE" == 1 || -z "$OAUTH_KEY" ]]; then
  OAUTH_KEY="$(gen_key)"
  set_var "$PLATFORM_ENV" OAUTH_SESSION_TOKEN_ENCRYPTION_KEY "$OAUTH_KEY"
  echo "✓ OAUTH_SESSION_TOKEN_ENCRYPTION_KEY: generated"
else
  echo "✓ OAUTH_SESSION_TOKEN_ENCRYPTION_KEY: already set"
fi

# ─── 3. MYAH_SECRET_KEY — JWT/session HMAC key ────────────────────────
#
# Empty key triggers python-jose InsecureKeyLengthWarning ("HMAC key is
# 0 bytes long") and degrades session-cookie signing security. Phase D
# finding D10 (docs/oss-launch/vm-testing-followups.md). The back-compat
# shim in env.py:522 also accepts WEBUI_SECRET_KEY, but the canonical
# name to write is MYAH_SECRET_KEY.

SECRET_KEY="$(get_var "$PLATFORM_ENV" MYAH_SECRET_KEY)"
LEGACY_WEBUI_KEY="$(get_var "$PLATFORM_ENV" WEBUI_SECRET_KEY)"

if [[ "$ROTATE" == 1 ]]; then
  SECRET_KEY="$(gen_key)"
  set_var "$PLATFORM_ENV" MYAH_SECRET_KEY "$SECRET_KEY"
  echo "✓ MYAH_SECRET_KEY: rotated"
elif [[ -n "$SECRET_KEY" ]]; then
  echo "✓ MYAH_SECRET_KEY: already set"
elif [[ -n "$LEGACY_WEBUI_KEY" ]]; then
  # Pre-rename install — promote legacy WEBUI_SECRET_KEY value to the
  # canonical MYAH_SECRET_KEY slot (env.py treats them as aliases).
  set_var "$PLATFORM_ENV" MYAH_SECRET_KEY "$LEGACY_WEBUI_KEY"
  echo "✓ MYAH_SECRET_KEY: adopted from legacy WEBUI_SECRET_KEY"
else
  SECRET_KEY="$(gen_key)"
  set_var "$PLATFORM_ENV" MYAH_SECRET_KEY "$SECRET_KEY"
  echo "✓ MYAH_SECRET_KEY: generated"
fi

echo
echo "✓ Platform .env: $PLATFORM_ENV"
echo "✓ Hermes  .env: $HERMES_ENV"
echo
echo "Next steps:"
echo "  1. Edit ~/.hermes/.env and add your LLM provider API key"
echo "     (any one of: OPENROUTER_API_KEY, OPENAI_API_KEY, ANTHROPIC_API_KEY,"
echo "     KIMI_API_KEY, XAI_API_KEY, DEEPSEEK_API_KEY, ...)"
echo "  2. Start the Hermes HTTP API server:  hermes gateway run --replace &"
echo "  3. Bring up the platform:             docker compose up -d"
echo "  4. Open http://localhost:8080 (no sign-up needed — single-user OSS)"
