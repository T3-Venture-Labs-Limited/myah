"""Tests for `myah dev worktree {create,list,destroy}` (Slice 2 Task 2.3).

These tests exercise the user-facing Typer command layer that wraps the
`worktree_setup` library. The orchestrator itself is tested in
`test_worktree_setup.py`; here we only verify that:

1. The CLI parses args/flags correctly.
2. It dispatches to the right library function with the expected kwargs.
3. It renders the right user-visible output.
4. It exits with the right code for each happy/sad path.

Mock targets follow the consumer-namespace rule: patch where the symbol
is *imported into* (`myah.cli.dev.worktree.create_worktree`), not where
it was originally defined.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from myah import app
from myah.lib.cli.shell import ShellError, ShellResult
from myah.lib.cli.worktree_setup import (
    WorktreeAlreadyExistsError,
    WorktreeCreationError,
    WorktreeInfo,
)


runner = CliRunner()


# "Three commands, three contracts. Every test starts where the user
#  presses Enter and ends where the shell returns to the prompt." — fixtures.


def _fake_info(tmp_path: Path, *, branch: str = 'feat/foo', mode: str = 'hosted') -> WorktreeInfo:
    """Synthetic WorktreeInfo for create-command happy-path tests."""
    return WorktreeInfo(
        path=tmp_path / '.worktrees' / branch,
        branch=branch,
        mode=mode,
        ports={'backend_port': 8123, 'frontend_port': 5245},
    )


# ---------------------------------------------------------------------------
# create
# ---------------------------------------------------------------------------


def test_create_invokes_orchestrator_with_branch_and_mode(mocker, tmp_path: Path) -> None:
    """The CLI delegates to `create_worktree(branch, mode=...)`."""
    mock_create = mocker.patch(
        'myah.cli.dev.worktree.create_worktree',
        return_value=_fake_info(tmp_path, branch='feat/foo', mode='hosted'),
    )

    result = runner.invoke(app, ['dev', 'worktree', 'create', 'feat/foo'])

    assert result.exit_code == 0, result.output
    mock_create.assert_called_once_with('feat/foo', mode='hosted')


def test_create_default_mode_is_hosted(mocker, tmp_path: Path) -> None:
    """Omitting `--mode` defaults to `hosted`."""
    mock_create = mocker.patch(
        'myah.cli.dev.worktree.create_worktree',
        return_value=_fake_info(tmp_path),
    )

    result = runner.invoke(app, ['dev', 'worktree', 'create', 'feat/foo'])

    assert result.exit_code == 0, result.output
    assert mock_create.call_args.kwargs['mode'] == 'hosted'


def test_create_oss_mode(mocker, tmp_path: Path) -> None:
    """`--mode oss` propagates to the orchestrator."""
    mock_create = mocker.patch(
        'myah.cli.dev.worktree.create_worktree',
        return_value=_fake_info(tmp_path, mode='oss'),
    )

    result = runner.invoke(app, ['dev', 'worktree', 'create', 'feat/foo', '--mode', 'oss'])

    assert result.exit_code == 0, result.output
    assert mock_create.call_args.kwargs['mode'] == 'oss'


def test_create_rejects_invalid_mode(mocker, tmp_path: Path) -> None:
    """An unknown mode aborts before the orchestrator is touched."""
    mock_create = mocker.patch('myah.cli.dev.worktree.create_worktree')

    result = runner.invoke(app, ['dev', 'worktree', 'create', 'feat/foo', '--mode', 'invalid'])

    assert result.exit_code != 0
    mock_create.assert_not_called()


def test_create_success_renders_summary_with_ports(mocker, tmp_path: Path) -> None:
    """The summary shows the branch, both ports, and next-steps hints."""
    mocker.patch(
        'myah.cli.dev.worktree.create_worktree',
        return_value=_fake_info(tmp_path, branch='feat/foo', mode='hosted'),
    )

    result = runner.invoke(app, ['dev', 'worktree', 'create', 'feat/foo'])

    assert result.exit_code == 0, result.output
    assert 'feat/foo' in result.output
    assert '8123' in result.output
    assert '5245' in result.output
    # Next-steps hints should mention the dev commands.
    assert 'Next steps' in result.output
    assert 'myah dev backend' in result.output
    assert 'myah dev frontend' in result.output


def test_create_already_exists_shows_error(mocker) -> None:
    """`WorktreeAlreadyExistsError` → exit 1, destroy-first hint."""
    mocker.patch(
        'myah.cli.dev.worktree.create_worktree',
        side_effect=WorktreeAlreadyExistsError(
            'Worktree already exists at /tmp/x. Use `myah dev worktree destroy feat/foo` first.'
        ),
    )

    result = runner.invoke(app, ['dev', 'worktree', 'create', 'feat/foo'])

    assert result.exit_code == 1, result.output
    assert 'already exists' in result.output.lower()
    assert 'destroy' in result.output.lower()


def test_create_creation_error_shows_step_and_original(mocker) -> None:
    """`WorktreeCreationError` → exit 1; surface step + original exception + rollback note."""
    mocker.patch(
        'myah.cli.dev.worktree.create_worktree',
        side_effect=WorktreeCreationError(
            step='install_hermes_into_venv',
            original=ValueError('boom'),
        ),
    )

    result = runner.invoke(app, ['dev', 'worktree', 'create', 'feat/foo'])

    assert result.exit_code == 1, result.output
    assert 'install_hermes_into_venv' in result.output
    assert 'ValueError' in result.output
    assert 'boom' in result.output
    assert 'rollback' in result.output.lower()


# ---------------------------------------------------------------------------
# list
# ---------------------------------------------------------------------------


def _porcelain(main_path: Path, *worktrees: tuple[str, Path, str]) -> str:
    """Build a porcelain `git worktree list` payload.

    Each worktree tuple is (branch, path, sha). The first entry given is
    NOT the main checkout — `main_path` is always emitted first.
    """
    blocks = [f'worktree {main_path}\nHEAD 0000000000000000000000000000000000000000\nbranch refs/heads/master\n']
    for branch, path, sha in worktrees:
        blocks.append(f'worktree {path}\nHEAD {sha}\nbranch refs/heads/{branch}\n')
    return '\n'.join(blocks)


def test_list_no_worktrees(mocker, tmp_path: Path) -> None:
    """Only the main checkout in porcelain → friendly empty-state message."""
    mocker.patch(
        'myah.cli.dev.worktree.resolve_main_repo_root',
        return_value=tmp_path,
    )
    mocker.patch(
        'myah.cli.dev.worktree.run',
        return_value=ShellResult(returncode=0, stdout=_porcelain(tmp_path), stderr=''),
    )

    result = runner.invoke(app, ['dev', 'worktree', 'list'])

    assert result.exit_code == 0, result.output
    assert 'No worktrees found' in result.output
    assert 'myah dev worktree create' in result.output


def test_list_renders_table_with_branch_path_ports_mode(mocker, tmp_path: Path) -> None:
    """A worktree with a populated .worktree-env + .env shows up with parsed values."""
    main = tmp_path
    wt_path = main / '.worktrees' / 'feat/foo'
    wt_path.mkdir(parents=True)
    (wt_path / '.worktree-env').write_text(
        'export WORKTREE_BRANCH=feat/foo\n'
        'export BACKEND_PORT=8123\n'
        'export FRONTEND_PORT=5245\n',
        encoding='utf-8',
    )
    (wt_path / 'platform-oss').mkdir()
    (wt_path / 'platform-oss' / '.env').write_text(
        'MYAH_DEPLOYMENT_MODE=hosted\n',
        encoding='utf-8',
    )

    mocker.patch('myah.cli.dev.worktree.resolve_main_repo_root', return_value=main)
    mocker.patch(
        'myah.cli.dev.worktree.run',
        return_value=ShellResult(
            returncode=0,
            stdout=_porcelain(main, ('feat/foo', wt_path, 'deadbeef')),
            stderr='',
        ),
    )

    result = runner.invoke(app, ['dev', 'worktree', 'list'])

    assert result.exit_code == 0, result.output
    assert 'feat/foo' in result.output
    assert '8123' in result.output
    assert '5245' in result.output
    assert 'hosted' in result.output


def test_list_handles_missing_worktree_env_gracefully(mocker, tmp_path: Path) -> None:
    """If `.worktree-env` is missing, ports render as `—` and we don't crash."""
    main = tmp_path
    wt_path = main / '.worktrees' / 'feat/bar'
    wt_path.mkdir(parents=True)
    # no .worktree-env, no platform-oss/.env

    mocker.patch('myah.cli.dev.worktree.resolve_main_repo_root', return_value=main)
    mocker.patch(
        'myah.cli.dev.worktree.run',
        return_value=ShellResult(
            returncode=0,
            stdout=_porcelain(main, ('feat/bar', wt_path, 'deadbeef')),
            stderr='',
        ),
    )

    result = runner.invoke(app, ['dev', 'worktree', 'list'])

    assert result.exit_code == 0, result.output
    assert 'feat/bar' in result.output
    assert '—' in result.output


