# OSS crons fire but produce no chat output — `MYAH_PLATFORM_BASE_URL` drift

**Date discovered:** 2026-05-19
**Affected:** OSS variant (`MYAH_DEPLOYMENT_MODE=oss`); does not affect hosted
**Status:** Mitigated by Task 3.3 (setup-myah-oss.sh always overwrites) +
Task 3.4 (`dev-oss.sh doctor` warns on non-canonical value)

## Symptom

A user with one or more cron jobs configured sees them tick on the
schedule — they show "last run: just now" in the jobs UI, and Hermes
logs confirm the run completed — but no message ever appears in the
chat. The chat just stays empty. The same prompts, when fired from
the composer in real time, produce normal agent output.

In Hermes / plugin logs you'll see the chat completion succeed
followed by a request to `POST /api/chat/completed` against the
platform that either:

- hangs until timeout with `Connection refused` (port nothing is
  listening on), or
- returns `404 Not Found` if some other unrelated service grabbed
  that port

There is no chat-side error because the platform never received the
delivery POST.

## Detection

```bash
grep '^MYAH_PLATFORM_BASE_URL=' ~/.hermes/.env
```

If the value is anything other than `http://host.docker.internal:8080`
(Linux/macOS docker compose default) or `http://localhost:8080` (when
you've intentionally overridden the platform port to match), the cron
delivery path is broken.

`scripts/dev-oss.sh doctor` surfaces this directly:

```
✓ MYAH_PLATFORM_BASE_URL = http://localhost:8154
  ⚠ Non-canonical value — expected http://host.docker.internal:8080 or http://localhost:8080
    → Fix: re-run scripts/setup-myah-oss.sh (idempotent, overwrites stale value)
```

## Root cause

The Myah plugin reads `MYAH_PLATFORM_BASE_URL` from `~/.hermes/.env`
at process start and uses that value as the base URL for ALL platform
callbacks — chat completion delivery, attachment fetches, secret
prompts, the lot.

Earlier OSS installs (pre-`v0.1.0-beta.1`) wrote
`http://localhost:8154` here when the platform briefly ran on a
different port during local iteration. The platform later moved back
to `:8080`, but `setup-myah-oss.sh` was conservative about overwriting
env values — it used the pattern `[[ -n value ]] || set_var ...`,
which preserves whatever value is already there. So users who ran the
script during the `:8154` window AND re-ran it after the platform
port reverted ended up with a stale URL the script "respected"
forever.

Live chat works because the user-facing path doesn't traverse this
URL — only cron delivery (and, in the hosted-mode parallel,
attachment fetches from the agent container back to the platform)
does.

## Fix — one-liner

```bash
sed -i.bak 's|^MYAH_PLATFORM_BASE_URL=.*|MYAH_PLATFORM_BASE_URL=http://host.docker.internal:8080|' ~/.hermes/.env
```

Then restart the gateway so the plugin reloads:

```bash
./scripts/dev-oss.sh restart
```

Or just re-run setup — it's now idempotent and ALWAYS overwrites this
value:

```bash
./scripts/setup-myah-oss.sh
```

## Prevention

- `scripts/setup-myah-oss.sh` (after Task 3.3) calls `set_var
  MYAH_PLATFORM_BASE_URL ...` unconditionally on every run, so a
  re-run always re-asserts the canonical value.
- `scripts/dev-oss.sh doctor` (Task 3.4) prints a `⚠` line when the
  value is non-canonical, even if it's set to *something*.
- Regression gate: `platform-oss/backend/myah/test/
  test_setup_myah_oss_script.py::test_stale_platform_base_url_is_overwritten`
  seeds the stale value and asserts the script overwrites it while
  preserving unrelated lines.

## Related code

- `scripts/setup-myah-oss.sh:238` — the unconditional `set_var` call
- `scripts/setup-myah-oss.sh:96` — the `set_var` helper (overwrite-or-create)
- `scripts/dev-oss.sh:doctor` — diagnostic warning
- Plugin: `myah_hermes_plugin.myah_platform.client` reads
  `MYAH_PLATFORM_BASE_URL` at module import

## Related issues

- VM-testing followup: cron delivery silently dropped (2026-05-19)
- See also: `2026-05-19-bug-cron-delivery.md`
