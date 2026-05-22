# Settings modal tabs: aria-selected flips but right pane stays on General

**Status:** Investigating
**Reported:** 2026-05-19
**Affects:** both
**Severity:** P2
**Reproduction confidence:** high

## Symptom

User opens Settings modal (gear icon → Settings). Default view: General
tab content rendered in the right pane. User clicks Provider, Secrets,
or Data Controls in the left tab list. The clicked tab's
`aria-selected` attribute correctly flips to `true` (visible in DOM
inspector), but the right pane content does NOT change — it stays on
General.

Specifically:
- `<button role="tab" aria-selected="true">Provider</button>` is correct
- The visible `<div role="tabpanel">` is still General's panel
- No console error
- Reproducible on every click, in Firefox / Chromium / Safari

## Reproduction

1. Open the Settings modal (gear icon, top-right).
2. Default view: General tab.
3. Click Provider (or Secrets, or Data Controls) in the left tab list.
4. Observe `aria-selected` flips on the clicked button but the right
   pane stays on General.

Detailed RCA + screenshots: `docs/oss-launch/settings-modal-repro.md`
(Task 0.2 of plan `docs/superpowers/plans/2026-05-19-oss-post-launch-reliability.md`).

**Version pins at reproduction time:**
- Platform commit: `<TBD — pre-fix>`
- Affected component: `platform-oss/src/lib/components/chat/SettingsModal.svelte`
- Browser: any (root cause is Svelte reactivity, not browser-specific)

## Root cause

Per Task 0.2 RCA (`docs/oss-launch/settings-modal-repro.md`): the
`config` store has a `subscribe()` handler in the SettingsModal that
runs on every config update. When the user clicks a tab, an unrelated
`config` update fires (often a settings probe triggered by the modal
opening); the subscribe handler resets the active-tab local state back
to its initial value (General).

Concretely: `selectedTab` is a `let` bound from a derived store, and
the store's `subscribe` callback overwrites it on every emission rather
than only on first load. The tab button's click handler updates a
local `selectedTab`, but the very next config emission clobbers it.

## Evidence of fix

REQUIRED to flip Status to Verified. Will include:
- Phase 2 Task 2.2 commit SHA fixing the selectedTab reset (already
  landed in this worktree per `git log` — see commit
  `ecd9e517ca fix(settings-modal): preserve selected tab across $config
  updates + add ARIA tabpanel`)
- Browser screenshot showing Provider tab content actually rendering
  after click
- Manual repro: click through all 7 tabs (general, interface,
  connections, provider, secrets, data_controls, account, about) and
  verify each panel renders
- Optional: vitest unit test exercising tab-click behavior with a
  mocked `config` store emission

## Workaround (if any)

Users on pre-fix builds: open the Settings modal fresh after each tab
they want to view (close, reopen, click target tab quickly before any
config probe fires). Not a real workaround — basically blocks settings
usage.

## Tracking

- Linear / issue: `<TBD>`
- RCA doc: `docs/oss-launch/settings-modal-repro.md`
- PR(s) that fix it: Phase 2 Task 2.2 — landed as commit `ecd9e517ca`
  on branch `spike/post-oss-reliability-spec`
- Platform commit that ships the fix: `ecd9e517ca` (target: v0.1.1 release)
