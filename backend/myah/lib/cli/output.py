"""Shared CLI output helpers.

The lib-shared-helper convention: anything used by 2+ command modules
under ``myah/cli/`` gets extracted here so the call sites can stay
typer-flavored and behavior stays consistent (stderr formatting, exit
code propagation) across the surface.

Cold-start: Rich is lazy-imported inside the helper bodies so the
CLI cold-start budget holds (`myah --help` < 200 ms).
"""

from __future__ import annotations

import typer

from myah.lib.cli.shell import ShellResult


def emit_result_or_exit(result: ShellResult) -> None:
    """Surface a shell.run result to the console and propagate exit code.

    Slice 5 verb wrappers share this pattern. Centralising avoids drift
    in stderr formatting / exit-code semantics across the agent /
    plugins / upgrade / uninstall surfaces. Rich Console import stays
    lazy so the cold-start budget holds.
    """
    from rich.console import Console

    console = Console()
    if result.stdout:
        console.print(result.stdout, end='')
    if result.stderr:
        console.print(result.stderr, end='')
    if result.returncode != 0:
        raise typer.Exit(code=result.returncode)


__all__ = ['emit_result_or_exit']
