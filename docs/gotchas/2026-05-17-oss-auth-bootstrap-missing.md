# OSS first-run has no path to issue the seed user's initial JWT

**Date discovered:** 2026-05-17 (during VM testing of `feat/oss-dashboard-topology`)
**Affected:** OSS variant (`MYAH_DEPLOYMENT_MODE=oss` + `MYAH_AUTH=false`) — ALL fresh installs
**Severity:** CRITICAL — a fresh OSS install cannot authenticate the seed user; the SPA bootstrap loop is stuck forever.

## The bug class

`platform-oss/backend/myah/routers/auths.py` only exposes three routes:

```python
@router.get('/', response_model=SessionUserInfoResponse)       # requires get_current_user
@router.post('/update/profile', response_model=...)            # requires get_verified_user
@router.post('/update/timezone')                                # requires get_verified_user
```

The multi-user surface (`signin`, `signup`, `signout`, `add_user`, `token_exchange`, ...) was surgically removed in Phase 1B of the OSS launch (anti-SaaS hardening, spec `2026-05-13-myah-oss-v0.1.0-launch-design.md` §6). Nothing replaced the signin path. The seed user is INSERTED by the `oss_seed_user` migration (`d5e3b1a9c742`) — `id=00000000-0000-0000-0000-000000000001`, `email=user@localhost`, `role=admin` — but no code path issues a JWT for them.

`get_current_user` (`platform-oss/backend/myah/utils/auth.py:196`) requires a Bearer token (or cookie / `request.state.token`). When all three are absent it raises `401 Not authenticated`. There is no `MYAH_AUTH=false` short-circuit that creates a session for the seed user.

`+layout.svelte` initialises by calling `getSessionUser(localStorage.token)` (line 183). On a fresh install:
- `localStorage.token` is `undefined`
- The backend returns 401
- The layout's catch path tries `goto('/auth')`
- `/auth/+page.svelte` for OSS is a 5-line stub that immediately `goto('/')`s back to the layout
- The layout retries, 401 again, redirect again, infinite stall

Symptom in the browser console (verified during testing):
```
[warning] No token found in localStorage after waiting, user-join not emitted
[warning] No token found in localStorage after waiting, user-join not emitted
...
```

The DOM renders nothing past the SvelteKit shell. `getText body` returns just the page title "Myah".

## Why this has been latent since the OSS launch

This bug shipped with v0.1.0-beta.1 on 2026-05-13. The team didn't catch it because of the bug documented in `2026-05-17-oss-public-deployment-mode-not-baked.md` — the OSS state machine was being silently bypassed because `PUBLIC_DEPLOYMENT_MODE` wasn't in the Vite build, so on fresh installs the layout was falling through to the **hosted** code path which renders the same `Connect a provider` screen regardless of OSS state. Once that Dockerfile bug is fixed (in this PR), the OSS gate fires and the auth bootstrap gap becomes visible.

Existing OSS installs (including the one this PR's author had been dogfooding) all started with a token in `localStorage` from some pre-Phase-1B build that still had a signin route. Once that token expires or `localStorage` is cleared, every existing install also breaks.

## How to detect

- `curl http://localhost:8080/api/v1/oss/probe` returns `hermes_reachable: true` but the browser at `http://localhost:8080` shows a blank page.
- Browser DevTools console: repeated "No token found in localStorage after waiting" warnings.
- `localStorage.getItem('token')` in the browser returns `null`.
- `curl http://localhost:8080/api/v1/auths/` (no auth) returns `{"detail":"Not authenticated"}`.
- DB has the seed user: `sqlite3 backend/data/myah.db 'SELECT id, email, role FROM user'` returns the row.

## How to fix (planned)

Two-part fix:

1. **Backend (`auths.py`):** add a new POST endpoint `/api/v1/auths/oss-signin` that is only mounted/enabled when `WEBUI_AUTH` (alias `MYAH_AUTH`) is `False`. It returns a JWT for the seed user with no auth required. Single-user OSS by definition has one user; this endpoint is the documented mechanism for that user to obtain a session.

2. **Frontend (`+layout.svelte`):** before calling `getSessionUser(localStorage.token)`, if no token is in `localStorage` AND the deployment mode is OSS, POST to `/api/v1/auths/oss-signin`, store the returned token, then continue with the normal flow.

The new endpoint must:
- Return 404 in hosted mode (when `WEBUI_AUTH=true`)
- Find the seed user by id (`00000000-0000-0000-0000-000000000001`)
- If the seed user is absent (someone deleted it), fall back to the first admin user; if no admin user exists, return 500 with a clear "run alembic migrations" message
- Use `create_session_response` (already defined at `auths.py:61`) so the cookie + Bearer token are issued consistently with the hosted path

## How we prevent regression

- New test in `platform-oss/backend/myah/test/test_oss_auth_bootstrap.py`:
  - oss-signin returns 200 + valid JWT when MYAH_AUTH=false
  - oss-signin returns 404 when MYAH_AUTH=true
  - JWT issued by oss-signin authenticates `/api/v1/auths/` (round-trip)
  - Seed-user-missing → 500 with clear error
- New gotcha entry (this file) so the next OSS-launch reviewer can grep for "auth bootstrap" and find the design rationale.
- The `oss-e2e-shape` CI gate (added by this PR) covers the welcome → providers → chat path; once that gate goes from advisory to required, this bug class cannot ship undetected.

## Acceptable trade-off

The new endpoint accepts ANY caller and issues an admin token. This is acceptable because:
- It's only enabled when `MYAH_AUTH=false`, which is OSS-single-user by definition. There is exactly one user, and there's nothing to protect from that user themselves.
- The OSS install is documented as loopback-only (`docker-compose.yml: 127.0.0.1:8080:8080`). LAN attackers cannot reach the endpoint.
- If a user explicitly exposes the platform to the LAN, they have already accepted the responsibility of `MYAH_AUTH=true` (as documented in the same docker-compose.yml comment).

This trade-off is identical to the dashboard's `--insecure --host 0.0.0.0` LAN-exposure trade-off documented in `2026-05-17-oss-dashboard-lan-exposure.md`. Both are unavoidable for OSS single-user UX.
