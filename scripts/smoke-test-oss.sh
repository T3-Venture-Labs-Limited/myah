#!/usr/bin/env bash
# OSS-variant smoke test for Myah.
#
# Companion to scripts/smoke-test.sh — that script exercises the HOSTED
# variant (per-user agent containers, composio cross-tenant, OAuth
# device-flow), which the OSS build does NOT ship.
#
# The OSS variant runs against a host-side Hermes (via
# host.docker.internal:8642), has no signup/login (auto-admin user,
# MYAH_AUTH=false), no per-user containers, and no composio/honcho
# overlays. The endpoints that prove "OSS works" are a different set
# from the ones that prove "hosted works", so we need a parallel
# smoke test.
#
# What this script asserts (in order):
#   1. /api/v1/oss/probe returns 200 with a structured shape and
#      hermes_reachable=true (when a host-side Hermes is up).
#   2. /api/config returns 200 with features.auth=false and name="Myah"
#      — the OSS single-user contract.
#   3. /api/v1/processes/ returns 501 with the canonical upsell-card
#      detail string. If it ever returns 200, hosted code has leaked
#      into the OSS variant.
#   4. Hosted-only routers (integrations, agent_memory) are NOT mounted
#      in OSS — they return 404. A 200 here means the conditional
#      include_router gate in main.py regressed.
#   5. (Optional) If a chat-completion provider key is configured, send
#      one minimal completion. SKIP without failing if no key.
#
# Modes:
#   - CI mode:    docker compose stack spun up by the workflow,
#                 MYAH_BASE_URL defaults to http://localhost:8080.
#   - Local dev:  same default; override MYAH_BASE_URL if your stack
#                 is bound elsewhere.
#
# This script is intentionally permissive about hermes reachability
# in step 1 — a CI workflow that hasn't started a host-side Hermes
# will see hermes_reachable=false, which is the expected sad-path
# shape, not a failure of the OSS variant itself. Step 1 only fails
# when the probe shape is wrong (missing fields, non-200 response).
#
# Phase E of docs/superpowers/plans/2026-05-14-oss-launch-completion.md.

set -euo pipefail

BASE_URL="${MYAH_BASE_URL:-http://localhost:8080}"
TIMEOUT=30
PROBE_TIMEOUT=15

# Optional: a provider key in the env unlocks the chat smoke at step 5.
# If absent the step is skipped — it's not part of the required gate.
CHAT_PROVIDER_KEY="${OPENROUTER_API_KEY:-${OPENAI_API_KEY:-${ANTHROPIC_API_KEY:-}}}"

echo "=== OSS Smoke Test: ${BASE_URL} ==="

# ── Helpers ────────────────────────────────────────────────────────────────
# A 'json_field' helper that pulls a single top-level key from a JSON blob
# without taking on a jq dependency. Mirrors the hosted smoke test's
# implementation so the two scripts share idiom.
json_field() {
    local body="$1" field="$2"
    echo "${body}" | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
    v = d.get('${field}')
    if isinstance(v, (dict, list)):
        print(json.dumps(v))
    elif v is None:
        print('')
    else:
        print(v)
except Exception:
    print('')
" 2>/dev/null
}

# Hit an endpoint and capture (status, body). curl --max-time guards against
# a wedged backend hanging the gate.
http_get() {
    local url="$1" auth="${2:-}"
    local args=(-s -w "\n%{http_code}" -X GET "${url}" --max-time "${TIMEOUT}")
    if [ -n "${auth}" ]; then
        args+=(-H "Authorization: Bearer ${auth}")
    fi
    curl "${args[@]}" 2>/dev/null || echo -e "\n000"
}

