"""Tests for ``myah uninstall [--keep-data] [--keep-config] [--yes]``.

Slice 5 Task 5.5 of T3-1084 (DevX + OSS CLI).

Composite of the three OSS removal steps:

  1. Confirm (unless `--yes`)
  2. ``docker compose -f <repo-root>/docker-compose.yml down [-v]``
     (`-v` unless `--keep-data`)
  3. ``hermes uninstall [--full] --yes`` (``--full`` unless either
     `--keep-data` or `--keep-config` is set — Hermes treats data +
     config as one bundle, so the two flags are partially redundant
     at the Hermes layer)
  4. Remove ``<repo-root>/platform-oss/.env`` (unless `--keep-config`)

Mock target = consumer namespace
(``myah.cli.uninstall.subprocess.run``,
 ``myah.cli.uninstall.resolve_hermes_binary_or_exit``,
 ``myah.cli.uninstall.find_repo_root``).
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
    """Pretend we're inside a Myah clone (monorepo layout) with a populated platform-oss/.env."""
    mocker.patch('myah.cli.uninstall.find_repo_root', return_value=tmp_path)
    # Sentinel: agent/Dockerfile.stock signals the monorepo layout, so
    # find_platform_env_path returns <tmp_path>/platform-oss/.env.
    (tmp_path / 'agent').mkdir(exist_ok=True)
    (tmp_path / 'agent' / 'Dockerfile.stock').write_text(
        'ARG HERMES_SHA=' + 'a' * 40 + '\n', encoding='utf-8'
    )
    # Create a platform-oss/.env so removal-detection is meaningful.
    (tmp_path / 'platform-oss').mkdir(exist_ok=True)
    (tmp_path / 'platform-oss' / '.env').write_text('FOO=bar\n', encoding='utf-8')
    return tmp_path


@pytest.fixture
def fake_public_repo(mocker, tmp_path: Path) -> Path:
    """Pretend we're inside the public OSS mirror (versions.env sentinel, flat layout).

    Regression coverage for C-1: uninstall must remove ``<root>/.env``
    here, not ``<root>/platform-oss/.env`` (which doesn't exist).
    """
    mocker.patch('myah.cli.uninstall.find_repo_root', return_value=tmp_path)
    (tmp_path / 'versions.env').write_text('MYAH_PLUGIN_SHA=' + 'b' * 40 + '\n', encoding='utf-8')
    (tmp_path / '.env').write_text('FOO=bar\n', encoding='utf-8')
    return tmp_path


@pytest.fixture
def fake_hermes_bin(mocker, tmp_path: Path) -> Path:
    bin_path = tmp_path / 'hermes-venv' / 'bin' / 'hermes'
    mocker.patch(
        'myah.cli.uninstall.resolve_hermes_binary_or_exit', return_value=bin_path
    )
    return bin_path


def _ok() -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(args=[], returncode=0, stdout='', stderr='')


def _fail(code: int = 1) -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(args=[], returncode=code, stdout='', stderr='boom')


# ── default: everything removed ────────────────────────────────────────


def test_uninstall_default_preserves_existing_hermes_agent(
    fake_repo: Path, fake_hermes_bin: Path, mocker
) -> None:
    """Default `--yes`: docker compose down -v + hermes uninstall --yes + remove .env.

    Myah OSS is bring-your-own-Hermes, so the default uninstall must not pass
    `--full` to Hermes. Users often install Myah against an existing Hermes
    profile with real providers, chats, and tasks; deleting that agent is a bad
    OSS footgun.
    """
    run_mock = mocker.patch('myah.cli.uninstall.subprocess.run', return_value=_ok())
    env_path = fake_repo / 'platform-oss' / '.env'
    assert env_path.is_file()

    result = runner.invoke(app, ['uninstall', '--yes'])

    assert result.exit_code == 0, f'stdout: {result.stdout}\nexc: {result.exception}'
    calls = [c.args[0] for c in run_mock.call_args_list]

    # docker compose down -v
    docker_idx = next(
        i for i, c in enumerate(calls) if c[:2] == ['docker', 'compose'] and 'down' in c
    )
    assert '-v' in calls[docker_idx], (
        f'Expected -v in docker compose down argv; got {calls[docker_idx]}'
    )
    assert calls[docker_idx] == [
        'docker',
        'compose',
        '-f',
        str(fake_repo / 'docker-compose.yml'),
        'down',
        '-v',
    ]

    # hermes uninstall --yes, but never --full by default.
    hermes_idx = next(
        i for i, c in enumerate(calls) if c[0] == str(fake_hermes_bin) and 'uninstall' in c
    )
    assert '--full' not in calls[hermes_idx]
    assert '--yes' in calls[hermes_idx]

    # platform-oss/.env removed
    assert not env_path.is_file()


