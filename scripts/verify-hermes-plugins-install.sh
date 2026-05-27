#!/usr/bin/env bash
# scripts/verify-hermes-plugins-install.sh
#
# Phase 0 Task 0.4b — verify whether `hermes plugins install` actually loads
# the current Myah plugin source.
#
# This script exists to surface the C-1 finding from the spec review pass:
# `hermes plugins install owner/repo` does a `git clone --depth 1` + reads
# `plugin.yaml` + `shutil.move` to `~/.hermes/plugins/<name>/`. It does NOT
# pip-install. The plugin's pyproject entry-points are irrelevant to this
# install path.
#
# Today the myah-hermes-plugin repo root has:
#   - pyproject.toml ✓
#   - myah_hermes_plugin/ (package subdir)
#   - LICENSE, CHANGELOG.md, README.md
# But it does NOT have:
#   - plugin.yaml at root  ✗
#   - __init__.py at root  ✗  (only inside myah_hermes_plugin/myah_platform/)
#
# Expected outcome (verified against upstream hermes-agent
# @faa13e49f81480771ceeb55991bb0c27edf1a5fb in hermes_cli/plugins_cmd.py +
# hermes_cli/plugins.py):
#
#   1. `hermes plugins install ...` succeeds (exit 0) BUT logs a yellow
#      warning that the dir has no plugin.yaml/__init__.py and "may not be
#      a valid plugin" — verified at plugins_cmd.py:383-388.
#   2. Plugin dir created at ~/.hermes/plugins/<reponame>/ (the repo name,
#      because no plugin.yaml means no manifest.name override) — verified
#      at plugins_cmd.py:347-348.
#   3. Plugin loader skips the dir because plugins.py:1038-1040 requires an
#      __init__.py at the dir root and raises FileNotFoundError otherwise.
#   4. `/myah/health` returns 404 from the hermes gateway because the plugin
#      didn't load + didn't register any routes.
#
# This is the evidence that Task F.0 in the OSS launch plan
# (`docs/superpowers/plans/2026-05-13-myah-oss-v0.1.0-launch.md`) is required:
# F.0 adds `plugin.yaml` + a root `__init__.py` with a `register(ctx)` shim
# that re-exports the package-internal register function.
#
# Usage (from the smoke-test VM, after `hermes` is installed):
#
#   # 1. Copy this script to the VM (or pipe via ssh)
#   scp -P 2222 scripts/verify-hermes-plugins-install.sh superdao@100.116.244.1:/tmp/
#
#   # 2. Run with a temporary PAT-authenticated HTTPS URL (the public repo
#   #    is private pre-launch, so the install command on the VM needs a
#   #    PAT in the URL OR a cloned-locally fallback URL)
#
#   PAT=ghp_xxxx PLUGIN_URL="https://${PAT}@github.com/T3-Venture-Labs-Limited/myah-hermes-plugin"
#   ssh -p 2222 superdao@100.116.244.1 PLUGIN_URL=\"$PLUGIN_URL\" bash /tmp/verify-hermes-plugins-install.sh
#
#   # 3. The script writes its findings to /tmp/myah-plugin-install-result.txt
#   #    on the VM. Pull it back with:
#   scp -P 2222 superdao@100.116.244.1:/tmp/myah-plugin-install-result.txt e2e-output/cycle-0/
#
# When this script is run AFTER Task F.0 lands (post-restructure), the
# expected outcome inverts: install succeeds clean, plugin dir contains
# plugin.yaml + __init__.py + the package subdir, hermes loads it, and
# /myah/health returns 200.

set -uo pipefail

# ── Deprecation warning ──────────────────────────────────────────────────
# This script is DEPRECATED in favor of the Myah CLI plugin commands.
# Will be removed in Slice 6 of the DevX + OSS CLI initiative (T3-1084).
# The legacy verification flow is preserved during the deprecation period
# so users mid-investigation aren't broken; new runs should use the CLI.
if [ -t 2 ] && [ "$(tput colors 2>/dev/null || echo 0)" -ge 8 ]; then
    _DEP_RED=$'\033[31m'; _DEP_BOLD=$'\033[1m'; _DEP_RESET=$'\033[0m'
else
    _DEP_RED=''; _DEP_BOLD=''; _DEP_RESET=''
fi
cat >&2 <<DEPRECATION
${_DEP_RED}${_DEP_BOLD}DEPRECATED:${_DEP_RESET} platform-oss/scripts/verify-hermes-plugins-install.sh is being replaced by:

    ${_DEP_BOLD}myah plugins list${_DEP_RESET}    — quick listing of installed plugins
    ${_DEP_BOLD}myah doctor${_DEP_RESET}          — full plugin install + SHA-drift check

Between them, the two commands cover everything this script verifies:
  - Plugin landed at the expected ~/.hermes/plugins/<name>/ path.
  - plugin.yaml + __init__.py present (directory-style install shape).
  - Plugin SHA matches the pin in agent/Dockerfile.stock.
  - Hermes gateway /myah/health reachable after plugin load.

