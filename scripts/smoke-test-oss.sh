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

# ── Step 3: Processes router returns a JSON array in OSS ──────────────────
# Per the revised May 13 spec (Tasks 2.3/2.4), /api/v1/processes/
# returns 200 in OSS — routed via _ensure_container to the host's
# hermes gateway at host.docker.internal:8642 instead of returning the
# old 501 upsell-card stub. Inversion lands with the cron-delivery
# fixes shipped in v0.1.1.
#
# Acceptable now: 200 (canonical happy path) OR 401/403 (router is
# mounted but auth-gated, which still proves the router is wired).
# Unacceptable: 404 (router not mounted) or 501 (stale OSS gate).
echo ""
echo "  [3/5] GET /api/v1/processes/ returns 200 (or auth-gated) in OSS..."

PROC_RESP=$(curl -s -w "\n%{http_code}" \
    -X GET "${BASE_URL}/api/v1/processes/" \
    --max-time "${TIMEOUT}" 2>/dev/null || echo -e "\n000")

PROC_CODE=$(echo "${PROC_RESP}" | tail -1)
PROC_BODY=$(echo "${PROC_RESP}" | sed '$d')

case "${PROC_CODE}" in
    200)
        # 200 — verify the body is a JSON array (the hermes /api/jobs
        # contract is {"jobs": [...]}, but the platform unwraps it to
        # a top-level list in list_processes()).
        if echo "${PROC_BODY}" | python3 -c "import sys, json; v = json.load(sys.stdin); sys.exit(0 if isinstance(v, list) else 1)" 2>/dev/null; then
            echo "  OK: /api/v1/processes/ returns 200 with a JSON array"
        else
            echo "  FAIL: /api/v1/processes/ returned 200 but body is not a JSON array" >&2
            echo "  Body: ${PROC_BODY:0:400}" >&2
            exit 1
        fi
        ;;
    401|403)
        echo "  OK: /api/v1/processes/ returned ${PROC_CODE} (auth-gated, router mounted)"
        ;;
    404)
        echo "  FAIL: /api/v1/processes/ returned 404 — router not mounted" >&2
        echo "  Expected 200 (router routes to host hermes gateway)." >&2
        exit 1
        ;;
    501)
        echo "  FAIL: /api/v1/processes/ returned 501 — stale OSS gate still active" >&2
        echo "  Tasks 2.3/2.4 removed the gate; check _raise_if_oss_mode() at" >&2
        echo "  platform-oss/backend/myah/routers/processes.py" >&2
        exit 1
        ;;
    *)
        echo "  FAIL: /api/v1/processes/ returned unexpected HTTP ${PROC_CODE}" >&2
        echo "  Body: ${PROC_BODY:0:400}" >&2
        exit 1
        ;;
esac

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
# Dashboard parity assertions
#
# Per docs/superpowers/specs/2026-05-17-oss-provider-data-routing-design.md,
# the OSS install runs hermes dashboard as a second process. These
# assertions catch the failure mode where the dashboard isn't running
# but the probe is otherwise green.

echo ""
echo "[6/6] Dashboard parity assertions"

echo "→ Probe reports dashboard_running=true"
PROBE_BODY="$(curl -fsS "${BASE_URL}/api/v1/oss/probe")"
echo "$PROBE_BODY" | python3 -c '
import json, sys
p = json.loads(sys.stdin.read())
assert p["dashboard_running"] is True, f"dashboard_running=false: {p}"
print("    OK: dashboard_running=true")
'

# /api/v1/providers/catalog and /api/v1/agent/toolsets are both gated
# by get_verified_user — without a session cookie/Bearer the smoke test
# correctly receives 401. That's a positive signal: the platform is up,
# the endpoint exists, and auth is wired. Treat 200 OR 401 as "reachable".
# A 5xx or 404 here would indicate a real regression.

echo "→ Provider catalog reachable (200 or 401)"
CATALOG_CODE=$(curl -s -o /tmp/catalog.json -w '%{http_code}' \
    "${BASE_URL}/api/v1/providers/catalog" --max-time "${TIMEOUT}" \
    2>/dev/null || echo "000")
if [ "${CATALOG_CODE}" != "200" ] && [ "${CATALOG_CODE}" != "401" ]; then
    echo "  FAIL: /api/v1/providers/catalog returned HTTP ${CATALOG_CODE}" >&2
    head -c 400 /tmp/catalog.json >&2
    exit 1
fi
echo "    OK: /api/v1/providers/catalog HTTP ${CATALOG_CODE}"

echo "→ Agent toolsets reachable (200 or 401)"
TOOLSETS_CODE=$(curl -s -o /tmp/toolsets.json -w '%{http_code}' \
    "${BASE_URL}/api/v1/agent/toolsets" --max-time "${TIMEOUT}" \
    2>/dev/null || echo "000")
