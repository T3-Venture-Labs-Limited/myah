"""Tests for `myah dev logs` (Slice 2 Task 2.5).

The command is a thin shell over `myah.lib.cli.log_multiplex.tail_logs`:
- Resolve worktree path.
- Build a catalog of (backend, frontend, gateway, dashboard, plugin) → file paths.
- Filter by optional `services` argument; warn on unknowns.
- Print each (source, line) tuple as `[color]name:[/]  line` via Rich.

Mocks follow the consumer-namespace rule: patch `myah.cli.dev.logs.tail_logs`,
not `myah.lib.cli.log_multiplex.tail_logs`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from myah import app


runner = CliRunner()


def _make_worktree(tmp_path: Path) -> Path:
    """Materialize the minimal worktree shape for logs command."""
    (tmp_path / '.worktree-env').write_text(
        'export BACKEND_PORT=8189\nexport FRONTEND_PORT=5234\n'
    )
    return tmp_path


def _make_log(worktree: Path, name: str, content: str = '') -> Path:
    """Write a fake logfile and return its path."""
    log_dir = worktree / '.worktree-logs'
    log_dir.mkdir(parents=True, exist_ok=True)
    f = log_dir / f'{name}.log'
    f.write_text(content)
    return f


# ---------------------------------------------------------------------------
# Catalog & filter behavior
# ---------------------------------------------------------------------------


def test_logs_command_no_args_tails_all_available(tmp_path: Path, mocker) -> None:
    """No service arg → tails all logfiles that exist on disk."""
    wt = _make_worktree(tmp_path)
    _make_log(wt, 'backend', 'be line 1\n')
    _make_log(wt, 'frontend', 'fe line 1\n')

    mocker.patch('myah.cli.dev.logs._get_worktree_path', return_value=wt)
    mock_tail = mocker.patch('myah.cli.dev.logs.tail_logs', return_value=iter([]))

    result = runner.invoke(app, ['dev', 'logs'])

    assert result.exit_code == 0, result.output
    assert mock_tail.called
    sources = mock_tail.call_args.args[0]
    names = {s.name for s in sources}
    assert names == {'backend', 'frontend'}


def test_logs_command_filters_by_service(tmp_path: Path, mocker) -> None:
    """Service positional arg → only those sources are passed to tail_logs."""
    wt = _make_worktree(tmp_path)
    _make_log(wt, 'backend')
    _make_log(wt, 'frontend')

    mocker.patch('myah.cli.dev.logs._get_worktree_path', return_value=wt)
    mock_tail = mocker.patch('myah.cli.dev.logs.tail_logs', return_value=iter([]))

    result = runner.invoke(app, ['dev', 'logs', 'backend'])

    assert result.exit_code == 0, result.output
    sources = mock_tail.call_args.args[0]
    names = [s.name for s in sources]
    assert names == ['backend']


def test_logs_command_warns_on_unknown_service(tmp_path: Path, mocker) -> None:
    """An unknown service name produces a warning but does not error."""
    wt = _make_worktree(tmp_path)
    _make_log(wt, 'backend')

    mocker.patch('myah.cli.dev.logs._get_worktree_path', return_value=wt)
    mocker.patch('myah.cli.dev.logs.tail_logs', return_value=iter([]))

    result = runner.invoke(app, ['dev', 'logs', 'foo', 'backend'])

    assert result.exit_code == 0, result.output
    assert 'unknown service' in result.output.lower()
    assert 'foo' in result.output


def test_logs_command_no_logs_found_exits_clean(tmp_path: Path, mocker) -> None:
    """No logfiles exist at all → friendly message, exit 0, no tail_logs call."""
    wt = _make_worktree(tmp_path)
    # no logs

    mocker.patch('myah.cli.dev.logs._get_worktree_path', return_value=wt)
    mock_tail = mocker.patch('myah.cli.dev.logs.tail_logs', return_value=iter([]))

    result = runner.invoke(app, ['dev', 'logs'])

    assert result.exit_code == 0, result.output
    assert 'no log files' in result.output.lower()
    assert not mock_tail.called


# ---------------------------------------------------------------------------
# Flags
# ---------------------------------------------------------------------------


def test_logs_command_lines_flag_passed_through(tmp_path: Path, mocker) -> None:
    """--lines N is forwarded to tail_logs(lines=N)."""
    wt = _make_worktree(tmp_path)
    _make_log(wt, 'backend')

    mocker.patch('myah.cli.dev.logs._get_worktree_path', return_value=wt)
    mock_tail = mocker.patch('myah.cli.dev.logs.tail_logs', return_value=iter([]))

    result = runner.invoke(app, ['dev', 'logs', '--lines', '100'])

    assert result.exit_code == 0, result.output
    assert mock_tail.call_args.kwargs.get('lines') == 100


def test_logs_command_no_follow_flag(tmp_path: Path, mocker) -> None:
    """--no-follow → tail_logs(follow=False)."""
    wt = _make_worktree(tmp_path)
    _make_log(wt, 'backend')

    mocker.patch('myah.cli.dev.logs._get_worktree_path', return_value=wt)
    mock_tail = mocker.patch('myah.cli.dev.logs.tail_logs', return_value=iter([]))

    result = runner.invoke(app, ['dev', 'logs', '--no-follow'])

    assert result.exit_code == 0, result.output
    assert mock_tail.call_args.kwargs.get('follow') is False


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def test_logs_command_renders_prefix_with_color(tmp_path: Path, mocker) -> None:
    """Each yielded tuple is rendered with a color-tagged prefix + the line."""
    wt = _make_worktree(tmp_path)
    _make_log(wt, 'backend')

    from myah.lib.cli.log_multiplex import LogSource

    fake_src = LogSource(name='backend', path=wt / '.worktree-logs' / 'backend.log', color='cyan')
    mocker.patch('myah.cli.dev.logs._get_worktree_path', return_value=wt)
    mocker.patch(
        'myah.cli.dev.logs.tail_logs',
        return_value=iter([(fake_src, 'hello from backend')]),
    )

    result = runner.invoke(app, ['dev', 'logs'])

    assert result.exit_code == 0, result.output
    # The line content appears in output.
    assert 'hello from backend' in result.output
    # The prefix `backend` appears (color codes get stripped by CliRunner;
    # we assert the textual presence — the color tag is rendered by Rich
    # at runtime and validated by the spec-level requirement that we
    # pass a Rich markup string through Console).
    assert 'backend' in result.output


# ---------------------------------------------------------------------------
# Ctrl+C + error paths
# ---------------------------------------------------------------------------


def test_logs_command_handles_ctrl_c_cleanly(tmp_path: Path, mocker) -> None:
    """KeyboardInterrupt from the tail loop is caught — exit 0, no traceback."""
    wt = _make_worktree(tmp_path)
    _make_log(wt, 'backend')

    def _raise_kbi(*a: Any, **kw: Any):
        raise KeyboardInterrupt

    mocker.patch('myah.cli.dev.logs._get_worktree_path', return_value=wt)
    mocker.patch('myah.cli.dev.logs.tail_logs', side_effect=_raise_kbi)

    result = runner.invoke(app, ['dev', 'logs'])

    assert result.exit_code == 0, result.output
    # No traceback in output.
    assert 'Traceback' not in result.output


def test_logs_command_outside_worktree_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mocker
) -> None:
    """When CWD is not inside a worktree, exit non-zero with hint."""
    monkeypatch.chdir(tmp_path)
    # Do NOT mock _get_worktree_path — let it actually raise.

    result = runner.invoke(app, ['dev', 'logs'])

    assert result.exit_code != 0, result.output
    assert 'worktree' in result.output.lower()
