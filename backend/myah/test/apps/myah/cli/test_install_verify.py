"""Tests for post-install verification (port probe + doctor aggregator).

Sub-phase 4e of Slice 4. Covers `probe_required_ports` and
`post_install_doctor_run` in `myah.lib.cli.doctor_checks`.

Port probing uses a `socket.socket` monkeypatch (deterministic, no flaky
real-port-binding fixtures). The aggregator tests patch each underlying
check predicate at the consumer-module namespace so the orchestrator's
behavior is exercised in isolation.
"""

from __future__ import annotations

import pytest

from myah.lib.cli.doctor_checks import (
    CheckResult,
    CheckStatus,
    post_install_doctor_run,
    probe_required_ports,
)


# A minimal fake socket whose `bind` raises only for ports in the
# `in_use` set; otherwise succeeds silently. Implements the context-
# manager protocol so the production `with socket.socket(...) as sock`
# block works unmodified.
class _FakeSocket:
    def __init__(self, in_use: set[int]) -> None:
        self._in_use = in_use

    def __call__(self, family: int, type_: int) -> _FakeSocket:
        # Returns self (not a fresh instance) — production opens one socket per
        # port in sequence and `in_use` is a read-only set, so sharing is safe.
        # If a future test needs per-call behavior, build a fresh fake rather
        # than mutating `_in_use`.
        return self

    def __enter__(self) -> _FakeSocket:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def bind(self, addr: tuple[str, int]) -> None:
        if addr[1] in self._in_use:
            raise OSError('Address in use (mocked)')


def _patch_sockets(monkeypatch: pytest.MonkeyPatch, in_use: set[int]) -> None:
    """Replace `socket.socket` in the consumer module with a deterministic fake."""
    fake = _FakeSocket(in_use)
    monkeypatch.setattr('myah.lib.cli.doctor_checks.socket.socket', fake)


# ---------- probe_required_ports ------------------------------------------


def test_probe_all_ports_free(monkeypatch: pytest.MonkeyPatch) -> None:
    """All 4 ports free → 4 OK results."""
    _patch_sockets(monkeypatch, in_use=set())

    results = probe_required_ports()

    assert len(results) == 4
    for r in results:
        assert r.status == CheckStatus.OK, f'{r.name} should be OK, got {r.status}: {r.message}'


def test_probe_one_port_in_use(monkeypatch: pytest.MonkeyPatch) -> None:
    """Port 8080 in-use → 3 OK + 1 WARN. WARN message mentions the service."""
    _patch_sockets(monkeypatch, in_use={8080})

    results = probe_required_ports()

    assert len(results) == 4
    # 8080 is documented as the last entry
    assert results[3].status == CheckStatus.WARN
    assert 'Myah platform' in results[3].message
    assert '8080' in results[3].message
    # Other 3 should be OK
    for r in results[:3]:
        assert r.status == CheckStatus.OK


def test_probe_all_ports_in_use(monkeypatch: pytest.MonkeyPatch) -> None:
    """All 4 ports in-use → 4 WARN results, each with the right service label."""
    _patch_sockets(monkeypatch, in_use={8642, 8643, 9119, 8080})

    results = probe_required_ports()

    assert len(results) == 4
    expected_services = (
        'Hermes api_server',
        'Hermes gateway adapter',
        'Hermes dashboard',
        'Myah platform',
    )
    for r, service in zip(results, expected_services, strict=True):
        assert r.status == CheckStatus.WARN
        assert service in r.message


def test_probe_preserves_documented_order(monkeypatch: pytest.MonkeyPatch) -> None:
    """results[0]..[3] correspond to ports 8642, 8643, 9119, 8080 in that order."""
    _patch_sockets(monkeypatch, in_use=set())

    results = probe_required_ports()

    assert results[0].name == 'port 8642'
    assert results[1].name == 'port 8643'
    assert results[2].name == 'port 9119'
    assert results[3].name == 'port 8080'


def test_probe_warn_message_hints_at_lsof(monkeypatch: pytest.MonkeyPatch) -> None:
    """WARN message gives the operator an lsof command to find the conflict."""
    _patch_sockets(monkeypatch, in_use={8642})

    results = probe_required_ports()

    assert results[0].status == CheckStatus.WARN
    assert 'lsof' in results[0].message
    assert '8642' in results[0].message


def test_probe_ok_message_mentions_ready_for(monkeypatch: pytest.MonkeyPatch) -> None:
    """Free-port OK message hints which service is expected to bind."""
    _patch_sockets(monkeypatch, in_use=set())

    results = probe_required_ports()

    assert 'Hermes api_server' in results[0].message
    assert 'free' in results[0].message.lower() or 'ready' in results[0].message.lower()


# ---------- post_install_doctor_run aggregator ----------------------------


def _ok(name: str) -> CheckResult:
    return CheckResult(name=name, status=CheckStatus.OK, message=f'{name} ok')


def _fail(name: str) -> CheckResult:
    return CheckResult(name=name, status=CheckStatus.FAIL, message=f'{name} failed')


