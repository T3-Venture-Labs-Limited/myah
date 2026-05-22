#!/usr/bin/env bash
# scripts/dev-oss.sh — start/stop/restart the OSS-mode dev stack.
#
# Convenience wrapper around `hermes gateway run`, `hermes dashboard --no-open
# --insecure --host 0.0.0.0`, and `docker compose`. Use this for ephemeral
# local-dev workflows; for always-on production-style usage prefer the
# systemd-user or launchd units that setup-myah-oss.sh can install (see
# --service flag).
#
# Defaults match what platform-oss/backend/myah/utils/hermes_web.py
# expects:
#   gateway   — port 8643 (MYAH_GATEWAY_PORT)
#   dashboard — port 9119 (MYAH_HERMES_WEB_PORT)
#   platform  — port 8080 (loopback, via docker compose)
#
# Dashboard launch flags --insecure --host 0.0.0.0 are required so the
# platform docker container can reach the dashboard via
# host.docker.internal:host-gateway (which resolves to the host bridge IP
# on Linux). Security implication (LAN exposure) documented in
# docs/gotchas/2026-05-17-oss-dashboard-lan-exposure.md.
#
# State (pidfiles, logs) lives in ~/.hermes/.dev-oss/ — outside the
# repo so multiple checkouts can share a single OSS test instance.
#
# Usage:
#   scripts/dev-oss.sh up                # start everything
#   scripts/dev-oss.sh down              # stop everything
#   scripts/dev-oss.sh restart           # stop + start
#   scripts/dev-oss.sh status            # PIDs, ports, health
#   scripts/dev-oss.sh doctor            # diagnose the OSS dev environment
#   scripts/dev-oss.sh logs <component>  # tail logs (gateway|dashboard|platform)
#   scripts/dev-oss.sh dashboard {start|stop|restart}  # dashboard only
#   scripts/dev-oss.sh gateway   {start|stop|restart}  # gateway only
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
HERMES_HOME_DIR="${HERMES_HOME:-$HOME/.hermes}"
DEV_DIR="$HERMES_HOME_DIR/.dev-oss"
mkdir -p "$DEV_DIR"

# Augment PATH with the canonical Hermes install location so `command -v
# hermes` works even when invoked from a non-interactive SSH shell that
# didn't source the user's .bashrc / .profile. Idempotent — only prepends
# if not already present.
case ":$PATH:" in
  *":$HOME/.local/bin:"*) ;;
  *) export PATH="$HOME/.local/bin:$PATH" ;;
esac

# Resolve the hermes binary once and fail loudly if not found, instead of
# letting nohup silently background a `hermes: command not found` and
# logging it to a per-component log the user has to think to inspect.
HERMES_BIN="$(command -v hermes || true)"
if [[ -z "$HERMES_BIN" ]]; then
  echo "✗ 'hermes' not found on PATH ($PATH)" >&2
  echo "  Install Hermes via the upstream installer and ensure ~/.local/bin" >&2
  echo "  is in your PATH (or symlink hermes to /usr/local/bin)." >&2
  exit 1
fi

pidfile_for()  { echo "$DEV_DIR/$1.pid"; }
logfile_for()  { echo "$DEV_DIR/$1.log"; }

is_running() {
  local pidfile
  pidfile="$(pidfile_for "$1")"
  [[ -f "$pidfile" ]] && kill -0 "$(cat "$pidfile")" 2>/dev/null
}

start_component() {
  local name="$1"
  shift
  if is_running "$name"; then
    echo "✓ $name already running (pid=$(cat "$(pidfile_for "$name")"))"
    return
  fi
  local logfile pidfile
  logfile="$(logfile_for "$name")"
  pidfile="$(pidfile_for "$name")"
  nohup "$@" >"$logfile" 2>&1 &
  echo $! > "$pidfile"
  # Brief startup verification — if the command bailed immediately (e.g.
  # 'command not found', port in use), the process is already gone by
  # the time start_component returns. Without this check the script
  # claimed "started" and the caller had to discover the failure via
  # the next status command. 500ms is enough to catch synchronous
  # exits without blocking real startup (gateway/dashboard take ~3s
  # to bind their ports).
  sleep 0.5
  if ! is_running "$name"; then
    echo "✗ $name failed to start — process exited immediately" >&2
    echo "  Log (last 10 lines from $logfile):" >&2
    tail -n 10 "$logfile" 2>&1 | sed 's/^/    /' >&2
    rm -f "$pidfile"
    return 1
  fi
  echo "✓ $name started (pid=$(cat "$pidfile"), logs=$logfile)"
}