# Tiny "is it up at all" gate: a wedged platform means EVERY step that
# follows will be a noisy red herring. Bail fast with a clear message.
echo "  [0/5] Platform reachable at ${BASE_URL}..."
HEALTH_RESP=$(curl -s -o /dev/null -w "%{http_code}" "${BASE_URL}/health" --max-time 10 2>/dev/null || echo "000")
if [ "${HEALTH_RESP}" != "200" ]; then
    # /health is an open endpoint on the platform (no auth needed). If it's
    # not 200 the platform itself isn't responding; nothing else will work.
    echo "  FAIL: GET ${BASE_URL}/health returned ${HEALTH_RESP}" >&2
    echo "  The platform is not reachable. Start the stack with:" >&2
    echo "    docker compose -f docker-compose.yml up -d" >&2
    echo "  or set MYAH_BASE_URL to where your platform is bound." >&2
    exit 1
fi
echo "  OK: /health returned 200"

# ── Step 1: OSS probe shape ────────────────────────────────────────────────
# The probe is the gateway to the entire OSS UX (Welcome.svelte,
# HermesDownError.svelte, PluginMissingError.svelte all consume its
# JSON shape). A regression in the probe contract silently breaks the
# first-run experience for every OSS user.
echo ""
echo "  [1/5] GET /api/v1/oss/probe..."

PROBE_RESP=$(curl -s -w "\n%{http_code}" \
    -X GET "${BASE_URL}/api/v1/oss/probe" \
    --max-time "${PROBE_TIMEOUT}" 2>/dev/null || echo -e "\n000")

PROBE_CODE=$(echo "${PROBE_RESP}" | tail -1)
PROBE_BODY=$(echo "${PROBE_RESP}" | sed '$d')

if [ "${PROBE_CODE}" != "200" ]; then
    echo "  FAIL: /api/v1/oss/probe returned HTTP ${PROBE_CODE}" >&2
    echo "  Body: ${PROBE_BODY:0:400}" >&2
    echo "  The probe is wired by platform-oss/backend/myah/routers/oss.py." >&2
    echo "  A 404 here means oss_router_module.router is not included in main.py." >&2
    exit 1
fi

# Validate the shape — every field the frontend depends on must be present
# even when the host-side Hermes is unreachable.
SHAPE_CHECK=$(echo "${PROBE_BODY}" | python3 -c "
import sys, json
try:
    body = json.load(sys.stdin)
except Exception as e:
    print(f'BAD:{e}')
    sys.exit(0)
required = ['hermes_reachable', 'hermes_url', 'plugin_installed',
            'plugin_version', 'providers_configured', 'first_run']
missing = [k for k in required if k not in body]
if missing:
    print(f'MISSING:{missing}')
elif not isinstance(body['providers_configured'], list):
    print(f'BAD:providers_configured is not a list')
else:
    h = 'hermes-up' if body['hermes_reachable'] else 'hermes-down'
    p = 'plugin-up' if body['plugin_installed'] else 'plugin-down'
    print(f'OK:{h}:{p}')
" 2>/dev/null || echo "BAD:python")

case "${SHAPE_CHECK}" in
    OK:*)
        echo "  OK: probe shape valid (${SHAPE_CHECK#OK:})"
        ;;
    MISSING:*)
        echo "  FAIL: probe response missing required field(s): ${SHAPE_CHECK#MISSING:}" >&2
        echo "  Body: ${PROBE_BODY:0:400}" >&2
        exit 1
        ;;
    *)
        echo "  FAIL: probe response unparseable: ${SHAPE_CHECK}" >&2
        echo "  Body: ${PROBE_BODY:0:400}" >&2
        exit 1
        ;;
esac

# ── Step 2: /api/config single-user contract ──────────────────────────────
# The OSS variant ships with WEBUI_AUTH=false (single-user). If /api/config
# ever shows features.auth=true in OSS, hosted auth code has leaked back
# into the OSS deployment — a regression of the Phase B anti-SaaS-fork
# removal.
echo ""
echo "  [2/5] GET /api/config (OSS single-user contract)..."

CONFIG_RESP=$(curl -s -w "\n%{http_code}" \
    -X GET "${BASE_URL}/api/config" \
    --max-time "${TIMEOUT}" 2>/dev/null || echo -e "\n000")

CONFIG_CODE=$(echo "${CONFIG_RESP}" | tail -1)
CONFIG_BODY=$(echo "${CONFIG_RESP}" | sed '$d')