# ── flag matrix ────────────────────────────────────────────────────────


def test_uninstall_keep_data_preserves_volume_and_hermes_state(
    fake_repo: Path, fake_hermes_bin: Path, mocker
) -> None:
    """`--keep-data`: no `-v` on docker down; no `--full` on hermes uninstall."""
    run_mock = mocker.patch('myah.cli.uninstall.subprocess.run', return_value=_ok())

    result = runner.invoke(app, ['uninstall', '--keep-data', '--yes'])

    assert result.exit_code == 0
    calls = [c.args[0] for c in run_mock.call_args_list]

    docker_idx = next(
        i for i, c in enumerate(calls) if c[:2] == ['docker', 'compose'] and 'down' in c
    )
    assert '-v' not in calls[docker_idx]

    hermes_idx = next(
        i for i, c in enumerate(calls) if c[0] == str(fake_hermes_bin) and 'uninstall' in c
    )
    assert '--full' not in calls[hermes_idx]
    assert '--yes' in calls[hermes_idx]


def test_uninstall_keep_config_preserves_platform_env_and_hermes_state(
    fake_repo: Path, fake_hermes_bin: Path, mocker
) -> None:
    """`--keep-config`: platform .env preserved; docker volume still removed; no `--full` on hermes."""
    run_mock = mocker.patch('myah.cli.uninstall.subprocess.run', return_value=_ok())
    env_path = fake_repo / 'platform-oss' / '.env'

    result = runner.invoke(app, ['uninstall', '--keep-config', '--yes'])

    assert result.exit_code == 0
    # .env still exists.
    assert env_path.is_file()

    # docker volume IS removed — `--keep-data` is the only flag that
    # suppresses `-v`; `--keep-config` does not.
    calls = [c.args[0] for c in run_mock.call_args_list]
    docker_idx = next(
        i for i, c in enumerate(calls) if c[:2] == ['docker', 'compose'] and 'down' in c
    )
    assert '-v' in calls[docker_idx], (
        f'`--keep-config` alone must NOT suppress `-v` (that is `--keep-data`\'s job); '
        f'got {calls[docker_idx]}'
    )


def test_uninstall_keep_config_skips_hermes_full(
    fake_repo: Path, fake_hermes_bin: Path, mocker
) -> None:
    """`--keep-config` alone also drops the `--full` flag from hermes uninstall."""
    run_mock = mocker.patch('myah.cli.uninstall.subprocess.run', return_value=_ok())

    result = runner.invoke(app, ['uninstall', '--keep-config', '--yes'])

    assert result.exit_code == 0
    calls = [c.args[0] for c in run_mock.call_args_list]
    hermes_idx = next(
        i for i, c in enumerate(calls) if c[0] == str(fake_hermes_bin) and 'uninstall' in c
    )
    assert '--full' not in calls[hermes_idx]


def test_uninstall_both_flags_preserves_all_state(
    fake_repo: Path, fake_hermes_bin: Path, mocker
) -> None:
    """`--keep-data --keep-config`: tear down running services only, all state kept."""
    run_mock = mocker.patch('myah.cli.uninstall.subprocess.run', return_value=_ok())
    env_path = fake_repo / 'platform-oss' / '.env'

    result = runner.invoke(app, ['uninstall', '--keep-data', '--keep-config', '--yes'])

    assert result.exit_code == 0
    calls = [c.args[0] for c in run_mock.call_args_list]

    # No -v on docker compose down.
    docker_idx = next(
        i for i, c in enumerate(calls) if c[:2] == ['docker', 'compose'] and 'down' in c
    )
    assert '-v' not in calls[docker_idx]

    # No --full on hermes uninstall.
    hermes_idx = next(
        i for i, c in enumerate(calls) if c[0] == str(fake_hermes_bin) and 'uninstall' in c
    )
    assert '--full' not in calls[hermes_idx]

    # platform .env preserved.
    assert env_path.is_file()


# ── confirmation prompt ────────────────────────────────────────────────


def test_uninstall_yes_skips_confirmation_prompt(
    fake_repo: Path, fake_hermes_bin: Path, mocker
) -> None:
    """`--yes` bypasses the interactive confirm."""
    run_mock = mocker.patch('myah.cli.uninstall.subprocess.run', return_value=_ok())

    result = runner.invoke(app, ['uninstall', '--yes'])

    assert result.exit_code == 0
    # Steps ran (proves we didn't abort on a prompt).
    assert run_mock.call_count >= 2


