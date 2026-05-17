# DashboardDownError "Try again" button does not re-render after probe succeeds

**Date discovered:** 2026-05-17 (during VM testing of `feat/oss-dashboard-topology`)
**Affected:** OSS variant — DashboardDownError, HermesDownError, PluginMissingError "Try again" buttons
**Severity:** MEDIUM — recovery still works via full page reload; only the in-place retry is broken.

## The bug class

`+layout.svelte:856-867` renders the OSS state machine:

```svelte
{#if ossProbeError || !ossProbe}
    <HermesDownError ... onRetry={runOssProbe} />
{:else if !ossProbe.hermes_reachable}
    <HermesDownError ... onRetry={runOssProbe} />
{:else if !ossProbe.plugin_installed}
    <PluginMissingError ... onRetry={runOssProbe} />
{:else if !ossProbe.dashboard_running}
    <DashboardDownError probe={ossProbe} onRetry={runOssProbe} />
{:else if ossProbe.first_run && ossProbe.providers_configured.length === 0}
    <Welcome probe={ossProbe} ... />
{:else if loaded}
    ... main app ...
{/if}
```

`runOssProbe`:

```javascript
let ossProbe = null;

async function runOssProbe() {
    ossProbeError = null;
    try {
        ossProbe = await getOssProbe();
    } catch (e) {
        ossProbeError = e;
    }
}
```

In Svelte 5 with the `$state` rune the assignment to `ossProbe` would trigger re-render. In Svelte 4 a top-level `let` is auto-reactive only when used inside a `$:` reactive statement or interpolated into the template. Looking at the actual code, `ossProbe` is referenced directly in `{:else if !ossProbe.hermes_reachable}` — Svelte does track that, but the chain depth (`!ossProbe ? ... : !ossProbe.x ? ... : ...`) may not invalidate cleanly when only a nested field of `ossProbe` changes.

The runtime symptom (verified during testing):

1. Dashboard is stopped → probe reports `dashboard_running: false` → DashboardDownError renders correctly. ✓
2. Dashboard is started → probe NOW reports `dashboard_running: true`. ✓ (confirmed by manual curl from inside the browser via `fetch('/api/v1/oss/probe', {cache:'no-store'})`).
3. User clicks "Try again" → `runOssProbe` runs → `ossProbe` is updated to the new response. ✓
4. The state machine does NOT re-render. DashboardDownError stays on screen.
5. A full page reload (`Cmd-Shift-R`) DOES re-render to the correct next state.

Hypothesis: Svelte 5's runic state tracking requires `$state` for top-level mutable bindings that drive reactive blocks. The current `let ossProbe = null` is non-reactive in Svelte 5 runes mode, which the project uses.

## How to detect

- Render DashboardDownError → start the dashboard → click "Try again" → the screen does not advance.
- DevTools console shows the click handler fires; `await getOssProbe()` returns the new shape; but no DOM update follows.
- A full reload (location.reload()) DOES advance the screen.

## How to fix (planned)

Two options:

1. **Wrap `ossProbe` in `$state`** (or whatever Svelte 5 idiom the project uses). Inspect the file's existing reactive bindings to confirm the convention.
2. **Make `runOssProbe` reassign with a new object reference** — Svelte 5 should see the identity change and re-track. Alternative: `ossProbe = {...await getOssProbe()}`.

Option 1 is the canonical fix. Option 2 is a workaround that should not be necessary if the project is correctly using runes.

Check what convention the rest of the file uses (do other top-level mutable bindings use `$state(null)` or plain `let x = null`?). Mirror the existing pattern.

## How we prevent regression

- Frontend integration test that mounts the layout with a mock probe, asserts DashboardDownError renders for `dashboard_running: false`, clicks "Try again" while changing the mock to return `dashboard_running: true`, and asserts the next state renders.
- The `oss-e2e-shape` CI gate (added in this PR) does NOT currently cover the in-place retry — it just covers initial-render shape. Worth a follow-up.

## Workaround for users

Until the fix lands: refresh the page after starting the dashboard. `Cmd-R` / `F5` works fine. Not a blocker, just a polish issue.
