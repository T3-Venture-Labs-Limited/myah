"""Tests for `myah.lib.cli.worktree_paths.get_worktree_path` (Slice 2 Task 2.5).

Extracted from `test_dev_server.py` — both `myah dev server`'s commands and
`myah dev logs` need the same walk-up resolver, so the implementation moved
into `myah.lib.cli.worktree_paths` (public surface) and `cli/dev/server.py`
keeps a back-compat alias for the existing 36 patches.
"""

from __future__ import annotations

from pathlib import Path

import pytest


def _make_worktree(tmp_path: Path) -> Path:
    """Minimal worktree shape (just `.worktree-env`) — sufficient for resolver."""
    (tmp_path / '.worktree-env').write_text('export WORKTREE_BRANCH=test/branch\n')
    return tmp_path


def test_get_worktree_path_resolves_from_cwd_with_worktree_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When CWD itself contains .worktree-env, return it."""
    wt = _make_worktree(tmp_path)
    monkeypatch.chdir(wt)

    from myah.lib.cli.worktree_paths import get_worktree_path

    resolved = get_worktree_path()
    assert resolved.resolve() == wt.resolve()


def test_get_worktree_path_walks_up_from_subdirectory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Walks up from nested subdirectories until .worktree-env is found."""
    wt = _make_worktree(tmp_path)
    nested = wt / 'platform-oss' / 'backend' / 'myah'
    nested.mkdir(parents=True)
    monkeypatch.chdir(nested)

    from myah.lib.cli.worktree_paths import get_worktree_path

    resolved = get_worktree_path()
    assert resolved.resolve() == wt.resolve()


def test_get_worktree_path_raises_outside_worktree(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Outside any worktree: RuntimeError with a hint pointing at `myah dev worktree create`."""
    monkeypatch.chdir(tmp_path)

    from myah.lib.cli.worktree_paths import get_worktree_path

    with pytest.raises(RuntimeError) as exc_info:
        get_worktree_path()

    msg = str(exc_info.value)
    assert 'worktree' in msg.lower()
    assert 'myah dev worktree create' in msg
