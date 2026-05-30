#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

TARGETS = [
    ("Streaming/chat router", "backend/myah/routers/openai.py"),
    ("Streaming event handler", "backend/myah/utils/hermes_stream_handler.py"),
    ("Cron/process router", "backend/myah/routers/processes.py"),
    ("Cron outbox model", "backend/myah/models/cron_deliveries.py"),
    ("Cron outbox worker", "backend/myah/utils/cron_outbox_worker.py"),
]


def fmt_pct(value: float | int | None) -> str:
    if value is None:
        return "missing"
    return f"{float(value):.1f}%"


def _count_pair(summary: dict[str, Any], covered_key: str, total_key: str) -> str:
    covered = summary.get(covered_key, "-")
    total = summary.get(total_key, "-")
    if covered == "-" or total == "-":
        return "-"
    return f"{covered}/{total}"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Print whole-file coverage for T3-1092 critical-path targets."
    )
    parser.add_argument("--coverage-json", default="coverage/backend/coverage.json")
    args = parser.parse_args()

    path = Path(args.coverage_json)
    data = json.loads(path.read_text())
    files = data.get("files", {})

    print("| Area | File | Line coverage | Covered / statements | Branches covered / total |")
    print("|---|---|---:|---:|---:|")
    for area, file_path in TARGETS:
        entry = files.get(file_path)
        if not entry:
            print(f"| {area} | `{file_path}` | missing | - | - |")
            continue

        summary = entry.get("summary", {})
        print(
            f"| {area} | `{file_path}` | {fmt_pct(summary.get('percent_covered'))} | "
            f"{_count_pair(summary, 'covered_lines', 'num_statements')} | "
            f"{_count_pair(summary, 'covered_branches', 'num_branches')} |"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
