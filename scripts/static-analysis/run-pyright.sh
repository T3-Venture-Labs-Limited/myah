#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

OUT="$ROOT/artifacts/static-analysis"
mkdir -p "$OUT/raw"

if ! command -v npx >/dev/null 2>&1 || ! npx --no-install pyright --version >/dev/null 2> "$OUT/raw/pyright.stderr.txt"; then
  : > "$OUT/raw/pyright.stdout.json"
  python scripts/static-analysis/write_report.py \
    --tool pyright \
    --command "npx --no-install pyright --project pyrightconfig.json --outputjson" \
    --exit-code 127 \
    --stdout-file "$OUT/raw/pyright.stdout.json" \
    --stderr-file "$OUT/raw/pyright.stderr.txt" \
    --json-out "$OUT/pyright.json" \
    --md-out "$OUT/pyright.md" \
    --summary-out "$OUT/summary.md"
  exit $?
fi

set +e
npx --no-install pyright --project pyrightconfig.json --outputjson \
  > "$OUT/raw/pyright.stdout.json" \
  2> "$OUT/raw/pyright.stderr.txt"
code=$?
set -e

python scripts/static-analysis/write_report.py \
  --tool pyright \
  --command "npx --no-install pyright --project pyrightconfig.json --outputjson" \
  --exit-code "$code" \
  --stdout-file "$OUT/raw/pyright.stdout.json" \
  --stderr-file "$OUT/raw/pyright.stderr.txt" \
  --json-out "$OUT/pyright.json" \
  --md-out "$OUT/pyright.md" \
  --summary-out "$OUT/summary.md"
