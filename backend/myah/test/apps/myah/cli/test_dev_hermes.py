"""Tests for `myah dev hermes {link-main,unlink-main,config {show,edit,validate}}`.

Slice 3 PR 3.B Task 3.2. Implements the escape-hatch into main `~/.hermes/`
plus worktree-scoped wrappers around `hermes config {show,edit,check}`.

Mock targets follow the consumer-namespace rule established earlier in
Slice 2/3: patches go on `myah.cli.dev.hermes.X`, never on the source
module. The two recurring patch targets are:

    mocker.patch('myah.cli.dev.hermes.get_worktree_path', return_value=wt)
    mocker.patch('myah.cli.dev.hermes.run')   # the subprocess wrapper

`config edit` is the one exception — it calls `subprocess.run` directly
(stdio passthrough for the interactive editor). Tests patch
`myah.cli.dev.hermes.subprocess.run` for that path.
"""

from __future__ import annotations

from pathlib import Path

from myah import app
from myah.lib.cli.shell import ShellResult
from typer.testing import CliRunner

runner = CliRunner()


# ---------------------------------------------------------------------------
# Fixtures — minimal worktree shape with a fake venv hermes binary
# ---------------------------------------------------------------------------


def _make_worktree(tmp_path: Path, *, worktree_env: str = '', with_hermes_bin: bool = True) -> Path:
    """Materialize a minimal worktree at tmp_path with optional fake hermes binary."""
    (tmp_path / 'platform-oss').mkdir(exist_ok=True)
    (tmp_path / '.worktree-env').write_text(
        worktree_env
        or (
            'export BACKEND_PORT=8189\n'
            'export FRONTEND_PORT=5234\n'
            'export WORKTREE_BRANCH=test/branch\n'
        )
    )
    venv_bin = tmp_path / '.venv' / 'bin'
    venv_bin.mkdir(parents=True, exist_ok=True)
    if with_hermes_bin:
        hermes_bin = venv_bin / 'hermes'
        hermes_bin.write_text('#!/bin/sh\necho fake hermes\n')
        hermes_bin.chmod(0o755)
    return tmp_path


# ---------------------------------------------------------------------------
# link-main
# ---------------------------------------------------------------------------


def test_link_main_aborts_without_confirmation(tmp_path: Path, mocker) -> None:
    """Empty / 'n' input must NOT touch .worktree-env."""
    wt = _make_worktree(tmp_path)
    mocker.patch('myah.cli.dev.hermes.get_worktree_path', return_value=wt)
    mocker.patch('myah.cli.dev.hermes._is_port_listening', return_value=False)

    original = (wt / '.worktree-env').read_text()

    result = runner.invoke(app, ['dev', 'hermes', 'link-main'], input='n\n')

    assert result.exit_code == 0, result.output
    assert 'aborted' in result.output.lower()
    assert (wt / '.worktree-env').read_text() == original


def test_link_main_writes_hermes_home_to_main_on_confirm(tmp_path: Path, mocker) -> None:
    """Confirming with 'y' rewrites .worktree-env with HERMES_HOME=<home>/.hermes."""
    wt = _make_worktree(tmp_path)
    mocker.patch('myah.cli.dev.hermes.get_worktree_path', return_value=wt)
    mocker.patch('myah.cli.dev.hermes._is_port_listening', return_value=False)

    fake_home = tmp_path / 'fakehome'
    fake_home.mkdir()
    mocker.patch('myah.cli.dev.hermes.Path.home', return_value=fake_home)

    result = runner.invoke(app, ['dev', 'hermes', 'link-main'], input='y\n')

    assert result.exit_code == 0, result.output
    text = (wt / '.worktree-env').read_text()
    expected = str(fake_home / '.hermes')
    assert f'HERMES_HOME={expected}' in text
    # Pre-existing exports survive.
    assert 'BACKEND_PORT=8189' in text


def test_link_main_outside_worktree_exits_code_2(mocker) -> None:
    mocker.patch(
        'myah.cli.dev.hermes.get_worktree_path',
        side_effect=RuntimeError('not in a worktree'),
    )

    result = runner.invoke(app, ['dev', 'hermes', 'link-main'], input='y\n')

    assert result.exit_code == 2, result.output
    assert 'worktree' in result.output.lower()


