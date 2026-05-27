"""Cold-start benchmark for the `myah` CLI binary.

Per spec Metric #7: `myah --help` must execute in < 200 ms (median of 10 runs).

This test is opt-in via `pytest -m slow` so it doesn't slow normal test runs.
It catches regressions where a new module accidentally pulls in heavy imports
(e.g., Rich, the FastAPI app, sqlalchemy) at module top instead of inside
the lazy-import wrappers in `myah/cli/__init__.py`.
"""

import os
import subprocess
import time

import pytest


@pytest.mark.slow
def test_myah_help_cold_start_under_200ms() -> None:
    """Spec Metric #7: CLI cold-start time `myah --help` < 200 ms (median of 10 runs).

    Uses subprocess (not CliRunner) to measure REAL cold-start cost — the
    fresh-Python-process startup, all module imports, Typer initialization,
    and help rendering. CliRunner would skip the process-startup cost.

    Uses PYTHONPATH=backend so we exercise THIS worktree's code, not
    main's symlinked-venv myah (the .venv/bin/myah console script
    resolves to main's myah package per Task 1.4 implementer's concern).

    Reports the median; non-blocking if a single run is slow (warmup).
    """
    env = os.environ.copy()
    env['PYTHONPATH'] = 'backend' + os.pathsep + env.get('PYTHONPATH', '')

    timings = []
    for _ in range(10):
        start = time.perf_counter()
        result = subprocess.run(
            ['python', '-c', 'from myah import app; app(["--help"])'],
            capture_output=True,
            text=True,
            env=env,
        )
        elapsed_ms = (time.perf_counter() - start) * 1000
        assert result.returncode == 0, (
            f'myah --help failed (exit {result.returncode}): {result.stderr[:300]}'
        )
        timings.append(elapsed_ms)

    timings.sort()
    median_ms = timings[5]  # 6th of 10 sorted (mid-of-10)

    # Report all timings for debugging
    print(f'Cold-start timings (sorted, ms): {[f"{t:.1f}" for t in timings]}')
    print(f'Median: {median_ms:.1f}ms (target: <200 ms)')

    assert median_ms < 200, (
        f'CLI cold-start median {median_ms:.1f}ms exceeds 200ms target. '
        f'All timings: {[f"{t:.1f}" for t in timings]}. '
        f'Likely cause: a new module pulled in heavy imports (Rich, sqlalchemy, '
        f'fastapi) at module top instead of inside the lazy-import wrappers '
        f'in myah/cli/__init__.py.'
    )
