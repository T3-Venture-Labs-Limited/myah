"""Tests for individual health-check predicates used by myah doctor."""

import pytest

from myah.lib.cli.doctor_checks import (
    CheckResult,
    CheckStatus,
    check_hermes_binary_on_path,
    check_hermes_plugin_installed,
    check_platform_container_running,
    check_plugin_sha_drift,
    check_port_for_service,
)


def test_check_result_dataclass_has_name_status_message() -> None:
    """CheckResult has the three fields the renderer uses."""
    result = CheckResult(name='X', status=CheckStatus.OK, message='all good')
    assert result.name == 'X'
    assert result.status == CheckStatus.OK
    assert result.message == 'all good'


def test_check_status_enum_has_ok_warn_fail() -> None:
    """Three status values cover the rendering needs."""
    assert CheckStatus.OK.value == 'ok'
    assert CheckStatus.WARN.value == 'warn'
    assert CheckStatus.FAIL.value == 'fail'


def test_check_hermes_binary_on_path_ok(mocker) -> None:
    """When `hermes` is on PATH, the check returns OK."""
    # Use shutil.which (more portable than `which` subprocess); patch at consumer namespace.
    mocker.patch('myah.lib.cli.doctor_checks.shutil.which', return_value='/usr/local/bin/hermes')

    result = check_hermes_binary_on_path()

    assert result.status == CheckStatus.OK
    assert '/usr/local/bin/hermes' in result.message


def test_check_hermes_binary_on_path_fail(mocker) -> None:
    """When `hermes` is not on PATH, the check returns FAIL with install hint."""
    mocker.patch('myah.lib.cli.doctor_checks.shutil.which', return_value=None)

    result = check_hermes_binary_on_path()

    assert result.status == CheckStatus.FAIL
    assert 'install' in result.message.lower() or 'not found' in result.message.lower()


def test_check_port_for_service_free_returns_ok(mocker) -> None:
    """When the port is free, check returns OK with 'available'."""
    # Patch socket.socket at the CONSUMER module (where doctor_checks looked it up).
    mock_socket = mocker.patch('myah.lib.cli.doctor_checks.socket.socket')
    mock_socket.return_value.__enter__.return_value.bind.return_value = None

    result = check_port_for_service(8080)

    assert result.status == CheckStatus.OK
    assert '8080' in result.message
    assert 'available' in result.message.lower()


def test_check_port_for_service_in_use_returns_ok(mocker) -> None:
    """When the port is bound (presumed by the paired service), check returns OK.

    Reverses the original semantic — a healthy stack binds its ports, so
    'port in use' must NOT be FAIL. The paired container/service check
    validates the owner; this check is a state probe only.
    """
    mock_socket = mocker.patch('myah.lib.cli.doctor_checks.socket.socket')
    mock_socket.return_value.__enter__.return_value.bind.side_effect = OSError('Address already in use')

    result = check_port_for_service(8080)

    assert result.status == CheckStatus.OK
    assert '8080' in result.message
    assert 'in use' in result.message.lower()


def test_check_port_for_service_with_service_name(mocker) -> None:
    """When a service_name is supplied and the port is bound, name appears in message."""
    mock_socket = mocker.patch('myah.lib.cli.doctor_checks.socket.socket')
    mock_socket.return_value.__enter__.return_value.bind.side_effect = OSError('Address already in use')

    result = check_port_for_service(8080, 'myah-platform')

    assert result.status == CheckStatus.OK
    assert 'myah-platform' in result.message


def test_check_hermes_plugin_installed_ok(mocker) -> None:
    """When the plugin is installed at HERMES_HOME/plugins/, check returns OK."""
    from myah.lib.cli.shell import ShellResult
    mock_run = mocker.patch('myah.lib.cli.doctor_checks.run')
    mock_run.return_value = ShellResult(
        returncode=0,
        stdout='myah-hermes-plugin 1.0.7\n',
        stderr='',
    )

    result = check_hermes_plugin_installed(hermes_home='/tmp/.hermes')

    assert result.status == CheckStatus.OK
    assert '1.0.7' in result.message or 'installed' in result.message.lower()