def test_list_detects_oss_mode(mocker, tmp_path: Path) -> None:
    """`MYAH_DEPLOYMENT_MODE=oss` in `platform-oss/.env` → mode column says `oss`."""
    main = tmp_path
    wt_path = main / '.worktrees' / 'feat/oss-thing'
    wt_path.mkdir(parents=True)
    (wt_path / '.worktree-env').write_text(
        'export BACKEND_PORT=8200\nexport FRONTEND_PORT=5300\n', encoding='utf-8',
    )
    (wt_path / 'platform-oss').mkdir()
    (wt_path / 'platform-oss' / '.env').write_text(
        'MYAH_DEPLOYMENT_MODE=oss\nMYAH_AUTH=false\n', encoding='utf-8',
    )

    mocker.patch('myah.cli.dev.worktree.resolve_main_repo_root', return_value=main)
    mocker.patch(
        'myah.cli.dev.worktree.run',
        return_value=ShellResult(
            returncode=0,
            stdout=_porcelain(main, ('feat/oss-thing', wt_path, 'deadbeef')),
            stderr='',
        ),
    )

    result = runner.invoke(app, ['dev', 'worktree', 'list'])

    assert result.exit_code == 0, result.output
    assert 'oss' in result.output
    assert 'feat/oss-thing' in result.output


