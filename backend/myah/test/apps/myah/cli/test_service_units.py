"""Tests for `myah.lib.cli.service_units` — Slice 4 sub-phase 4d.

Replaces phase 7 of ``platform-oss/scripts/setup-myah-oss.sh`` (lines
569-856): service-unit install (systemd-user on Linux, launchd plists
on macOS), legacy plist/unit migration, and stale-process cleanup.

Closes R10 (template path-resolution drift in the bash) by loading
templates via ``importlib.resources.files('myah.cli') / 'templates'``
instead of walking ``$ROOT/scripts/oss-service-templates/``.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from myah.lib.cli import service_units
from myah.lib.cli.shell import ShellError, ShellResult

# `loguru_caplog` fixture lives in conftest.py — auto-discovered by pytest.


# ── _get_template_text ────────────────────────────────────────────────


class TestGetTemplateText:
    @pytest.mark.parametrize(
        'name',
        [
            'hermes-gateway.service.in',
            'hermes-dashboard.service.in',
            'dev.myah.hermes-gateway.plist.in',
            'dev.myah.hermes-dashboard.plist.in',
        ],
    )
    def test_each_bundled_template_loads_with_both_markers(self, name: str) -> None:
        text = service_units._get_template_text(name)
        assert '__HERMES_BIN__' in text
        assert '__HERMES_HOME__' in text
        if name in ('hermes-dashboard.service.in', 'dev.myah.hermes-dashboard.plist.in'):
            assert '__HERMES_WEB_SESSION_TOKEN__' in text

    def test_unknown_template_raises_file_not_found(self) -> None:
        with pytest.raises(FileNotFoundError):
            service_units._get_template_text('does-not-exist.in')


# ── render_template ───────────────────────────────────────────────────


class TestRenderTemplate:
    def test_systemd_unit_substitutes_both_markers(self, tmp_path: Path) -> None:
        rendered = service_units.render_template(
            'hermes-gateway.service.in',
            hermes_bin='/usr/local/bin/hermes',
            hermes_home=tmp_path / '.hermes',
        )
        assert '__HERMES_BIN__' not in rendered
        assert '__HERMES_HOME__' not in rendered
        assert '/usr/local/bin/hermes' in rendered
        assert str(tmp_path / '.hermes') in rendered

    def test_launchd_plist_substitutes_all_marker_positions(self, tmp_path: Path) -> None:
        """The plist has __HERMES_HOME__ in multiple positions including
        StandardOutPath + StandardErrorPath. Verify ALL are substituted,
        not just the first. Dashboard units also embed the web-session token
        because launchd does not source <hermes_home>/.env.
        """
        hermes_home = tmp_path / '.hermes'
        hermes_home.mkdir()
        (hermes_home / '.env').write_text('HERMES_WEB_SESSION_TOKEN=tok-123\n')
        rendered = service_units.render_template(
            'dev.myah.hermes-dashboard.plist.in',
            hermes_bin='/usr/local/bin/hermes',
            hermes_home=hermes_home,
        )
        assert '__HERMES_BIN__' not in rendered
        assert '__HERMES_HOME__' not in rendered
        assert '__HERMES_WEB_SESSION_TOKEN__' not in rendered
        assert 'tok-123' in rendered
        # plist references HOME at minimum 3 times: EnvironmentVariables,
        # StandardOutPath, StandardErrorPath. Count substituted occurrences.
        assert rendered.count(str(hermes_home)) >= 3

    def test_empty_hermes_bin_raises_value_error(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match='hermes_bin'):
            service_units.render_template(
                'hermes-gateway.service.in',
                hermes_bin='',
                hermes_home=tmp_path,
            )

    def test_none_hermes_bin_raises_value_error(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match='hermes_bin'):
            service_units.render_template(
                'hermes-gateway.service.in',
                hermes_bin=None,  # type: ignore[arg-type]
                hermes_home=tmp_path,
            )


# ── stop_stale_hermes_processes ───────────────────────────────────────


def _result(returncode: int = 0, stdout: str = '', stderr: str = '') -> ShellResult:
    return ShellResult(returncode=returncode, stdout=stdout, stderr=stderr)


class TestStopStaleHermesProcesses:
    def test_pgrep_missing_returns_zero_silently(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            'myah.lib.cli.service_units.shutil.which',
            lambda name: None if name == 'pgrep' else '/bin/' + name,
        )
        calls: list[list[str]] = []
        monkeypatch.setattr(
            'myah.lib.cli.service_units.run',
            lambda cmd, **kwargs: calls.append(list(cmd)) or _result(),
        )

        assert service_units.stop_stale_hermes_processes() == 0
        assert calls == []

    def test_all_three_pgrep_patterns_called_with_dash_f(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr('myah.lib.cli.service_units.shutil.which', lambda name: '/usr/bin/pgrep')
        calls: list[list[str]] = []

        def fake_run(cmd, **kwargs):
            calls.append(list(cmd))
            return _result(returncode=1)  # no matches

        monkeypatch.setattr('myah.lib.cli.service_units.run', fake_run)

        service_units.stop_stale_hermes_processes()

        pgrep_calls = [c for c in calls if c[0] == 'pgrep']
        assert len(pgrep_calls) == 3
        assert all(c[1] == '-f' for c in pgrep_calls)
        patterns = [c[2] for c in pgrep_calls]
        assert patterns == ['hermes dashboard', 'hermes gateway', r'hermes_cli\.main']

    def test_no_matches_returns_zero_and_makes_no_kill_calls(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr('myah.lib.cli.service_units.shutil.which', lambda name: '/usr/bin/pgrep')
        calls: list[list[str]] = []

        def fake_run(cmd, **kwargs):
            calls.append(list(cmd))
            return _result(returncode=1)

        monkeypatch.setattr('myah.lib.cli.service_units.run', fake_run)

        assert service_units.stop_stale_hermes_processes() == 0
        assert all(c[0] != 'kill' for c in calls)

    def test_two_pids_get_sigterm_no_sigkill_when_kills_succeed(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr('myah.lib.cli.service_units.shutil.which', lambda name: '/usr/bin/pgrep')
        monkeypatch.setattr('myah.lib.cli.service_units.os.getpid', lambda: 9999)
        # First pgrep call returns 2 pids on the first pattern; rest empty.
        pgrep_responses = iter([
            _result(stdout='1111\n2222\n'),
            _result(returncode=1),
            _result(returncode=1),
            # Second-pass after sleep: all empty (kill succeeded).
            _result(returncode=1),
            _result(returncode=1),
            _result(returncode=1),
        ])
        calls: list[list[str]] = []
        slept: list[float] = []

        def fake_run(cmd, **kwargs):
            calls.append(list(cmd))
            if cmd[0] == 'pgrep':
                return next(pgrep_responses)
            return _result()

        monkeypatch.setattr('myah.lib.cli.service_units.run', fake_run)
        monkeypatch.setattr('myah.lib.cli.service_units.time.sleep', lambda s: slept.append(s))

        killed = service_units.stop_stale_hermes_processes()

        assert killed == 2
        term_calls = [c for c in calls if c[:2] == ['kill', '-TERM']]
        assert sorted(c[2] for c in term_calls) == ['1111', '2222']
        assert slept == [1]
        kill9_calls = [c for c in calls if c[:2] == ['kill', '-9']]
        assert kill9_calls == []

    def test_own_pid_is_skipped(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr('myah.lib.cli.service_units.shutil.which', lambda name: '/usr/bin/pgrep')
        monkeypatch.setattr('myah.lib.cli.service_units.os.getpid', lambda: 1111)
        pgrep_responses = iter([
            _result(stdout='1111\n2222\n'),  # 1111 is our own pid
            _result(returncode=1),
            _result(returncode=1),
            _result(returncode=1),
            _result(returncode=1),
            _result(returncode=1),
        ])
        calls: list[list[str]] = []

        def fake_run(cmd, **kwargs):
            calls.append(list(cmd))
            if cmd[0] == 'pgrep':
                return next(pgrep_responses)
            return _result()

        monkeypatch.setattr('myah.lib.cli.service_units.run', fake_run)
        monkeypatch.setattr('myah.lib.cli.service_units.time.sleep', lambda s: None)

        killed = service_units.stop_stale_hermes_processes()

        assert killed == 1
        term_pids = [c[2] for c in calls if c[:2] == ['kill', '-TERM']]
        assert term_pids == ['2222']  # 1111 (own pid) skipped

    def test_second_pgrep_pass_sends_sigkill_to_survivors(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr('myah.lib.cli.service_units.shutil.which', lambda name: '/usr/bin/pgrep')
        monkeypatch.setattr('myah.lib.cli.service_units.os.getpid', lambda: 9999)
        # First pass: PID 1111 matched on pattern 0. Second pass: still
        # alive on pattern 1.
        pgrep_responses = iter([
            _result(stdout='1111\n'),
            _result(returncode=1),
            _result(returncode=1),
            _result(returncode=1),
            _result(stdout='1111\n'),  # still alive
            _result(returncode=1),
        ])
        calls: list[list[str]] = []
        slept: list[float] = []

        def fake_run(cmd, **kwargs):
            calls.append(list(cmd))
            if cmd[0] == 'pgrep':
                return next(pgrep_responses)
            return _result()

        monkeypatch.setattr('myah.lib.cli.service_units.run', fake_run)
        monkeypatch.setattr('myah.lib.cli.service_units.time.sleep', lambda s: slept.append(s))

        killed = service_units.stop_stale_hermes_processes()

        assert killed == 1
        assert slept == [1]
        kill9_calls = [c for c in calls if c[:2] == ['kill', '-9']]
        assert any(c[2] == '1111' for c in kill9_calls)


# ── migrate_legacy_launchagents ───────────────────────────────────────


@pytest.fixture
def fake_launch_agents_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Redirect _launch_agents_dir() to a tmp_path-relative directory."""
    agents = tmp_path / 'LaunchAgents'
    monkeypatch.setattr('myah.lib.cli.service_units._launch_agents_dir', lambda: agents)
    return agents


