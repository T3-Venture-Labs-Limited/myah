# Myah

Myah is a self-hosted web chat interface for [Hermes Agent](https://hermes-agent.nousresearch.com).

It is built for people who already have Hermes on their computer and want a local web UI without creating a hosted Myah account.

## What you need

Before you start, make sure you already have:

- Hermes Agent installed and working (`hermes --help` should run)
- Docker with Docker Compose v2 (`docker compose version` should run)
- `git`
- Python 3.11+
- macOS, Linux, or Windows via WSL2

> Myah does not install Hermes for you. If Hermes is not installed yet, follow the Hermes docs first, then come back here.

## Quickstart

From a terminal:

```bash
# 1. Get Myah
git clone https://github.com/T3-Venture-Labs-Limited/myah
cd myah

# 2. Install the `myah` CLI in a local virtualenv
python3 -m venv .venv
source .venv/bin/activate
MYAH_SKIP_HATCH_NPM=1 pip install -e .

# 3. Connect Myah to your existing Hermes install
myah install

# 4. Start everything
myah agent up
myah platform up

# 5. Open Myah
open http://localhost:8080  # macOS
# or visit http://localhost:8080 in your browser
```

That is the normal path. After the first run, day-to-day startup is just:

```bash
cd myah
source .venv/bin/activate
myah agent up
myah platform up
```

## What each step does

### `pip install -e .`

Installs the `myah` command into this repo's `.venv`.

We use `MYAH_SKIP_HATCH_NPM=1` because normal OSS users run the prebuilt Myah Docker image. You do not need to build the Svelte frontend locally just to use Myah.

### `myah install`

Connects Myah to your existing Hermes setup. It is safe to re-run.

It will:

- create the shared secrets that let Myah and Hermes talk to each other
- install and enable the Myah Hermes plugin at the pinned version
- update your Hermes config so the Myah gateway routes are enabled
- install service units for the Hermes gateway and dashboard on macOS/Linux, unless you choose otherwise
- run a post-install check

If you want to provide an OpenRouter key during setup:

```bash
myah install --openrouter-key sk-or-v1-...
```

For CI or scripted setup:

```bash
myah install --non-interactive --service none
```

### `myah agent up`

Starts the Hermes-side processes that Myah needs:

- Hermes gateway: chat and agent API
- Hermes dashboard: provider configuration and OAuth/model UI

On Linux this uses systemd-user. On macOS this uses launchd. These are installed by `myah install`.

### `myah platform up`

Starts the Myah web app container with Docker Compose.

The app is available at:

```text
http://localhost:8080
```

## How it is laid out

Myah OSS runs your existing Hermes on the host plus one Docker container:

| Component | Default port | Purpose |
|---|---:|---|
| Hermes API | 8642 | chat runs, health checks, jobs API |
| Myah Hermes plugin | 8643 | Myah-specific plugin endpoints |
| Hermes dashboard | 9119 | provider setup, OAuth, model catalog |
| Myah platform container | 8080 | web UI and platform API |

The platform container talks back to your host Hermes through `host.docker.internal`.

## Useful commands

```bash
myah status                                            # show what is running
myah doctor                                            # diagnose the whole stack
myah logs platform -f                                  # tail the Myah container logs
myah logs gateway -f                                   # tail Hermes gateway logs
myah env set --scope hermes OPENROUTER_API_KEY sk-...  # add/update a provider key
myah plugins list                                      # verify the Myah plugin
myah plugins update myah                               # update the Myah plugin
myah agent restart                                     # restart Hermes gateway + dashboard
myah platform restart                                  # restart the Myah container
myah upgrade --check                                   # check for updates
myah upgrade                                           # update Hermes + Myah + platform image
```

For every command and flag, see [`docs/cli-reference.md`](./docs/cli-reference.md).

## Network exposure

By default:

- Myah binds to `127.0.0.1:8080`, so it is only reachable from your machine.
- The Hermes dashboard binds to `0.0.0.0:9119` so the Docker container can reach it.

That means port `9119` may be reachable from your LAN. On an untrusted network, block port `9119` from non-local traffic with your firewall.

If you intentionally expose Myah beyond localhost, also enable auth and rotate secrets first. The root `docker-compose.yml` comments show the advanced settings.

## Updating

```bash
cd myah
source .venv/bin/activate
myah upgrade --check
myah upgrade
```

`myah upgrade` runs three update steps:

1. `hermes update`
2. `git pull` for this Myah checkout
3. `docker compose pull` for the platform image

To pin the platform image to a specific version:

```bash
export MYAH_PLATFORM_IMAGE=ghcr.io/t3-venture-labs-limited/myah-platform-oss:0.1.0-beta.1
docker compose up -d
```

Available image tags: https://github.com/T3-Venture-Labs-Limited/myah/pkgs/container/myah-platform-oss

## Uninstalling

```bash
myah uninstall                 # full removal, with confirmation prompt
myah uninstall --keep-data     # preserve chats + Hermes data
myah uninstall --keep-config   # preserve platform .env and Hermes config
myah uninstall --yes           # no prompt
```

## Troubleshooting

Start here:

```bash
myah doctor
myah status
```

Common fixes:

| Symptom | Try |
|---|---|
| Blank page on first load | `myah logs platform -n 100` then `myah doctor` |
| `myah status` says a component is stopped but the app works | An older Hermes process may own the port. Run `pkill -f "hermes gateway" && pkill -f "hermes dashboard" && myah agent up`. |
| Settings page is empty | Check the dashboard: `curl -s -o /dev/null -w '%{http_code}\n' http://localhost:9119/`. Any HTTP code means it is running. Then run `myah agent restart`. |
| Provider key in `~/.hermes/.env` is not detected | Run `myah env set --scope hermes OPENROUTER_API_KEY sk-or-v1-...` then `myah agent restart`. |
| `:8643/myah/health` connection refused | Re-run `myah install`, then `myah agent restart`. |
| Attachment send fails with `Adapter missing MYAH_PLATFORM_BASE_URL / MYAH_PLATFORM_BEARER env` | You likely used an older setup script. Re-run `myah install`, then `myah agent restart`. |

## Legacy scripts

The old bash scripts in `scripts/` are deprecated. Use the `myah` CLI instead:

| Old | New |
|---|---|
| `./scripts/setup-myah-oss.sh` | `myah install` |
| `./scripts/dev-oss.sh up` | `myah agent up && myah platform up` |
| `./scripts/dev-oss.sh status` | `myah status` |
| `./scripts/verify-hermes-plugins-install.sh` | `myah plugins list` |

## License

AGPL-3.0-or-later. For closed-source SaaS deployments and embedded distribution, contact hello@myah.dev for commercial licensing terms.

The Myah plugin lives in a separate repo, [`T3-Venture-Labs-Limited/myah-hermes-plugin`](https://github.com/T3-Venture-Labs-Limited/myah-hermes-plugin), under the MIT license.
