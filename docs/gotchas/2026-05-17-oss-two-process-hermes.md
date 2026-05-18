# OSS runs TWO Hermes processes — gateway AND dashboard

**Date discovered:** 2026-05-17
**Affected:** OSS variant (`MYAH_DEPLOYMENT_MODE=oss`); does not affect hosted

## The bug class

The platform forwards every provider/toolset/model request through
`web_call_or_raise` → `host.docker.internal:9119` → `hermes dashboard`.
In hosted mode every per-user agent container runs its own dashboard
inside the container. In OSS the dashboard runs on the host as a
SECOND Hermes process alongside `hermes gateway`.

If only one of the two processes is running, the OSS install presents
asymmetrically:
- Welcome screen says "OK" (probe goes through gateway runtime_admin)
- Settings page is blank / errors (router goes through dashboard)
- Add Provider button is non-functional

## Why this happens

Hermes's authors split provider configuration into the dashboard
plugin (`myah_admin/dashboard/`) deliberately. The gateway's
`runtime_admin` only exposes a read view (`GET /myah/v1/admin/providers`)
for liveness probes; writes + OAuth flow live in the dashboard plugin.

The platform uses the dashboard for both reads and writes (hosted/OSS
code parity); the probe uses runtime_admin for reads only (it's
liveness-tolerant). This asymmetry is intentional but easy to miss.

## How to detect

- `/api/v1/oss/probe` → `dashboard_running: false`
- Frontend shows `DashboardDownError.svelte`
- `./scripts/dev-oss.sh status` → dashboard row says `stopped`

## How to fix

- `./scripts/dev-oss.sh dashboard start`
- Or if systemd-user / launchd unit was installed: `systemctl --user
  start hermes-dashboard` / `launchctl kickstart -k gui/$UID/dev.myah.hermes-dashboard`

## How we prevent regression

- `pr-tests.yml::oss-e2e-shape` boots BOTH processes on every PR and
  asserts the full welcome → providers → chat path
- `dev-oss.sh status` exposes the running/not-running state explicitly