def test_link_main_prints_restart_hint_when_backend_running(tmp_path: Path, mocker) -> None:
    """If a backend port is listening, the user is told to restart."""
    wt = _make_worktree(tmp_path)
    mocker.patch('myah.cli.dev.hermes.get_worktree_path', return_value=wt)
    # backend (8189) is up; frontend is not.
    mocker.patch(
        'myah.cli.dev.hermes._is_port_listening',
        side_effect=lambda port: port == 8189,
    )

    result = runner.invoke(app, ['dev', 'hermes', 'link-main'], input='y\n')

    assert result.exit_code == 0, result.output
    assert 'restart' in result.output.lower()
    assert '8189' in result.output


# ---------------------------------------------------------------------------
# unlink-main
# ---------------------------------------------------------------------------


def test_unlink_main_resets_hermes_home_to_worktree(tmp_path: Path, mocker) -> None:
    """unlink-main sets HERMES_HOME back to <worktree>/.hermes (no confirmation)."""
    worktree_env = (
        'export BACKEND_PORT=8189\n'
        'export FRONTEND_PORT=5234\n'
        f'export HERMES_HOME={Path.home() / ".hermes"}\n'
    )
    wt = _make_worktree(tmp_path, worktree_env=worktree_env)
    mocker.patch('myah.cli.dev.hermes.get_worktree_path', return_value=wt)
    mocker.patch('myah.cli.dev.hermes._is_port_listening', return_value=False)

    result = runner.invoke(app, ['dev', 'hermes', 'unlink-main'])

    assert result.exit_code == 0, result.output
    text = (wt / '.worktree-env').read_text()
    expected = str(wt / '.hermes')
    assert f'HERMES_HOME={expected}' in text


def test_unlink_main_no_confirmation_needed(tmp_path: Path, mocker) -> None:
    """unlink-main is the safe direction; no prompt, no abort path."""
    wt = _make_worktree(tmp_path)
    mocker.patch('myah.cli.dev.hermes.get_worktree_path', return_value=wt)
    mocker.patch('myah.cli.dev.hermes._is_port_listening', return_value=False)

    # No `input=` provided — would hang if a prompt were issued.
    result = runner.invoke(app, ['dev', 'hermes', 'unlink-main'])

    assert result.exit_code == 0, result.output
    assert 'unlinked' in result.output.lower() or 'HERMES_HOME' in result.output


# ---------------------------------------------------------------------------
# config show
# ---------------------------------------------------------------------------


def test_config_show_invokes_worktree_hermes_binary(tmp_path: Path, mocker) -> None:
    """Show must invoke the absolute <worktree>/.venv/bin/hermes path, not bare 'hermes'."""
    wt = _make_worktree(tmp_path)
    mocker.patch('myah.cli.dev.hermes.get_worktree_path', return_value=wt)
    mock_run = mocker.patch(
        'myah.cli.dev.hermes.run',
        return_value=ShellResult(returncode=0, stdout='fake config', stderr=''),
    )

    result = runner.invoke(app, ['dev', 'hermes', 'config', 'show'])

    assert result.exit_code == 0, result.output
    assert mock_run.called, 'shell.run was not invoked'
    cmd = mock_run.call_args.args[0]
    assert cmd[0] == str(wt / '.venv' / 'bin' / 'hermes'), f'wrong binary: {cmd[0]!r}'
    assert cmd[1:] == ['config', 'show']
    assert 'fake config' in result.output


def test_config_show_passes_hermes_home_via_env_merge(tmp_path: Path, mocker) -> None:
    """The env passed to `run` must merge os.environ with HERMES_HOME — not replace."""
    wt = _make_worktree(tmp_path)
    mocker.patch('myah.cli.dev.hermes.get_worktree_path', return_value=wt)
    mock_run = mocker.patch(
        'myah.cli.dev.hermes.run',
        return_value=ShellResult(returncode=0, stdout='', stderr=''),
    )

    runner.invoke(app, ['dev', 'hermes', 'config', 'show'])

    env_kwarg = mock_run.call_args.kwargs.get('env')
    assert env_kwarg is not None, 'env kwarg was not passed'
    # HERMES_HOME present and points at the worktree's .hermes by default.
    assert env_kwarg.get('HERMES_HOME') == str(wt / '.hermes')
    # PATH inherited from os.environ — env-merge, not env-replace.
    assert 'PATH' in env_kwarg, f'PATH stripped from env! keys: {list(env_kwarg)[:10]}'