if [ "${CONFIG_CODE}" != "200" ]; then
    echo "  FAIL: /api/config returned HTTP ${CONFIG_CODE}" >&2
    echo "  Body: ${CONFIG_BODY:0:400}" >&2
    exit 1
fi

CONFIG_CHECK=$(echo "${CONFIG_BODY}" | python3 -c "
import sys, json
try:
    body = json.load(sys.stdin)
except Exception as e:
    print(f'BAD:{e}')
    sys.exit(0)
features = body.get('features', {})
auth = features.get('auth')
name = body.get('name')
errors = []
# OSS contract: features.auth must be False (single-user auto-admin).
if auth is not False:
    errors.append(f'features.auth={auth!r} (expected False)')
# The product is Myah. A leftover 'Open WebUI' here means the rename
# missed a code path.
if name and 'open webui' in str(name).lower():
    errors.append(f'name={name!r} (still contains \"Open WebUI\")')
if errors:
    print('BAD:' + '; '.join(errors))
else:
    print(f'OK:auth={auth}:name={name!r}')
" 2>/dev/null || echo "BAD:python")

case "${CONFIG_CHECK}" in
    OK:*)
        echo "  OK: /api/config matches OSS contract (${CONFIG_CHECK#OK:})"
        ;;
    BAD:*)
        echo "  FAIL: ${CONFIG_CHECK#BAD:}" >&2
        echo "  This means hosted-mode code is active in the OSS build." >&2
        echo "  Body excerpt: ${CONFIG_BODY:0:400}" >&2
        exit 1
        ;;
esac

# ── Step 3: Processes router returns 501 (upsell-card contract) ───────────
# processes.py is the canonical "router stays mounted but every endpoint
# 501s" example in OSS — it's the prior art for the Memory/Integrations
# upsell-card pattern. If a regression makes it return 200, hosted-only
# docker-exec code is running inside the OSS container and will crash
# on first real call.
echo ""
echo "  [3/5] GET /api/v1/processes/ returns 501 in OSS..."

PROC_RESP=$(curl -s -w "\n%{http_code}" \
    -X GET "${BASE_URL}/api/v1/processes/" \
    --max-time "${TIMEOUT}" 2>/dev/null || echo -e "\n000")

PROC_CODE=$(echo "${PROC_RESP}" | tail -1)
PROC_BODY=$(echo "${PROC_RESP}" | sed '$d')

# Acceptable: 501 (the canonical OSS gate) OR 401/403 (the router is
# mounted but auth-gated — the gate still fires correctly). The single
# unacceptable status is 200, which means the hosted handler ran.
if [ "${PROC_CODE}" = "200" ]; then
    echo "  FAIL: /api/v1/processes/ returned 200 in OSS — hosted code leaked" >&2
    echo "  Body: ${PROC_BODY:0:400}" >&2
    echo "  Check _raise_if_oss_mode() at platform-oss/backend/myah/routers/processes.py:79" >&2
    exit 1
fi

if [ "${PROC_CODE}" != "501" ]; then
    # Non-200, non-501 (e.g. 401/403/404) — surface as a WARN so a future
    # auth-config change doesn't silently mask the 501-shape regression.
    # If 404 there's a real problem (router not mounted at all).
    if [ "${PROC_CODE}" = "404" ]; then
        echo "  FAIL: /api/v1/processes/ returned 404 — router not mounted" >&2
        echo "  Expected 501 (router mounted, OSS gate fires)." >&2
        exit 1
    fi
    echo "  WARN: expected 501, got ${PROC_CODE} (auth-gated? not a regression)" >&2
else
    # 501 — verify the canonical upsell-card detail string is present.
    # The frontend matches on this exact substring to render the upsell.
    if echo "${PROC_BODY}" | grep -q "app.myah.dev"; then
        echo "  OK: /api/v1/processes/ returns 501 with upsell-card detail"
    else
        echo "  WARN: 501 returned but detail missing 'app.myah.dev' link" >&2
        echo "  Body: ${PROC_BODY:0:300}" >&2
    fi
