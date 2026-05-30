"""Tests for ``myah upgrade [--check] [--yes]``.

Slice 5 Task 5.5 of T3-1084 (DevX + OSS CLI).

Composite of the four OSS upgrade steps:

  1. ``hermes update [--check|--yes]`` — bumps the Hermes runtime
  2. ``hermes plugins update myah`` — updates the Myah Hermes plugin
  3. ``git -C <repo-root> pull`` — refreshes Myah source (skips if not a
     clone; warns + skips if dirty tree)
  4. ``docker compose -f <repo-root>/docker-compose.yml build platform`` —
     rebuilds the local OSS platform image when the compose file has a
     local ``build:`` section; otherwise ``pull``s a prebuilt image, then
     recreates the platform container.

Mock target = consumer namespace (``myah.cli.upgrade.subprocess.run``,
``myah.cli.upgrade.resolve_hermes_binary_or_exit``,
``myah.cli.upgrade.find_repo_root``). Same discipline as Slices 2-4.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from myah import app
from typer.testing import CliRunner

runner = CliRunner()


# ── fixtures ───────────────────────────────────────────────────────────


@pytest.fixture
def fake_repo(mocker, tmp_path: Path) -> Path:
    """Pretend we're inside a Myah clone."""
    mocker.patch('myah.cli.upgrade.find_repo_root', return_value=tmp_path)
    return tmp_path


@pytest.fixture
def fake_hermes_bin(mocker, tmp_path: Path) -> Path:
    """Pretend the user has a system Hermes binary."""
    bin_path = tmp_path / 'hermes-venv' / 'bin' / 'hermes'
    mocker.patch(
        'myah.cli.upgrade.resolve_hermes_binary_or_exit', return_value=bin_path
    )
    return bin_path


def _ok(stdout: str = '') -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(args=[], returncode=0, stdout=stdout, stderr='')


def _fail(code: int = 1) -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(args=[], returncode=code, stdout='', stderr='boom')


def _write_local_build_compose(repo_root: Path) -> None:
    (repo_root / 'docker-compose.yml').write_text(
        'services:\n'
        '  platform:\n'
        '    image: myah/platform:latest\n'
        '    build:\n'
        '      context: .\n',
        encoding='utf-8',
    )


# ── --check short-circuit ──────────────────────────────────────────────


def test_upgrade_check_only_runs_hermes_update_check(
    fake_repo: Path, fake_hermes_bin: Path, mocker
) -> None:
    """`myah upgrade --check` runs only `hermes update --check` and stops."""
    run_mock = mocker.patch('myah.cli.upgrade.subprocess.run', return_value=_ok())

    result = runner.invoke(app, ['upgrade', '--check'])

    assert result.exit_code == 0, f'stdout: {result.stdout}\nexc: {result.exception}'
    # Exactly one subprocess call: hermes update --check.
    assert run_mock.call_count == 1
    cmd = run_mock.call_args.args[0]
    assert cmd == [str(fake_hermes_bin), 'update', '--check']


def test_upgrade_check_and_yes_both_forwarded(
    fake_repo: Path, fake_hermes_bin: Path, mocker
) -> None:
    """`--check` and `--yes` are independent — both flags forward to hermes.

    `hermes update --check --yes` is safe: Hermes ignores `--yes` in
    check-only mode. The earlier `elif` form silently dropped `--yes`
    when both were passed; the fixed form uses two independent `if`s.
    """
    run_mock = mocker.patch('myah.cli.upgrade.subprocess.run', return_value=_ok())

    result = runner.invoke(app, ['upgrade', '--check', '--yes'])

    assert result.exit_code == 0, f'stdout: {result.stdout}\nexc: {result.exception}'
    # Still short-circuits after the check call (no git / docker steps).
    assert run_mock.call_count == 1
    cmd = run_mock.call_args.args[0]
    assert cmd == [str(fake_hermes_bin), 'update', '--check', '--yes']