def test_config_show_uses_main_hermes_home_when_linked(tmp_path: Path, mocker) -> None:
    """When .worktree-env has HERMES_HOME set, that value wins."""
    main_hermes = tmp_path / 'fakehome' / '.hermes'
    main_hermes.mkdir(parents=True)
    wt = _make_worktree(
        tmp_path,
        worktree_env=(
            'export BACKEND_PORT=8189\n'
            'export FRONTEND_PORT=5234\n'
            f'export HERMES_HOME={main_hermes}\n'
        ),
    )
    mocker.patch('myah.cli.dev.hermes.get_worktree_path', return_value=wt)
    mock_run = mocker.patch(
        'myah.cli.dev.hermes.run',
        return_value=ShellResult(returncode=0, stdout='', stderr=''),
    )

    runner.invoke(app, ['dev', 'hermes', 'config', 'show'])

    env_kwarg = mock_run.call_args.kwargs.get('env')
    assert env_kwarg.get('HERMES_HOME') == str(main_hermes)


def test_config_show_missing_hermes_binary_exits_code_2(tmp_path: Path, mocker) -> None:
    """If <worktree>/.venv/bin/hermes is absent, exit 2 with a clear message."""
    wt = _make_worktree(tmp_path, with_hermes_bin=False)
    mocker.patch('myah.cli.dev.hermes.get_worktree_path', return_value=wt)

    result = runner.invoke(app, ['dev', 'hermes', 'config', 'show'])

    assert result.exit_code == 2, result.output
    assert 'hermes' in result.output.lower()
    assert 'not found' in result.output.lower() or 'missing' in result.output.lower()


def test_config_show_surfaces_nonzero_exit(tmp_path: Path, mocker) -> None:
    """A non-zero exit from `hermes config show` propagates to the CLI exit code."""
    wt = _make_worktree(tmp_path)
    mocker.patch('myah.cli.dev.hermes.get_worktree_path', return_value=wt)
    mocker.patch(
        'myah.cli.dev.hermes.run',
        return_value=ShellResult(returncode=3, stdout='', stderr='boom'),
    )

    result = runner.invoke(app, ['dev', 'hermes', 'config', 'show'])

    assert result.exit_code == 3, result.output


# ---------------------------------------------------------------------------
# config edit
# ---------------------------------------------------------------------------


def test_config_edit_calls_subprocess_with_passthrough_stdio(tmp_path: Path, mocker) -> None:
    """`config edit` must NOT capture stdio (interactive editor)."""

    class _Completed:
        returncode = 0

    wt = _make_worktree(tmp_path)
    mocker.patch('myah.cli.dev.hermes.get_worktree_path', return_value=wt)
    mock_sub_run = mocker.patch(
        'myah.cli.dev.hermes.subprocess.run',
        return_value=_Completed(),
    )

    result = runner.invoke(app, ['dev', 'hermes', 'config', 'edit'])

    assert result.exit_code == 0, result.output
    assert mock_sub_run.called, 'subprocess.run was not invoked'
    cmd = mock_sub_run.call_args.args[0]
    assert cmd[0] == str(wt / '.venv' / 'bin' / 'hermes')
    assert cmd[1:] == ['config', 'edit']
    # Critical: NO capture — the editor needs the user's tty.
    kwargs = mock_sub_run.call_args.kwargs
    assert kwargs.get('capture_output') is not True
    assert kwargs.get('stdout') is None
    assert kwargs.get('stderr') is None
    # HERMES_HOME still injected via env-merge.
    env_kwarg = kwargs.get('env')
    assert env_kwarg is not None
    assert env_kwarg.get('HERMES_HOME') == str(wt / '.hermes')
    assert 'PATH' in env_kwarg


# ---------------------------------------------------------------------------
# config validate
# ---------------------------------------------------------------------------


def test_config_validate_invokes_hermes_config_check(tmp_path: Path, mocker) -> None:
    """Validate wraps `hermes config check`."""
    wt = _make_worktree(tmp_path)
    mocker.patch('myah.cli.dev.hermes.get_worktree_path', return_value=wt)
    mock_run = mocker.patch(
        'myah.cli.dev.hermes.run',
        return_value=ShellResult(returncode=0, stdout='ok', stderr=''),
    )

    result = runner.invoke(app, ['dev', 'hermes', 'config', 'validate'])

    assert result.exit_code == 0, result.output
    cmd = mock_run.call_args.args[0]
    assert cmd[0] == str(wt / '.venv' / 'bin' / 'hermes')
    assert cmd[1:] == ['config', 'check']
