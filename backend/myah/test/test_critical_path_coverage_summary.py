from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[3]


def _write_coverage_json(tmp_path: Path, files: dict[str, object]) -> Path:
    coverage_dir = tmp_path / "coverage" / "backend"
    coverage_dir.mkdir(parents=True)
    coverage_json = coverage_dir / "coverage.json"
    coverage_json.write_text(
        json.dumps(
            {
                "files": files,
                "totals": {"percent_covered": 31.2},
            }
        )
    )
    return coverage_json


def _run_summary(coverage_json: Path) -> subprocess.CompletedProcess[str]:
    script = PROJECT_ROOT / "scripts/coverage/critical_path_summary.py"
    return subprocess.run(
        [sys.executable, str(script), "--coverage-json", str(coverage_json)],
        cwd=PROJECT_ROOT,
        text=True,
        capture_output=True,
        check=True,
    )


def test_critical_path_summary_reads_coverage_json(tmp_path: Path) -> None:
    coverage_json = _write_coverage_json(
        tmp_path,
        {
            "backend/myah/routers/openai.py": {
                "summary": {
                    "percent_covered": 12.9,
                    "covered_lines": 153,
                    "num_statements": 1011,
                    "covered_branches": 34,
                    "num_branches": 434,
                }
            }
        },
    )

    result = _run_summary(coverage_json)

    assert "| Area | File | Line coverage | Covered / statements | Branches covered / total |" in result.stdout
    assert "backend/myah/routers/openai.py" in result.stdout
    assert "12.9%" in result.stdout
    assert "153/1011" in result.stdout
    assert "34/434" in result.stdout


def test_critical_path_summary_reports_missing_targets(tmp_path: Path) -> None:
    coverage_json = _write_coverage_json(tmp_path, {})

    result = _run_summary(coverage_json)

    assert "backend/myah/utils/hermes_stream_handler.py" in result.stdout
    assert "| Streaming event handler | `backend/myah/utils/hermes_stream_handler.py` | missing | - | - |" in result.stdout
