"""Tests for `myah.lib.cli.hermes_install` — Slice 4 sub-phase 4b primitives.

Covers the six functions that replace phase 5 of
`platform-oss/scripts/setup-myah-oss.sh`:

  - detect_hermes_venv         (bash 183-227)
  - read_pinned_plugin_sha_from_dockerfile (wraps Slice 2 _read_plugin_sha)
  - bootstrap_pip              (bash 454-465)
  - pip_install_plugin_at_sha  (bash 478-489)
  - materialize_dashboard_shim (bash 491-501)
  - verify_dashboard_plugin_mounted (bash 636-669)

Mock targets follow the consumer-namespace rule: patches go on
`myah.lib.cli.hermes_install.X`, never on source modules.
"""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest

from myah.lib.cli import hermes_install
from myah.lib.cli.shell import ShellError, ShellResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _ok(stdout: str = '', stderr: str = '') -> ShellResult:
    return ShellResult(returncode=0, stdout=stdout, stderr=stderr)


def _fail(returncode: int = 1, stdout: str = '', stderr: str = 'boom') -> ShellResult:
    return ShellResult(returncode=returncode, stdout=stdout, stderr=stderr)


def _make_executable_python(venv_root: Path) -> Path:
    """Create venv_root/bin/python as an executable stub. Return venv_root."""
    bin_dir = venv_root / 'bin'
    bin_dir.mkdir(parents=True, exist_ok=True)
    py = bin_dir / 'python'
    py.write_text('#!/bin/sh\necho fake python\n')
    py.chmod(0o755)
    return venv_root


# ---------------------------------------------------------------------------
# detect_hermes_venv
# ---------------------------------------------------------------------------


