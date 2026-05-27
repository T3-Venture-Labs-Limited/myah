"""Sanity tests for the CLI test tree. Runs before any CLI code lands."""

import importlib


def test_rich_importable() -> None:
    """Rich must be importable as a direct dep (not just transitive)."""
    rich = importlib.import_module('rich')
    assert rich is not None
    # Rich must support tabulate-like output for `myah status` and `myah doctor`
    from rich.table import Table  # noqa: F401
    from rich.console import Console  # noqa: F401


def test_typer_importable() -> None:
    """Typer is already a runtime dep; confirm import works."""
    typer = importlib.import_module('typer')
    assert typer is not None