# ── full upgrade sequence ──────────────────────────────────────────────


def test_upgrade_yes_passes_through_to_hermes(
    fake_repo: Path, fake_hermes_bin: Path, mocker
) -> None:
    """`--yes` adds `--yes` to the hermes update argv."""
    run_mock = mocker.patch('myah.cli.upgrade.subprocess.run', return_value=_ok())

    result = runner.invoke(app, ['upgrade', '--yes'])

    assert result.exit_code == 0
    hermes_call = run_mock.call_args_list[0].args[0]
    assert hermes_call == [str(fake_hermes_bin), 'update', '--yes']


def test_upgrade_propagates_hermes_failure_and_short_circuits(
    fake_repo: Path, fake_hermes_bin: Path, mocker
) -> None:
    """`hermes update` non-zero → upgrade exits non-zero and skips git/docker."""
    # First call (hermes update) fails; later calls return ok so we can
    # detect them being skipped via assertion on call count.
    run_mock = mocker.patch(
        'myah.cli.upgrade.subprocess.run',
        side_effect=[_fail(7), _ok(), _ok(), _ok()],
    )

    result = runner.invoke(app, ['upgrade', '--yes'])

    assert result.exit_code == 7
    # Only one subprocess call — hermes update — fired.
    assert run_mock.call_count == 1


def test_upgrade_continues_when_platform_image_update_fails(
    fake_repo: Path, fake_hermes_bin: Path, mocker
) -> None:
    """Platform image refresh failure warns + continues; overall exit code is 0."""
    _write_local_build_compose(fake_repo)
    mocker.patch(
        'myah.cli.upgrade.subprocess.run',
        side_effect=[_ok(), _ok(), _ok(), _ok(), _fail(125)],
    )

    result = runner.invoke(app, ['upgrade', '--yes'])

    assert result.exit_code == 0, (
        f'platform image refresh failure should NOT abort upgrade; '
        f'got {result.exit_code}, stdout: {result.stdout}'
    )
    assert 'docker' in result.stdout.lower() or 'build' in result.stdout.lower()


def test_upgrade_batches_agent_plugin_source_and_platform_update(
    fake_repo: Path, fake_hermes_bin: Path, mocker
) -> None:
    """`myah upgrade` batches the individual update commands in order."""
    _write_local_build_compose(fake_repo)
    run_mock = mocker.patch('myah.cli.upgrade.subprocess.run', return_value=_ok())

    result = runner.invoke(app, ['upgrade', '--yes'])

    assert result.exit_code == 0, f'stdout: {result.stdout}\nexc: {result.exception}'
    calls = [c.args[0] for c in run_mock.call_args_list]
    assert calls == [
        [str(fake_hermes_bin), 'update', '--yes'],
        [str(fake_hermes_bin), 'plugins', 'update', 'myah'],
        ['git', '-C', str(fake_repo), 'status', '--porcelain'],
        ['git', '-C', str(fake_repo), 'pull'],
        ['docker', 'compose', '-f', str(fake_repo / 'docker-compose.yml'), 'build', 'platform'],
        ['docker', 'compose', '-f', str(fake_repo / 'docker-compose.yml'), 'up', '-d', '--force-recreate', 'platform'],
    ]


def test_upgrade_propagates_plugin_update_failure_and_short_circuits(
    fake_repo: Path, fake_hermes_bin: Path, mocker
) -> None:
    """Plugin update is a required upgrade step; failure skips source/platform updates."""
    run_mock = mocker.patch(
        'myah.cli.upgrade.subprocess.run',
        side_effect=[_ok(), _fail(9), _ok(), _ok()],
    )

    result = runner.invoke(app, ['upgrade', '--yes'])

    assert result.exit_code == 9
    calls = [c.args[0] for c in run_mock.call_args_list]
    assert calls == [
        [str(fake_hermes_bin), 'update', '--yes'],
        [str(fake_hermes_bin), 'plugins', 'update', 'myah'],
    ]