def test_check_hermes_plugin_installed_fail(mocker) -> None:
    """When the plugin is missing, check returns FAIL with install hint."""
    from myah.lib.cli.shell import ShellResult
    mock_run = mocker.patch('myah.lib.cli.doctor_checks.run')
    mock_run.return_value = ShellResult(returncode=1, stdout='', stderr='no plugins found')

    result = check_hermes_plugin_installed(hermes_home='/tmp/.hermes')

    assert result.status == CheckStatus.FAIL
    assert 'install' in result.message.lower()


def test_check_hermes_plugin_installed_matches_real_hermes_0_14_output(mocker) -> None:
    """Regression for PR #16 review H-3: ``hermes plugins list`` on
    Hermes 0.14.0 prints a Rich table with the plugin name ``myah`` —
    not ``myah-hermes-plugin``. The old grep for ``myah-hermes-plugin``
    in stdout produced a false FAIL on every healthy install.

    The verbatim Hermes 0.14.0 output captured on the VM was:

        ┃ Name ┃ Status      ┃ Version ┃ Description ...
        ┡━━━━━━╇━━━━━━━━━━━━━╇━━━━━━━━━╇━━━━━━━━━━━━━...
        │ myah │ enabled     │ 1.1.1   │ Myah platform ...
    """
    from myah.lib.cli.shell import ShellResult
    real_hermes_output = (
        '                                    Plugins                                     \n'
        '┏━━━━━━┳━━━━━━━━━━━━━┳━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━┓\n'
        '┃ Name ┃ Status      ┃ Version ┃ Description                          ┃ Source ┃\n'
        '┡━━━━━━╇━━━━━━━━━━━━━╇━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━┩\n'
        '│ myah │ enabled     │ 1.1.1   │ Myah platform adapter for Hermes     │ git    │\n'
        '└──────┴─────────────┴─────────┴──────────────────────────────────────┴────────┘\n'
    )
    mock_run = mocker.patch('myah.lib.cli.doctor_checks.run')
    mock_run.return_value = ShellResult(returncode=0, stdout=real_hermes_output, stderr='')

    result = check_hermes_plugin_installed(hermes_home='/tmp/.hermes')

    assert result.status == CheckStatus.OK, (
        f'Real Hermes 0.14.0 output must be recognized as installed; got {result}'
    )
    assert '1.1.1' in result.message, f'version 1.1.1 should appear in message; got: {result.message}'


def test_check_hermes_plugin_does_not_false_positive_on_myah_admin(mocker) -> None:
    """The dashboard shim is registered as ``myah-admin``. That row alone
    must NOT cause the gateway-side ``myah`` plugin to be reported as
    installed — they are independent plugins, and only ``myah`` makes
    port 8643 bind.
    """
    from myah.lib.cli.shell import ShellResult
    only_admin = (
        '┃ Name       ┃ Status      ┃ Version ┃\n'
        '│ myah-admin │ enabled     │ 1.1.1   │\n'
    )
    mock_run = mocker.patch('myah.lib.cli.doctor_checks.run')
    mock_run.return_value = ShellResult(returncode=0, stdout=only_admin, stderr='')

    result = check_hermes_plugin_installed(hermes_home='/tmp/.hermes')

    assert result.status == CheckStatus.FAIL, (
        'myah-admin alone must not satisfy the myah-plugin check'
    )


def test_check_hermes_plugin_installed_default_expands_tilde(mocker, monkeypatch) -> None:
    """The default hermes_home expands ~ via os.path.expanduser.

    Without expansion, passing 'HERMES_HOME=~/.hermes' to the subprocess would
    point hermes at a literal '~' directory (which doesn't exist), making
    the check report FAIL even on machines with the plugin correctly installed.
    """
    from myah.lib.cli.shell import ShellResult
    monkeypatch.setenv('HOME', '/Users/testuser')
    mock_run = mocker.patch('myah.lib.cli.doctor_checks.run')
    mock_run.return_value = ShellResult(returncode=0, stdout='myah-hermes-plugin 1.0.7\n', stderr='')

    check_hermes_plugin_installed()  # no arg, default expansion

    # Inspect the run call to verify HERMES_HOME was the expanded path, not '~/.hermes'
    call_env = mock_run.call_args.kwargs['env']
    assert call_env['HERMES_HOME'] == '/Users/testuser/.hermes', (
        f"HERMES_HOME should be expanded; got: {call_env['HERMES_HOME']}"
    )
    assert '~' not in call_env['HERMES_HOME']


