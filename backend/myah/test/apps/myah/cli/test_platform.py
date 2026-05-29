"""Tests for ``myah platform {up,down,restart}``.

Slice 5 Task 5.3 of T3-1084 (DevX + OSS CLI).

Native — no Hermes equivalent. The "platform" here is the FastAPI
platform container (defined by the repo-root ``docker-compose.yml``),
NOT the Hermes agent (that's ``myah agent``) and NOT the per-worktree
hermes stack (that's ``myah dev oss``).

All three subcommands are thin wrappers around::

    docker compose -f <repo-root>/docker-compose.yml {up -d, down, restart}

Pre-flight: ``shutil.which('docker')`` → exit 2 with an install hint
when docker is absent. ``find_repo_root`` raising → exit 2 with a
"not inside a Myah clone" hint.

Mock target = consumer namespace (``myah.cli.platform_.run`` /
``myah.cli.platform_.find_repo_root`` /
``myah.cli.platform_.shutil.which``). Never patch source modules.
Same discipline as Slices 2-4.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from myah import app
from myah.lib.cli.shell import ShellResult
from typer.testing import CliRunner

runner = CliRunner()


# ── helpers ────────────────────────────────────────────────────────────


def _ok(stdout: str = '', stderr: str = '') -> ShellResult:
    return ShellResult(returncode=0, stdout=stdout, stderr=stderr)


@pytest.fixture
def fake_env(mocker, tmp_path: Path) -> Path:
    """Pretend docker is installed and we're inside a Myah clone.

    Returns the fake repo root so tests can assert on the compose-file
    path passed to docker.
    """
    mocker.patch('myah.cli.platform_.shutil.which', return_value='/usr/local/bin/docker')
    mocker.patch('myah.cli.platform_.find_repo_root', return_value=tmp_path)
    return tmp_path


# ── happy path: argv shape ─────────────────────────────────────────────


def test_platform_up_invokes_docker_compose_up_dash_d(fake_env: Path, mocker) -> None:
    """`myah platform up` invokes `docker compose -f <root>/docker-compose.yml up -d`.

    Now also runs a `docker ps` orphan pre-flight (S3) — empty stdout means
    no orphan, so the compose-up call still happens. We assert on the last
    invocation of ``run`` (the compose-up call).
    """
    run_mock = mocker.patch('myah.cli.platform_.run', return_value=_ok())

    result = runner.invoke(app, ['platform', 'up'])

    assert result.exit_code == 0, f'stdout: {result.stdout}\nexc: {result.exception}'
    # First call: orphan pre-flight. Last call: compose up.
    assert run_mock.call_count == 2
    cmd = run_mock.call_args_list[-1].args[0]
    assert cmd == [
        'docker',
        'compose',
        '-f',
        str(fake_env / 'docker-compose.yml'),
        'up',
        '-d',
    ]


def test_platform_up_bind_option_sets_compose_port_binding_env(fake_env: Path, mocker) -> None:
    """`myah platform up --bind 0.0.0.0` exposes the platform beyond localhost.

    The compose file reads MYAH_PLATFORM_BIND in its port mapping. The CLI
    should pass that env var only for this command, so users do not need to
    hand-edit docker-compose.yml just to access Myah over Tailscale/LAN.
    """
    run_mock = mocker.patch('myah.cli.platform_.run', return_value=_ok())

    result = runner.invoke(app, ['platform', 'up', '--bind', '0.0.0.0'])

    assert result.exit_code == 0, result.stdout
    compose_call = run_mock.call_args_list[-1]
    assert compose_call.kwargs['env']['MYAH_PLATFORM_BIND'] == '0.0.0.0'


def test_platform_up_expose_alias_sets_public_bind(fake_env: Path, mocker) -> None:
    """`--expose` is the easy-mode alias for remote/Tailscale access."""
    run_mock = mocker.patch('myah.cli.platform_.run', return_value=_ok())

    result = runner.invoke(app, ['platform', 'up', '--expose'])

    assert result.exit_code == 0, result.stdout
    compose_call = run_mock.call_args_list[-1]
    assert compose_call.kwargs['env']['MYAH_PLATFORM_BIND'] == '0.0.0.0'


def test_platform_down_invokes_docker_compose_down(fake_env: Path, mocker) -> None:
    """`myah platform down` invokes `docker compose -f <root>/docker-compose.yml down`.

    NOT `down -v` (would delete the SQLite volume — footgun guard).
    """
    run_mock = mocker.patch('myah.cli.platform_.run', return_value=_ok())

    result = runner.invoke(app, ['platform', 'down'])

    assert result.exit_code == 0, f'stdout: {result.stdout}\nexc: {result.exception}'
    cmd = run_mock.call_args.args[0]
    assert cmd == [
        'docker',
        'compose',
        '-f',
        str(fake_env / 'docker-compose.yml'),
        'down',
    ]
    # Footgun guard: no --volumes / -v in the argv.
    assert '-v' not in cmd
    assert '--volumes' not in cmd


def test_platform_restart_invokes_docker_compose_restart(fake_env: Path, mocker) -> None:
    """`myah platform restart` invokes `docker compose -f <root>/docker-compose.yml restart`."""
    run_mock = mocker.patch('myah.cli.platform_.run', return_value=_ok())

    result = runner.invoke(app, ['platform', 'restart'])

    assert result.exit_code == 0, f'stdout: {result.stdout}\nexc: {result.exception}'
    cmd = run_mock.call_args.args[0]
    assert cmd == [
        'docker',
        'compose',
        '-f',
        str(fake_env / 'docker-compose.yml'),
        'restart',
    ]


def test_platform_up_succeeds_when_compose_returns_0(fake_env: Path, mocker) -> None:
    """Successful docker compose run → exit 0; stdout surfaces."""
    mocker.patch(
        'myah.cli.platform_.run',
        return_value=_ok(stdout='Container platform Started\n'),
    )

    result = runner.invoke(app, ['platform', 'up'])

    assert result.exit_code == 0
    assert 'Container platform Started' in result.stdout


# ── error paths ────────────────────────────────────────────────────────


@pytest.mark.parametrize('verb', ['up', 'down', 'restart'])
def test_platform_exits_2_when_docker_missing(mocker, verb: str) -> None:
    """`shutil.which('docker') is None` → exit 2 with an install hint."""
    mocker.patch('myah.cli.platform_.shutil.which', return_value=None)
    # find_repo_root and run should not be reached.
    repo_mock = mocker.patch('myah.cli.platform_.find_repo_root')
    run_mock = mocker.patch('myah.cli.platform_.run')

    result = runner.invoke(app, ['platform', verb])

    assert result.exit_code == 2, f'wanted 2, got {result.exit_code}; stdout: {result.stdout}'
    repo_mock.assert_not_called()
    run_mock.assert_not_called()
    # Canonical substring from the actual emitted text. No `or`-fallback.
    assert 'docker is not installed' in result.stdout.lower(), (
        f'expected docker-install hint in: {result.stdout!r}'
    )


@pytest.mark.parametrize('verb', ['up', 'down', 'restart'])
def test_platform_exits_2_when_outside_myah_clone(mocker, verb: str) -> None:
    """`find_repo_root` raising RuntimeError → exit 2 with a clone hint."""
    mocker.patch('myah.cli.platform_.shutil.which', return_value='/usr/local/bin/docker')
    mocker.patch(
        'myah.cli.platform_.find_repo_root',
        side_effect=RuntimeError('Could not locate repo root.'),
    )
    run_mock = mocker.patch('myah.cli.platform_.run')

    result = runner.invoke(app, ['platform', verb])

    assert result.exit_code == 2, f'wanted 2, got {result.exit_code}; stdout: {result.stdout}'
    run_mock.assert_not_called()
    # Canonical substring from the actual emitted text. No `or`-fallback.
    assert 'Not inside a Myah clone' in result.stdout, (
        f'expected clone-not-found hint in: {result.stdout!r}'
    )


def test_platform_up_surfaces_failing_returncode_from_docker_compose(fake_env: Path, mocker) -> None:
    """Non-zero exit from docker compose propagates to typer's exit code."""
    mocker.patch(
        'myah.cli.platform_.run',
        return_value=ShellResult(returncode=125, stdout='', stderr='no such service'),
    )

    result = runner.invoke(app, ['platform', 'up'])

    assert result.exit_code == 125, f'wanted 125, got {result.exit_code}'