# ── outside-clone behavior ─────────────────────────────────────────────


def test_upgrade_skips_git_and_docker_outside_clone(
    fake_hermes_bin: Path, mocker
) -> None:
    """Outside a Myah clone → hermes update still runs; git+docker skipped."""
    mocker.patch(
        'myah.cli.upgrade.find_repo_root',
        side_effect=RuntimeError('Could not locate repo root.'),
    )
    run_mock = mocker.patch('myah.cli.upgrade.subprocess.run', return_value=_ok())

    result = runner.invoke(app, ['upgrade', '--yes'])

    assert result.exit_code == 0, f'stdout: {result.stdout}'
    # Only the Hermes + plugin update calls fired; repo/platform steps were skipped.
    assert run_mock.call_count == 2
    calls = [c.args[0] for c in run_mock.call_args_list]
    assert calls == [
        [str(fake_hermes_bin), 'update', '--yes'],
        [str(fake_hermes_bin), 'plugins', 'update', 'myah'],
    ]
    # Warning surfaces.
    assert 'clone' in result.stdout.lower() or 'skip' in result.stdout.lower()


# ── dirty-tree behavior ────────────────────────────────────────────────


def test_upgrade_skips_git_pull_and_local_build_on_dirty_tree(
    fake_repo: Path, fake_hermes_bin: Path, mocker
) -> None:
    """Dirty git tree → warn + skip git pull and local image rebuild."""
    _write_local_build_compose(fake_repo)
    # hermes update ok, git status returns non-empty (dirty), local platform build is skipped.
    run_mock = mocker.patch(
        'myah.cli.upgrade.subprocess.run',
        side_effect=[
            _ok(),  # hermes update
            _ok(),  # plugin update
            _ok(stdout=' M platform-oss/backend/myah/cli/upgrade.py\n'),
        ],
    )

    result = runner.invoke(app, ['upgrade', '--yes'])

    assert result.exit_code == 0
    # Warning about dirty tree.
    assert 'dirty' in result.stdout.lower() or 'uncommitted' in result.stdout.lower() \
        or 'skip' in result.stdout.lower()

    all_argvs = [c.args[0] for c in run_mock.call_args_list]
    pull_calls = [c for c in all_argvs if c[0] == 'git' and 'pull' in c]
    docker_calls = [c for c in all_argvs if c[:2] == ['docker', 'compose']]
    assert not pull_calls, f'git pull must NOT run with dirty tree; got: {all_argvs}'
    assert not docker_calls, f'local platform image build must NOT run with dirty tree; got: {all_argvs}'


def test_upgrade_skips_local_build_when_git_status_fails(
    fake_repo: Path, fake_hermes_bin: Path, mocker
) -> None:
    """Unknown git state → warn + skip local image rebuild/recreate."""
    _write_local_build_compose(fake_repo)
    run_mock = mocker.patch(
        'myah.cli.upgrade.subprocess.run',
        side_effect=[
            _ok(),  # hermes update
            _ok(),  # plugin update
            _fail(128),  # git status failed
        ],
    )

    result = runner.invoke(app, ['upgrade', '--yes'])

    assert result.exit_code == 0, f'stdout: {result.stdout}\nexc: {result.exception}'
    assert 'git status' in result.stdout.lower() or 'skipping' in result.stdout.lower()
    all_argvs = [c.args[0] for c in run_mock.call_args_list]
    docker_calls = [c for c in all_argvs if c[:2] == ['docker', 'compose']]
    assert not docker_calls, f'local platform image build must NOT run after git status failure; got: {all_argvs}'