def _patch_named_checks(monkeypatch: pytest.MonkeyPatch, fail_name: str | None = None) -> None:
    """Patch all 5 named doctor predicates + probe_required_ports.

    Each named check returns OK unless its name matches `fail_name`. The
    port probe is patched to return 4 sentinel results so the aggregator
    test can verify the orchestrator delegates rather than reimplementing.
    """
    named = (
        ('check_hermes_binary_on_path', 'hermes binary'),
        ('check_hermes_plugin_installed', 'myah-hermes-plugin'),
        ('check_plugin_sha_drift', 'plugin SHA pin'),
        ('check_platform_container_running', 'myah-platform container'),
        ('check_agent_container_env_injection', 'agent container env injection'),
    )
    for attr, label in named:
        result = _fail(label) if fail_name == attr else _ok(label)
        # `r=result` captures the value at lambda-definition time; without
        # the default arg, all lambdas would close over the final loop value.
        monkeypatch.setattr(f'myah.lib.cli.doctor_checks.{attr}', lambda r=result: r)

    sentinel_ports = [
        CheckResult(name=f'port-probe-{i}', status=CheckStatus.OK, message='sentinel')
        for i in range(4)
    ]
    monkeypatch.setattr(
        'myah.lib.cli.doctor_checks.probe_required_ports',
        lambda **_kwargs: sentinel_ports,
    )


def test_aggregator_happy_path_returns_nine_results(monkeypatch: pytest.MonkeyPatch) -> None:
    """5 named checks + 4 port probes = 9 CheckResults."""
    _patch_named_checks(monkeypatch)

    results = post_install_doctor_run()

    assert len(results) == 9


def test_aggregator_preserves_documented_order(monkeypatch: pytest.MonkeyPatch) -> None:
    """Order: hermes binary, plugin, SHA drift, platform container, agent env, then 4 port probes."""
    _patch_named_checks(monkeypatch)

    results = post_install_doctor_run()

    assert results[0].name == 'hermes binary'
    assert results[1].name == 'myah-hermes-plugin'
    assert results[2].name == 'plugin SHA pin'
    assert results[3].name == 'myah-platform container'
    assert results[4].name == 'agent container env injection'
    # Last 4 are the sentinel port-probe results
    for i in range(4):
        assert results[5 + i].name == f'port-probe-{i}'


def test_aggregator_does_not_bail_early_on_individual_fail(monkeypatch: pytest.MonkeyPatch) -> None:
    """A FAIL in the first check must not truncate the result list."""
    _patch_named_checks(monkeypatch, fail_name='check_hermes_binary_on_path')

    results = post_install_doctor_run()

    assert len(results) == 9
    assert results[0].status == CheckStatus.FAIL
    assert results[0].name == 'hermes binary'
    # The remaining 8 are still present
    for r in results[1:]:
        assert r.status == CheckStatus.OK


def test_aggregator_delegates_to_probe_required_ports(monkeypatch: pytest.MonkeyPatch) -> None:
    """The aggregator must invoke probe_required_ports (verified via sentinel)."""
    _patch_named_checks(monkeypatch)

    results = post_install_doctor_run()

    # The 4 port-probe sentinels are the proof of delegation; if the
    # aggregator reimplemented port binding it would emit `port 8642`-
    # shaped results instead.
    port_results = results[5:]
    assert all(r.name.startswith('port-probe-') for r in port_results)
    assert all(r.message == 'sentinel' for r in port_results)


def test_aggregator_returns_list_of_check_results(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every entry is a CheckResult — sanity check on the type contract."""
    _patch_named_checks(monkeypatch)

    results = post_install_doctor_run()

    assert isinstance(results, list)
    assert all(isinstance(r, CheckResult) for r in results)


def test_platform_container_running_accepts_compose_generated_names(monkeypatch: pytest.MonkeyPatch) -> None:
    """Public OSS compose names containers like `myah-oss-platform-1`.

    The doctor must not look only for the old hard-coded `myah-platform`
    name, otherwise a healthy compose stack reports a false WARN.
    """
    from myah.lib.cli import doctor_checks
    from myah.lib.cli.shell import ShellResult

    monkeypatch.setattr(
        doctor_checks,
        'run',
        lambda _cmd: ShellResult(
            returncode=0,
            stdout='abc123\tmyah/platform:latest\tUp 5 minutes\t127.0.0.1:8080->8080/tcp\tmyah-oss-platform-1\n',
            stderr='',
        ),
    )

    result = doctor_checks.check_platform_container_running()

    assert result.status == CheckStatus.OK


def test_agent_env_injection_is_ok_for_oss_mode_without_agent_container(monkeypatch: pytest.MonkeyPatch) -> None:
    """OSS mode uses host Hermes, not per-user `myah-agent-*` containers."""
    from myah.lib.cli import doctor_checks
    from myah.lib.cli.shell import ShellResult

    def fake_run(cmd: list[str]) -> ShellResult:
        if cmd[:3] == ['docker', 'exec', 'myah-agent-00000000-0000-0000-0000-000000000001']:
            return ShellResult(returncode=1, stdout='', stderr='No such container')
        if cmd[:5] == ['docker', 'ps', '--filter', 'label=com.docker.compose.service=platform', '-q']:
            return ShellResult(returncode=0, stdout='platform123\n', stderr='')
        if cmd[:2] == ['docker', 'inspect']:
            return ShellResult(returncode=0, stdout='MYAH_DEPLOYMENT_MODE=oss\n', stderr='')
        return ShellResult(returncode=1, stdout='', stderr='unexpected')

    monkeypatch.setattr(doctor_checks, 'run', fake_run)

    result = doctor_checks.check_agent_container_env_injection()

    assert result.status == CheckStatus.OK
    assert 'OSS mode' in result.message