stop_component() {
  local name="$1"
  local pidfile
  pidfile="$(pidfile_for "$name")"
  if [[ ! -f "$pidfile" ]]; then
    echo "✓ $name not running"
    return
  fi
  local pid
  pid="$(cat "$pidfile")"
  if kill -0 "$pid" 2>/dev/null; then
    # SIGTERM first; SIGKILL after 5s if still up.
    #
    # NOTE: `nohup cmd &` doesn't create a new process group — the child
    # inherits the parent shell's PGID, so a `kill -- -$pid` would target a
    # non-existent group. We don't `setsid` to create one because `setsid`
    # isn't on the macOS base install. In practice Hermes gateway and
    # dashboard run as single processes (asyncio internally, no forked
    # workers), so a single-pid SIGTERM is sufficient. If we ever switch
    # to a process model that forks workers, prepend `setsid` to the
    # `nohup` line in start_component and the existing pgrp-kill branch
    # below will start being load-bearing.
    kill -TERM "$pid" 2>/dev/null || true
    for _ in 1 2 3 4 5; do
      kill -0 "$pid" 2>/dev/null || break
      sleep 1
    done
    if kill -0 "$pid" 2>/dev/null; then
      kill -KILL "$pid" 2>/dev/null || true
    fi
  fi
  rm -f "$pidfile"
  echo "✓ $name stopped"
}

probe_port() {
  local port="$1"
  if command -v nc >/dev/null 2>&1; then
    nc -z 127.0.0.1 "$port" 2>/dev/null && echo "open" || echo "closed"
  else
    timeout 1 bash -c "</dev/tcp/127.0.0.1/$port" 2>/dev/null && echo "open" || echo "closed"
  fi
}

print_status() {
  local port pid_status docker_status
  printf "%-12s %-12s %-10s %s\n" COMPONENT STATUS PORT HEALTH
  for c in gateway dashboard; do
    case "$c" in
      gateway)   port=8643 ;;
      dashboard) port=9119 ;;
    esac
    pid_status="stopped"
    is_running "$c" && pid_status="running($(cat "$(pidfile_for "$c")"))"
    printf "%-12s %-12s %-10s %s\n" "$c" "$pid_status" "$port" "$(probe_port "$port")"
  done
  docker_status="stopped"
  # docker-compose.yml:44 names the service 'platform' (container_name is
  # 'myah-platform' which is a different identifier and not what
  # `docker compose ps -q` accepts).
  if (cd "$ROOT" && docker compose ps -q platform 2>/dev/null | grep -q .); then
    docker_status="running"
  fi
  printf "%-12s %-12s %-10s %s\n" "platform" "$docker_status" "8080" "$(probe_port 8080)"
}