class TestDetectHermesVenv:
    def test_env_override_returns_override_when_python_executable(self, tmp_path: Path, monkeypatch) -> None:
        venv = _make_executable_python(tmp_path / 'override-venv')
        monkeypatch.setenv('MYAH_HERMES_VENV', str(venv))
        result = hermes_install.detect_hermes_venv()
        assert result == venv

    def test_env_override_raises_when_python_missing(self, tmp_path: Path, monkeypatch) -> None:
        bad = tmp_path / 'nope'
        bad.mkdir()
        monkeypatch.setenv('MYAH_HERMES_VENV', str(bad))
        with pytest.raises(RuntimeError, match=str(bad)):
            hermes_install.detect_hermes_venv()

    def test_first_candidate_with_executable_python_wins(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.delenv('MYAH_HERMES_VENV', raising=False)
        first = _make_executable_python(tmp_path / 'first')
        second = _make_executable_python(tmp_path / 'second')
        third = _make_executable_python(tmp_path / 'third')
        monkeypatch.setattr(hermes_install, '_HERMES_VENV_CANDIDATES', (first, second, third))
        assert hermes_install.detect_hermes_venv() == first

    def test_second_candidate_returned_when_first_missing_python(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.delenv('MYAH_HERMES_VENV', raising=False)
        first = tmp_path / 'first'  # no bin/python
        first.mkdir()
        second = _make_executable_python(tmp_path / 'second')
        third = _make_executable_python(tmp_path / 'third')
        monkeypatch.setattr(hermes_install, '_HERMES_VENV_CANDIDATES', (first, second, third))
        assert hermes_install.detect_hermes_venv() == second

    def test_no_candidates_no_path_hermes_raises_listing_candidates(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.delenv('MYAH_HERMES_VENV', raising=False)
        cands = (
            tmp_path / 'a',
            tmp_path / 'b',
            tmp_path / 'c',
        )
        monkeypatch.setattr(hermes_install, '_HERMES_VENV_CANDIDATES', cands)
        with patch.object(hermes_install.shutil, 'which', return_value=None):
            with pytest.raises(RuntimeError) as exc:
                hermes_install.detect_hermes_venv()
        # all candidate paths should appear in the error message
        for cand in cands:
            assert str(cand) in str(exc.value)

    def test_path_shebang_fallback_resolves_venv_root(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.delenv('MYAH_HERMES_VENV', raising=False)
        monkeypatch.setattr(hermes_install, '_HERMES_VENV_CANDIDATES', (tmp_path / 'noexist',))
        # Build a realistic hermes-on-PATH layout: <venv>/bin/python + <venv>/bin/hermes
        venv = _make_executable_python(tmp_path / 'path-venv')
        python_path = venv / 'bin' / 'python'
        hermes_bin = venv / 'bin' / 'hermes'
        hermes_bin.write_text(f'#!{python_path}\nprint("hi")\n')
        hermes_bin.chmod(0o755)
        with patch.object(hermes_install.shutil, 'which', return_value=str(hermes_bin)):
            result = hermes_install.detect_hermes_venv()
        assert result == venv

    def test_path_hermes_with_malformed_shebang_raises(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.delenv('MYAH_HERMES_VENV', raising=False)
        monkeypatch.setattr(hermes_install, '_HERMES_VENV_CANDIDATES', (tmp_path / 'noexist',))
        bad_hermes = tmp_path / 'hermes-bad'
        bad_hermes.write_text('not a shebang line\n')
        bad_hermes.chmod(0o755)
        with patch.object(hermes_install.shutil, 'which', return_value=str(bad_hermes)):
            with pytest.raises(RuntimeError, match='locate hermes-agent venv'):
                hermes_install.detect_hermes_venv()

    def test_path_hermes_with_env_shebang_raises_with_hint(self, tmp_path: Path, monkeypatch) -> None:
        """`#!/usr/bin/env python3` form gets a dedicated, actionable error."""
        monkeypatch.delenv('MYAH_HERMES_VENV', raising=False)
        monkeypatch.setattr(hermes_install, '_HERMES_VENV_CANDIDATES', (tmp_path / 'noexist',))
        env_hermes = tmp_path / 'hermes-env'
        env_hermes.write_text('#!/usr/bin/env python3\nprint("hi")\n')
        env_hermes.chmod(0o755)
        with patch.object(hermes_install.shutil, 'which', return_value=str(env_hermes)):
            with pytest.raises(RuntimeError) as exc:
                hermes_install.detect_hermes_venv()
        msg = str(exc.value)
        assert 'MYAH_HERMES_VENV' in msg
        assert 'env-based shebang' in msg


# ---------------------------------------------------------------------------
# read_pinned_plugin_sha_from_dockerfile
# ---------------------------------------------------------------------------


class TestReadPinnedPluginShaFromDockerfile:
    def test_happy_path_returns_sha(self, tmp_path: Path) -> None:
        sha = 'a' * 40
        df = tmp_path / 'Dockerfile.stock'
        df.write_text(f'ARG HERMES_SHA={"b" * 40}\nARG MYAH_PLUGIN_SHA={sha}\n')
        assert hermes_install.read_pinned_plugin_sha_from_dockerfile(df) == sha

    def test_missing_arg_raises(self, tmp_path: Path) -> None:
        df = tmp_path / 'Dockerfile.stock'
        df.write_text('FROM scratch\n')
        with pytest.raises(RuntimeError):
            hermes_install.read_pinned_plugin_sha_from_dockerfile(df)


# ---------------------------------------------------------------------------
# bootstrap_pip
# ---------------------------------------------------------------------------


class TestBootstrapPip:
    def test_pip_already_present_is_noop(self, tmp_path: Path) -> None:
        venv_py = tmp_path / 'venv' / 'bin' / 'python'
        with patch.object(hermes_install, 'run') as mock_run:
            mock_run.return_value = _ok(stdout='pip 25.0')
            hermes_install.bootstrap_pip(venv_py)
        assert mock_run.call_count == 1
        cmd = mock_run.call_args_list[0].args[0]
        assert cmd == [str(venv_py), '-m', 'pip', '--version']

    def test_bootstraps_via_ensurepip_when_pip_missing(self, tmp_path: Path) -> None:
        venv_py = tmp_path / 'venv' / 'bin' / 'python'
        with patch.object(hermes_install, 'run') as mock_run:
            mock_run.side_effect = [
                _fail(returncode=1, stderr='No module named pip'),
                _ok(),  # ensurepip
                _ok(stdout='pip 25.0'),
            ]
            hermes_install.bootstrap_pip(venv_py)
        assert mock_run.call_count == 3
        ensurepip_cmd = mock_run.call_args_list[1].args[0]
        assert ensurepip_cmd[0] == str(venv_py)
        assert '-m' in ensurepip_cmd and 'ensurepip' in ensurepip_cmd

    def test_ensurepip_does_not_pass_unsupported_quiet_flag(
        self, tmp_path: Path
    ) -> None:
        """Regression for PR #16 review C-2: ``python -m ensurepip`` on
        Python 3.11 (the Hermes 0.14.0 venv) does NOT accept ``--quiet``.
        Passing it makes argparse exit 2 with
        ``unrecognized arguments: --quiet`` and the install aborts in
        Phase 5 before the plugin pip-install ever runs.

        Captured stdout is suppressed by ``shell.run``'s ``capture_output=True``
        regardless, so dropping the flag is a no-op for terminal noise.
        """
        venv_py = tmp_path / 'venv' / 'bin' / 'python'
        with patch.object(hermes_install, 'run') as mock_run:
            mock_run.side_effect = [
                _fail(returncode=1, stderr='No module named pip'),
                _ok(),
                _ok(stdout='pip 25.0'),
            ]
            hermes_install.bootstrap_pip(venv_py)
        ensurepip_cmd = mock_run.call_args_list[1].args[0]
        assert '--quiet' not in ensurepip_cmd, (
            f'ensurepip does not accept --quiet on Python 3.11; got {ensurepip_cmd!r}. '
            f'See PR #16 review C-2.'
        )

    def test_ensurepip_succeeds_but_pip_still_missing_raises(self, tmp_path: Path) -> None:
        venv_py = tmp_path / 'venv' / 'bin' / 'python'
        with patch.object(hermes_install, 'run') as mock_run:
            mock_run.side_effect = [
                _fail(returncode=1),
                _ok(),
                _fail(returncode=1),
            ]
            with pytest.raises(RuntimeError, match=str(venv_py.parent.parent)):
                hermes_install.bootstrap_pip(venv_py)


# ---------------------------------------------------------------------------
# pip_install_plugin_at_sha
# ---------------------------------------------------------------------------


class TestPipInstallPluginAtSha:
    def test_no_auth_builds_unauthenticated_url(self, tmp_path: Path) -> None:
        sha = 'd' * 40
        venv_py = tmp_path / 'venv' / 'bin' / 'python'
        with patch.object(hermes_install, 'run') as mock_run:
            mock_run.return_value = _ok()
            hermes_install.pip_install_plugin_at_sha(sha, venv_py)
        cmd = mock_run.call_args.args[0]
        assert cmd[0] == str(venv_py)
        assert '-m' in cmd and 'pip' in cmd and 'install' in cmd
        req = cmd[-1]
        assert req == (f'myah-hermes-plugin @ git+https://github.com/T3-Venture-Labs-Limited/myah-hermes-plugin@{sha}')
        assert mock_run.call_args.kwargs.get('check') is True

    def test_with_auth_token_embeds_in_url(self, tmp_path: Path) -> None:
        sha = 'e' * 40
        venv_py = tmp_path / 'venv' / 'bin' / 'python'
        token = 'ghp_secret123'  # noqa: S105 — test fixture
        with patch.object(hermes_install, 'run') as mock_run:
            mock_run.return_value = _ok()
            hermes_install.pip_install_plugin_at_sha(sha, venv_py, auth_token=token)
        req = mock_run.call_args.args[0][-1]
        assert f'https://{token}@github.com/' in req
        assert req.endswith(f'@{sha}')

    def test_shell_error_propagates(self, tmp_path: Path) -> None:
        sha = 'f' * 40
        venv_py = tmp_path / 'venv' / 'bin' / 'python'
        with patch.object(hermes_install, 'run') as mock_run:
            mock_run.side_effect = ShellError(['pip'], _fail())
            with pytest.raises(ShellError):
                hermes_install.pip_install_plugin_at_sha(sha, venv_py)


# ---------------------------------------------------------------------------
# materialize_dashboard_shim
# ---------------------------------------------------------------------------


class TestMaterializeDashboardShim:
    def test_missing_console_script_raises(self, tmp_path: Path) -> None:
        venv = tmp_path / 'venv'
        (venv / 'bin').mkdir(parents=True)
        hermes_home = tmp_path / 'hermes'
        with pytest.raises(RuntimeError, match='myah-hermes-plugin'):
            hermes_install.materialize_dashboard_shim(venv, hermes_home)

    def test_invokes_absolute_script_with_target_and_merged_env(self, tmp_path: Path) -> None:
        venv = tmp_path / 'venv'
        (venv / 'bin').mkdir(parents=True)
        script = venv / 'bin' / 'myah-hermes-plugin'
        script.write_text('#!/bin/sh\n')
        script.chmod(0o755)
        hermes_home = tmp_path / 'hermes'
        with patch.object(hermes_install, 'run') as mock_run:
            mock_run.return_value = _ok()
            hermes_install.materialize_dashboard_shim(venv, hermes_home)
        cmd = mock_run.call_args.args[0]
        assert cmd[0] == str(script)
        assert 'install' in cmd
        assert '--dashboard-only' in cmd
        assert '--target' in cmd
        target_index = cmd.index('--target')
        assert cmd[target_index + 1] == str(hermes_home / 'plugins')

    def test_env_is_merged_not_replaced_path_survives(self, tmp_path: Path) -> None:
        venv = tmp_path / 'venv'
        (venv / 'bin').mkdir(parents=True)
        script = venv / 'bin' / 'myah-hermes-plugin'
        script.write_text('#!/bin/sh\n')
        script.chmod(0o755)
        hermes_home = tmp_path / 'hermes'
        sentinel_path = '/sentinel/path/bin:/usr/bin'
        with patch.dict(os.environ, {'PATH': sentinel_path}, clear=False):
            with patch.object(hermes_install, 'run') as mock_run:
                mock_run.return_value = _ok()
                hermes_install.materialize_dashboard_shim(venv, hermes_home)
        env = mock_run.call_args.kwargs.get('env')
        assert env is not None, 'env must be passed (merged), not None'
        assert env.get('HERMES_HOME') == str(hermes_home)
        # CRITICAL: PATH from parent env survives — proves env-merge not env-replace
        assert env.get('PATH') == sentinel_path

    def test_shell_error_propagates(self, tmp_path: Path) -> None:
        venv = tmp_path / 'venv'
        (venv / 'bin').mkdir(parents=True)
        script = venv / 'bin' / 'myah-hermes-plugin'
        script.write_text('#!/bin/sh\n')
        script.chmod(0o755)
        hermes_home = tmp_path / 'hermes'
        with patch.object(hermes_install, 'run') as mock_run:
            mock_run.side_effect = ShellError(['myah-hermes-plugin'], _fail())
            with pytest.raises(ShellError):
                hermes_install.materialize_dashboard_shim(venv, hermes_home)


# ---------------------------------------------------------------------------
# verify_dashboard_plugin_mounted
# ---------------------------------------------------------------------------


class TestVerifyDashboardPluginMounted:
    def test_first_poll_succeeds_returns_true_no_sleep(self) -> None:
        with patch.object(hermes_install, '_http_get_ok', return_value=True) as mock_http:
            with patch.object(hermes_install.time, 'sleep') as mock_sleep:
                ok = hermes_install.verify_dashboard_plugin_mounted('tok')
        assert ok is True
        assert mock_http.call_count == 1
        mock_sleep.assert_not_called()

    def test_succeeds_on_fourth_poll_sleeps_three_times(self) -> None:
        responses = [False, False, False, True]
        with patch.object(hermes_install, '_http_get_ok', side_effect=responses):
            with patch.object(hermes_install.time, 'sleep') as mock_sleep:
                ok = hermes_install.verify_dashboard_plugin_mounted('tok')
        assert ok is True
        assert mock_sleep.call_count == 3
        # Lock in the configured poll_interval_s (default 0.5) being honored.
        assert mock_sleep.call_args_list == [call(0.5), call(0.5), call(0.5)]

    def test_returns_false_after_timeout_never_raises(self) -> None:
        with patch.object(hermes_install, '_http_get_ok', return_value=False) as mock_http:
            with patch.object(hermes_install.time, 'sleep'):
                ok = hermes_install.verify_dashboard_plugin_mounted('tok', timeout_s=2.0, poll_interval_s=0.5)
        assert ok is False
        # timeout_s / poll_interval_s = 4 attempts
        assert mock_http.call_count == 4

    def test_no_token_sends_no_auth_header(self) -> None:
        captured: dict = {}

        def _fake(url, headers):
            captured['headers'] = headers
            return True

        with patch.object(hermes_install, '_http_get_ok', side_effect=_fake):
            with patch.object(hermes_install.time, 'sleep'):
                hermes_install.verify_dashboard_plugin_mounted(None)
        assert 'Authorization' not in captured['headers']

    def test_with_token_sends_bearer_header(self) -> None:
        captured: dict = {}

        def _fake(url, headers):
            captured['headers'] = headers
            return True

        with patch.object(hermes_install, '_http_get_ok', side_effect=_fake):
            with patch.object(hermes_install.time, 'sleep'):
                hermes_install.verify_dashboard_plugin_mounted('foo')
        assert captured['headers'].get('Authorization') == 'Bearer foo'


# ---------------------------------------------------------------------------
# verify_gateway_plugin_bound  (regression for PR #16 review M-1)
# ---------------------------------------------------------------------------


class TestVerifyGatewayPluginBound:
    """Polls ``127.0.0.1:<port>/myah/health`` — the real "is the platform
    adapter bound?" signal. The dashboard-side check at
    ``:9119/api/plugins/myah-admin/health`` only proves the shim
    materialized; it doesn't prove the gateway loaded the plugin."""

    def test_polls_gateway_myah_health_endpoint(self) -> None:
        captured: dict = {}

        def _fake(url, headers):
            captured['url'] = url
            captured['headers'] = headers
            return True

        with patch.object(hermes_install, '_http_get_ok', side_effect=_fake):
            with patch.object(hermes_install.time, 'sleep'):
                ok = hermes_install.verify_gateway_plugin_bound()
        assert ok is True
        assert captured['url'] == 'http://127.0.0.1:8643/myah/health'
        # /myah/health is unauthed — no bearer needed.
        assert 'Authorization' not in captured['headers']

    def test_returns_false_after_timeout_never_raises(self) -> None:
        with patch.object(hermes_install, '_http_get_ok', return_value=False) as mock_http:
            with patch.object(hermes_install.time, 'sleep'):
                ok = hermes_install.verify_gateway_plugin_bound(timeout_s=2.0, poll_interval_s=0.5)
        assert ok is False
        assert mock_http.call_count == 4

    def test_custom_port_honored(self) -> None:
        captured: dict = {}

        def _fake(url, headers):
            captured['url'] = url
            return True

        with patch.object(hermes_install, '_http_get_ok', side_effect=_fake):
            with patch.object(hermes_install.time, 'sleep'):
                hermes_install.verify_gateway_plugin_bound(port=18643)
        assert captured['url'] == 'http://127.0.0.1:18643/myah/health'

    def test_url_uses_provided_port(self) -> None:
        captured: dict = {}

        def _fake(url, headers):
            captured['url'] = url
            return True

        with patch.object(hermes_install, '_http_get_ok', side_effect=_fake):
            with patch.object(hermes_install.time, 'sleep'):
                hermes_install.verify_dashboard_plugin_mounted('tok', port=9999)
        assert '127.0.0.1:9999' in captured['url']
        assert '/api/plugins/myah-admin/health' in captured['url']


# ---------------------------------------------------------------------------
# _http_get_ok — direct unit tests
# ---------------------------------------------------------------------------


class TestHttpGetOk:
    """Direct unit tests for the urllib helper.

    Lock in the exception-swallow list — the helper MUST swallow URLError,
    HTTPError, and OSError (which catches ConnectionRefusedError +
    TimeoutError that fire during dashboard boot), and MUST NOT swallow
    programmer errors like TypeError.
    """

    def test_returns_true_on_200(self) -> None:
        resp = MagicMock()
        resp.status = 200
        ctx = MagicMock()
        ctx.__enter__.return_value = resp
        ctx.__exit__.return_value = False
        with patch('urllib.request.urlopen', return_value=ctx):
            ok = hermes_install._http_get_ok('http://127.0.0.1:9119/foo', {})
        assert ok is True

    def test_returns_false_on_non_200(self) -> None:
        resp = MagicMock()
        resp.status = 503
        ctx = MagicMock()
        ctx.__enter__.return_value = resp
        ctx.__exit__.return_value = False
        with patch('urllib.request.urlopen', return_value=ctx):
            ok = hermes_install._http_get_ok('http://127.0.0.1:9119/foo', {})
        assert ok is False

    def test_returns_false_on_url_error(self) -> None:
        import urllib.error

        with patch('urllib.request.urlopen', side_effect=urllib.error.URLError('nope')):
            ok = hermes_install._http_get_ok('http://127.0.0.1:9119/foo', {})
        assert ok is False

    def test_returns_false_on_http_error(self) -> None:
        import urllib.error

        err = urllib.error.HTTPError(
            url='http://127.0.0.1:9119/foo',
            code=404,
            msg='Not Found',
            hdrs=None,  # type: ignore[arg-type]
            fp=None,
        )
        with patch('urllib.request.urlopen', side_effect=err):
            ok = hermes_install._http_get_ok('http://127.0.0.1:9119/foo', {})
        assert ok is False

    def test_returns_false_on_connection_refused(self) -> None:
        """Proves OSError catch — ConnectionRefusedError is OSError, NOT URLError.

        If someone tightens the swallow list to URLError only, this test fails
        and `verify_dashboard_plugin_mounted` would crash mid-poll during
        normal dashboard boot.
        """
        with patch('urllib.request.urlopen', side_effect=ConnectionRefusedError('refused')):
            ok = hermes_install._http_get_ok('http://127.0.0.1:9119/foo', {})
        assert ok is False

    def test_does_not_swallow_type_error(self) -> None:
        """Programmer errors must propagate — TypeError is not a network error."""
        with patch('urllib.request.urlopen', side_effect=TypeError('bad call')):
            with pytest.raises(TypeError):
                hermes_install._http_get_ok('http://127.0.0.1:9119/foo', {})


# ---------------------------------------------------------------------------
# detect_installed_plugin_sha  (Slice 5 Task 5.2)
# ---------------------------------------------------------------------------
#
# Reads PEP 610 ``direct_url.json`` from the installed
# ``myah-hermes-plugin``'s ``.dist-info`` directory. Returns the git
# commit SHA the package was built from, or None when:
#   - the package isn't installed
#   - direct_url.json doesn't exist (editable / non-pip install)
#   - the recorded source is an editable install (``dir_info`` instead of
#     ``vcs_info``)
#   - the recorded vcs is not git
#   - JSON is malformed
#
# Caller treats None as "skip drift warning", not as an error.


def _make_dist_info(
    venv: Path,
    *,
    python_version: str = '3.11',
    direct_url_content: str | None,
) -> Path:
    """Build a fake venv layout with myah-hermes-plugin-<v>.dist-info/.

    Returns the dist-info dir path. If direct_url_content is None, no
    direct_url.json is created (simulates pre-PEP-610 pip or non-pip
    install).
    """
    site_packages = venv / 'lib' / f'python{python_version}' / 'site-packages'
    site_packages.mkdir(parents=True, exist_ok=True)
    dist_info = site_packages / 'myah_hermes_plugin-0.1.0.dist-info'
    dist_info.mkdir(parents=True, exist_ok=True)
    if direct_url_content is not None:
        (dist_info / 'direct_url.json').write_text(direct_url_content, encoding='utf-8')
    return dist_info


class TestDetectInstalledPluginSha:
    def test_returns_sha_from_valid_direct_url_json(self, tmp_path: Path) -> None:
        venv = tmp_path / 'hermes-venv'
        sha = '4a1a6c5eb6ee19fc968b892b26983c0d13aad4bf'
        _make_dist_info(
            venv,
            direct_url_content=(
                '{"url": "https://github.com/T3-Venture-Labs-Limited/myah-hermes-plugin",'
                f' "vcs_info": {{"vcs": "git", "commit_id": "{sha}",'
                f' "requested_revision": "{sha}"}}}}'
            ),
        )
        assert hermes_install.detect_installed_plugin_sha(venv) == sha

    def test_returns_none_for_editable_install_dir_info(self, tmp_path: Path) -> None:
        """Editable installs record `dir_info`, not `vcs_info` — return None."""
        venv = tmp_path / 'hermes-venv'
        _make_dist_info(
            venv,
            direct_url_content=('{"url": "file:///some/path/myah-hermes-plugin", "dir_info": {"editable": true}}'),
        )
        assert hermes_install.detect_installed_plugin_sha(venv) is None

    def test_returns_none_when_no_dist_info_present(self, tmp_path: Path) -> None:
        """Package not installed: no .dist-info dir → None."""
        venv = tmp_path / 'hermes-venv'
        # Build the site-packages but no plugin dist-info
        (venv / 'lib' / 'python3.11' / 'site-packages').mkdir(parents=True)
        assert hermes_install.detect_installed_plugin_sha(venv) is None

    def test_returns_none_when_direct_url_missing(self, tmp_path: Path) -> None:
        """Pre-PEP-610 pip / non-pip install: dist-info exists, no direct_url.json."""
        venv = tmp_path / 'hermes-venv'
        _make_dist_info(venv, direct_url_content=None)
        assert hermes_install.detect_installed_plugin_sha(venv) is None

    def test_returns_none_when_json_malformed(self, tmp_path: Path) -> None:
        """Tolerate malformed JSON — return None, don't crash."""
        venv = tmp_path / 'hermes-venv'
        _make_dist_info(venv, direct_url_content='{this is not json}')
        assert hermes_install.detect_installed_plugin_sha(venv) is None

    def test_returns_none_when_vcs_is_not_git(self, tmp_path: Path) -> None:
        """Mercurial/SVN/etc.: vcs_info exists but vcs != 'git' → None."""
        venv = tmp_path / 'hermes-venv'
        _make_dist_info(
            venv,
            direct_url_content=(
                '{"url": "https://example.com/repo", "vcs_info": {"vcs": "hg", "commit_id": "abc123"}}'
            ),
        )
        assert hermes_install.detect_installed_plugin_sha(venv) is None

    def test_works_with_different_python_version_dirs(self, tmp_path: Path) -> None:
        """Globs python* dir, so python3.12 works too without hardcoding."""
        venv = tmp_path / 'hermes-venv'
        sha = 'b' * 40
        _make_dist_info(
            venv,
            python_version='3.12',
            direct_url_content=(f'{{"vcs_info": {{"vcs": "git", "commit_id": "{sha}"}}}}'),
        )
        assert hermes_install.detect_installed_plugin_sha(venv) == sha


# ---------------------------------------------------------------------------
# register_plugin_with_gateway  (regression for PR #16 review C-3)
# ---------------------------------------------------------------------------


class TestRegisterPluginWithGateway:
    """Phase 5b: ``hermes plugins install <repo>`` + ``hermes plugins enable myah``.

    Pip-installing the plugin into the Hermes venv is necessary but not
    sufficient. The gateway only loads plugins that are registered in
    ``~/.hermes/plugins/<name>/`` AND enabled. Without this step the
    OSS probe reports ``plugin_installed: false`` and the platform
    adapter never binds port 8643 — see PR #16 review C-3 for the
    VM-test transcript.
    """

    def test_invokes_hermes_plugins_install_then_enable(self, tmp_path: Path) -> None:
        hermes_bin = tmp_path / 'hermes-venv' / 'bin' / 'hermes'
        with patch.object(hermes_install, 'run') as mock_run:
            mock_run.return_value = _ok()
            hermes_install.register_plugin_with_gateway(hermes_bin)
        assert mock_run.call_count == 2
        install_cmd = mock_run.call_args_list[0].args[0]
        assert install_cmd[0] == str(hermes_bin)
        assert install_cmd[1:3] == ['plugins', 'install']
        assert install_cmd[3] == 'T3-Venture-Labs-Limited/myah-hermes-plugin'
        enable_cmd = mock_run.call_args_list[1].args[0]
        assert enable_cmd == [str(hermes_bin), 'plugins', 'enable', 'myah']

    def test_passes_adapter_auth_key_env_to_avoid_prompt(self, tmp_path: Path) -> None:
        """The plugin's post-install hook prompts for ``MYAH_ADAPTER_AUTH_KEY``
        unless it finds the env var. In non-interactive mode the prompt
        blocks forever, so we pre-set the env var to the value we just
        wrote to the Hermes .env."""
        hermes_bin = tmp_path / 'venv' / 'bin' / 'hermes'
        bearer = 'b' * 32
        with patch.object(hermes_install, 'run') as mock_run:
            mock_run.return_value = _ok()
            hermes_install.register_plugin_with_gateway(hermes_bin, adapter_auth_key=bearer)
        env_first = mock_run.call_args_list[0].kwargs.get('env') or {}
        assert env_first.get('MYAH_ADAPTER_AUTH_KEY') == bearer

    def test_install_failure_propagates(self, tmp_path: Path) -> None:
        """If ``hermes plugins install`` fails, surface the ShellError."""
        hermes_bin = tmp_path / 'venv' / 'bin' / 'hermes'
        with patch.object(hermes_install, 'run') as mock_run:
            mock_run.side_effect = ShellError(['hermes'], _fail())
            with pytest.raises(ShellError):
                hermes_install.register_plugin_with_gateway(hermes_bin)

    def test_idempotent_when_already_installed(self, tmp_path: Path) -> None:
        """Re-running an install must not error — `hermes plugins install`
        emits ``already installed`` to stderr and exits 0. The enable
        step still runs (enabling an already-enabled plugin is a no-op).
        """
        hermes_bin = tmp_path / 'venv' / 'bin' / 'hermes'
        with patch.object(hermes_install, 'run') as mock_run:
            mock_run.return_value = _ok(stderr='Plugin myah already installed.\n')
            hermes_install.register_plugin_with_gateway(hermes_bin)
        assert mock_run.call_count == 2

    def test_idempotent_when_install_reports_already_exists(self, tmp_path: Path) -> None:
        """Re-run case: `hermes plugins install` exits non-zero with "already exists"
        in stdout. The wrapper must treat that as success, still run enable, and
        NOT raise. Regression for PR #16 post-merge laptop test (Bug 1).

        Simulates what real ``run()`` does: when called with ``check=True`` and
        the subprocess returns non-zero, it raises ``ShellError``. The fix
        must call ``run(check=False)`` for the install step and inspect
        ``stdout`` for the already-exists sentinel before re-raising.
        """
        hermes_bin = tmp_path / 'venv' / 'bin' / 'hermes'
        already_exists_stdout = (
            'Cloning https://github.com/T3-Venture-Labs-Limited/myah-hermes-plugin.git...\n'
            "Error: Plugin 'myah' already exists. Use force reinstall or run "
            '`hermes plugins update myah`.\n'
        )
        already_exists_result = _fail(returncode=1, stdout=already_exists_stdout, stderr='')

        def fake_run(cmd, *, check=False, env=None, **_kwargs):
            # Mirror the real ``run()`` contract: check=True raises ShellError
            # on non-zero. The fix is required to pass check=False on the
            # install step so this branch is NOT taken.
            if cmd[1:3] == ['plugins', 'install']:
                if check:
                    raise ShellError(cmd, already_exists_result)
                return already_exists_result
            # plugins enable
            return _ok()

        with patch.object(hermes_install, 'run', side_effect=fake_run) as mock_run:
            # Must NOT raise.
            hermes_install.register_plugin_with_gateway(hermes_bin)
        # Both subprocess calls happened — install was attempted, enable still ran.
        assert mock_run.call_count == 2
        enable_cmd = mock_run.call_args_list[1].args[0]
        assert enable_cmd[1:] == ['plugins', 'enable', 'myah']