This script will be removed in Slice 6 of T3-1084.
Continuing with legacy verification flow for backward compat...

DEPRECATION
unset _DEP_RED _DEP_BOLD _DEP_RESET

PLUGIN_URL="${PLUGIN_URL:-T3-Venture-Labs-Limited/myah-hermes-plugin}"
RESULT_FILE="${RESULT_FILE:-/tmp/myah-plugin-install-result.txt}"

# Helper: log to both stdout and the result file
log() {
    echo "$@" | tee -a "$RESULT_FILE"
}

{
    echo "=== Myah plugin install verification ==="
    echo "Date:       $(date -u +%Y-%m-%dT%H:%M:%SZ)"
    echo "Host:       $(hostname)"
    echo "User:       $(whoami)"
    echo "PLUGIN_URL: ${PLUGIN_URL}"
    echo "Hermes:     $(hermes --version 2>&1 | head -1)"
    echo ""
} > "$RESULT_FILE"

# Clean any previous install of this plugin so we exercise the fresh path
log "→ Cleaning previous install (if any)"
hermes plugins remove myah-hermes-plugin 2>&1 | head -5 | sed 's/^/    /' | tee -a "$RESULT_FILE"
hermes plugins remove myah 2>&1 | head -5 | sed 's/^/    /' | tee -a "$RESULT_FILE"
log ""

# The actual install attempt
log "→ Running: hermes plugins install $PLUGIN_URL"
HERMES_PLUGINS_INSTALL_OUTPUT=$(hermes plugins install "$PLUGIN_URL" 2>&1)
INSTALL_EXIT=$?
log "$HERMES_PLUGINS_INSTALL_OUTPUT" | sed 's/^/    /'
log "  Install exit code: $INSTALL_EXIT"
log ""

# Where did hermes drop the plugin?
log "→ Plugin directories under ~/.hermes/plugins/"
ls -la ~/.hermes/plugins/ 2>&1 | head -20 | sed 's/^/    /' | tee -a "$RESULT_FILE"
log ""

# Look for the install in the most likely directory names
for candidate_dir in myah-hermes-plugin myah; do
    if [ -d "$HOME/.hermes/plugins/$candidate_dir" ]; then
        log "→ Found plugin at ~/.hermes/plugins/$candidate_dir"
        log "  Contents:"
        ls -la "$HOME/.hermes/plugins/$candidate_dir" 2>&1 | head -20 | sed 's/^/      /' | tee -a "$RESULT_FILE"
        log ""

        # Check for the two files hermes' plugin loader REQUIRES
        if [ -f "$HOME/.hermes/plugins/$candidate_dir/plugin.yaml" ]; then
            log "  ✓ plugin.yaml exists"
            log "    Contents:"
            cat "$HOME/.hermes/plugins/$candidate_dir/plugin.yaml" 2>&1 | sed 's/^/      /' | tee -a "$RESULT_FILE"
        else
            log "  ✗ plugin.yaml MISSING — hermes plugin loader will skip this dir"
        fi

        if [ -f "$HOME/.hermes/plugins/$candidate_dir/__init__.py" ]; then
            log "  ✓ __init__.py exists at dir root"
        else
            log "  ✗ __init__.py MISSING at dir root — hermes loader will raise FileNotFoundError"
        fi
        break
    fi
done

log ""

# Restart hermes so the plugin loader runs
log "→ Restarting hermes gateway to exercise the plugin loader"
hermes gateway restart 2>&1 | head -10 | sed 's/^/    /' | tee -a "$RESULT_FILE"
sleep 5

# Probe the plugin's health endpoint
log ""
log "→ Probing http://localhost:8642/myah/health (the plugin's health endpoint)"
HEALTH_OUTPUT=$(curl -sS -m 5 -o /tmp/myah-health-body -w "%{http_code}" http://localhost:8642/myah/health 2>&1)
HEALTH_STATUS=$?
HEALTH_BODY=$(cat /tmp/myah-health-body 2>/dev/null || echo "(no body)")
log "  HTTP status: $HEALTH_OUTPUT"
log "  Body:        $HEALTH_BODY"
log "  Curl exit:   $HEALTH_STATUS"

log ""
log "=== Verification complete ==="
log ""
log "Interpretation:"
log "  - If install exit==0 BUT plugin.yaml/__init__.py missing AND /myah/health 404s,"
log "    C-1 is confirmed and Task F.0 (directory-style restructure) is required."
log "  - If install exit==0 AND plugin.yaml/__init__.py present AND /myah/health 200s,"
log "    the plugin is already directory-style; F.0 may already be done."
log "  - If install exit!=0, investigate — likely a credentials issue if the plugin"
log "    repo is still PRIVATE (use a PAT-authenticated HTTPS URL)."

log ""
log "Results written to: $RESULT_FILE"