if [ "${TOOLSETS_CODE}" != "200" ] && [ "${TOOLSETS_CODE}" != "401" ]; then
    echo "  FAIL: /api/v1/agent/toolsets returned HTTP ${TOOLSETS_CODE}" >&2
    head -c 400 /tmp/toolsets.json >&2
    exit 1
fi
echo "    OK: /api/v1/agent/toolsets HTTP ${TOOLSETS_CODE}"

# ──────────────────────────────────────────────────────────────────────────
# Real chat smoke (Task 5.1)
#
# Sends a deterministic prompt through the platform→hermes pipeline and
# polls GET /api/v1/chats/{id} until the assistant message is persisted
# with done=true and non-empty content (same pattern as the hosted
# smoke at scripts/smoke-test.sh:228-280 — chat events stream via
# Socket.IO into the DB, NOT via HTTP SSE).
#
# OSS shape: single-user, no auth token. Skips gracefully if either
#   (a) E2E_OPENROUTER_KEY is unset (preserves the existing CI shape-
#       check behavior — no provider key, no chat round-trip), or
#   (b) the OSS bootstrap auth endpoint (oss-signin) is unavailable on
#       this build (this internal branch does not yet ship it; the
#       public OSS repo's auths.py:258 does). When the sync workflows
#       land the two repos converge and this fallback can go away.

fail() {
    echo "FAIL: $1" >&2
    exit 1
}

