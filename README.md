# Myah

A self-hostable chat platform for [Hermes Agent](https://hermes-agent.nousresearch.com).
Single-user, BYO Hermes, Docker Compose.

## Quickstart

You need Docker, `git`, Python 3.11+, and a machine to run [Hermes
Agent](https://hermes-agent.nousresearch.com) on. macOS and Linux are
the supported install paths today; Windows works via WSL2.

```bash
# 1. Install Hermes Agent (one-time, BYO).
#    Installs uv + Python 3.11 + Node 22 + a hermes launcher at ~/.local/bin/hermes
#    Windows: see https://hermes-agent.nousresearch.com/docs/install
curl -fsSL https://raw.githubusercontent.com/NousResearch/hermes-agent/main/scripts/install.sh | bash

# 2. Clone and install Myah
git clone https://github.com/T3-Venture-Labs-Limited/myah && cd myah
python3 -m venv .venv && source .venv/bin/activate
MYAH_SKIP_HATCH_NPM=1 pip install -e .
# The venv keeps us out of Ubuntu 24.04 / Debian 12+ PEP 668 territory.
# MYAH_SKIP_HATCH_NPM=1 skips the frontend build step inside hatch_build.py
# (the OSS install pulls a prebuilt platform container later, so the
# editable wheel doesn't need its own frontend build). See docs/cli-reference.md
# §Installation for the full rationale and the no-skip path.

# 3. Run the installer (replaces the legacy setup-myah-oss.sh)
myah install
#   - generates aligned platform↔Hermes secrets (5-slot bearer)
#   - installs + registers + enables the Myah plugin at the pinned SHA
#     (pip install + `hermes plugins install` + `hermes plugins enable myah`)
#   - merges ~/.hermes/config.yaml (enables myah platform)
#   - optionally installs systemd/launchd units for always-on
#   - --openrouter-key sk-or-v1-... skips the credential prompt
#   - --non-interactive --service none is the CI-safe form

# 4. Start the stack
myah platform up                # FastAPI + UI (docker compose up -d)
myah agent up                   # Hermes gateway + dashboard via systemd/launchd

# 5. Open http://localhost:8080
```

On first open Myah probes your Hermes; if everything is wired up the
welcome screen lands directly in chat. If anything is off,
`myah doctor` tells you exactly what to fix.

## Day-to-day

```bash
myah doctor                                            # diagnose the whole stack
myah status                                            # what's running, on what ports
myah logs gateway -f                                   # tail Hermes gateway
myah logs platform -n 100                              # last 100 platform-container lines
myah env set --scope hermes OPENROUTER_API_KEY sk-...  # add/update an LLM provider key
myah plugins update myah                               # bump the Myah plugin
myah upgrade --check                                   # is an update available?
myah upgrade                                           # full upgrade (Hermes + git + docker)
```

For the full reference of every flag and subcommand, see
[`docs/cli-reference.md`](./docs/cli-reference.md).

## How OSS is laid out

Myah OSS runs **two Hermes processes plus one Docker container**:

| Process | Default port | Purpose |
|---|---|---|
| `hermes gateway` | 8642 / 8643 | Chat I/O + Myah plugin endpoints |
| `hermes dashboard --no-open --insecure --host 0.0.0.0` | 9119 | Provider configuration, OAuth flows, model catalog |
| `docker compose up` (myah-platform) | 8080 | Web UI, API |

Two Hermes processes is by design. The dashboard is what makes "Add
Provider" and OAuth flows work in the OSS UI. If you don't run the
dashboard, the welcome screen still works (it uses the gateway for
liveness probes) but the settings page is empty.

`myah agent up` starts both Hermes processes via the OS supervisor
(systemd-user on Linux, launchd on macOS) that `myah install` set up.
`myah platform up` starts the third component (the FastAPI/UI
container) via Docker Compose.

### Network exposure

By default the platform binds to `127.0.0.1:8080` (loopback only) and
the dashboard binds to `0.0.0.0:9119` so the platform container can
reach it via `host.docker.internal`. The dashboard binding means port
9119 is reachable from your LAN. If your machine is on an untrusted
network, add a firewall rule blocking port 9119 from non-loopback
interfaces.

## Updating

```bash
cd myah
myah upgrade --check        # see what would change
myah upgrade                # bump Hermes + plugin + platform image + Myah source
```

`myah upgrade` is a composite of three steps:
1. `hermes update` — bump the Hermes runtime.
2. `git pull` — refresh the Myah source (skipped + warned on a dirty tree, or if Myah isn't installed via clone).
3. `docker compose pull` — pull the newest platform image.

To pin to a specific version for reproducible installs:

```bash
export MYAH_PLATFORM_IMAGE=ghcr.io/t3-venture-labs-limited/myah-platform-oss:0.1.0-beta.1
docker compose up -d
```

Available image tags: https://github.com/T3-Venture-Labs-Limited/myah/pkgs/container/myah-platform-oss

## Uninstalling

```bash
myah uninstall                 # full removal (with confirmation prompt)
myah uninstall --keep-data     # preserve chats + Hermes data, remove platform container + .env
myah uninstall --keep-config   # preserve platform .env and Hermes config, remove data
myah uninstall --yes           # cron-safe: full removal, no prompt
```

## Troubleshooting

| Symptom | Try |
|---|---|
| Blank page on first load | `myah logs platform`; `myah doctor` |
| `myah status` shows a component "stopped" but the app works | An older Hermes process holds the port; `pkill -f "hermes gateway" && pkill -f "hermes dashboard" && myah agent up` |
| Settings page empty | Confirm `hermes dashboard` is running: `curl -s -o /dev/null -w '%{http_code}\n' http://localhost:9119/` should return any HTTP code (200 / 401 / 404 are all "running") |
| Provider key in `~/.hermes/.env` not detected | Use `myah env set --scope hermes OPENROUTER_API_KEY sk-or-v1-...` then `myah agent restart` |
| `:8643/myah/health` connection refused | `myah install` (idempotent) — it ensures `gateway.platforms.myah.enabled: true` in `~/.hermes/config.yaml` |
| Sending a message with an attachment fails with 500 `Adapter missing MYAH_PLATFORM_BASE_URL / MYAH_PLATFORM_BEARER env` | Your `~/.hermes/.env` was bootstrapped by an older `setup-myah-oss.sh` that didn't write the attachment-fetch bearer. Run `myah install` (it now writes `MYAH_PLATFORM_BEARER` and migrates the broken legacy `MYAH_PLATFORM_BASE_URL`), then `myah agent restart` |

For a complete diagnostic, run `myah doctor` — it checks plugin SHA
drift, port alignment, service-unit health, and attachment-pipeline
env injection in one pass.

## CLI reference

The full `myah` CLI reference — every command, every flag, recipes,
troubleshooting, known gaps — lives at
[`docs/cli-reference.md`](./docs/cli-reference.md).

For developers contributing back, the `myah dev *` namespace (hidden
from `myah --help`) covers per-worktree isolation, mode switching, the
Hermes escape hatch, plugin local-dev, and per-worktree dev servers.

## Legacy bash scripts

The original install/lifecycle bash scripts are still in `scripts/`
but they now print loud deprecation warnings and recommend the
equivalent `myah` command. They will be deleted in a future release.

| Old | New |
|---|---|
| `./scripts/setup-myah-oss.sh` | `myah install` |
| `./scripts/dev-oss.sh up` | `myah agent up && myah platform up` |
| `./scripts/dev-oss.sh status` | `myah status` |
| `./scripts/verify-hermes-plugins-install.sh` | `myah plugins list` (Myah plugin row) |

## License

AGPL-3.0-or-later (see [`LICENSE`](./LICENSE)). For closed-source SaaS
deployments and embedded distribution, contact hello@myah.dev for
commercial licensing terms.

The Myah plugin lives in a separate repo,
[`T3-Venture-Labs-Limited/myah-hermes-plugin`](https://github.com/T3-Venture-Labs-Limited/myah-hermes-plugin),
under the MIT license.
