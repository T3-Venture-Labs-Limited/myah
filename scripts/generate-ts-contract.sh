#!/usr/bin/env bash
# Regenerate the TypeScript view of the platform↔Hermes contract.
#
# Usage:  bash platform/scripts/generate-ts-contract.sh
#
# This script reads every Pydantic model + str-Enum exported by
# ``platform/shared/contract`` and writes a single TypeScript file at
# ``platform/src/lib/types/contract.ts``. It is idempotent: running it
# twice in a row produces an identical file (CI relies on this).
#
# Tool chain:
#   * pydantic-to-typescript   — emits TypeScript from Pydantic models
#                                via JSON Schema (see Phase 0 spike,
#                                2026-04-25).
#   * json-schema-to-typescript — drives the JSON-Schema -> TS step.
#                                 Installed as a frontend devDependency so
#                                 the binary lives at
#                                 ``node_modules/.bin/json2ts``.
#
# Pre-commit / CI integration: the project has no Husky setup as of
# 2026-04-25, so drift detection runs in CI only. The workflow at
# ``.github/workflows/contract-typecheck.yml`` regenerates the file and
# diffs against the committed copy.

set -euo pipefail

# Resolve the platform/ directory regardless of where the caller runs us
# from. ``${BASH_SOURCE[0]}`` works for both `bash path/to/script.sh` and
# direct invocation; ``cd -P`` follows symlinks (worktrees symlink the
# scripts dir into the main checkout).
SCRIPT_DIR="$(cd -P "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLATFORM_DIR="$(cd -P "${SCRIPT_DIR}/.." && pwd)"

cd "${PLATFORM_DIR}"

# The model-collector module — pydantic2ts walks every BaseModel exported
# from this Python module. We expose a curated facade in
# ``shared/contract/_codegen_module.py`` rather than pointing the tool at
# ``shared/contract/__init__.py`` directly: that way enum-only files (no
# BaseModel) still work, and Phase 2+ can add additional models without
# touching the public ``__init__``.
INPUT_MODULE="${PLATFORM_DIR}/shared/contract/_codegen_module.py"
OUTPUT_FILE="${PLATFORM_DIR}/src/lib/types/contract.ts"
PYDANTIC2TS_BIN="${PLATFORM_DIR}/.venv/bin/pydantic2ts"
JSON2TS_BIN="${PLATFORM_DIR}/node_modules/.bin/json2ts"

if [[ ! -x "${PYDANTIC2TS_BIN}" ]]; then
    echo "error: ${PYDANTIC2TS_BIN} not found." >&2
    echo "       Run: cd platform && .venv/bin/pip install pydantic-to-typescript" >&2
    exit 1
fi
if [[ ! -x "${JSON2TS_BIN}" ]]; then
    echo "error: ${JSON2TS_BIN} not found." >&2
    echo "       Run: cd platform && npm install --save-dev --ignore-scripts json-schema-to-typescript" >&2
    exit 1
fi

mkdir -p "$(dirname "${OUTPUT_FILE}")"

# pydantic2ts loads ``_codegen_module.py`` via importlib's spec_from_file_location,
# which does NOT add the parent dir to sys.path. The module's ``from shared.contract...``
# imports therefore fail unless ``platform/`` is on PYTHONPATH. ``cd`` above makes
# CWD == platform; export PYTHONPATH=. so dotted imports of the ``shared`` package
# resolve. Local dev environments where the platform is ``pip install -e .``'d also
# work — this just makes the script self-contained.
PYTHONPATH="${PLATFORM_DIR}${PYTHONPATH:+:${PYTHONPATH}}" \
"${PYDANTIC2TS_BIN}" \
    --module "${INPUT_MODULE}" \
    --output "${OUTPUT_FILE}" \
    --json2ts-cmd "${JSON2TS_BIN}"

echo "Wrote ${OUTPUT_FILE}"