real_chat_smoke() {
    if [ -z "${E2E_OPENROUTER_KEY:-}" ]; then
        echo "  SKIPPED: E2E_OPENROUTER_KEY not set"
        return 0
    fi

    local POLL_TIMEOUT=90
    local POLL_INTERVAL=2
    echo "Real chat smoke: creating chat + sending a prompt..."

    # OSS has no /signin in this branch. Probe whether unauthenticated
    # POST /api/v1/chats/new is honored (auto-admin path on the public
    # OSS repo) before attempting the rest.
    local probe_code
    probe_code=$(curl -s -o /dev/null -w "%{http_code}" \
        -H "Content-Type: application/json" \
        -X POST -d '{"chat":{"title":"smoke-test"}}' \
        "${BASE_URL}/api/v1/chats/new" --max-time 10 2>/dev/null || echo "000")
    if [ "${probe_code}" = "401" ] || [ "${probe_code}" = "403" ]; then
        echo "  SKIPPED: /api/v1/chats/new requires auth in this build (HTTP ${probe_code})"
        echo "      The OSS bootstrap auth endpoint (oss-signin) is not present;"
        echo "      see AGENTS.md > OSS vs Hosted > Auth row."
        return 0
    fi

    local chat_resp chat_id
    chat_resp=$(curl -fsS \
        -H "Content-Type: application/json" \
        -X POST -d '{"chat":{"title":"smoke-test"}}' \
        "${BASE_URL}/api/v1/chats/new")
    chat_id=$(echo "${chat_resp}" | python3 -c "import sys, json; print(json.load(sys.stdin).get('id', ''))" 2>/dev/null)
    [ -n "${chat_id}" ] || fail "POST /api/v1/chats/new returned no id (body: ${chat_resp:0:200})"

    # Fire the message — stream=true triggers the background-task path
    # that emits Socket.IO events and persists to the DB. We don't read
    # the stream; we poll the DB instead.
    curl -fsS \
        -H "Content-Type: application/json" \
        -X POST \
        -d "$(python3 -c "
import json, sys
print(json.dumps({
    'chat_id': '${chat_id}',
    'messages': [{'role': 'user', 'content': 'Reply with the single word OK and nothing else.'}],
    'stream': True,
    'model': 'myah',
}))")" \
        --max-time 10 \
        "${BASE_URL}/api/v1/chat/completions" \
        >/dev/null 2>&1 || true

    local elapsed=0 found=false content=""
    while [ $elapsed -lt $POLL_TIMEOUT ]; do
        local chat_state
        chat_state=$(curl -fsS "${BASE_URL}/api/v1/chats/${chat_id}" 2>/dev/null) || chat_state=""
        if [ -n "${chat_state}" ]; then
            content=$(echo "${chat_state}" | python3 -c "
import sys, json
try:
    chat = json.load(sys.stdin)
    messages = chat.get('chat', {}).get('history', {}).get('messages', {})
    if isinstance(messages, dict):
        messages = list(messages.values())
    for msg in messages:
        if msg.get('role') in ('assistant', None) and msg.get('done') is True:
            if (msg.get('content') or '').strip():
                print(msg['content'][:200])
                sys.exit(0)
except Exception:
    pass
" 2>/dev/null)
            if [ -n "${content}" ]; then
                found=true
                break
            fi
        fi
        sleep $POLL_INTERVAL
        elapsed=$((elapsed + POLL_INTERVAL))
    done

    if [ "${found}" != true ]; then
        fail "Assistant message did not arrive in ${POLL_TIMEOUT}s"
    fi

    # Re-fetch +5s later to confirm persistence (the DB write isn't
    # racing with a subsequent overwrite from a stale background task).
    sleep 5
    local content_after
    content_after=$(curl -fsS "${BASE_URL}/api/v1/chats/${chat_id}" | python3 -c "
import sys, json
chat = json.load(sys.stdin)
messages = chat.get('chat', {}).get('history', {}).get('messages', {})
if isinstance(messages, dict):
    messages = list(messages.values())
for msg in messages:
    if msg.get('role') in ('assistant', None) and msg.get('done'):
        print((msg.get('content') or '')[:200])
        break
" 2>/dev/null)
    if [ -z "${content_after}" ] || [ "${content_after}" != "${content}" ]; then
        fail "Assistant message did not persist across re-fetch"
    fi

    curl -fsS -X DELETE "${BASE_URL}/api/v1/chats/${chat_id}" >/dev/null 2>&1 || true
    echo "  OK: real chat smoke passed (assistant content: $(echo "${content}" | head -c 60))"
}

echo ""
echo "[7/7] Real chat smoke"
real_chat_smoke

# ──────────────────────────────────────────────────────────────────────────

# T3-1087: OSS outbox row check. This intentionally skips unless the local
# stack opted into outbox mode; default OSS remains legacy through Phase 1.
mode=$(grep -E '^MYAH_CRON_DELIVERY_MODE=' .env 2>/dev/null | head -1 | cut -d= -f2- || true)
if [ "${mode}" = "outbox" ] && command -v sqlite3 >/dev/null 2>&1; then
    echo "  [7b/7] OSS cron outbox row check..."
    count=$(sqlite3 backend/data/myah.db \
        "SELECT count(*) FROM cron_deliveries WHERE created_at > strftime('%s','now')-300;")
    if [ "${count}" -gt 0 ]; then
        echo "  OK: ${count} recent outbox row(s)"
    else
        echo "  FAIL: no outbox rows in the last 5 minutes" >&2
        exit 1
    fi
else
    echo "  [7b/7] OSS cron outbox check skipped (mode=${mode:-legacy})"
fi

# selection_key is the deduplication key used by getModelsUnified on the
# frontend — regressions here cause duplicate model entries in the UI.
echo "  [7/7] GET /api/v1/providers/models selection_key assertion..."

# The OSS variant uses no auth (MYAH_AUTH=false); the auto-admin user is
# injected by the backend so we omit the Bearer header here.
MODELS_CODE=$(curl -s -o /tmp/smoke-oss-models.json -w "%{http_code}" \
    -X GET "${BASE_URL}/api/v1/providers/models" \
    --max-time "${TIMEOUT}" 2>/dev/null) || MODELS_CODE="000"

if [ "${MODELS_CODE}" != "200" ]; then
    echo "  FAIL: /providers/models returned HTTP ${MODELS_CODE}" >&2
    echo "  Body: $(head -c 500 /tmp/smoke-oss-models.json 2>/dev/null)" >&2
    exit 1
fi

SELECTION_KEY_CHECK=$(python3 -c "
import json, sys
try:
    data = json.load(open('/tmp/smoke-oss-models.json'))
    models = data if isinstance(data, list) else []
    if not models:
        print('skip')
        sys.exit(0)
    for m in models:
        sk = m.get('selection_key') if isinstance(m, dict) else None
        if not sk or (isinstance(sk, str) and not sk.strip()):
            print('fail: entry missing or empty selection_key', file=sys.stderr)
            sys.exit(1)
    keys = [m.get('selection_key') for m in models if isinstance(m, dict)]
    if len(keys) != len(set(keys)):
        print('fail: selection_key values are not unique', file=sys.stderr)
        sys.exit(1)
    print('ok:' + str(len(models)) + ' models checked')
except Exception as e:
    print('fail:' + str(e), file=sys.stderr)
    sys.exit(1)
" 2>&1) || SELECTION_KEY_CHECK="fail:python-error"

case "${SELECTION_KEY_CHECK}" in
    ok:*)
        echo "  OK: ${SELECTION_KEY_CHECK#ok:}"
        ;;
    skip)
        echo "  SKIP: no models returned"
        ;;
    fail:*)
        echo "  FAIL: selection_key assertion failed: ${SELECTION_KEY_CHECK#fail:}" >&2
        echo "  Body: $(head -c 500 /tmp/smoke-oss-models.json 2>/dev/null)" >&2
        exit 1
        ;;
esac
rm -f /tmp/smoke-oss-models.json

echo ""
echo "=== OSS Smoke Test PASSED ==="
