#!/usr/bin/env python3
"""Backend lint: catch production-invariant violations at lint time.

Two checks run against every .py under platform/backend/open_webui/ (skipping
test/ and migrations/):

  1) Any string literal (plain or f-string constant part) containing
     'http://localhost:' or 'http://127.0.0.1:'
     -- cross-container URLs must use AGENT_HOST; see
     docs/gotchas/agent-networking-localhost.md

  2) Any call of the form `<expr>.logger.<method>(...)` whose arguments
     include a string literal containing a %s / %d / %r placeholder
     -- loguru does NOT interpolate %s; see
     docs/gotchas/loguru-percent-format.md

Exits 0 if zero violations, 1 if any. Cross-platform, stdlib-only.

Invoked from npm run lint (`npm run lint:backend-network` wraps it) or
directly: `python3 platform/scripts/check_backend_lint.py`.
"""
from __future__ import annotations

import ast
import pathlib
import re
import sys

BACKEND = pathlib.Path(__file__).resolve().parent.parent / "backend" / "open_webui"
SKIP_DIRS = {"test", "migrations"}
# Files whose localhost strings are intentionally configurable defaults (env vars),
# not cross-container hardcodes. Pattern: the file only *defines* the default;
# callers override it via environment variables. Add to this set when a new
# env-var file legitimately contains a localhost default URL.
SKIP_FILES_LOCALHOST = {"env.py"}
URL_RE = re.compile(r"http://(?:localhost|127\.0\.0\.1):")
PCT_RE = re.compile(r"%(?:[sdr]|\([^)]+\)[sdr])")  # %s %d %r and %(name)s style
LOGURU_METHODS = {
    "trace", "debug", "info", "success", "warning",
    "error", "critical", "exception", "log",
}


def string_literals(node: ast.AST):
    """Yield every string literal inside `node` (plain string or f-string parts)."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        yield node.value
    elif isinstance(node, ast.JoinedStr):
        for part in node.values:
            if isinstance(part, ast.Constant) and isinstance(part.value, str):
                yield part.value


def ends_in_logger(func: ast.AST) -> bool:
    """True if `func` resolves to `<expr>.logger.X` or `logger.X`.

    Walks attribute chain and skips any intermediate Call nodes so we also
    recognise logger.bind(...).warning(...) and logger.opt(...).info(...).
    """
    cur = func
    while isinstance(cur, ast.Attribute):
        cur = cur.value
        if isinstance(cur, ast.Call):
            cur = cur.func
    return isinstance(cur, ast.Name) and cur.id == "logger"


def _docstring_nodes(tree: ast.AST) -> set[int]:
    """Return ids of AST Constant nodes that are docstrings.

    Docstrings are the first statement of a module/class/function body when
    that statement is a bare ast.Expr wrapping an ast.Constant string. They
    should not be flagged by Check 1 — it's fine to have a localhost example
    in a docstring.
    """
    docs: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = getattr(node, "body", [])
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
                docs.add(id(body[0].value))
    return docs


def check_file(path: pathlib.Path, skip_localhost: bool = False) -> list[tuple[int, str, str]]:
    """Return list of (lineno, check_id, offending_text) for violations in path."""
    try:
        tree = ast.parse(path.read_text(), filename=str(path))
    except SyntaxError:
        return []
    violations: list[tuple[int, str, str]] = []
    # Track f-string Constant children to avoid double-reporting their content
    # (ast.walk visits both the JoinedStr and each Constant inside it).
    fstring_constants: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.JoinedStr):
            for child in ast.walk(node):
                if child is not node and isinstance(child, ast.Constant):
                    fstring_constants.add(id(child))
    docstrings = _docstring_nodes(tree)

    for node in ast.walk(tree):
        # Skip bare Constant nodes that are already part of an f-string
        # (we'll catch them via the parent JoinedStr instead).
        if isinstance(node, ast.Constant) and id(node) in fstring_constants:
            continue
        # Check 1: any string literal holding a http://localhost: URL
        # Skipped for files in SKIP_FILES_LOCALHOST (env-var default files) and
        # skipped for docstring nodes (example URLs in docstrings are fine).
        if not skip_localhost and id(node) not in docstrings:
            for lit in string_literals(node):
                if URL_RE.search(lit):
                    violations.append((getattr(node, "lineno", 0), "localhost", lit))
                    break
        # Check 2: logger.<method>(...) with %s/%d/%r in any string argument
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in LOGURU_METHODS
            and ends_in_logger(node.func)
        ):
            for arg in [*node.args, *(kw.value for kw in node.keywords)]:
                matched = False
                for lit in string_literals(arg):
                    if PCT_RE.search(lit):
                        violations.append((node.lineno, "loguru-%s", lit))
                        matched = True
                        break
                if matched:
                    break
    return violations


def main() -> int:
    if not BACKEND.is_dir():
        print(f"fatal: backend dir not found at {BACKEND}", file=sys.stderr)
        return 2
    exit_code = 0
    for py in sorted(BACKEND.rglob("*.py")):
        if any(part in SKIP_DIRS for part in py.relative_to(BACKEND).parts):
            continue
        skip_localhost = py.name in SKIP_FILES_LOCALHOST
        for lineno, check, text in check_file(py, skip_localhost=skip_localhost):
            rel = py.relative_to(BACKEND.parent.parent)
            snippet = text if len(text) <= 80 else text[:77] + "..."
            print(f"{rel}:{lineno}  [{check}]  {snippet!r}", file=sys.stderr)
            exit_code = 1
    if exit_code:
        print("", file=sys.stderr)
        print("[localhost]  See docs/gotchas/agent-networking-localhost.md", file=sys.stderr)
        print("             Use AGENT_HOST from open_webui.routers.containers.", file=sys.stderr)
        print("[loguru-%s]  See docs/gotchas/loguru-percent-format.md", file=sys.stderr)
        print("             Loguru does not interpolate %s; use f-string or .bind().", file=sys.stderr)
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
