"""Sanity test for the run_all_checks extraction (C.4 prerequisite)."""

from __future__ import annotations

from myah.cli.doctor import run_all_checks
from myah.lib.cli.doctor_checks import CheckResult


def test_run_all_checks_returns_a_list_of_check_results():
    """Minimum contract: returns a non-empty list of CheckResult objects.
    Don't pin the exact set — that's an implementation detail and would
    make every new check a test edit."""
    results = run_all_checks()
    assert isinstance(results, list)
    assert results, 'run_all_checks must return at least one check'
    assert all(isinstance(r, CheckResult) for r in results)