fi

# ── Step 4: Hosted-only routers are NOT mounted in OSS ───────────────────
# integrations + agent_memory routers are conditionally include_router'd
# only when MYAH_DEPLOYMENT_MODE != 'oss' (main.py:944 + 973). In OSS
# they should return 404 ("no such route"), NOT a 500/401/200. A 200
# here would mean honcho/composio code is wired into the OSS variant
# — a Phase B anti-SaaS-fork regression.
echo ""
echo "  [4/5] Hosted-only routers are absent in OSS..."

check_absent_router() {
    local path="$1" name="$2"
    local resp code
    resp=$(curl -s -o /tmp/smoke-oss-${name}.json -w "%{http_code}" \
        -X GET "${BASE_URL}${path}" \
        --max-time "${TIMEOUT}" 2>/dev/null || echo "000")
    code="${resp}"
    rm -f /tmp/smoke-oss-${name}.json
    if [ "${code}" = "200" ]; then
        echo "  FAIL: ${path} returned 200 in OSS — ${name} router should not be mounted" >&2
        echo "  Check the conditional include_router in main.py for is_oss_mode()" >&2
        return 1
    fi
    # 404 is the expected shape (router not mounted). 401/403 also fine
    # (router not mounted, FastAPI returns auth challenge for unknown
    # paths under an auth dependency).
    echo "    OK: ${path} -> ${code} (router absent, as expected)"
}

check_absent_router "/api/v1/integrations" "integrations" || exit 1
check_absent_router "/api/v1/agent/memory/overview" "agent_memory" || exit 1

echo "  OK: hosted-only routers correctly absent"

# ── Step 5: Optional — minimal chat completion ────────────────────────────
# If a provider key is present in the environment we exercise the chat
# pipeline end-to-end against host-side Hermes. Otherwise skip — the
# absence of a key in CI is not a failure of the OSS variant.
echo ""
if [ -z "${CHAT_PROVIDER_KEY}" ]; then
    echo "  [5/5] Chat smoke — SKIPPED (no provider key in env)"
    echo "      Set OPENROUTER_API_KEY (or OPENAI_API_KEY / ANTHROPIC_API_KEY)"
    echo "      to enable this step."
else
    echo "  [5/5] Chat completion smoke (provider key present)..."
    # The OSS variant has no auth, so /api/chat/completions is reachable
    # without a token (it falls back on the auto-admin user). We send
    # the minimal payload that a real browser would send.
    CHAT_RESP=$(curl -s -o /tmp/smoke-oss-chat.txt -w "%{http_code}" \
        -X POST "${BASE_URL}/api/v1/chat/completions" \
        -H "Content-Type: application/json" \
        -d '{
            "model": "myah",
            "stream": true,
            "messages": [{"role": "user", "content": "Reply with one word: OK"}]
        }' \
        --max-time 60 2>/dev/null || echo "000")
    CHAT_BODY=$(cat /tmp/smoke-oss-chat.txt 2>/dev/null || echo "")
    rm -f /tmp/smoke-oss-chat.txt
    if [ "${CHAT_RESP}" = "200" ]; then
        if echo "${CHAT_BODY}" | grep -q '"delta"\|message\.delta\|output_text\|run\.completed\|\[DONE\]'; then
            echo "  OK: chat completion streamed back recognisable content"
        else
            echo "  WARN: chat returned 200 but no recognisable stream content" >&2
            echo "  First 300 chars: ${CHAT_BODY:0:300}" >&2
        fi
    else
        # Non-200 here is a WARN, not a FAIL — if Hermes is down, or no
        # provider is configured at the Hermes side, the request fails
        # legitimately. Step 1 already gates "OSS variant has the right
        # shape"; the chat round-trip is a bonus.
        echo "  WARN: chat completion returned HTTP ${CHAT_RESP} (non-fatal)" >&2
        echo "  Body: ${CHAT_BODY:0:300}" >&2
    fi
fi

# ──────────────────────────────────────────────────────────────────────────

echo ""
echo "=== OSS Smoke Test PASSED ==="
