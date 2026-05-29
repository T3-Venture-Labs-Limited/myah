#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

base="${1:-origin/master}"
OUT="$ROOT/artifacts/static-analysis"
mkdir -p "$OUT/raw"

export NODE_OPTIONS="${NODE_OPTIONS:---max-old-space-size=4096}"
COMMAND="NODE_OPTIONS=$NODE_OPTIONS timeout 120 npx --no-install fallow audit --changed-since $base --gate all --format json --quiet --threads 1"

# Memory guardrails: changed-file audit, --threads 1, timeout, and NODE_OPTIONS
# are always active. A hard virtual-memory ulimit is opt-in because Fallow's
# native binary can reserve address space in ways that make a low ulimit abort
# before useful JSON is produced. Set FALLOW_ULIMIT_KB explicitly when running
# on a host where a tested value is known to work.
if [ -n "${FALLOW_ULIMIT_KB:-}" ] && command -v ulimit >/dev/null 2>&1; then
  ulimit -v "$FALLOW_ULIMIT_KB" 2>/dev/null || true
fi

if ! git rev-parse --verify --quiet "$base^{commit}" >/dev/null; then
  : > "$OUT/raw/fallow-audit.stdout.json"
  printf 'Invalid Fallow base ref: %s\n' "$base" > "$OUT/raw/fallow-audit.stderr.txt"
  python scripts/static-analysis/write_report.py \
    --tool fallow-audit \
    --command "$COMMAND" \
    --exit-code 128 \
    --stdout-file "$OUT/raw/fallow-audit.stdout.json" \
    --stderr-file "$OUT/raw/fallow-audit.stderr.txt" \
    --json-out "$OUT/fallow-audit.json" \
    --md-out "$OUT/fallow-audit.md" \
    --summary-out "$OUT/summary.md"
  exit $?
fi

changed_files="$(git diff --name-only "$base"...HEAD --)"
source_files="$(printf '%s\n' "$changed_files" | grep -E '^(platform-oss/)?(src|test|tests|e2e|playwright|cypress|scripts|packages|apps)/.*\.(js|jsx|ts|tsx|svelte)$|^(platform-oss/)?[^[:space:]/]+\.(js|jsx|ts|tsx|svelte)$' || true)"

if [ -z "$source_files" ]; then
  cat > "$OUT/raw/fallow-audit.stdout.json" <<JSON
{
  "version": "2.84.0",
  "verdict": "pass",
  "summary": {
    "skipped": true,
    "reason": "No JavaScript/TypeScript/Svelte source files changed relative to ${base}; skipped memory-sensitive Fallow graph audit."
  },
  "changed_files_count": $(printf '%s\n' "$changed_files" | sed '/^$/d' | wc -l | tr -d ' ')
}
JSON
  : > "$OUT/raw/fallow-audit.stderr.txt"
  code=0
else
  set +e
  timeout 120 npx --no-install fallow audit --changed-since "$base" --gate all --format json --quiet --threads 1 \
    > "$OUT/raw/fallow-audit.stdout.json" \
    2> "$OUT/raw/fallow-audit.stderr.txt"
  code=$?
  set -e
fi

python scripts/static-analysis/write_report.py \
  --tool fallow-audit \
  --command "$COMMAND" \
  --exit-code "$code" \
  --stdout-file "$OUT/raw/fallow-audit.stdout.json" \
  --stderr-file "$OUT/raw/fallow-audit.stderr.txt" \
  --json-out "$OUT/fallow-audit.json" \
  --md-out "$OUT/fallow-audit.md" \
  --summary-out "$OUT/summary.md"