def test_check_platform_container_running_ok(mocker) -> None:
    """When `docker ps` shows myah-platform, check returns OK."""
    from myah.lib.cli.shell import ShellResult
    mock_run = mocker.patch('myah.lib.cli.doctor_checks.run')
    mock_run.return_value = ShellResult(
        returncode=0,
        stdout='abc123  myah/platform:latest  Up 5 minutes  0.0.0.0:8080->8080/tcp  myah-platform\n',
        stderr='',
    )

    result = check_platform_container_running()

    assert result.status == CheckStatus.OK
    assert 'platform' in result.message.lower()


def test_check_platform_container_running_warn_when_down(mocker) -> None:
    """When the docker daemon is responsive but no container matches, check returns WARN."""
    from myah.lib.cli.shell import ShellResult
    mock_run = mocker.patch('myah.lib.cli.doctor_checks.run')
    mock_run.return_value = ShellResult(returncode=0, stdout='', stderr='')

    result = check_platform_container_running()

    assert result.status == CheckStatus.WARN
    assert 'not running' in result.message.lower() or 'down' in result.message.lower()


def test_check_platform_container_running_fail_when_docker_daemon_down(mocker) -> None:
    """When `docker ps` returns non-zero (daemon down / permission denied), check returns FAIL.

    Distinct from the WARN case above: daemon-down requires operator action
    (systemctl start docker, fix permissions, install Docker) before any
    container can run, whereas WARN only requires `myah platform up`.
    """
    from myah.lib.cli.shell import ShellResult
    mock_run = mocker.patch('myah.lib.cli.doctor_checks.run')
    mock_run.return_value = ShellResult(
        returncode=1,
        stdout='',
        stderr='Cannot connect to the Docker daemon at unix:///var/run/docker.sock. Is the docker daemon running?',
    )

    result = check_platform_container_running()

    assert result.status == CheckStatus.FAIL
    assert 'daemon' in result.message.lower() or 'permission' in result.message.lower()


def test_check_plugin_sha_drift_ok_when_consistent(tmp_path, mocker) -> None:
    """When Dockerfile and deploy.yml pin the same SHA, check returns OK."""
    dockerfile = tmp_path / 'Dockerfile.stock'
    dockerfile.write_text(
        'ARG HERMES_SHA=faa13e49f81480771ceeb55991bb0c27edf1a5fb\n'
        'ARG MYAH_PLUGIN_SHA=99abf4ee0c19a3d4f5e6a7b8c9d0e1f2a3b4c5d6\n'
    )
    deploy_yml = tmp_path / 'deploy.yml'
    deploy_yml.write_text(
        '          MYAH_PLUGIN_SHA=99abf4ee0c19a3d4f5e6a7b8c9d0e1f2a3b4c5d6\n'
    )

    result = check_plugin_sha_drift(
        dockerfile_path=str(dockerfile),
        deploy_yml_path=str(deploy_yml),
    )

    assert result.status == CheckStatus.OK


def test_check_plugin_sha_drift_warn_when_different(tmp_path) -> None:
    """When Dockerfile and deploy.yml pin different SHAs, check returns WARN."""
    dockerfile = tmp_path / 'Dockerfile.stock'
    dockerfile.write_text('ARG MYAH_PLUGIN_SHA=99abf4ee0c19a3d4f5e6a7b8c9d0e1f2a3b4c5d6\n')
    deploy_yml = tmp_path / 'deploy.yml'
    deploy_yml.write_text('          MYAH_PLUGIN_SHA=4a1a6c5e000000000000000000000000abcdef00\n')

    result = check_plugin_sha_drift(
        dockerfile_path=str(dockerfile),
        deploy_yml_path=str(deploy_yml),
    )

    assert result.status == CheckStatus.WARN
    assert '99abf4ee' in result.message
    assert '4a1a6c5e' in result.message


