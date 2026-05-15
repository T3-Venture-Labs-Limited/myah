#!/usr/bin/env python3
"""CI guard: forbid private-attribute access on the Hermes GatewayRunner.

Workstream B Phase 1 added a public `GatewayRunner` API
(`get_session_override`, `set_session_override`, `evict_session_agent`,
`is_session_running`, plus a small set of accessors used by Myah).  This
script enforces that no Myah code reaches into the private internals the
public API replaces — preventing the production NameError class of bug
that occurs when upstream Hermes refactors a private dict or method.

Scope:
  * `platform/backend/**/*.py` — full subtree
  * `agent/hermes/gateway/platforms/myah*.py` — Myah-owned platform adapters

Excluded:
  * `agent/hermes/gateway/run.py` — defines the public API and the
    underlying private fields.
  * Anything under `tests/` — test fixtures legitimately seed the private
    fields when constructing a stripped-down runner via `__new__`.
  * Comment-only matches — handled by the patterns themselves (we match
    `<token>.<priv>` form, not bare references in prose).

Exit codes:
  0 — clean
  1 — forbidden access(es) found (file:line listing printed to stderr)
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Iterable, List, Tuple

# Repo root is two levels up from this file (platform/scripts/<this>).
REPO_ROOT = Path(__file__).resolve().parents[2]

# Match `<expr>._priv` where _priv is one of the forbidden private names.
# We anchor on a non-word char or line start to avoid matching e.g.
# `myrunner._private_helper`'s internal calls.  The trailing pattern allows
# the full attribute name to be longer (e.g. `_running_agents_ts`) but the
# starting fragment must be one of the listed prefixes.
_FORBIDDEN_PATTERNS: List[Tuple[str, re.Pattern[str]]] = [
    (
        "GatewayRunner._session_model_overrides",
        re.compile(r"\b\w+\._session_model_overrides\b"),
    ),
    (
        "GatewayRunner._agent_cache",
        re.compile(r"\b\w+\._agent_cache\b"),
    ),
    (
        "GatewayRunner._running_agents",
        re.compile(r"\b\w+\._running_agents\b"),
    ),
    (
        "GatewayRunner._evict_cached_agent",
        re.compile(r"\b\w+\._evict_cached_agent\b"),
    ),
    (
        "GatewayRunner._native_streaming_used",
        re.compile(r"\b\w+\._native_streaming_used\b"),
    ),
    (
        "GatewayRunner._reasoning_deltas_fired",
        re.compile(r"\b\w+\._reasoning_deltas_fired\b"),
    ),
    (
        "GatewayRunner._structured_cbs",
        re.compile(r"\b\w+\._structured_cbs\b"),
    ),
]

# Files that legitimately reference the private fields.
_EXEMPT_PATHS = {
    REPO_ROOT / "agent" / "hermes" / "gateway" / "run.py",
    REPO_ROOT / "platform" / "scripts" / "check_no_private_hermes_access.py",
}

# Subtrees to skip outright.
_SKIP_DIR_PARTS = {"tests", "__pycache__", ".venv", "venv", "node_modules"}


def _iter_target_files() -> Iterable[Path]:
    backend = REPO_ROOT / "platform" / "backend"
    if backend.is_dir():
        for p in backend.rglob("*.py"):
            if any(part in _SKIP_DIR_PARTS for part in p.parts):
                continue
            if p in _EXEMPT_PATHS:
                continue
            yield p

    platforms_dir = REPO_ROOT / "agent" / "hermes" / "gateway" / "platforms"
    if platforms_dir.is_dir():
        for p in platforms_dir.glob("myah*.py"):
            if any(part in _SKIP_DIR_PARTS for part in p.parts):
                continue
            if p in _EXEMPT_PATHS:
                continue
            yield p


def _scan_file(path: Path) -> List[Tuple[int, str, str]]:
    """Return list of (line_no, label, line_text) violations."""
    violations: List[Tuple[int, str, str]] = []
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return violations
    for line_no, line in enumerate(text.splitlines(), start=1):
        # Skip comment-only lines — they describe behavior, not invoke it.
        stripped = line.lstrip()
        if stripped.startswith("#"):
            continue
        for label, pattern in _FORBIDDEN_PATTERNS:
            if pattern.search(line):
                violations.append((line_no, label, line.rstrip()))
                # one violation per line is enough
                break
    return violations


def main(argv: List[str]) -> int:
    any_violations = False
    for path in sorted(_iter_target_files()):
        violations = _scan_file(path)
        if not violations:
            continue
        any_violations = True
        rel = path.relative_to(REPO_ROOT)
        for line_no, label, text in violations:
            sys.stderr.write(
                f"{rel}:{line_no}: forbidden access to {label}\n"
                f"    {text}\n"
            )

    if any_violations:
        sys.stderr.write(
            "\n"
            "Replace private-attribute access with the public GatewayRunner API:\n"
            "  runner._session_model_overrides[k] = v  ->  runner.set_session_override(k, v)\n"
            "  runner._session_model_overrides.get(k) ->  runner.get_session_override(k)\n"
            "  runner._evict_cached_agent(k)          ->  runner.evict_session_agent(k)\n"
            "  k in runner._running_agents            ->  runner.is_session_running(k)\n"
            "See agent/hermes/gateway/run.py (Myah public API marker block).\n"
        )
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