def test_list_excludes_main_checkout(mocker, tmp_path: Path) -> None:
    """The main checkout (no `.worktrees/` ancestor) is filtered out."""
    main = tmp_path
    wt_path = main / '.worktrees' / 'feat/zzz'
    wt_path.mkdir(parents=True)
    (wt_path / '.worktree-env').write_text(
        'export BACKEND_PORT=8200\nexport FRONTEND_PORT=5300\n', encoding='utf-8',
    )

    mocker.patch('myah.cli.dev.worktree.resolve_main_repo_root', return_value=main)
    mocker.patch(
        'myah.cli.dev.worktree.run',
        return_value=ShellResult(
            returncode=0,
            stdout=_porcelain(main, ('feat/zzz', wt_path, 'deadbeef')),
            stderr='',
        ),
    )

    result = runner.invoke(app, ['dev', 'worktree', 'list'])

    assert result.exit_code == 0, result.output
    # Main's `master` branch must NOT appear as a row.
    assert 'master' not in result.output
    # But our worktree should.
    assert 'feat/zzz' in result.output


# ---------------------------------------------------------------------------
# destroy
# ---------------------------------------------------------------------------


def test_destroy_no_worktree_is_noop(mocker, tmp_path: Path) -> None:
    """If the path doesn't exist, exit 0 with a soft warning."""
    mocker.patch('myah.cli.dev.worktree.resolve_main_repo_root', return_value=tmp_path)
    mock_run = mocker.patch('myah.cli.dev.worktree.run')

    result = runner.invoke(app, ['dev', 'worktree', 'destroy', 'feat/missing'])

    assert result.exit_code == 0, result.output
    assert 'nothing to destroy' in result.output.lower()
    mock_run.assert_not_called()


def test_destroy_requires_confirmation_by_default(mocker, tmp_path: Path) -> None:
    """Without `--yes`, a 'n' answer at the prompt aborts without running git."""
    main = tmp_path
    wt_path = main / '.worktrees' / 'feat/foo'
    wt_path.mkdir(parents=True)

    mocker.patch('myah.cli.dev.worktree.resolve_main_repo_root', return_value=main)
    mock_run = mocker.patch('myah.cli.dev.worktree.run')

    result = runner.invoke(app, ['dev', 'worktree', 'destroy', 'feat/foo'], input='n\n')

    assert result.exit_code == 0, result.output
    mock_run.assert_not_called()