# ── help text ──────────────────────────────────────────────────────────


def test_platform_help_lists_subcommands() -> None:
    """`myah platform --help` enumerates up/down/restart."""
    result = runner.invoke(app, ['platform', '--help'])

    assert result.exit_code == 0
    assert 'up' in result.stdout
    assert 'down' in result.stdout
    assert 'restart' in result.stdout


def test_top_level_help_lists_platform_group() -> None:
    """`myah --help` must surface the `platform` subgroup for OSS users."""
    result = runner.invoke(app, ['--help'])

    assert result.exit_code == 0
    assert 'platform' in result.stdout


# ── cold-start sentinel ────────────────────────────────────────────────


def test_platform_module_does_not_import_heavy_libs_at_top_level() -> None:
    """Same pattern as agent.py / plugins.py — Rich, yaml, time, socket must
    stay out of the module top so `myah --help` cold-start stays under 200ms.
    """
    from myah.cli import platform_ as mod

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
        assert offender not in head, f'cli/platform_.py top-level imports {offender!r}'


# ── orphan-container pre-flight (S3) ───────────────────────────────────


def test_platform_up_detects_orphan_container_and_offers_removal(mocker):
    """Empirical (laptop, pre-A.2): a stale `myah-platform` container from
    another compose project blocks `myah platform up`. Detect it BEFORE
    issuing the compose command, surface the conflict, exit cleanly with
    a remediation hint."""
    from myah.lib.cli.shell import ShellResult

    # Mock docker ps returning a conflicting container.
    mock_run = mocker.patch('myah.cli.platform_.run')
    mock_run.return_value = ShellResult(
        returncode=0,
        stdout='c45a7d70f175\tmyah-platform\n',
        stderr='',
    )
    mocker.patch('myah.cli.platform_.find_repo_root', return_value='/tmp/fake-root')
    mocker.patch('myah.cli.platform_.shutil.which', return_value='/usr/bin/docker')

    result = runner.invoke(app, ['platform', 'up'])

    # Non-zero exit + clear remediation message — don't crash, don't
    # silently bring down the orphan.
    assert result.exit_code != 0
    assert 'orphan' in result.stdout.lower() or 'conflict' in result.stdout.lower()
    assert '--rm-orphans' in result.stdout or 'docker rm' in result.stdout


def test_platform_up_rm_orphans_flag_removes_then_starts(mocker):
    """--rm-orphans: detect the orphan, `docker rm -f` it, then start."""
    from myah.lib.cli.shell import ShellResult

    mock_run = mocker.patch('myah.cli.platform_.run')
    # docker ps → orphan present → docker rm -f → compose up.
    mock_run.side_effect = [
        ShellResult(returncode=0, stdout='c45a7d70f175\tmyah-platform\n', stderr=''),  # ps
        ShellResult(returncode=0, stdout='', stderr=''),  # rm
        ShellResult(returncode=0, stdout='Started', stderr=''),  # compose up
    ]
    mocker.patch('myah.cli.platform_.find_repo_root', return_value='/tmp/fake-root')
    mocker.patch('myah.cli.platform_.shutil.which', return_value='/usr/bin/docker')

    result = runner.invoke(app, ['platform', 'up', '--rm-orphans'])

    assert result.exit_code == 0, result.stdout
    # Verify the `docker rm -f` call was made.
    argvs = [c.args[0] for c in mock_run.call_args_list]
    assert any(a[:2] == ['docker', 'rm'] and '-f' in a for a in argvs), (
        f'expected `docker rm -f` call; got argvs: {argvs}'
    )