class TestMigrateLegacyLaunchAgents:
    def test_dir_missing_returns_zero(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        missing = tmp_path / 'no-such-dir'
        monkeypatch.setattr('myah.lib.cli.service_units._launch_agents_dir', lambda: missing)
        calls: list[list[str]] = []
        monkeypatch.setattr(
            'myah.lib.cli.service_units.run',
            lambda cmd, **kw: calls.append(list(cmd)) or _result(),
        )

        assert service_units.migrate_legacy_launchagents() == 0
        assert calls == []

    def test_empty_dir_returns_zero(
        self,
        monkeypatch: pytest.MonkeyPatch,
        fake_launch_agents_dir: Path,
    ) -> None:
        fake_launch_agents_dir.mkdir()
        calls: list[list[str]] = []
        monkeypatch.setattr(
            'myah.lib.cli.service_units.run',
            lambda cmd, **kw: calls.append(list(cmd)) or _result(),
        )

        assert service_units.migrate_legacy_launchagents() == 0
        assert calls == []

    def test_one_legacy_plist_bootout_and_renamed(
        self,
        monkeypatch: pytest.MonkeyPatch,
        fake_launch_agents_dir: Path,
    ) -> None:
        fake_launch_agents_dir.mkdir()
        plist = fake_launch_agents_dir / 'com.nous-research.hermes.gateway.plist'
        plist.write_text('<plist/>')
        monkeypatch.setattr('myah.lib.cli.service_units.os.getuid', lambda: 501)
        calls: list[list[str]] = []
        monkeypatch.setattr(
            'myah.lib.cli.service_units.run',
            lambda cmd, **kw: calls.append(list(cmd)) or _result(),
        )

        result = service_units.migrate_legacy_launchagents()

        assert result == 1
        assert any(
            c[:3] == ['launchctl', 'bootout', 'gui/501/com.nous-research.hermes.gateway']
            for c in calls
        )
        # Original plist gone, backup present.
        assert not plist.exists()
        backups = list(fake_launch_agents_dir.glob('com.nous-research.hermes.gateway.plist.bak.*'))
        assert len(backups) == 1

    def test_does_not_touch_current_dev_myah_plists(
        self,
        monkeypatch: pytest.MonkeyPatch,
        fake_launch_agents_dir: Path,
    ) -> None:
        fake_launch_agents_dir.mkdir()
        legacy = fake_launch_agents_dir / 'com.myah.old.plist'
        current = fake_launch_agents_dir / 'dev.myah.hermes-gateway.plist'
        legacy.write_text('<plist/>')
        current.write_text('<plist/>')
        monkeypatch.setattr('myah.lib.cli.service_units.os.getuid', lambda: 501)
        monkeypatch.setattr('myah.lib.cli.service_units.run', lambda cmd, **kw: _result())

        result = service_units.migrate_legacy_launchagents()

        assert result == 1
        assert current.exists()  # current plist untouched
        assert current.read_text() == '<plist/>'
        assert not legacy.exists()  # legacy renamed

    def test_bootout_failure_falls_back_to_unload(
        self,
        monkeypatch: pytest.MonkeyPatch,
        fake_launch_agents_dir: Path,
    ) -> None:
        fake_launch_agents_dir.mkdir()
        plist = fake_launch_agents_dir / 'com.myah.legacy.plist'
        plist.write_text('<plist/>')
        monkeypatch.setattr('myah.lib.cli.service_units.os.getuid', lambda: 501)
        calls: list[list[str]] = []

        def fake_run(cmd, **kwargs):
            calls.append(list(cmd))
            if cmd[:2] == ['launchctl', 'bootout']:
                return _result(returncode=37, stderr='no such service')
            return _result()

        monkeypatch.setattr('myah.lib.cli.service_units.run', fake_run)

        result = service_units.migrate_legacy_launchagents()

        assert result == 1
        # bootout was tried...
        assert any(c[:2] == ['launchctl', 'bootout'] for c in calls)
        # ...and then unload was tried as fallback.
        assert any(c[:3] == ['launchctl', 'unload', str(plist)] for c in calls)
        # Rename still happened.
        assert not plist.exists()
        assert list(fake_launch_agents_dir.glob('com.myah.legacy.plist.bak.*'))


# ── migrate_legacy_systemd_units ──────────────────────────────────────


class TestMigrateLegacySystemdUnits:
    def test_systemctl_missing_returns_zero(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr('myah.lib.cli.service_units.shutil.which', lambda name: None)
        calls: list[list[str]] = []
        monkeypatch.setattr(
            'myah.lib.cli.service_units.run',
            lambda cmd, **kw: calls.append(list(cmd)) or _result(),
        )

        assert service_units.migrate_legacy_systemd_units() == 0
        assert calls == []

    def test_no_legacy_units_returns_zero(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            'myah.lib.cli.service_units.shutil.which',
            lambda name: '/usr/bin/systemctl' if name == 'systemctl' else None,
        )
        calls: list[list[str]] = []
        monkeypatch.setattr(
            'myah.lib.cli.service_units.run',
            lambda cmd, **kw: calls.append(list(cmd)) or _result(stdout=''),
        )

        assert service_units.migrate_legacy_systemd_units() == 0
        # Only the list-unit-files probe should have happened — no stop/disable/mask.
        assert all('list-unit-files' in c for c in calls)

    def test_legacy_unit_present_runs_stop_disable_mask_in_order(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            'myah.lib.cli.service_units.shutil.which',
            lambda name: '/usr/bin/systemctl' if name == 'systemctl' else None,
        )
        calls: list[list[str]] = []

        def fake_run(cmd, **kwargs):
            calls.append(list(cmd))
            if 'list-unit-files' in cmd:
                return _result(stdout='myah-platform.service enabled\n')
            return _result()

        monkeypatch.setattr('myah.lib.cli.service_units.run', fake_run)

        result = service_units.migrate_legacy_systemd_units()

        assert result == 1
        mgmt = [c for c in calls if c[2] in {'stop', 'disable', 'mask'}]
        assert [c[2] for c in mgmt] == ['stop', 'disable', 'mask']
        for c in mgmt:
            assert c[3] == 'myah-platform.service'


# ── install_systemd_user_units ────────────────────────────────────────


@pytest.fixture
def fake_systemd_user_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Redirect _systemd_user_dir() to a tmp_path-relative directory."""
    target = tmp_path / 'systemd-user'
    monkeypatch.setattr('myah.lib.cli.service_units._systemd_user_dir', lambda: target)
    return target


def _make_call_recorder(monkeypatch: pytest.MonkeyPatch, order: list[str]) -> list[list[str]]:
    """Install fake run() + record the call ordering against named ops."""
    calls: list[list[str]] = []

    def fake_run(cmd, **kwargs):
        calls.append(list(cmd))
        if cmd[0] == 'pgrep':
            return _result(returncode=1)
        if 'list-unit-files' in cmd:
            return _result(stdout='')
        return _result()

    monkeypatch.setattr('myah.lib.cli.service_units.run', fake_run)
    return calls


class TestInstallSystemdUserUnits:
    def test_empty_hermes_bin_raises_value_error(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match='hermes_bin'):
            service_units.install_systemd_user_units('', tmp_path)

    def test_happy_path_writes_units_and_calls_enable_now(
        self,
        monkeypatch: pytest.MonkeyPatch,
        fake_systemd_user_dir: Path,
        tmp_path: Path,
    ) -> None:
        monkeypatch.setattr(
            'myah.lib.cli.service_units.shutil.which',
            lambda name: '/usr/bin/' + name,
        )
        hermes_home = tmp_path / '.hermes'
        calls = _make_call_recorder(monkeypatch, [])

        service_units.install_systemd_user_units('/usr/local/bin/hermes', hermes_home)

        # Two unit files written with substitutions.
        for unit in ('hermes-gateway', 'hermes-dashboard'):
            dest = fake_systemd_user_dir / f'{unit}.service'
            assert dest.is_file()
            text = dest.read_text()
            assert '__HERMES_BIN__' not in text
            assert '__HERMES_HOME__' not in text
            assert '/usr/local/bin/hermes' in text
            assert str(hermes_home) in text

        enable_calls = [
            c for c in calls if c[:4] == ['systemctl', '--user', 'enable', '--now']
        ]
        assert len(enable_calls) == 2
        services = sorted(c[4] for c in enable_calls)
        assert services == ['hermes-dashboard.service', 'hermes-gateway.service']

    def test_call_order_migrate_then_stop_then_install(
        self,
        monkeypatch: pytest.MonkeyPatch,
        fake_systemd_user_dir: Path,
        tmp_path: Path,
    ) -> None:
        """Verify migrate_legacy_systemd_units happens before
        stop_stale_hermes_processes, which happens before any enable."""
        monkeypatch.setattr(
            'myah.lib.cli.service_units.shutil.which',
            lambda name: '/usr/bin/' + name,
        )

        events: list[str] = []

        def fake_migrate_systemd() -> int:
            events.append('migrate-systemd')
            return 0

        def fake_stop_stale() -> int:
            events.append('stop-stale')
            return 0

        monkeypatch.setattr(
            'myah.lib.cli.service_units.migrate_legacy_systemd_units', fake_migrate_systemd
        )
        monkeypatch.setattr(
            'myah.lib.cli.service_units.stop_stale_hermes_processes', fake_stop_stale
        )

        def fake_run(cmd, **kwargs):
            if cmd[:4] == ['systemctl', '--user', 'enable', '--now']:
                events.append(f'enable:{cmd[4]}')
            return _result()

        monkeypatch.setattr('myah.lib.cli.service_units.run', fake_run)

        service_units.install_systemd_user_units('/usr/local/bin/hermes', tmp_path / '.hermes')

        assert events[0] == 'migrate-systemd'
        assert events[1] == 'stop-stale'
        # Then the two enable calls (order: gateway, dashboard).
        assert events[2:] == ['enable:hermes-gateway.service', 'enable:hermes-dashboard.service']

    def test_systemctl_failure_propagates_shell_error(
        self,
        monkeypatch: pytest.MonkeyPatch,
        fake_systemd_user_dir: Path,
        tmp_path: Path,
    ) -> None:
        monkeypatch.setattr(
            'myah.lib.cli.service_units.shutil.which',
            lambda name: '/usr/bin/' + name,
        )
        monkeypatch.setattr(
            'myah.lib.cli.service_units.migrate_legacy_systemd_units', lambda: 0
        )
        monkeypatch.setattr(
            'myah.lib.cli.service_units.stop_stale_hermes_processes', lambda: 0
        )

        def fake_run(cmd, **kwargs):
            if cmd[:4] == ['systemctl', '--user', 'enable', '--now']:
                if kwargs.get('check'):
                    raise ShellError(cmd, _result(returncode=1, stderr='boom'))
                return _result(returncode=1, stderr='boom')
            return _result()

        monkeypatch.setattr('myah.lib.cli.service_units.run', fake_run)

        with pytest.raises(ShellError):
            service_units.install_systemd_user_units('/usr/local/bin/hermes', tmp_path / '.hermes')

    def test_running_twice_is_idempotent(
        self,
        monkeypatch: pytest.MonkeyPatch,
        fake_systemd_user_dir: Path,
        tmp_path: Path,
    ) -> None:
        """Re-running install_systemd_user_units overwrites the unit files
        and re-enables (systemd treats re-enable as no-op + restart). No
        errors. Each migrate / stop / enable call doubles in count."""
        monkeypatch.setattr(
            'myah.lib.cli.service_units.shutil.which',
            lambda name: '/usr/bin/' + name,
        )

        migrate_calls: list[None] = []
        stop_calls: list[None] = []
        monkeypatch.setattr(
            'myah.lib.cli.service_units.migrate_legacy_systemd_units',
            lambda: migrate_calls.append(None) or 0,
        )
        monkeypatch.setattr(
            'myah.lib.cli.service_units.stop_stale_hermes_processes',
            lambda: stop_calls.append(None) or 0,
        )

        enable_calls: list[list[str]] = []

        def fake_run(cmd, **kwargs):
            if cmd[:4] == ['systemctl', '--user', 'enable', '--now']:
                enable_calls.append(list(cmd))
            return _result()

        monkeypatch.setattr('myah.lib.cli.service_units.run', fake_run)

        hermes_home_first = tmp_path / 'first-home'
        hermes_home_second = tmp_path / 'second-home'

        service_units.install_systemd_user_units('/usr/local/bin/hermes', hermes_home_first)
        service_units.install_systemd_user_units('/usr/local/bin/hermes', hermes_home_second)

        # Each helper called twice; enable called 2 units × 2 invocations.
        assert len(migrate_calls) == 2
        assert len(stop_calls) == 2
        assert len(enable_calls) == 4

        # Files reflect the *second* render (overwritten in place).
        for unit in ('hermes-gateway', 'hermes-dashboard'):
            text = (fake_systemd_user_dir / f'{unit}.service').read_text()
            assert str(hermes_home_second) in text
            assert str(hermes_home_first) not in text


# ── install_launchd_plists ────────────────────────────────────────────


class TestInstallLaunchdPlists:
    def test_empty_hermes_bin_raises_value_error(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match='hermes_bin'):
            service_units.install_launchd_plists('', tmp_path)

    def test_happy_path_writes_plists_and_bootstraps(
        self,
        monkeypatch: pytest.MonkeyPatch,
        fake_launch_agents_dir: Path,
        tmp_path: Path,
    ) -> None:
        monkeypatch.setattr(
            'myah.lib.cli.service_units.migrate_legacy_launchagents', lambda: 0
        )
        monkeypatch.setattr(
            'myah.lib.cli.service_units.stop_stale_hermes_processes', lambda: 0
        )
        monkeypatch.setattr('myah.lib.cli.service_units.os.getuid', lambda: 501)
        hermes_home = tmp_path / '.hermes'
        calls: list[list[str]] = []

        monkeypatch.setattr(
            'myah.lib.cli.service_units.run',
            lambda cmd, **kw: calls.append(list(cmd)) or _result(),
        )

        service_units.install_launchd_plists('/usr/local/bin/hermes', hermes_home)

        # logs dir + plist dir created.
        assert (hermes_home / 'logs').is_dir()
        assert fake_launch_agents_dir.is_dir()

        for service in ('dev.myah.hermes-gateway', 'dev.myah.hermes-dashboard'):
            plist_path = fake_launch_agents_dir / f'{service}.plist'
            assert plist_path.is_file()
            text = plist_path.read_text()
            assert '__HERMES_BIN__' not in text
            assert '__HERMES_HOME__' not in text
            assert '/usr/local/bin/hermes' in text
            if service == 'dev.myah.hermes-dashboard':
                assert 'HERMES_WEB_SESSION_TOKEN' in text

            # bootout-then-bootstrap call pair per service.
            assert any(
                c[:3] == ['launchctl', 'bootout', f'gui/501/{service}'] for c in calls
            )
            assert any(
                c[:3] == ['launchctl', 'bootstrap', 'gui/501'] and c[3] == str(plist_path)
                for c in calls
            )

    def test_bootstrap_failure_falls_back_to_load(
        self,
        monkeypatch: pytest.MonkeyPatch,
        fake_launch_agents_dir: Path,
        tmp_path: Path,
    ) -> None:
        monkeypatch.setattr(
            'myah.lib.cli.service_units.migrate_legacy_launchagents', lambda: 0
        )
        monkeypatch.setattr(
            'myah.lib.cli.service_units.stop_stale_hermes_processes', lambda: 0
        )
        monkeypatch.setattr('myah.lib.cli.service_units.os.getuid', lambda: 501)
        calls: list[list[str]] = []

        def fake_run(cmd, **kwargs):
            calls.append(list(cmd))
            if cmd[:2] == ['launchctl', 'bootstrap']:
                return _result(returncode=1, stderr='unknown verb')
            # 'load' fallback succeeds.
            return _result()

        monkeypatch.setattr('myah.lib.cli.service_units.run', fake_run)

        service_units.install_launchd_plists('/usr/local/bin/hermes', tmp_path / '.hermes')

        load_calls = [c for c in calls if c[:2] == ['launchctl', 'load']]
        # Two services, both fell back to load.
        assert len(load_calls) == 2

    def test_load_fallback_failure_raises_shell_error(
        self,
        monkeypatch: pytest.MonkeyPatch,
        fake_launch_agents_dir: Path,
        tmp_path: Path,
    ) -> None:
        monkeypatch.setattr(
            'myah.lib.cli.service_units.migrate_legacy_launchagents', lambda: 0
        )
        monkeypatch.setattr(
            'myah.lib.cli.service_units.stop_stale_hermes_processes', lambda: 0
        )
        monkeypatch.setattr('myah.lib.cli.service_units.os.getuid', lambda: 501)

        def fake_run(cmd, **kwargs):
            if cmd[:2] == ['launchctl', 'bootstrap']:
                return _result(returncode=1, stderr='unknown verb')
            if cmd[:2] == ['launchctl', 'load']:
                if kwargs.get('check'):
                    raise ShellError(cmd, _result(returncode=1, stderr='load failed'))
                return _result(returncode=1)
            return _result()

        monkeypatch.setattr('myah.lib.cli.service_units.run', fake_run)

        with pytest.raises(ShellError):
            service_units.install_launchd_plists('/usr/local/bin/hermes', tmp_path / '.hermes')

    def test_bootout_failure_is_silent(
        self,
        monkeypatch: pytest.MonkeyPatch,
        fake_launch_agents_dir: Path,
        tmp_path: Path,
    ) -> None:
        """bootout returncode != 0 should NOT abort install — the service
        may simply not have been loaded before."""
        monkeypatch.setattr(
            'myah.lib.cli.service_units.migrate_legacy_launchagents', lambda: 0
        )
        monkeypatch.setattr(
            'myah.lib.cli.service_units.stop_stale_hermes_processes', lambda: 0
        )
        monkeypatch.setattr('myah.lib.cli.service_units.os.getuid', lambda: 501)

        def fake_run(cmd, **kwargs):
            if cmd[:2] == ['launchctl', 'bootout']:
                return _result(returncode=36, stderr='not loaded')
            return _result()

        monkeypatch.setattr('myah.lib.cli.service_units.run', fake_run)

        # Should not raise.
        service_units.install_launchd_plists('/usr/local/bin/hermes', tmp_path / '.hermes')

    def test_running_twice_is_idempotent(
        self,
        monkeypatch: pytest.MonkeyPatch,
        fake_launch_agents_dir: Path,
        tmp_path: Path,
    ) -> None:
        """Re-running install_launchd_plists: bootout cleans up the prior
        bootstrap, then bootstrap re-loads the (re-rendered) plist. No
        errors. Call counts double."""
        migrate_calls: list[None] = []
        stop_calls: list[None] = []
        monkeypatch.setattr(
            'myah.lib.cli.service_units.migrate_legacy_launchagents',
            lambda: migrate_calls.append(None) or 0,
        )
        monkeypatch.setattr(
            'myah.lib.cli.service_units.stop_stale_hermes_processes',
            lambda: stop_calls.append(None) or 0,
        )
        monkeypatch.setattr('myah.lib.cli.service_units.os.getuid', lambda: 501)

        calls: list[list[str]] = []
        monkeypatch.setattr(
            'myah.lib.cli.service_units.run',
            lambda cmd, **kw: calls.append(list(cmd)) or _result(),
        )

        hermes_home_first = tmp_path / 'first-home'
        hermes_home_second = tmp_path / 'second-home'

        service_units.install_launchd_plists('/usr/local/bin/hermes', hermes_home_first)
        service_units.install_launchd_plists('/usr/local/bin/hermes', hermes_home_second)

        # Each helper called twice.
        assert len(migrate_calls) == 2
        assert len(stop_calls) == 2

        # Two services × two invocations × (bootout + bootstrap) = 8 launchctl calls.
        bootout_calls = [c for c in calls if c[:2] == ['launchctl', 'bootout']]
        bootstrap_calls = [c for c in calls if c[:2] == ['launchctl', 'bootstrap']]
        assert len(bootout_calls) == 4
        assert len(bootstrap_calls) == 4

        # Files reflect the *second* render (overwritten in place).
        for service in ('dev.myah.hermes-gateway', 'dev.myah.hermes-dashboard'):
            text = (fake_launch_agents_dir / f'{service}.plist').read_text()
            assert str(hermes_home_second) in text
            assert str(hermes_home_first) not in text


# ── structural sentinel: heavy libs must stay out of module top ───────


def test_module_does_not_import_heavy_libs_at_top_level() -> None:
    """Mirrors the 4a/4c pattern — Rich, PyYAML, Typer, etc. must stay
    out of the module top so `myah --help` cold-start budget holds."""
    from myah.lib.cli import service_units as mod

    source = Path(mod.__file__).read_text(encoding='utf-8')
    head = source.split('\ndef ', 1)[0]

    for offender in ('import rich', 'from rich', 'import yaml', 'from yaml',
                     'import typer', 'from typer'):
        assert offender not in head, f'service_units top-level imports {offender!r}'