def test_uninstall_no_yes_aborts_on_no(
    fake_repo: Path, fake_hermes_bin: Path, mocker
) -> None:
    """Without `--yes`: prompt; answering "n" aborts before any side effects."""
    run_mock = mocker.patch('myah.cli.uninstall.subprocess.run', return_value=_ok())
    env_path = fake_repo / 'platform-oss' / '.env'

    result = runner.invoke(app, ['uninstall'], input='n\n')

    # User declined; .env preserved and no subprocess calls.
    assert env_path.is_file()
    run_mock.assert_not_called()


def test_uninstall_no_yes_proceeds_on_yes_input(
    fake_repo: Path, fake_hermes_bin: Path, mocker
) -> None:
    """Without `--yes`: answering "y" at the prompt proceeds with removal."""
    run_mock = mocker.patch('myah.cli.uninstall.subprocess.run', return_value=_ok())

    result = runner.invoke(app, ['uninstall'], input='y\n')

    assert result.exit_code == 0, f'stdout: {result.stdout}\nexc: {result.exception}'
    assert run_mock.call_count >= 2


# ── soft-fail behavior ────────────────────────────────────────────────


def test_uninstall_continues_platform_cleanup_after_hermes_failure(
    fake_repo: Path, fake_hermes_bin: Path, mocker
) -> None:
    """Hermes uninstall failure does NOT abort docker compose down / .env removal.

    Soft-fail policy: even if hermes uninstall fails (e.g. corrupted state),
    still tear down the platform side so the user can re-install cleanly.
    The hermes failure is intentionally swallowed (exit 0 + warning) — the
    main user-observable outcome (platform cleanup) succeeded.
    """
    # Sequence: docker down ok, hermes uninstall fails. Stub
    # remove_service_units so it doesn't pull extra subprocess.run
    # calls into the side_effect queue.
    mocker.patch('myah.cli.uninstall.remove_service_units')
    mocker.patch(
        'myah.cli.uninstall.subprocess.run',
        side_effect=[_ok(), _fail(3)],
    )
    env_path = fake_repo / 'platform-oss' / '.env'

    result = runner.invoke(app, ['uninstall', '--yes'])

    # Soft-fail policy: hermes failure is swallowed (exit 0 + yellow
    # warning), since the platform-side cleanup still succeeded.
    assert result.exit_code == 0, (
        f'soft-fail policy: hermes failure should NOT abort overall; '
        f'got exit {result.exit_code}, stdout: {result.stdout}'
    )
    # platform .env removed even though hermes uninstall failed.
    assert not env_path.is_file()
    # Warning surfaces.
    assert 'hermes' in result.stdout.lower() or 'warn' in result.stdout.lower() \
        or 'fail' in result.stdout.lower()


# ── outside-clone behavior ─────────────────────────────────────────────


def test_uninstall_skips_docker_outside_clone(
    fake_hermes_bin: Path, mocker
) -> None:
    """Outside a Myah clone → hermes uninstall still runs; docker + .env skipped."""
    mocker.patch(
        'myah.cli.uninstall.find_repo_root',
        side_effect=RuntimeError('Could not locate repo root.'),
    )
    # Stub remove_service_units so its launchctl/systemctl calls don't
    # contaminate run_mock.call_count.
    mocker.patch('myah.cli.uninstall.remove_service_units')
    run_mock = mocker.patch('myah.cli.uninstall.subprocess.run', return_value=_ok())

    result = runner.invoke(app, ['uninstall', '--yes'])

    assert result.exit_code == 0, f'stdout: {result.stdout}'
    # Only hermes uninstall was fired; no docker compose call.
    assert run_mock.call_count == 1
    cmd = run_mock.call_args.args[0]
    assert cmd[0] == str(fake_hermes_bin)
    assert 'uninstall' in cmd
    # Warning surfaces.
    assert 'clone' in result.stdout.lower() or 'skip' in result.stdout.lower()


# ── C-1 regression: public-mirror layout removes <root>/.env, not platform-oss/ ──


def test_uninstall_public_mirror_removes_root_env(
    fake_public_repo: Path, fake_hermes_bin: Path, mocker
) -> None:
    """On the public OSS mirror layout, uninstall must remove ``<root>/.env``.

    Regression for PR #16 review C-1: the path was hard-coded to
    ``platform-oss/.env`` which doesn't exist on the public mirror,
    so the actual ``.env`` (which docker-compose reads) survived a
    "full" uninstall.
    """
    mocker.patch('myah.cli.uninstall.subprocess.run', return_value=_ok())
    root_env = fake_public_repo / '.env'
    legacy_env = fake_public_repo / 'platform-oss' / '.env'
    assert root_env.is_file()
    assert not legacy_env.exists()

    result = runner.invoke(app, ['uninstall', '--yes'])

    assert result.exit_code == 0, result.stdout
    assert not root_env.is_file(), '<root>/.env must be removed on the public mirror'


