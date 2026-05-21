# OSS Hermes gateway refuses non-loopback binding without `API_SERVER_KEY`

**Date discovered:** 2026-05-19
**Affected:** OSS variant (`MYAH_DEPLOYMENT_MODE=oss`); does not affect hosted
**Status:** Mitigated by `setup-myah-oss.sh` writing `API_SERVER_KEY` +
`API_SERVER_ENABLED=true` by default. Symptom can recur if the user
manually deletes those vars from `~/.hermes/.env`.

## Symptom

The platform's job-listing call (`GET {gateway}/api/jobs`, triggered
whenever the user opens the Processes tab or whenever cron delivery
needs to resolve the job's owner) hangs until timeout or returns
`401 Unauthorized`. The Processes UI shows the loading spinner
indefinitely, or — after the platform's HTTP timeout fires — renders
a generic "Could not load jobs" toast.

In `~/.hermes/.dev-oss/gateway.log` (or `journalctl --user -u
hermes-gateway` if you've installed the systemd unit) you'll see one
of:

- `Refusing to bind --host 0.0.0.0 without API_SERVER_KEY set —
  exiting` (gateway never starts; port 8642 stays closed)
- `Refusing /v1/runs request without bearer auth` (gateway started
  but rejected the request)

Live chat is unaffected because the chat path goes through the Myah
plugin's `/myah/v1/*` routes (port 8643), which use a separate auth
key (`MYAH_ADAPTER_AUTH_KEY`).

## Detection

```bash
grep -E '^(API_SERVER_KEY|API_SERVER_ENABLED)=' ~/.hermes/.env
```

If either is missing, or `API_SERVER_KEY` is empty, you've hit this.

`scripts/dev-oss.sh doctor` doesn't currently surface this directly
(it checks `MYAH_AGENT_BEARER_TOKEN` alignment, which is closely
related but not the same env var). A future check could probe
`curl -sf http://localhost:8642/health` and report.

## Root cause

Upstream Hermes's `api_server.py` enforces a startup check: if the
gateway is configured to bind to any non-loopback host (including
`0.0.0.0`, which is the default when the platform runs in docker and
needs to reach the gateway via `host.docker.internal`) AND
`API_SERVER_KEY` is unset, the gateway refuses to start. This is a
defense-in-depth measure: an unauthed `/v1/runs` endpoint reachable
from the LAN would let any attacker spend the user's LLM provider
budget.

`API_SERVER_ENABLED=true` is also required because the `/v1/runs`
adapter is opt-in — it's the surface the platform uses for raw runs
(smoke tests, admin tools), not the main chat path.

`setup-myah-oss.sh` writes both values during normal setup. The
gotcha is that they're easy to lose:

- User edits `~/.hermes/.env` manually (e.g. rotating other secrets)
  and accidentally deletes the lines
- User restores a backup of an older `~/.hermes/.env` from before
  the Myah install
- A future OSS upgrade changes the env var name and the old name
  lingers stale (no example of this happening yet, but it's the
  most likely future breakage shape)

## Fix

Re-run `setup-myah-oss.sh` — it's idempotent and will re-assert both
values. If you want to do it manually:

```bash
# Reuse the existing bearer token (must match MYAH_AGENT_BEARER_TOKEN)
BEARER=$(grep '^MYAH_AGENT_BEARER_TOKEN=' ~/.hermes/.env | cut -d= -f2-)
echo "API_SERVER_KEY=$BEARER"         >> ~/.hermes/.env
echo "API_SERVER_ENABLED=true"        >> ~/.hermes/.env
./scripts/dev-oss.sh restart
```

If you have NO bearer token at all (truly empty `~/.hermes/.env`),
re-run `setup-myah-oss.sh` to bootstrap from scratch.

## Prevention

- `scripts/setup-myah-oss.sh` writes both vars unconditionally during
  the bearer-token alignment step (line ~226 and the
  `API_SERVER_ENABLED` block at line ~230)
- The script's banner comment (line 19-20) calls out both vars
  explicitly so a human editor knows they're load-bearing
- `scripts/dev-oss.sh doctor` could grow a `curl -sf
  http://localhost:8642/health` check that surfaces "gateway not
  reachable" with a hint about `API_SERVER_KEY` (deferred — file a
  follow-up if hit in production again)

## Related code

- `scripts/setup-myah-oss.sh:226` — `set_var API_SERVER_KEY`
- `scripts/setup-myah-oss.sh:230-231` — `set_var API_SERVER_ENABLED`
- Upstream Hermes: `hermes_agent/api_server.py` — the startup binding
  check (line numbers drift; grep for "Refusing to bind" or
  "API_SERVER_KEY")

## Related issues

- VM-testing followup: Processes tab hangs (2026-05-18)
- Companion gotcha: `2026-05-19-oss-cron-platform-base-url-drift.md`
  (different env var, same diagnosis-pain class)
