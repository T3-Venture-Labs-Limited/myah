#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

OUT="$ROOT/artifacts/static-analysis"
mkdir -p "$OUT/raw"

COMMAND=".venv/bin/ruff check backend/myah --output-format=json"

if [ ! -x ".venv/bin/ruff" ]; then
  printf '{"error":"missing .venv/bin/ruff","hint":"Run MYAH_SKIP_HATCH_NPM=1 .venv/bin/pip install -e '\''.[dev]'\'' from the public Myah repo root"}\n' \
    > "$OUT/raw/ruff.stdout.json"
  printf 'missing executable: .venv/bin/ruff\n' > "$OUT/raw/ruff.stderr.txt"
  code=127
else
  set +e
  .venv/bin/ruff check backend/myah --output-format=json \
    > "$OUT/raw/ruff.stdout.json" \
    2> "$OUT/raw/ruff.stderr.txt"
  code=$?
  set -e
fi

python scripts/static-analysis/write_report.py \
  --tool ruff \
  --command "$COMMAND" \
  --exit-code "$code" \
  --stdout-file "$OUT/raw/ruff.stdout.json" \
  --stderr-file "$OUT/raw/ruff.stderr.txt" \
  --json-out "$OUT/ruff.json" \
  --md-out "$OUT/ruff.md" \
  --summary-out "$OUT/summary.md"