# ── help + top-level ───────────────────────────────────────────────────


def test_uninstall_help_lists_flags() -> None:
    """`myah uninstall --help` mentions --keep-data, --keep-config, --yes."""
    result = runner.invoke(app, ['uninstall', '--help'])

    assert result.exit_code == 0
    assert '--keep-data' in result.stdout
    assert '--keep-config' in result.stdout
    assert '--yes' in result.stdout


def test_top_level_help_lists_uninstall() -> None:
    """`myah --help` surfaces the `uninstall` command for OSS users."""
    result = runner.invoke(app, ['--help'])

    assert result.exit_code == 0
    assert 'uninstall' in result.stdout


# ── cold-start sentinel ────────────────────────────────────────────────


def test_uninstall_module_does_not_import_heavy_libs_at_top_level() -> None:
    """Rich / yaml / time / socket must stay out of the module top so
    `myah --help` cold-start holds under 200ms.
    """
    from myah.cli import uninstall as mod

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
        assert offender not in head, f'cli/uninstall.py top-level imports {offender!r}'


# ── service-unit teardown (A.4) ───────────────────────────────────────


def test_uninstall_removes_service_units(fake_repo, fake_hermes_bin, mocker):
    """Symmetric teardown: `myah uninstall` must call remove_service_units
    so launchd plists / systemd-user units don't survive uninstall.
    Regression for PR #16 post-merge laptop test, simplification S5.
    """
    mocker.patch('myah.cli.uninstall.subprocess.run', return_value=_ok())
    mock_remove = mocker.patch('myah.cli.uninstall.remove_service_units')

    result = runner.invoke(app, ['uninstall', '--yes'])

    assert result.exit_code == 0, result.stdout
    mock_remove.assert_called_once()


# ── A.5: hermes uninstall TTY-failure graceful recovery ────────────────


def test_uninstall_hermes_tty_failure_prints_clear_recovery(
    fake_repo, fake_hermes_bin, mocker
):
    """When `hermes uninstall` fails with the TTY-required signature,
    print a one-line copy-paste recovery command instead of a generic
    'returned exit N' warning. Regression for PR #16 H-5 + post-merge
    laptop test, simplification S6.
    """
    tty_failure = subprocess.CompletedProcess(
        args=[],
        returncode=1,
        stdout="Error: 'hermes uninstall' requires an interactive terminal.\n",
        stderr='',
    )
    mocker.patch(
        'myah.cli.uninstall.subprocess.run',
        side_effect=[_ok(), tty_failure],  # docker down OK, hermes fails
    )
    mocker.patch('myah.cli.uninstall.remove_service_units')

    result = runner.invoke(app, ['uninstall', '--yes'])

    assert result.exit_code == 0, result.stdout
    # Recovery hint must be precise + copy-paste-ready.
    assert 'rm -rf ~/.hermes' in result.stdout or '--force-purge-hermes' in result.stdout
    assert 'interactive terminal' in result.stdout.lower() or 'TTY' in result.stdout


def test_uninstall_force_purge_hermes_removes_dir_when_hermes_uninstall_fails(
    fake_repo, fake_hermes_bin, tmp_path, mocker, monkeypatch
):
    """--force-purge-hermes: when `hermes uninstall` fails (TTY or other),
    fall through to `rm -rf $HERMES_HOME` so the cron-safe form actually
    tears down. Opt-in only.
    """
    fake_hermes_home = tmp_path / 'fake-hermes'
    fake_hermes_home.mkdir()
    (fake_hermes_home / 'config.yaml').write_text('# test')
    monkeypatch.setenv('HERMES_HOME', str(fake_hermes_home))

    tty_failure = subprocess.CompletedProcess(
        args=[], returncode=1,
        stdout="Error: 'hermes uninstall' requires an interactive terminal.\n",
        stderr='',
    )
    mocker.patch(
        'myah.cli.uninstall.subprocess.run',
        side_effect=[_ok(), tty_failure],
    )
    mocker.patch('myah.cli.uninstall.remove_service_units')

    result = runner.invoke(
        app, ['uninstall', '--yes', '--force-purge-hermes']
    )

    assert result.exit_code == 0, result.stdout
    assert not fake_hermes_home.exists(), (
        f'HERMES_HOME survived --force-purge-hermes: {fake_hermes_home}'
    )