def test_destroy_yes_flag_skips_confirmation(mocker, tmp_path: Path) -> None:
    """`--yes` bypasses the confirmation prompt and runs git directly."""
    main = tmp_path
    wt_path = main / '.worktrees' / 'feat/foo'
    wt_path.mkdir(parents=True)

    mocker.patch('myah.cli.dev.worktree.resolve_main_repo_root', return_value=main)
    mock_run = mocker.patch(
        'myah.cli.dev.worktree.run',
        return_value=ShellResult(returncode=0, stdout='', stderr=''),
    )

    result = runner.invoke(app, ['dev', 'worktree', 'destroy', 'feat/foo', '--yes'])

    assert result.exit_code == 0, result.output
    assert mock_run.called


def test_destroy_invokes_git_worktree_remove(mocker, tmp_path: Path) -> None:
    """The destroy command shells out to `git worktree remove <path>`."""
    main = tmp_path
    wt_path = main / '.worktrees' / 'feat/foo'
    wt_path.mkdir(parents=True)

    mocker.patch('myah.cli.dev.worktree.resolve_main_repo_root', return_value=main)
    mock_run = mocker.patch(
        'myah.cli.dev.worktree.run',
        return_value=ShellResult(returncode=0, stdout='', stderr=''),
    )

    result = runner.invoke(app, ['dev', 'worktree', 'destroy', 'feat/foo', '--yes'])

    assert result.exit_code == 0, result.output
    cmd = mock_run.call_args.args[0]
    assert 'git' in cmd
    assert 'worktree' in cmd
    assert 'remove' in cmd
    assert str(wt_path) in cmd


def test_destroy_force_flag_passes_force_to_git(mocker, tmp_path: Path) -> None:
    """`--force` passes `--force` through to `git worktree remove`."""
    main = tmp_path
    wt_path = main / '.worktrees' / 'feat/foo'
    wt_path.mkdir(parents=True)

    mocker.patch('myah.cli.dev.worktree.resolve_main_repo_root', return_value=main)
    mock_run = mocker.patch(
        'myah.cli.dev.worktree.run',
        return_value=ShellResult(returncode=0, stdout='', stderr=''),
    )

    result = runner.invoke(app, ['dev', 'worktree', 'destroy', 'feat/foo', '--yes', '--force'])

    assert result.exit_code == 0, result.output
    cmd = mock_run.call_args.args[0]
    assert '--force' in cmd


def test_destroy_rmtree_after_git_remove(mocker, tmp_path: Path) -> None:
    """After git worktree remove succeeds, the path is rmtree'd."""
    main = tmp_path
    wt_path = main / '.worktrees' / 'feat/foo'
    (wt_path / '.venv').mkdir(parents=True)
    (wt_path / '.venv' / 'placeholder').write_text('x', encoding='utf-8')

    mocker.patch('myah.cli.dev.worktree.resolve_main_repo_root', return_value=main)
    mocker.patch(
        'myah.cli.dev.worktree.run',
        return_value=ShellResult(returncode=0, stdout='', stderr=''),
    )

    result = runner.invoke(app, ['dev', 'worktree', 'destroy', 'feat/foo', '--yes'])

    assert result.exit_code == 0, result.output
    assert not wt_path.exists()


def test_destroy_git_remove_failure_shows_force_hint(mocker, tmp_path: Path) -> None:
    """If `git worktree remove` fails, surface stderr + suggest `--force`."""
    main = tmp_path
    wt_path = main / '.worktrees' / 'feat/foo'
    wt_path.mkdir(parents=True)

    mocker.patch('myah.cli.dev.worktree.resolve_main_repo_root', return_value=main)
    mocker.patch(
        'myah.cli.dev.worktree.run',
        side_effect=ShellError(
            ['git', 'worktree', 'remove', str(wt_path)],
            ShellResult(returncode=1, stdout='', stderr='worktree is dirty'),
        ),
    )

    result = runner.invoke(app, ['dev', 'worktree', 'destroy', 'feat/foo', '--yes'])

    assert result.exit_code == 1, result.output
    assert '--force' in result.output


# ---------------------------------------------------------------------------
# help / registration
# ---------------------------------------------------------------------------


def test_worktree_subgroup_is_registered() -> None:
    """`myah dev worktree --help` lists all three commands."""
    result = runner.invoke(app, ['dev', 'worktree', '--help'])

    assert result.exit_code == 0
    assert 'create' in result.output
    assert 'list' in result.output
    assert 'destroy' in result.output