def test_check_plugin_sha_drift_recognizes_versions_env(tmp_path, monkeypatch) -> None:
    """Regression for PR #16 review H-4: on the public OSS mirror the
    plugin SHA lives in ``versions.env`` (not ``agent/Dockerfile.stock``).
    The doctor check must read it from there when the Dockerfile is
    absent, instead of producing a spurious ``could not extract
    MYAH_PLUGIN_SHA`` WARN on every healthy public-mirror install.
    """
    public_repo = tmp_path / 'public'
    public_repo.mkdir()
    plugin_sha = 'a' * 40
    (public_repo / 'versions.env').write_text(f'MYAH_PLUGIN_SHA={plugin_sha}\n', encoding='utf-8')
    monkeypatch.chdir(public_repo)

    result = check_plugin_sha_drift()

    assert result.status == CheckStatus.OK, (
        f'public mirror must be recognized via versions.env; got {result.status}: {result.message}'
    )
    assert plugin_sha[:8] in result.message


def test_probe_required_ports_services_started_reports_in_use_as_ok(mocker) -> None:
    """Regression for PR #16 review M-2: after ``myah install
    --service systemd`` starts the gateway + dashboard, ports 8642 /
    8643 / 9119 are in use BY THOSE SERVICES — the post-install table
    must report OK, not WARN. The ``services_started=True`` kwarg
    selects the post-start semantics.
    """
    from myah.lib.cli.doctor_checks import probe_required_ports

    # Mock socket.bind to always fail (i.e. every port is in use).
    mock_socket = mocker.patch('myah.lib.cli.doctor_checks.socket.socket')
    mock_socket.return_value.__enter__.return_value.bind.side_effect = OSError('Address in use')

    results = probe_required_ports(services_started=True)

    assert len(results) == 4
    for r in results:
        assert r.status == CheckStatus.OK, (
            f'services_started=True with bound ports must report OK; '
            f'got {r.status} for {r.name}: {r.message}'
        )


def test_probe_required_ports_default_treats_in_use_as_warn(mocker) -> None:
    """Default (pre-flight) semantics: in-use → WARN (something else is
    bound; the OSS stack will fail to claim the port). Preserved from
    the original behavior for the bash-parity check path."""
    from myah.lib.cli.doctor_checks import probe_required_ports

    mock_socket = mocker.patch('myah.lib.cli.doctor_checks.socket.socket')
    mock_socket.return_value.__enter__.return_value.bind.side_effect = OSError('Address in use')

    results = probe_required_ports()  # default services_started=False

    assert all(r.status == CheckStatus.WARN for r in results)


def test_check_plugin_sha_drift_outside_any_clone_warns_softly(tmp_path, monkeypatch) -> None:
    """Outside a Myah clone (neither sentinel present) the check is a
    no-op WARN — never raises, since ``myah doctor`` may run from
    anywhere."""
    nowhere = tmp_path / 'nowhere'
    nowhere.mkdir()
    monkeypatch.chdir(nowhere)

    result = check_plugin_sha_drift()

    # WARN is fine; the key invariant is "doesn't blow up the doctor".
    assert result.status in {CheckStatus.WARN, CheckStatus.OK}


