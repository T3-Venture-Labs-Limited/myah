"""Subprocess indirection for the myah CLI.

All CLI subprocess calls (git, pip, hermes, npm, docker compose) go
through this module's `run()` function. Tests mock `myah.lib.cli.shell.run`
at one point and don't need to patch `subprocess` everywhere.

Why this exists: see plan task 1.3 and spec section 'Testing Approach'.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from typing import Mapping, Sequence


@dataclass(frozen=True, slots=True)
class ShellResult:
    """Result of a subprocess invocation.

    Mirrors `subprocess.CompletedProcess` but with stdout/stderr as
    decoded strings (UTF-8) and a frozen dataclass for safer test
    assertions (`assert mock.call_args.return_value == ShellResult(...)`).
    """

    returncode: int
    stdout: str
    stderr: str


class ShellError(RuntimeError):
    """Raised by `run(..., check=True)` when the subprocess returns non-zero.

    Carries the returncode + captured streams for inspection.
    """

    def __init__(self, cmd: Sequence[str], result: ShellResult) -> None:
        super().__init__(
            f'Command {list(cmd)!r} returned non-zero exit {result.returncode}.\n'
            f'stdout: {result.stdout!r}\nstderr: {result.stderr!r}'
        )
        self.cmd = list(cmd)
        self.returncode = result.returncode
        self.stdout = result.stdout
        self.stderr = result.stderr


def run(
    cmd: Sequence[str],
    *,
    check: bool = False,
    cwd: str | None = None,
    env: Mapping[str, str] | None = None,
    input: str | None = None,
    timeout: float | None = None,
) -> ShellResult:
    """Run a subprocess and return its captured output.

    By default, does NOT raise on non-zero exit (call sites check
    `result.returncode` explicitly). Pass `check=True` to raise
    `ShellError` instead.

    The `env` kwarg, when provided, REPLACES the subprocess environment
    (it does not merge with the parent's environment). If you want to
    inherit + override, do that at the call site.

    All stdout/stderr is captured and decoded as UTF-8 (errors=replace
    to handle binary output gracefully).

    Timeouts raise `subprocess.TimeoutExpired` unwrapped — deliberately,
    so callers can access its `.timeout`, `.cmd`, and partial
    `.stdout`/`.stderr` attributes. `ShellError` is only raised by
    `check=True` on non-zero exit codes; it never wraps a timeout.
    """
    completed = subprocess.run(  # noqa: S603 — input is caller-controlled
        list(cmd),
        capture_output=True,
        text=True,
        encoding='utf-8',
        errors='replace',
        check=False,  # we handle check ourselves to raise ShellError
        cwd=cwd,
        env=dict(env) if env is not None else None,
        input=input,
        timeout=timeout,
    )
    result = ShellResult(
        returncode=completed.returncode,
        stdout=completed.stdout or '',
        stderr=completed.stderr or '',
    )
    if check and result.returncode != 0:
        raise ShellError(cmd, result)
    return result
