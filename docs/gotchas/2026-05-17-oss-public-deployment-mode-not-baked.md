# OSS frontend gate ($env.PUBLIC_DEPLOYMENT_MODE) was never baked into the build

**Date discovered:** 2026-05-17 (during VM testing of `feat/oss-dashboard-topology`)
**Affected:** All OSS images built before commit `187d7b6f84`
**Severity:** HIGH — the entire OSS state machine (welcome, errors, dashboard-down) was silently bypassed.

## The bug class

`platform-oss/src/routes/+layout.svelte:55`:

```javascript
const isOss = env.PUBLIC_DEPLOYMENT_MODE === 'oss';
```

This gate decides whether the OSS state-machine block (lines ~849-880) runs at all. The block contains `HermesDownError`, `PluginMissingError`, `DashboardDownError`, and `Welcome` — every OSS-specific screen.

SvelteKit reads `$env/dynamic/public` variables at **build time** from `process.env`. For Docker builds, the value has to be supplied via `ARG` + `ENV` before `RUN npm run build` in the Dockerfile.

Before this PR, `platform-oss/Dockerfile` set `PUBLIC_SENTRY_DSN` via ARG/ENV but had NO equivalent for `PUBLIC_DEPLOYMENT_MODE`. The Vite build picked up an empty value, baked `env.PUBLIC_DEPLOYMENT_MODE === 'oss'` as `undefined === 'oss'` (`false`), and the OSS state machine was unreachable in every shipped image since v0.1.0-beta.1 (2026-05-13).

## How to detect

In a built image:

```bash
docker run --rm myah/platform:latest grep -h 'PUBLIC_DEPLOYMENT_MODE' /app/build/_app/immutable/chunks/*.js
```

Before the fix: the literal `PUBLIC_DEPLOYMENT_MODE==="oss"` appears, but `PUBLIC_DEPLOYMENT_MODE` resolves to undefined at runtime so the comparison is always false.

In the running app:

```javascript
// Browser DevTools console
window.__sveltekit_env_public // → does NOT contain PUBLIC_DEPLOYMENT_MODE
```

Or, more practically: load the page and check whether any OSS state ever renders. If you can navigate to `/` on a fresh install and see the `Connect a provider` flow without the welcome screen ever appearing, the gate is wrong.

## How the bug was masked

The hosted path also renders a "Connect a provider" screen (it's a normal first-launch experience), so casual observation of a fresh OSS install didn't surface anything obviously wrong. The OSS state machine's blocking screens (HermesDownError, PluginMissingError, DashboardDownError) only render when a backend error condition is true — and the team's primary dogfooding was against the hosted variant where those errors don't fire.

## How we fixed it

`platform-oss/Dockerfile` commit `187d7b6f84`:

```dockerfile
ARG PUBLIC_DEPLOYMENT_MODE="oss"
...
ENV PUBLIC_DEPLOYMENT_MODE=${PUBLIC_DEPLOYMENT_MODE}
RUN npm run build
```

Default is `"oss"` because this Dockerfile produces the OSS image (`myah/platform`). The hosted variant's Dockerfile (`platform-hosted/Dockerfile`) overrides if needed.

## How we prevent regression

- The `oss-e2e-shape` CI gate (added in this PR) boots the OSS stack and asserts the welcome → providers → chat flow renders. Without `PUBLIC_DEPLOYMENT_MODE=oss`, the OSS state machine never fires and the welcome assertion fails — the gate would have caught this bug from day one.
- The bug is structurally impossible to reintroduce as long as the Dockerfile retains the `ARG PUBLIC_DEPLOYMENT_MODE=oss` default — and CI exercises the built image.

## Lessons

- Vite `$env/dynamic/public` works at runtime in dev but bakes at build time in production. The two evaluation strategies have caused other bugs in the past; consider preferring `$env/static/public` and a build-time check that fails the build when the value is missing.
- Existing OSS dogfooders didn't catch this because they were running the platform with a token already in localStorage from pre-Phase-1B builds; the layout never re-checked `isOss` for them.
