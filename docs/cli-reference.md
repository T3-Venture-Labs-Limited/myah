# Myah CLI Reference

The `myah` binary is the single front door for both OSS users and Myah developers. It is a Typer-based Python CLI that ships in the platform wheel — when you `pip install -e .` (or run any of the bootstrap scripts), `myah` becomes available on your `PATH`.

This document covers **every command** the CLI exposes, with synopsis, flags, behavior notes, and worked examples. For the design rationale see [`docs/superpowers/specs/2026-05-22-devx-oss-cli-design.md`](./superpowers/specs/2026-05-22-devx-oss-cli-design.md).

> **Quick reference card:** if all you want is "what's the command that does X", jump to [Recipes](#recipes) near the bottom.

## Contents

- [Conventions](#conventions)
- [Installation](#installation)
- [Top-level commands (OSS users)](#top-level-commands-oss-users)
  - [`myah quickstart`](#myah-quickstart)
  - [`myah install`](#myah-install)
  - [`myah doctor`](#myah-doctor)
  - [`myah status`](#myah-status)
  - [`myah agent`](#myah-agent)
  - [`myah platform`](#myah-platform)
  - [`myah plugins`](#myah-plugins)
  - [`myah env`](#myah-env)
  - [`myah logs`](#myah-logs)
  - [`myah upgrade`](#myah-upgrade)
  - [`myah uninstall`](#myah-uninstall)
  - [`myah serve`](#myah-serve)
- [Developer-only commands (`myah dev *`)](#developer-only-commands-myah-dev)
  - [`myah dev worktree`](#myah-dev-worktree)
  - [`myah dev backend / frontend / both`](#myah-dev-backend--frontend--both)
  - [`myah dev stop / restart / status`](#myah-dev-stop--restart--status)
  - [`myah dev logs`](#myah-dev-logs)
  - [`myah dev mode`](#myah-dev-mode)
  - [`myah dev hermes`](#myah-dev-hermes)
  - [`myah dev plugin`](#myah-dev-plugin)
  - [`myah dev oss`](#myah-dev-oss)
- [Recipes](#recipes)
- [Troubleshooting](#troubleshooting)
- [Known gaps](#known-gaps)

---

## Conventions

| Convention                | What it means                                                                                                                                                                                              |
| ------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `myah <verb>`             | A top-level command. These are the commands OSS end-users normally need.                                                                                                                                       |
| `myah dev <verb>`         | A developer-only command. Hidden from `myah --help`; visible via `myah dev --help`. Most operate inside a per-branch git worktree.                                                                              |
| **Exit codes**            | `0` = success. `1` = a check failed but the command ran to completion (e.g. `myah doctor` finishes the report but reports FAIL). `2` = the command refused to run (bad flags, missing prerequisite, etc.).      |
| **Idempotent**            | Safe to re-run. Most lifecycle commands are.                                                                                                                                                                |
| **Mutually exclusive**    | Two flags can't be set together; passing both is a 2-exit error.                                                                                                                                            |
| **Wrap** / **Composite**  | Per the spec's *Relation to Upstream Hermes CLI* table, every Myah verb is classified as **wrap** (thin passthrough to `hermes`), **wrap-and-validate** (passthrough plus Myah-side check), **composite** (a documented sequence of underlying calls), or **native** (no upstream equivalent). Each section below states the class. |

## Installation

`myah` ships in the platform wheel. After cloning the repo:

```bash
git clone https://github.com/T3-Venture-Labs-Limited/myah && cd myah
python3 -m venv .venv && source .venv/bin/activate
MYAH_SKIP_HATCH_NPM=1 pip install -e .
myah --help
```

### Why the venv

Most modern Linux distros (Ubuntu 24.04+, Debian 12+, Fedora 39+, Arch) ship Python with [PEP 668](https://peps.python.org/pep-0668/) protection enabled by default. Running `pip install -e .` against the system Python on those distros exits 1 immediately with `error: externally-managed-environment`. A per-clone venv is the safest, most portable workaround — it sidesteps PEP 668 without polluting the system Python and matches what `myah dev worktree create` does internally.

If you have `pipx` available, `pipx install --editable .` works too and is interchangeable.

### Why `MYAH_SKIP_HATCH_NPM=1`

`pip install -e .` triggers `hatch_build.py`, which by default runs `npm install --force` followed by `npm run build` so the wheel ships with the frontend baked in. Two consequences for editable installs:

* On a fresh Ubuntu 24.04 VM with Node 22 from the Hermes installer, `npm run build` has been seen to exit 134 (SIGABRT) during the Vite step — likely a glibc / Node interaction. The install aborts with a hatchling `AttributeError` cascade.
* OSS users `myah platform up` pulls a prebuilt `ghcr.io/.../myah-platform-oss` image whose frontend is already built. The editable wheel's frontend is therefore unused for the OSS path.

`MYAH_SKIP_HATCH_NPM=1` short-circuits the hook. The `build/.gitkeep` already in the repo satisfies the hatchling `force-include` check.

If you want the full editable build (e.g. you're modifying the frontend), drop the env var:

```bash
pip install -e .   # runs npm install + npm run build inside hatch_build.py
```

The production container's `CMD` is `myah serve` — `myah` is the binary baked into the image. The container build path always runs the full frontend build.

---

# Top-level commands (OSS users)

## `myah quickstart`

**Class:** Composite — one-command first-run for OSS users.

Equivalent to running:

```bash
myah install [...] && myah platform up && myah doctor
```

### Synopsis

```bash
myah quickstart [--non-interactive] [--service systemd|launchd|none]
                [--openrouter-key KEY] [--rotate]
```

### Behavior

| Step | What runs                                                  | Failure mode                                                                       |
| ---- | ---------------------------------------------------------- | ---------------------------------------------------------------------------------- |
| 1/3  | `myah install` (with `--service` defaulting to OS pick)    | Short-circuit; quickstart exits 1.                                                 |
| 2/3  | `myah platform up`                                         | Continue to step 3 so doctor surfaces the cause; exit code propagated.             |
| 3/3  | `myah doctor`                                              | Doctor's exit code becomes the final exit code unless step 2 already failed.       |

Print:
* "Step N/3:" headers before each phase.
* On success: `✓ Quickstart complete. Open http://localhost:8080`.

---

## `myah install`

**Class:** Composite. Replaces the legacy 922-line `setup-myah-oss.sh`.

End-to-end first-time setup of the Myah OSS stack. Idempotent — safe to re-run.

### Synopsis

```bash
myah install [OPTIONS]
```

### Flags

| Flag                          | Purpose                                                                                                                                              |
| ----------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------- |
| `--non-interactive`           | Skip all TTY prompts. Required for CI. Combined with `--service`, fails fast if any interactive-only value is missing.                                  |
| `--service systemd\|launchd\|none` | Choose the service-supervision backend. `none` skips unit-file install. Interactive mode prompts with the platform-appropriate default if omitted.    |
| `--openrouter-key KEY`        | Pre-sets `OPENROUTER_API_KEY` in the Hermes `.env`. Avoids the interactive provider-credential prompt.                                                  |
| `--rotate`                    | Regenerate **all** tokens (bearer slots, adapter auth, API server key, OAuth Fernet key, JWT secret, session token). Mutually exclusive with `--keep-data`. |
| `--keep-data`                 | Documented-intent flag — preserves existing tokens/data (this is the default behavior; use the flag to declare intent in scripts).                       |
| `--skip-start`                | After laying down service units, skip the automatic `agent up` (launchctl kickstart / systemctl start). Use for CI or when you'll start services manually. No-op when `--service none`. |

### What it does — 8 phases

1. **Pre-flight** — Verifies `hermes` is on PATH; locates repo root via `agent/Dockerfile.stock` (private) or `versions.env` (public).
2. **Bearer-token 5-slot alignment** — Writes the same bearer token to all 5 slots: `MYAH_AGENT_BEARER_TOKEN`, `MYAH_ADAPTER_AUTH_KEY`, `API_SERVER_KEY`, `MYAH_PLATFORM_BEARER` (Hermes `.env`) + `MYAH_AGENT_BEARER_TOKEN` (platform `.env`). Adds 6 OSS-default Hermes env vars if empty.
3. **OAuth Fernet key** — Generates `OAUTH_SESSION_TOKEN_ENCRYPTION_KEY` if unset, or on `--rotate`.
4. **MYAH_SECRET_KEY** — Adopts legacy `WEBUI_SECRET_KEY` if present (Open WebUI migration path), else generates a fresh JWT secret. With `--rotate`, *always* generates fresh — the legacy adoption is bypassed (see Slice 4 fix commit).
5. **HERMES_WEB_SESSION_TOKEN** — 2-slot alignment between platform and Hermes `.env`.
6. **Plugin install** — Detects Hermes venv → bootstraps `pip` if missing → installs the myah-hermes-plugin at the SHA pinned in `agent/Dockerfile.stock:183` → materializes the dashboard shim → verifies the mount via `hermes plugins list`.
7. **Hermes config merge + auto-start** — PyYAML deep-merge: ensures `gateway.platforms.myah.enabled: true`. Type-mismatch handling warns and overwrites (matches bash `yq` behavior). When `--service {systemd,launchd}` is in effect, Phase 7 also auto-kickstarts the freshly-laid-down units (equivalent to running `myah agent up`) so the next user step is a working stack. Pass `--skip-start` to opt out (CI, scripted callers that start services manually).
8. **Service units + verification** — Installs systemd-user / launchd plists / nothing per `--service`. Final Rich table from `post_install_doctor_run`. **Exits 1 on any FAIL.**

### Examples

```bash
# Typical interactive install on Linux
myah install

# Non-interactive CI install
myah install --non-interactive --service none --openrouter-key sk-or-v1-...

# Rotate all tokens (e.g. after a key compromise)
myah install --rotate

# Explicit "don't rotate, just verify everything is wired up" — re-run safety
myah install --keep-data
```

### Notes / gotchas

- **`--rotate`** regenerates `MYAH_SECRET_KEY` even when `WEBUI_SECRET_KEY` is present. If you specifically want to keep an Open WebUI–migrated secret, don't pass `--rotate`.
- The bash script `platform-oss/scripts/setup-myah-oss.sh` is now a loud-banner deprecation stub that recommends `myah install`. It still runs the original 922-line install behind the banner during the deprecation period.
- CI invokes `myah install --non-interactive --service none`.

---

## `myah doctor`

**Class:** Wrap-and-extend.

Diagnose stack health. Runs `hermes doctor` and appends Myah-specific checks (plugin SHA drift, platform container reachability, port alignment, agent-container env injection).

### Synopsis

```bash
myah doctor [--fix]
```

Read-only by default. Exits `1` if any check returns FAIL.

### Flags

| Flag    | Purpose |
| ------- | ------- |
| `--fix` | Opt-in self-healing. After rendering the initial report, attempt a remediation for each actionable (FAIL/WARN) finding, then re-render the table. Currently fixes: plugin not enabled (runs `hermes plugins enable myah` + `myah agent restart`), Hermes gateway/dashboard port unbound (runs `myah agent restart`), `myah-platform` container down (runs `myah platform up`). Always exits `0` regardless of post-fix state — the rendered tables are what the user reads. Destructive remediations (wiping `~/.hermes`, rotating tokens) are out of scope and require their own subcommand. |

### Example

```bash
$ myah doctor
✓ hermes binary on PATH
✓ ~/.hermes/config.yaml present
✓ MYAH plugin installed at pinned SHA 725b61fa…
✓ platform container running (myah-platform:latest)
WARN Hermes dashboard not reachable on :9119 (may be intentional)
✓ MYAH_PLATFORM_BASE_URL and MYAH_PLATFORM_BEARER aligned

5 checks passed, 1 warning, 0 failures
```

---

## `myah status`

**Class:** Wrap-and-extend.

Show what's running. Rich table with PID, port, and a `/health` probe per service.

### Synopsis

```bash
myah status
```

No flags. Always exits `0`; status info is informational only.

---

## `myah agent`

**Class:** Pure wrapper around the OS supervisor (`systemctl --user` on Linux, `launchctl` on macOS).

Controls the Hermes gateway + dashboard processes. The unit names match what `myah install` installs: `hermes-gateway.service`, `hermes-dashboard.service` (Linux) or `dev.myah.hermes-gateway`, `dev.myah.hermes-dashboard` (macOS).

> **Design note.** The spec originally said `myah agent up` would wrap `hermes gateway start`. In practice that command resolves to a different unit name than `myah install` lays down. The current implementation drives the OS supervisor directly against Myah's units — the result is the same, the path is cleaner.

### Synopsis

```bash
myah agent up
myah agent down
myah agent restart
myah agent config show | edit | validate
```

### Subcommands

| Subcommand          | Purpose                                                                              |
| ------------------- | ------------------------------------------------------------------------------------ |
| `up`                | Start gateway + dashboard via the OS supervisor. Idempotent — already-running returns 0. |
| `down`              | Stop gateway + dashboard via the OS supervisor.                                       |
| `restart`           | Stop, then start, both.                                                              |
| `config show`       | Print the active Hermes config (wraps `hermes config show`).                          |
| `config edit`       | Open the Hermes config in `$EDITOR` (wraps `hermes config edit` with stdio passthrough). |
| `config validate`   | Validate the Hermes config (wraps `hermes config check`). The only verb rename — `validate → check`. |

### Examples

```bash
# Start the agent (run after `myah install --service systemd`)
myah agent up

# After editing config.yaml manually
myah agent config validate
myah agent restart
```

---

## `myah platform`

**Class:** Native. Wraps `docker compose -f <repo>/docker-compose.yml`.

Controls the Myah FastAPI platform container. **Not a Hermes wrapper** — this is the SvelteKit + FastAPI surface, separate from the Hermes runtime.

### Synopsis

```bash
myah platform up [--bind 127.0.0.1|0.0.0.0] [--expose]
myah platform down
myah platform restart
```

### Subcommands

| Subcommand | Purpose                                                                                                              |
| ---------- | -------------------------------------------------------------------------------------------------------------------- |
| `up`       | `docker compose up -d` — always detached. Defaults to local-only `127.0.0.1:8080`. Use `--expose` for Tailscale/LAN. |
| `down`     | `docker compose down` — **does NOT pass `-v`** (preserves the SQLite volume; SQLite-data-loss footgun guard).            |
| `restart`  | `docker compose restart`.                                                                                            |

### Examples

```bash
# After myah install, bring up the platform
myah platform up

# Expose the web UI over trusted Tailscale/LAN
myah platform up --expose
# equivalent: myah platform up --bind 0.0.0.0

# Pull a fresh image then restart
docker compose pull && myah platform restart
```

### Notes

- The `-v` omission on `down` is **intentional** — see `cli/platform_.py:109-113`. If you really want to nuke the data volume, use `docker compose -f docker-compose.yml down -v` directly. `myah uninstall --rotate` is the supported path for full teardown.
- `myah platform up --expose` publishes the platform as `0.0.0.0:8080->8080/tcp`; this is convenient for Tailscale but should only be used on trusted networks. The default remains `127.0.0.1` so a fresh OSS install is not LAN-exposed by accident.

---

## `myah plugins`

**Class:** Wrap-and-validate. After every action, prints an informational drift warning if the installed myah-hermes-plugin's SHA (read from PEP 610 `direct_url.json`) differs from `agent/Dockerfile.stock:183`'s pin. The warning never fails the command.

### Synopsis

```bash
myah plugins list
myah plugins install <PLUGIN>
myah plugins update [PLUGIN]
myah plugins remove <PLUGIN>
```

### Subcommands

| Subcommand                | Purpose                                                                                |
| ------------------------- | -------------------------------------------------------------------------------------- |
| `list`                    | List installed Hermes plugins.                                                          |
| `install <PLUGIN>`        | Install a plugin (passes through to `hermes plugins install`).                          |
| `update [PLUGIN]`         | Update one or all plugins (passes through to `hermes plugins update`).                 |
| `remove <PLUGIN>`         | Remove a plugin.                                                                       |

### Examples

```bash
myah plugins list
myah plugins update myah          # update the Myah plugin
# Plugin SHA drift warning (informational):
#   ! installed myah-hermes-plugin SHA 7e394b68 differs from
#     pinned SHA in agent/Dockerfile.stock:183 (725b61fa).
```

---

## `myah env`

**Class:** Native. Read/write the platform and Hermes `.env` files. Atomic writes via tmp + `os.replace`.

### Synopsis

```bash
myah env list [--scope platform|hermes] [--show-secrets]
myah env set --scope platform|hermes KEY VALUE
myah env unset --scope platform|hermes KEY
```

### Flags

| Flag                       | Purpose                                                                                                                                                       |
| -------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `--scope platform\|hermes` | Required for `set` / `unset`. Optional for `list` — defaults to both. Distinguishes the platform's `.env` from Hermes's `~/.hermes/.env`.                          |
| `--show-secrets`           | Reveal masked values. Sensitive keys (`*_KEY`, `*_TOKEN`, `*_SECRET`, `*_PASSWORD`) are masked by default with `••••••`.                                              |

### Examples

```bash
# Inspect everything (sensitive values masked)
myah env list

# Just the Hermes scope, with secrets revealed (e.g. before pasting into a support thread — sanitize first!)
myah env list --scope hermes --show-secrets

# Add an LLM provider key
myah env set --scope hermes OPENROUTER_API_KEY sk-or-v1-...

# Remove a key
myah env unset --scope hermes LANGFUSE_SECRET_KEY
```

### Notes

- Atomic writes mean a mid-write crash leaves the original `.env` intact (no half-written secrets).
- `unset` of a key that doesn't exist is a successful no-op (`exit 0`).

---

## `myah logs`

**Class:** Thin wrapper. Routes by argument: `LOG_NAME=platform` → `docker compose logs platform`; anything else → `hermes logs`.

### Synopsis

```bash
myah logs [LOG_NAME] [-n LINES] [-f]
```

### Flags

| Flag                | Purpose                                                                                                                                                 |
| ------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `-n / --lines N`    | Number of tail lines (maps to `--tail` on docker, `-n` on hermes).                                                                                       |
| `-f / --follow`     | Live tail (maps to `--follow` on docker, `-f` on hermes).                                                                                                |
| `--level LEVEL`     | Minimum log level. **Hermes-only** — rejected with exit 2 when `LOG_NAME=platform`.                                                                       |
| `--session SESSION` | Filter by session id. **Hermes-only**.                                                                                                                  |
| `--since DURATION`  | Show entries newer than `DURATION` (e.g. `1h`, `30m`). **Hermes-only**.                                                                                  |
| `--component NAME`  | Hermes component name (`gateway`, `dashboard`, etc.). **Hermes-only**.                                                                                  |

### Examples

```bash
# Tail the platform container
myah logs platform -n 100 -f

# Tail Hermes gateway with level filter
myah logs gateway --level WARNING --since 1h
```

---

## `myah upgrade`

**Class:** Composite. Documented sequence of three underlying calls.

### Synopsis

```bash
myah upgrade [--check] [--yes]
```

### Flags

| Flag         | Purpose                                                                                                          |
| ------------ | ---------------------------------------------------------------------------------------------------------------- |
| `--check`    | Only run `hermes update --check` and stop. **True no-op** — no side effects, no state change.                      |
| `--yes`, `-y` | Skip confirmation prompts; pass `--yes` through to `hermes update`.                                              |

### What it does

1. `hermes update [--check] [--yes]` — upstream Hermes upgrade.
2. `git -C <repo> pull` — refresh the Myah source. **Skipped + warned** if the tree is dirty (`git status --porcelain` not empty), or if Myah was not installed via clone (no `.git` directory).
3. `docker compose pull` — pull the latest platform image. Warns and continues on failure (no Docker, offline, etc.).

If `--check` is passed, only step 1 runs (and short-circuits on its `--check` output). Steps 2-3 are skipped entirely.

> **Known gap.** The plan called for a 4th step (`pip install -U myah`) once Myah ships on PyPI. Until then, `cli/upgrade.py:105` carries a `TODO(slice-5-followup)` marker. Use `git pull && pip install -e .` to update the Python package manually.

### Examples

```bash
# Check if anything's new
myah upgrade --check

# Run the full upgrade
myah upgrade

# Skip prompts (e.g. cron'd auto-upgrade)
myah upgrade --yes
```

---

## `myah uninstall`

**Class:** Composite. Tears down platform + Hermes data per the flag truth table.

### Synopsis

```bash
myah uninstall [--keep-data] [--keep-config] [--yes]
```

### Flags

| Flag             | Purpose                                                                                                                                                                                                                       |
| ---------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `--keep-data`    | Preserve the platform SQLite volume AND skip `--full` on `hermes uninstall` (which also preserves Hermes config). Hermes treats data + config as one bundle, so this flag protects both. Mutually exclusive with default-full. |
| `--keep-config`  | Preserve the platform `.env` AND skip `--full` on `hermes uninstall`. Same Hermes bundle behavior as above.                                                                                                                    |
| `--yes`, `-y`    | Skip the confirmation prompt.                                                                                                                                                                                                 |

### Truth table

| `--keep-data` | `--keep-config` | Platform container          | Platform volume          | Platform `.env`        | Hermes (via `hermes uninstall`)       |
| ------------- | --------------- | --------------------------- | ------------------------ | ---------------------- | ------------------------------------- |
| no            | no              | removed (`docker compose down -v`) | **DELETED** (`-v`)         | removed                | `--full` (config + data both removed) |
| **yes**       | no              | removed (`docker compose down`)    | kept                     | removed                | no `--full` (data + config kept)      |
| no            | **yes**         | removed (`docker compose down -v`) | **DELETED** (`-v`)         | kept                   | no `--full` (data + config kept)      |
| **yes**       | **yes**         | removed (`docker compose down`)    | kept                     | kept                   | no `--full` (data + config kept)      |

If `hermes uninstall` fails (e.g. partial install state), the platform-side cleanup continues — **soft-fail** on the Hermes step only.

### Known limitation: `hermes uninstall` needs a TTY

Hermes 0.14.0's `hermes uninstall` rejects non-TTY invocations with
`Error: 'hermes uninstall' requires an interactive terminal.` even
when `--yes` is passed. `myah uninstall --yes` therefore:

* tears down the platform container + volume + service units + platform `.env`;
* prints a clear recovery hint when the TTY failure is detected;
* exits 0 (the platform side completed successfully).

Two recovery paths:

```bash
# Option 1: finish manually from a TTY
hermes uninstall --full --yes

# Option 2: re-run with --force-purge-hermes for cron-safe full teardown
myah uninstall --yes --force-purge-hermes
```

`--force-purge-hermes` is mutually exclusive with `--keep-data` /
`--keep-config` — it removes everything.

### Examples

```bash
# Full nuke (with prompt)
myah uninstall

# Keep my chat history but tear down the platform container
myah uninstall --keep-data

# Cron-safe — tears down the platform; the hermes-side teardown
# still requires a manual `hermes uninstall --full --yes` from a TTY
# until upstream lifts the requirement. See "Known limitation" above.
myah uninstall --yes
```

---

## `myah serve`

**Class:** Native. Production container's `CMD ["myah", "serve"]` and the local dev-server entrypoint.

### Synopsis

```bash
myah serve [--host HOST] [--port PORT] [--reload]
```

### Flags

| Flag       | Purpose                                                                                                |
| ---------- | ------------------------------------------------------------------------------------------------------ |
| `--host`   | Bind address (default `0.0.0.0`).                                                                       |
| `--port`   | Port (default `8082`).                                                                                  |
| `--reload` | Enable uvicorn hot-reload — **the new home for the old `myah dev` command**. Use for local development. |

### Notes

- The old `myah dev` top-level command was retired in Slice 1; `myah serve --reload` is its replacement. Production behavior (`myah serve` with no flags) is unchanged.
- For per-worktree development with isolated venvs + ports, prefer `myah dev backend` / `myah dev frontend` (see below).

---

# Developer-only commands (`myah dev *`)

These are hidden from `myah --help`. Run `myah dev --help` to see them. All `myah dev` commands either operate inside a per-branch git worktree (under `.worktrees/<branch>/`) or manage worktree lifecycles from the main repo.

## `myah dev worktree`

**Class:** Native. Per-worktree lifecycle. Run from the **main repo root** (not from inside a worktree).

### Synopsis

```bash
myah dev worktree create <BRANCH> [--mode oss|hosted]
myah dev worktree list
myah dev worktree destroy <BRANCH> [--yes] [--force]
```

### Subcommands

#### `create <BRANCH> [--mode oss|hosted]`

Creates an isolated worktree at `.worktrees/<BRANCH>/`. The orchestrator runs 12 steps with reverse-order rollback on failure:

1. Idempotence guard (fail loudly if the worktree already exists)
2. `git worktree add .worktrees/<BRANCH> -b <BRANCH>` (or attach to existing branch)
3. Create per-worktree venv (`<worktree>/.venv/`) — NOT a symlink
4. Install Myah platform into the venv (`pip install -e ./platform-oss[dev]`) with `MYAH_SKIP_HATCH_NPM=1`
5. Create isolated Hermes home (`<worktree>/.hermes/`)
6. Install Hermes into the venv at the SHA pinned in `agent/Dockerfile.stock:13`
7. Install myah-hermes-plugin at the SHA pinned in `agent/Dockerfile.stock:183`
8. Materialize the dashboard shim (otherwise the dashboard can't load the plugin)
9. Generate fresh per-worktree tokens (3 bearer/signing tokens; `secrets.token_urlsafe(32)` each)
10. Copy non-bearer secrets from main's `.env` (`OPENROUTER_API_KEY`, `SENTRY_DSN_*`, `LANGFUSE_*`, `OAUTH_SESSION_TOKEN_ENCRYPTION_KEY`)
11. Write `<worktree>/platform-oss/.env` (5-way bearer-aligned) and `<worktree>/.worktree-env` (per-branch ports + CORS overrides)
12. Write `<worktree>/.hermes/.env` aligning the same bearer to 4 slots

On any step failure, the cleanup ledger walks backward, removing everything created up to that point.

**Flags:**

| Flag                   | Purpose                                                                                                          |
| ---------------------- | ---------------------------------------------------------------------------------------------------------------- |
| `--mode oss\|hosted`   | Initial deployment mode. Defaults to `hosted`. `oss` sets `MYAH_DEPLOYMENT_MODE=oss` + `MYAH_AUTH=false`.            |

#### `list`

Print a Rich table of every worktree under `.worktrees/` showing branch, mode, allocated ports, and the worktree path.

#### `destroy <BRANCH> [--yes] [--force]`

Tear down a worktree. `git worktree remove` + `rmtree` the directory.

| Flag        | Purpose                                                  |
| ----------- | -------------------------------------------------------- |
| `--yes`     | Skip the confirmation prompt.                            |
| `--force`   | Force-remove even if the worktree has uncommitted changes. |

### Examples

```bash
# Start work on a new feature (run from main repo root)
myah dev worktree create feat/cool-thing

# Same, but in OSS mode
myah dev worktree create feat/cool-thing --mode oss

# See what worktrees exist
myah dev worktree list

# Clean up after a merged PR
myah dev worktree destroy feat/cool-thing --yes
```

### Notes

- Per-worktree venvs are **real** (not symlinks). This eliminates the venv-corruption bug class where one worktree's `pip install` mutates main's venv.
- Per-worktree Hermes (`<worktree>/.hermes/`) eliminates the two-worktree-OSS-conflict bug class.
- The legacy `scripts/setup-worktree.sh` still works but prints a deprecation warning on every invocation and uses the older symlinked-venv topology.

---

## `myah dev backend / frontend / both`

**Class:** Native. Start the per-worktree dev servers. Run from **inside** a worktree.

### Synopsis

```bash
myah dev backend     # uvicorn on $BACKEND_PORT
myah dev frontend    # vite on $FRONTEND_PORT
myah dev both        # backend then frontend
```

### Behavior

- **Env composition order is locked:** `os.environ → platform-oss/.env → .worktree-env`. The per-worktree port overrides win. Reversing this order silently breaks attachment forwarding because `platform-oss/.env` ships with `MYAH_PLATFORM_PORT=8082` baked in.
- All three commands are **idempotent** — already-running returns 0.
- Logs go to `<worktree>/.worktree-logs/{backend,frontend}.log`.
- The backend uses the worktree's `<worktree>/.venv/bin/uvicorn` (absolute path, not PATH-resolved).

### Examples

```bash
cd .worktrees/feat/cool-thing
myah dev both
# Watch the live tail
myah dev logs
```

---

## `myah dev stop / restart / status`

**Class:** Native. Lifecycle for the per-worktree dev servers.

### Synopsis

```bash
myah dev stop        # SIGTERM, then SIGKILL after grace
myah dev restart     # stop + both
myah dev status      # Rich table: PIDs, ports, /health probe
```

### Notes

- `stop` reaps orphaned processes by port if the PID file is stale.
- `status` includes a `/health` probe against the backend port — green if 200, yellow if non-200, red if connection refused.

---

## `myah dev logs`

**Class:** Native. Unified parallel tail of `.worktree-logs/*` with color-coded prefixes.

### Synopsis

```bash
myah dev logs
```

No flags. Streams `backend.log` and `frontend.log` interleaved with `[backend]` / `[frontend]` prefixes. Ctrl-C stops.

---

## `myah dev mode`

**Class:** Native. Switch the current worktree between OSS and hosted modes by rewriting `platform-oss/.env`.

### Synopsis

```bash
myah dev mode oss      # MYAH_DEPLOYMENT_MODE=oss, MYAH_AUTH=false, comment out COMPOSIO_API_KEY / HONCHO_*
myah dev mode hosted   # MYAH_AUTH=true, comment out MYAH_DEPLOYMENT_MODE, copy COMPOSIO / HONCHO_* from main's .env
myah dev mode show     # Rich table of mode + relevant env state (secrets masked)
```

### Notes

- Bearer tokens + OAuth encryption key are **always preserved** across mode switches. A regression test exercises the full `hosted → oss → hosted` round-trip.
- After switching, the command prints a hint to restart backend/frontend. **Auto-restart is a follow-up** (`TODO(post-cli-cleanup)` in `cli/dev/mode.py:76`).
- Switching to hosted prints a hint to install `composio` + `honcho-ai` into the worktree venv if not present. **Auto-install is a follow-up** (`TODO(post-cli-cleanup)` in `cli/dev/mode.py:148`).

---

## `myah dev hermes`

**Class:** Native (link-main / unlink-main) + Pure wrapper (config).

Worktree-scoped Hermes operations + the escape hatch.

### Synopsis

```bash
myah dev hermes link-main           # loud [y/N] confirm, then point at ~/.hermes (escape hatch)
myah dev hermes unlink-main         # restore HERMES_HOME=<worktree>/.hermes (no confirm — safe direction)
myah dev hermes config show
myah dev hermes config edit         # opens $EDITOR with stdio passthrough
myah dev hermes config validate     # wraps `hermes config check`
```

### Notes

- `link-main` mutates `<worktree>/.worktree-env` to set `HERMES_HOME=$HOME/.hermes` (absolute path — `parse_env_file` doesn't expand `$HOME`).
- All `dev hermes config *` commands use `<worktree>/.venv/bin/hermes` (absolute path); they fail loudly if the venv hermes is missing.
- `config edit` uses `subprocess.run` directly (not `shell.run`) so `$EDITOR` can interact with the terminal.

---

## `myah dev plugin`

**Class:** Native. Local-dev workflow for the myah-hermes-plugin.

### Synopsis

```bash
myah dev plugin install-local <PATH>    # editable install from a local plugin checkout
myah dev plugin install-pinned          # reinstall plugin at the SHA in Dockerfile.stock
```

### Subcommands

#### `install-local <PATH>` — 7-step workflow

1. Validate `<PATH>/pyproject.toml` has `name = "myah-hermes-plugin"`.
2. `pip uninstall -y myah-hermes-plugin`.
3. `pip install -e <abspath>` — editable install pointing at the source tree.
4. Verify the `myah-hermes-plugin install --dashboard-only` flag still exists (it could be removed upstream — warn but don't abort).
5. **Re-materialize the dashboard shim.** Critical: without this, `<worktree>/.hermes/plugins/myah-admin/plugin_api.py` points at the OLD package while sys.path resolves to the new editable source — silent stale-import bug.
6. Sanity-check the shim resolves to the editable source. **LOUD warning** if not (does NOT abort).
7. Print a restart hint if backend/frontend are running.

#### `install-pinned`

Reinstall the plugin at the SHA pinned in `agent/Dockerfile.stock:183`. Reuses Slice 2's `install_plugin_into_hermes` + `materialize_dashboard_shim` primitives.

### Examples

```bash
cd .worktrees/feat/plugin-work
myah dev plugin install-local ../../myah-hermes-plugin   # editable
# ... edit, test, commit ...
myah dev plugin install-pinned                            # restore to canonical
```

---

## `myah dev oss`

**Class:** Native. Worktree-scoped `hermes gateway` + `hermes dashboard` lifecycle.

State (PID files, logs) lives in `<worktree>/.worktree-logs/` so two worktrees can run isolated OSS stacks in parallel.

### Synopsis

```bash
myah dev oss up        # spawn gateway + dashboard in background
myah dev oss down      # SIGTERM → SIGKILL after grace
myah dev oss restart   # down + up
myah dev oss status    # Rich table: PIDs, ports, /health
```

### Notes

- `up` is **idempotent** — skips spawn when the target port is already listening.
- After each spawn, a brief liveness check catches synchronous failures (e.g. config errors).
- The legacy `scripts/dev-oss.sh` (single shared `~/.hermes/.dev-oss/` instance) still works but prints a deprecation warning.

---

# Recipes

### First-time OSS install

```bash
curl -fsSL https://raw.githubusercontent.com/NousResearch/hermes-agent/main/scripts/install.sh | bash
git clone https://github.com/T3-Venture-Labs-Limited/myah && cd myah
pip install -e .
myah install
myah platform up
myah agent up
# Open http://localhost:8080
```

### Day-to-day OSS lifecycle

```bash
myah agent up                                    # start the agent (idempotent)
myah doctor                                      # diagnose
myah logs gateway -f                             # tail Hermes gateway
myah logs platform -n 100                        # last 100 platform lines
myah env set --scope hermes OPENROUTER_API_KEY sk-or-v1-...
myah plugins update myah
myah upgrade --check                             # is an upgrade available?
myah upgrade                                     # run full 3-step upgrade
```

### Teardown

```bash
myah uninstall --keep-data           # keep chats, remove platform + hermes
myah uninstall --keep-config         # keep .env, remove DB
myah uninstall                       # full nuke (with confirm)
myah uninstall --yes                 # full nuke, no prompt (cron-safe)
```

### Per-branch developer workflow (a feature PR)

```bash
# From main repo root
myah dev worktree create feat/cool-thing
cd .worktrees/feat/cool-thing
myah dev both                         # backend + frontend
myah dev status                       # confirm running
myah dev logs                         # live tail
# ... edit, test, commit ...
myah dev stop
cd ../..
# After merge:
myah dev worktree destroy feat/cool-thing --yes
```

### Per-branch plugin local-dev

```bash
cd .worktrees/feat/plugin-work
myah dev plugin install-local ~/code/myah-hermes-plugin
myah dev oss restart                  # apply the new plugin
# ... edit plugin, test, commit ...
myah dev plugin install-pinned        # restore to the Dockerfile pin
```

### Mode-switching a worktree (hosted ↔ OSS)

```bash
cd .worktrees/feat/cool-thing
myah dev mode show                    # what mode am I in?
myah dev mode oss                     # switch to OSS
myah dev restart                      # apply new mode
```

### Hermes escape hatch (when you specifically want to share main's Hermes)

```bash
cd .worktrees/feat/cool-thing
myah dev hermes link-main             # loud confirm: HERMES_HOME=$HOME/.hermes
# ... do whatever needs main's Hermes ...
myah dev hermes unlink-main           # restore worktree-local Hermes
```

---

# Troubleshooting

### `myah install` fails at Phase 5 (plugin install)

The plugin install requires interactive credentials by default (it prompts for `MYAH_ADAPTER_AUTH_KEY`). `myah install` pre-writes the `.env` before invoking, so the prompt is skipped — but if you ran a partial install that didn't reach the env-write step, you may see this prompt. Re-run with `--rotate` to force fresh tokens.

### `myah doctor` reports "MYAH plugin SHA drift"

Your installed plugin's SHA doesn't match `agent/Dockerfile.stock:183`. Run `myah plugins update myah` (or `myah dev plugin install-pinned` from a worktree). The warning is informational and never fails CI.

### `myah dev backend` fails with "hermes binary not found"

The worktree's venv is missing or incomplete. Re-create the worktree:

```bash
myah dev worktree destroy <branch> --yes
myah dev worktree create <branch>
```

The "fail loudly" path here is intentional — the alternative (silently falling back to the system Hermes) was the cause of the original venv-corruption + wrong-version bug class.

### Cold-start of `myah --help` feels slow

The `myah --help` cold-start median is ~205ms on Apple Silicon (target was <200ms; current state). The benchmark is `@pytest.mark.slow` and not gated. A follow-up profiling pass is in the post-CLI cleanup backlog. Day-to-day commands are unaffected.

### Production deploy after merge cancelled by next merge

GitHub's concurrent-deploy guard. The most recent SHA's deploy will run to completion. Use `gh run list --workflow=deploy.yml --branch=master --limit 5` to see the chain.

---

# Known gaps

These are documented in the spec but not yet implemented; they're tracked in the post-CLI cleanup backlog (Linear T3-1084 completion comment):

| Gap                                              | Workaround                                                      | Tracked at                            |
| ------------------------------------------------ | --------------------------------------------------------------- | ------------------------------------- |
| `pip install -U myah` in `myah upgrade`          | `git pull && pip install -e .`                                  | `cli/upgrade.py:105` TODO marker      |
| Auto-restart on `myah dev mode` switch           | Run `myah dev restart` manually                                  | `cli/dev/mode.py:76` TODO marker      |
| Auto-install composio + honcho on hosted-mode switch | Run `pip install composio honcho-ai` in the worktree venv       | `cli/dev/mode.py:148` TODO marker     |
| `env list` graceful degradation outside a clone  | Pass `--scope hermes` explicitly                                 | T3-1084 follow-up                     |
| `myah-cli` PyPI subset                            | n/a — currently shipped inside the platform wheel                | T3-1084 follow-up                     |

For the design rationale on what's intentionally **not** implemented (e.g. `--share-models`, `--resume`), see the spec's *Non-Goals* and *Open Questions* sections.

---

## See also

- **Spec:** `docs/superpowers/specs/2026-05-22-devx-oss-cli-design.md` — design rationale, locked-in decisions, risk register
- **Plan:** `docs/superpowers/plans/2026-05-22-devx-oss-cli.md` — task-by-task TDD plan
- **Spike findings:** `docs/superpowers/specs/2026-05-22-devx-oss-cli-spike-findings.md` — Slice 0 viability investigation
- **AGENTS.md** — *Myah CLI* and *Worktree Dev Loop* sections (developer onboarding)
- **`myah <command> --help`** — every command has detailed inline help; the doc above is the consolidated reference but inline help is the source of truth for flags.
