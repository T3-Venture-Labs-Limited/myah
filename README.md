# Myah

A self-hostable chat platform for [Hermes Agent](https://hermes-agent.nousresearch.com).
Single-user, BYO Hermes, Docker Compose.

## Quickstart

You need Docker, `git`, and a machine to run [Hermes
Agent](https://hermes-agent.nousresearch.com) on. macOS and Linux are
the supported install paths today; Windows works via WSL2.

```bash
# 1. Install Hermes Agent (one-time, BYO).
#    Installs uv + Python 3.11 + Node 22 + a hermes launcher at ~/.local/bin/hermes
#    Windows: see https://hermes-agent.nousresearch.com/docs/install
curl -fsSL https://raw.githubusercontent.com/NousResearch/hermes-agent/main/scripts/install.sh | bash

# 2. Install the Myah plugin into your Hermes
hermes plugins install T3-Venture-Labs-Limited/myah-hermes-plugin

# 3. Add at least one LLM provider key to ~/.hermes/.env. Pick one:
echo 'OPENROUTER_API_KEY=sk-or-v1-...' >> ~/.hermes/.env
# or OPENAI_API_KEY, ANTHROPIC_API_KEY, KIMI_API_KEY, etc.

# 4. Clone and bootstrap Myah
git clone https://github.com/T3-Venture-Labs-Limited/myah && cd myah
./scripts/setup-myah-oss.sh         # generates shared platform↔hermes secrets

# 5. Start everything
./scripts/dev-oss.sh up             # starts hermes gateway + hermes dashboard + platform container
                                    # (first run builds the platform image locally, ~5 min)

# 6. Open http://localhost:8080
```

On first open Myah probes your Hermes; if everything is wired up the
welcome screen lands directly in chat. If anything is off, a blocking
error screen tells you exactly what to fix.

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

`./scripts/dev-oss.sh up` starts all three. For always-on usage, pick
the `systemd` (Linux) or `launchd` (macOS) option when
`./scripts/setup-myah-oss.sh` prompts.

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
git pull origin master           # picks up the latest pinned plugin + hermes SHAs
docker compose pull              # pulls the newest platform image
./scripts/setup-myah-oss.sh      # re-installs the plugin at the new pinned SHA
./scripts/dev-oss.sh restart     # restart everything against the new versions
```

The `:latest` image tag follows the newest tagged release on the public
repo. To pin to a specific version for reproducible installs:

```bash
export MYAH_PLATFORM_IMAGE=ghcr.io/t3-venture-labs-limited/myah-platform-oss:0.1.0-beta.1
docker compose up -d
```

Available image tags: https://github.com/T3-Venture-Labs-Limited/myah/pkgs/container/myah-platform-oss

## Troubleshooting

| Symptom | Try |
|---|---|
| Blank page on first load | `docker compose logs platform`; check that `./scripts/setup-myah-oss.sh` ran cleanly |
| `dev-oss.sh status` shows component "stopped" but the app works | An older Hermes process holds the port; `pkill -f "hermes gateway" && pkill -f "hermes dashboard" && ./scripts/dev-oss.sh up` |
| Settings page empty | Confirm `hermes dashboard` is running: `curl -s -o /dev/null -w '%{http_code}\n' http://localhost:9119/` should return any HTTP code (200 / 401 / 404 are all "running") |
| Provider key in `~/.hermes/.env` not detected | Restart hermes processes after editing `~/.hermes/.env`: `./scripts/dev-oss.sh restart` |
| `:8643/myah/health` connection refused | Re-run `./scripts/setup-myah-oss.sh` — it ensures `gateway.platforms.myah.enabled: true` in `~/.hermes/config.yaml` |

## License

AGPL-3.0-or-later (see [`LICENSE`](./LICENSE)). For closed-source SaaS
deployments and embedded distribution, contact hello@myah.dev for
commercial licensing terms.

The Myah plugin lives in a separate repo,
[`T3-Venture-Labs-Limited/myah-hermes-plugin`](https://github.com/T3-Venture-Labs-Limited/myah-hermes-plugin),
under the MIT license.
