# Hermes gateway running but argv[0] points to wrong python (legacy LaunchAgent)

**Status:** Investigating
**Reported:** 2026-05-19
**Affects:** OSS
**Severity:** P2
**Reproduction confidence:** high

## Symptom

OSS user runs `hermes status` or inspects `ps aux | grep hermes` and
sees the gateway process is alive, but argv[0] points at a stale Python
binary from a previous Hermes install — typically a venv from an
earlier `curl install.sh | bash` run that the user has since
reinstalled or upgraded. New plugin code (added via
`hermes plugins install ...`) doesn't load because the running process
is importing from the OLD venv's `site-packages/`.

Symptoms downstream:
- Plugin features missing from `/myah/health` or `/myah/v1/admin/*`
  responses
- `hermes plugins list` shows the plugin installed, but `/myah/v1/*`
  routes return 404
- Stale Sentry breadcrumb tags (`hermes.version`, plugin version) in
  emitted events

## Reproduction

1. Install Hermes on macOS via `curl ...install.sh | bash` — this
   registers a `~/Library/LaunchAgents/com.nousresearch.hermes.gateway.plist`.
2. Later, re-run the installer (e.g. to pick up a new Hermes SHA), or
   manually re-create the venv at a different path.
3. The LaunchAgent's `<string>...</string>` ProgramArguments still
   points at the OLD venv's `python` binary.
4. `launchctl` restarts the old binary on next login — old venv,
   old plugin code.

**Version pins at reproduction time:**
- Hermes SHA: `<TBD>`
- macOS version: 14.x or later
- Install method: `curl install.sh | bash` (legacy LaunchAgent path)

## Root cause

LaunchAgent plists are not migrated when the user re-runs the
installer. `install.sh` writes the plist on first run but doesn't
detect or rewrite an existing plist pointing at a stale venv path.

Per Phase 3 Task 3.2 of plan
`docs/superpowers/plans/2026-05-19-oss-post-launch-reliability.md`,
the migration adds:
1. A check at install time: if
   `~/Library/LaunchAgents/com.nousresearch.hermes.*.plist` exists with
   a `ProgramArguments` path that doesn't match the current install
   target, rewrite the plist and `launchctl bootout / bootstrap` to
   pick up the change.
2. A `hermes doctor` subcommand check surfacing the drift to the user
   if detected post-install.

## Evidence of fix

REQUIRED to flip Status to Verified. Will include:
- Phase 3 Task 3.2 commit SHA (the install.sh migration)
- `hermes doctor` output (post-fix) on a host with a previously-stale
  LaunchAgent — should report "LaunchAgent migrated" the first run and
  "OK" on subsequent runs
- Smoke step on a fresh macOS test host: install Hermes, re-install at
  a different venv path, verify the running process argv[0] matches
  the latest install
- Manual repro on a known-affected dev machine confirming the bug no
  longer reproduces

## Workaround (if any)

Manual fix:
```bash
launchctl bootout gui/$(id -u) ~/Library/LaunchAgents/com.nousresearch.hermes.gateway.plist
launchctl bootout gui/$(id -u) ~/Library/LaunchAgents/com.nousresearch.hermes.dashboard.plist
rm ~/Library/LaunchAgents/com.nousresearch.hermes.*.plist
curl -fsSL https://raw.githubusercontent.com/NousResearch/hermes-agent/main/scripts/install.sh | bash
```

Then verify `ps aux | grep hermes` shows the current venv path.

## Tracking

- Linear / issue: `<TBD>`
- PR(s) that fix it: `<TBD>` — Phase 3 Task 3.2 install.sh migration
- Hermes SHA / installer version that ships the fix: `<TBD>`
