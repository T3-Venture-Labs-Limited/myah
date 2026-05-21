# OSS legacy LaunchAgent / systemd unit conflicts with new install

**Date discovered:** 2026-05-19
**Affected:** OSS users who installed Myah / Hermes before `v0.1.0-beta.1`
and are now upgrading; does not affect hosted
**Status:** Mitigated by Task 3.2 (setup-myah-oss.sh auto-migrates legacy
units). Manual cleanup is still useful if migration was skipped.

## Symptom

After re-running `scripts/setup-myah-oss.sh` and selecting the
service-install option, the gateway or dashboard appears to start
("✓ launchd plists installed") but `http://localhost:8642/health`
returns connection-refused, OR you see two `hermes gateway`
processes in `ps`, OR the gateway keeps respawn-flapping every few
seconds in `Console.app` / `journalctl --user`.

Pattern: the OS happily runs two competing copies of the gateway
against port 8642. The older one usually wins the bind race because
it was started first; the newer plist enters a
spawn-fail-respawn loop with `Address already in use` in its log.

## Detection

**macOS:**

```bash
launchctl list | grep -E 'hermes|myah|nous-research'
ls -la ~/Library/LaunchAgents/ | grep -E 'hermes|myah|nous-research'
```

Anything matching `com.nous-research.hermes.*` or `com.myah.*` is
legacy. The canonical post-`v0.1.0-beta.1` labels are
`dev.myah.hermes-gateway` and `dev.myah.hermes-dashboard`.

**Linux:**

```bash
systemctl --user list-unit-files | grep -E 'hermes|myah'
systemctl --user status hermes-gateway hermes-dashboard
```

A `myah-platform.service` is legacy (an older pattern where the
platform itself was a systemd-user unit instead of `docker compose`).
A `hermes-gateway.service` / `hermes-dashboard.service` is current.

## Root cause

Pre-`v0.1.0-beta.1` setup scripts used different label conventions.
The macOS plist names evolved through several rounds:

- `com.nous-research.hermes.gateway.plist` (very early)
- `com.myah.gateway.plist` (transitional)
- `dev.myah.hermes-gateway.plist` (current)

A user who installed at any of those stages and ran a newer
`setup-myah-oss.sh` would end up with both the old plist AND the new
one loaded. `launchctl` doesn't know they conflict — it just runs
whichever the user told it to, and the OS bind machinery picks the
winner.

## Automatic migration (Task 3.2)

`scripts/setup-myah-oss.sh` (after the Task 3.2 commit) detects and
retires legacy units before installing the new ones. Specifically:

- `install_launchd_plists` calls `migrate_legacy_launchagents` which:
  - globs for `com.nous-research.hermes.*.plist` and `com.myah.*.plist`
    in `~/Library/LaunchAgents`
  - `launchctl bootout gui/<UID>/<label>` (or `unload` on older macOS)
  - renames each plist to `*.bak.<timestamp>` so the user can
    forensically check what was there
- `install_systemd_units` calls `migrate_legacy_systemd_units` which:
  - looks for `myah-platform.service` only (the gateway/dashboard
    names overlap with what we install, so they overwrite cleanly via
    daemon-reload — no migration needed for those)
  - stops + disables + masks it so it won't come back

This is opt-in via the same prompt that asks "Run hermes gateway +
dashboard as a background service?" — answering "none" skips both
the migration AND the install, leaving everything alone.

## Manual cleanup

If you've hit the symptom and want to clean up by hand instead:

**macOS:**

```bash
for plist in ~/Library/LaunchAgents/com.nous-research.hermes.*.plist \
             ~/Library/LaunchAgents/com.myah.*.plist; do
    [ -f "$plist" ] || continue
    label=$(basename "$plist" .plist)
    launchctl bootout "gui/$UID/$label" 2>/dev/null \
        || launchctl unload "$plist" 2>/dev/null
    mv "$plist" "$plist.bak.$(date +%Y%m%d_%H%M%S)"
done
```

Then re-run `./scripts/setup-myah-oss.sh` and pick `launchd`.

**Linux:**

```bash
systemctl --user stop    myah-platform.service 2>/dev/null
systemctl --user disable myah-platform.service 2>/dev/null
systemctl --user mask    myah-platform.service 2>/dev/null
```

Then re-run `./scripts/setup-myah-oss.sh` and pick `systemd`.

## Prevention

- New OSS installs from `v0.1.0-beta.1` onward use the canonical
  label set — no migration ever needed.
- Existing users are protected by the automatic migration on the
  next `setup-myah-oss.sh` run.
- Once `launchctl list | grep -E 'nous-research|com\.myah'` is empty,
  you're past this gotcha permanently.

## Related code

- `scripts/setup-myah-oss.sh:migrate_legacy_launchagents`
- `scripts/setup-myah-oss.sh:migrate_legacy_systemd_units`
- `scripts/setup-myah-oss.sh:install_launchd_plists` (calls migrate first)
- `scripts/setup-myah-oss.sh:install_systemd_units` (calls migrate first)
- Plist templates: `scripts/oss-service-templates/dev.myah.hermes-*.plist.in`
- Systemd templates: `scripts/oss-service-templates/hermes-*.service.in`

## Related issues

- VM-testing followup: gateway respawn-loop on upgrade (2026-05-19)
- Companion gotcha: `2026-05-19-bug-wrong-venv-launchagent.md` (a
  similar "stale plist from prior install" failure mode, different env)