def test_check_agent_container_env_injection_warn_when_missing(mocker) -> None:
    """Per AGENTS.md attachment-pipeline invariant #2, MYAH_PLATFORM_BASE_URL
    and MYAH_PLATFORM_BEARER must be injected into per-user agent containers
    (hosted mode). Without them, agent containers can't fetch attachment content
    from /api/v1/files/{id}/content — attachments silently dropped.

    Independent reviewer M3 finding: this check is currently missing from doctor.
    """
    from myah.lib.cli.doctor_checks import check_agent_container_env_injection
    from myah.lib.cli.shell import ShellResult

    # Mock docker exec to return env that's MISSING the required vars
    mock_run = mocker.patch('myah.lib.cli.doctor_checks.run')
    mock_run.return_value = ShellResult(
        returncode=0,
        stdout='PATH=/usr/local/bin:/usr/bin\nHOME=/root\nMYAH_USER_ID=abc\n',
        stderr='',
    )

    result = check_agent_container_env_injection()

    assert result.status == CheckStatus.WARN
    assert 'MYAH_PLATFORM_BASE_URL' in result.message or 'MYAH_PLATFORM_BEARER' in result.message
    assert 'attachment' in result.message.lower()


def test_check_agent_container_env_injection_ok_when_both_present(mocker) -> None:
    """When both env vars are present in the agent container, check is OK."""
    from myah.lib.cli.doctor_checks import check_agent_container_env_injection
    from myah.lib.cli.shell import ShellResult

    mock_run = mocker.patch('myah.lib.cli.doctor_checks.run')
    mock_run.return_value = ShellResult(
        returncode=0,
        stdout='MYAH_PLATFORM_BASE_URL=http://host.docker.internal:8082\nMYAH_PLATFORM_BEARER=abc123\n',
        stderr='',
    )

    result = check_agent_container_env_injection()

    assert result.status == CheckStatus.OK


def test_check_platform_container_matches_auto_generated_name(mocker) -> None:
    """Post-A.2 regression: docker-compose no longer hard-codes
    container_name, so the actual container name is e.g.
    `myah_platform_1` or `myah-platform-1` (slug varies by compose
    version). The check_platform_container_running filter must still
    detect it.
    """
    from myah.lib.cli.shell import ShellResult

    mock_run = mocker.patch('myah.lib.cli.doctor_checks.run')
    mock_run.return_value = ShellResult(
        returncode=0,
        # Compose v2 auto-name on the `myah` project dir:
        stdout='abc123\tmyah-platform-oss\tUp 5 minutes\t127.0.0.1:8080->8080/tcp\tmyah_platform_1\n',
        stderr='',
    )
    result = check_platform_container_running()
    assert result.status == CheckStatus.OK


def test_check_plugin_sha_drift_default_paths_resolve_from_repo_root() -> None:
    """Integration test: default paths must resolve correctly when myah doctor is invoked from the repo root.

    Production call site uses defaults: `check_plugin_sha_drift()` with no args
    → reads `'agent/Dockerfile.stock'` and `'.github/workflows/deploy.yml'`.
    These are CWD-relative. If a user runs `myah doctor` from inside a worktree
    or from anywhere other than the repo root, the defaults won't resolve.

    This test verifies the defaults work from the standard invocation point
    (the repo root) — it would fail in CI if the file paths drift.
    """
    import os
    from pathlib import Path

    # Find the repo root by walking up from this test file. The hosted
    # monorepo stores the pin in agent/Dockerfile.stock; the public repo is
    # a flattened platform-oss subtree and stores the same pin in versions.env.
    repo_root = Path(__file__).resolve()
    while repo_root.parent != repo_root and not (
        (repo_root / 'agent' / 'Dockerfile.stock').exists()
        or (repo_root / 'versions.env').exists()
    ):
        repo_root = repo_root.parent
    assert (
        (repo_root / 'agent' / 'Dockerfile.stock').exists()
        or (repo_root / 'versions.env').exists()
    ), 'repo root with plugin SHA pin source not found'

    # cwd into repo root, then call with defaults
    original_cwd = os.getcwd()
    try:
        os.chdir(repo_root)
        result = check_plugin_sha_drift()
        # The status will be OK or WARN depending on production state, but
        # critically it must NOT be "could not extract" (which would mean the
        # default paths didn't resolve).
        assert 'could not extract' not in result.message.lower(), \
            f'Default paths did not resolve from repo root: {result.message}'
    finally:
        os.chdir(original_cwd)