# `doctor` — environment diagnostic. Cheaper than `up + status` because
# it doesn't try to start anything; just inspects state. Each check
# prints ✓ on success and ✗ + a one-line "→ Fix: …" suggestion on
# failure. Useful first stop when a fresh OSS install or an upgrade
# leaves the user staring at a 401 / cron-no-output / "Plugin not
# installed" banner. See gotchas/2026-05-19-oss-*.md for the
# documented failure modes this exercises.
doctor() {
  local hermes_env="${HERMES_HOME_DIR}/.env"
  # Public layout: .env lives at the repo root (no platform-oss/ subdir).
  # The internal monorepo equivalent is platform-oss/.env; MYAH_PLATFORM_ENV
  # overrides for non-standard checkouts.
  local platform_env="${MYAH_PLATFORM_ENV:-$ROOT/.env}"
  echo "Myah OSS environment diagnostic:"

  # 1. gateway running?
  if pgrep -f 'hermes gateway' >/dev/null 2>&1; then
    local gw_pid
    gw_pid=$(pgrep -f 'hermes gateway' | head -1)
    echo "  ✓ Gateway running (PID $gw_pid)"
  else
    echo "  ✗ Gateway NOT running"
    echo "    → Fix: ./scripts/dev-oss.sh up"
  fi

  # 2. dashboard running?
  if pgrep -f 'hermes dashboard' >/dev/null 2>&1; then
    local dash_pid
    dash_pid=$(pgrep -f 'hermes dashboard' | head -1)
    echo "  ✓ Dashboard running (PID $dash_pid)"
  else
    echo "  ✗ Dashboard NOT running"
    echo "    → Fix: ./scripts/dev-oss.sh up"
  fi

  # 3. platform .env exists?
  if [[ -f "$platform_env" ]]; then
    echo "  ✓ Platform .env exists ($platform_env)"
  else
    echo "  ✗ Platform .env NOT found at $platform_env"
    echo "    → Fix: cp $ROOT/.env.example $platform_env  (or re-run scripts/setup-myah-oss.sh)"
  fi

  # 4. MYAH_PLATFORM_BASE_URL in hermes .env (Task 3.5 gotcha).
  if [[ -f "$hermes_env" ]]; then
    local hermes_url
    hermes_url=$(grep '^MYAH_PLATFORM_BASE_URL=' "$hermes_env" 2>/dev/null | tail -n1 | cut -d= -f2-)
    if [[ -n "$hermes_url" ]]; then
      echo "  ✓ MYAH_PLATFORM_BASE_URL = $hermes_url"
      if [[ "$hermes_url" != "http://host.docker.internal:8080" ]] \
         && [[ "$hermes_url" != "http://localhost:8080" ]]; then
        echo "    ⚠ Non-canonical value — expected http://host.docker.internal:8080 or http://localhost:8080"
        echo "      → Fix: re-run scripts/setup-myah-oss.sh (idempotent, overwrites stale value)"
      fi
    else
      echo "  ✗ MYAH_PLATFORM_BASE_URL not set in $hermes_env"
      echo "    → Fix: re-run scripts/setup-myah-oss.sh"
    fi
  else
    echo "  ✗ $hermes_env not found"
    echo "    → Fix: re-run scripts/setup-myah-oss.sh"
  fi

  # 5. MYAH_AGENT_BEARER_TOKEN alignment between platform .env and ~/.hermes/.env.
  if [[ -f "$hermes_env" ]] && [[ -f "$platform_env" ]]; then
    local hermes_token platform_token
    hermes_token=$(grep '^MYAH_AGENT_BEARER_TOKEN=' "$hermes_env" 2>/dev/null | tail -n1 | cut -d= -f2-)
    platform_token=$(grep '^MYAH_AGENT_BEARER_TOKEN=' "$platform_env" 2>/dev/null | tail -n1 | cut -d= -f2-)
    if [[ -n "$hermes_token" ]] && [[ "$hermes_token" == "$platform_token" ]]; then
      echo "  ✓ MYAH_AGENT_BEARER_TOKEN aligned (platform .env ↔ ~/.hermes/.env)"
    elif [[ -z "$hermes_token" && -z "$platform_token" ]]; then
      echo "  ✗ MYAH_AGENT_BEARER_TOKEN missing from both .envs"
      echo "    → Fix: re-run scripts/setup-myah-oss.sh"
    else
      echo "  ✗ MYAH_AGENT_BEARER_TOKEN mismatch (or missing on one side)"
      echo "    → Fix: re-run scripts/setup-myah-oss.sh"
    fi
  fi

  # 6. ports reachable?
  for port_pair in "platform 8080" "gateway 8642" "gateway-secondary 8643" "dashboard 9119"; do
    local name=${port_pair%% *}
    local port=${port_pair##* }
    if [[ "$(probe_port "$port")" == "open" ]]; then
      echo "  ✓ Port $port ($name) reachable"
    else
      echo "  ✗ Port $port ($name) NOT reachable"
    fi
  done

  # 7. plugin installed?
  if command -v hermes >/dev/null 2>&1; then
    if hermes plugins list 2>/dev/null | grep -qE '(^|[[:space:]])myah([[:space:]]|$)'; then
      echo "  ✓ Plugin myah installed"
    else
      echo "  ✗ Plugin myah NOT installed"
      echo "    → Fix: hermes plugins install T3-Venture-Labs-Limited/myah-hermes-plugin"
    fi
  else
    echo "  ✗ hermes binary not on PATH"
    echo "    → Fix: curl -fsSL https://raw.githubusercontent.com/NousResearch/hermes-agent/main/scripts/install.sh | bash"
  fi
}

case "${1:-status}" in
  up)
    start_component gateway   "$HERMES_BIN" gateway run
    # --insecure --host 0.0.0.0 required for Docker→dashboard reach; see
    # spec §13 risk row on LAN exposure.
    start_component dashboard "$HERMES_BIN" dashboard --no-open --insecure --host 0.0.0.0
    (cd "$ROOT" && docker compose up -d)
    echo
    echo "All up. Open http://localhost:8080"
    ;;
  down)
    stop_component gateway
    stop_component dashboard
    (cd "$ROOT" && docker compose down) || true
    ;;
  restart)
    "$0" down
    sleep 1
    "$0" up
    ;;
  status)
    print_status
    ;;
  doctor)
    doctor
    ;;
  logs)
    case "${2:-}" in
      gateway|dashboard)
        tail -f "$(logfile_for "$2")"
        ;;
      platform)
        # Service name (per docker-compose.yml:44) is 'platform' — not the
        # container_name 'myah-platform'.
        (cd "$ROOT" && docker compose logs -f platform)
        ;;
      *)
        echo "usage: $0 logs {gateway|dashboard|platform}" >&2
        exit 2
        ;;
    esac
    ;;
  gateway|dashboard)
    # Dashboard needs --insecure --host 0.0.0.0; gateway doesn't.
    if [[ "$1" = dashboard ]]; then
      launch_args=(dashboard --no-open --insecure --host 0.0.0.0)
    else
      launch_args=(gateway run)
    fi
    case "${2:-}" in
      start)   start_component "$1" "$HERMES_BIN" "${launch_args[@]}" ;;
      stop)    stop_component "$1" ;;
      restart) stop_component "$1"; sleep 1; start_component "$1" "$HERMES_BIN" "${launch_args[@]}" ;;
      *)       echo "usage: $0 $1 {start|stop|restart}" >&2; exit 2 ;;
    esac
    ;;
  *)
    echo "usage: $0 {up|down|restart|status|doctor|logs <c>|gateway {start|stop|restart}|dashboard {start|stop|restart}}" >&2
    exit 2
    ;;
esac
