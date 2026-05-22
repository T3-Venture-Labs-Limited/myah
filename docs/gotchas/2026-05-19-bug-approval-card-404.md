# Approval card flips to "no longer active" or returns 404 when user clicks an option

**Status:** Investigating
**Reported:** 2026-05-19
**Affects:** both
**Severity:** P1
**Reproduction confidence:** high

## Symptom

User sees an approval card in chat (e.g. "Allow tool X to run?") with
options like Approve / Deny. Clicking any option either:

1. Returns HTTP 404 from `POST /myah/v1/confirm/{stream_id}` with body
   `{"detail": "stream_id not found"}`, OR
2. The card UI immediately flips to a greyed-out "This approval is no
   longer active" state, and the agent run hangs indefinitely (or fails
   with `run.failed` carrying a timeout error).

The card appears responsive (button click registers, request fires) but
the resolution never reaches the agent's pending approval queue.

## Reproduction

1. Start a chat that triggers an approval gate (e.g. a tool call
   requiring user consent in `config.yaml`'s approval section).
2. Wait for the approval card to render in the chat.
3. **Either wait >300s before clicking** (triggers the `_action_queues`
   timeout path), **or** click rapidly while a parallel stream cleanup
   is in flight (triggers the `_stream_sessions` race).
4. Click any option.
5. Observe 404 response or "no longer active" UI state.

**Version pins at reproduction time:**
- Plugin SHA: `<TBD — pre-v0.1.1>`
- Hermes SHA: `<TBD>`
- Platform commit: `<TBD>`

## Root cause

Per spec `docs/superpowers/specs/2026-05-19-oss-post-launch-reliability-design.md`
§5.1, dual root cause in `myah_hermes_plugin/myah_platform/adapter.py`:

1. **`_action_queues` timeout (300s)** — pending approval queues expire
   too aggressively. Users in long-running chats (multi-tab workflows,
   distracted users) hit the timeout before responding.
2. **`_stream_sessions` cleanup race** — a parallel stream-teardown
   path can delete the session entry before the confirm POST resolves.
   The confirm handler then can't find `stream_id` and 404s.

## Evidence of fix

REQUIRED to flip Status to Verified. Will include:
- Phase 1 PR 1 plugin commit SHA(s) bumping `_action_queues` timeout
  to 1800s and serializing `_stream_sessions` mutations (Tasks 1.1, 1.3, 1.4)
- Smoke-test step asserting approval resolution succeeds at T+600s
  (canonical observability evidence)
- Sentry breadcrumb `myah.approval.confirm_404` count delta showing
  drop to zero post-deploy
- Browser screenshot of working ConfirmationCard with retry button
  (Phase 2 Task 2.1) successfully resolving an approval

## Workaround (if any)

Users on pre-fix plugin builds: respond to approval prompts within
5 minutes of card appearance. If the card flips to "no longer active",
reload the chat and re-issue the command that triggered the approval.

## Tracking

- Linear / issue: `<TBD>`
- PR(s) that fix it:
  - Plugin PR (Phase 1 PR 1): `<TBD>` — Tasks 1.1 + 1.3 + 1.4
  - Platform PR (Phase 2 Task 2.1): `<TBD>` — ConfirmationCard retry button
- Plugin SHA that ships the fix: `<TBD>` (target: v0.1.1 plugin bump)