def test_upgrade_still_pulls_registry_image_when_git_status_fails(
    fake_repo: Path, fake_hermes_bin: Path, mocker
) -> None:
    """Unknown git state only suppresses local builds; registry pulls remain safe."""
    (fake_repo / 'docker-compose.yml').write_text(
        'services:\n  platform:\n    image: ghcr.io/acme/myah:latest\n',
        encoding='utf-8',
    )
    run_mock = mocker.patch(
        'myah.cli.upgrade.subprocess.run',
        side_effect=[
            _ok(),  # hermes update
            _ok(),  # plugin update
            _fail(128),  # git status failed
            _ok(),  # docker pull
            _ok(),  # force recreate
        ],
    )

    result = runner.invoke(app, ['upgrade', '--yes'])

    assert result.exit_code == 0, f'stdout: {result.stdout}\nexc: {result.exception}'
    calls = [c.args[0] for c in run_mock.call_args_list]
    assert calls[-2:] == [
        ['docker', 'compose', '-f', str(fake_repo / 'docker-compose.yml'), 'pull'],
        ['docker', 'compose', '-f', str(fake_repo / 'docker-compose.yml'), 'up', '-d', '--force-recreate', 'platform'],
    ]


# ── binary-missing handling ────────────────────────────────────────────


def test_upgrade_handles_docker_not_in_path(
    fake_repo: Path, fake_hermes_bin: Path, mocker
) -> None:
    """If docker is missing, hermes update + git pull still succeed; docker step warns."""
    # hermes update ok, git status clean, git pull ok, docker pull raises FileNotFoundError.
    mocker.patch(
        'myah.cli.upgrade.subprocess.run',
        side_effect=[
            _ok(),  # hermes update
            _ok(),  # plugin update
            _ok(),  # git status
            _ok(),  # git pull
            FileNotFoundError("[Errno 2] No such file or directory: 'docker'"),
        ],
    )

    result = runner.invoke(app, ['upgrade', '--yes'])

    # Soft-fail: missing docker is a warning, not a fatal — the rest of
    # the upgrade succeeded.
    assert result.exit_code == 0, f'stdout: {result.stdout}\nexc: {result.exception}'
    assert 'docker' in result.stdout.lower()


def test_upgrade_handles_git_not_in_path(
    fake_repo: Path, fake_hermes_bin: Path, mocker
) -> None:
    """If git is missing, hermes update still ran; git step warns + skips."""
    # hermes update ok, then git status raises FileNotFoundError.
    mocker.patch(
        'myah.cli.upgrade.subprocess.run',
        side_effect=[
            _ok(),  # hermes update
            _ok(),  # plugin update
            FileNotFoundError("[Errno 2] No such file or directory: 'git'"),
            _ok(),  # docker build
            _ok(),  # force recreate
        ],
    )

    result = runner.invoke(app, ['upgrade', '--yes'])

    # Soft-fail: missing git is a warning, not a fatal.
    assert result.exit_code == 0, f'stdout: {result.stdout}'
    assert 'git' in result.stdout.lower()


# ── help + top-level ───────────────────────────────────────────────────


def test_upgrade_help_lists_flags() -> None:
    """`myah upgrade --help` mentions --check and --yes."""
    result = runner.invoke(app, ['upgrade', '--help'])

    assert result.exit_code == 0
    assert '--check' in result.stdout
    assert '--yes' in result.stdout


def test_top_level_help_lists_upgrade() -> None:
    """`myah --help` surfaces the `upgrade` command for OSS users."""
    result = runner.invoke(app, ['--help'])

    assert result.exit_code == 0
    assert 'upgrade' in result.stdout


# ── cold-start sentinel ────────────────────────────────────────────────


def test_upgrade_module_does_not_import_heavy_libs_at_top_level() -> None:
    """Rich / yaml / time / socket must stay out of the module top so
    `myah --help` cold-start holds under 200ms.
    """
    from myah.cli import upgrade as mod

    source = Path(mod.__file__).read_text(encoding='utf-8')
    head = source.split('\ndef ', 1)[0]

    offenders = (
        'import rich',
        'from rich',
        'import time',
        'import socket',
        'import yaml',
        'from yaml',
    )
    for offender in offenders:
        assert offender not in head, f'cli/upgrade.py top-level imports {offender!r}'
