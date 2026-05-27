"""Tests for ``myah plugins {list,install,update,remove}``.

Slice 5 Task 5.2 of T3-1084 (DevX + OSS CLI).

Top-level wrappers that pass-through to ``hermes plugins <verb>`` with
one Myah-specific value-add: a yellow SHA-drift warning emitted when
the installed ``myah-hermes-plugin``'s recorded git SHA (from PEP 610
``direct_url.json``) differs from the SHA pinned at
``agent/Dockerfile.stock:183``.

The warning is informational, never an error: a divergence usually
means the user ran ``hermes plugins update myah`` ahead of the
Dockerfile bump, or upgraded out-of-band. Chat may still work fine.

Mock target = consumer namespace (``myah.cli.plugins.run`` /
``myah.cli.plugins.detect_hermes_venv`` /
``myah.cli.plugins.detect_installed_plugin_sha``). Never patch source
modules. Same discipline as Slices 2-4.
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
def fake_hermes_venv(tmp_path: Path, mocker) -> Path:
    """A fake hermes venv with bin/hermes; detect_hermes_venv returns it."""
    venv = tmp_path / 'fake-hermes-venv'
    (venv / 'bin').mkdir(parents=True)
    hermes_bin = venv / 'bin' / 'hermes'
    hermes_bin.write_text('#!/bin/sh\necho fake-hermes\n', encoding='utf-8')
    hermes_bin.chmod(0o755)
    mocker.patch('myah.lib.cli.hermes_install.detect_hermes_venv', return_value=venv)
    return venv


@pytest.fixture
def no_drift(mocker) -> None:
    """Pin both SHAs to the same value so no drift warning fires."""
    same_sha = 'a' * 40
    mocker.patch('myah.cli.plugins.find_repo_root', return_value=Path('/fake/repo'))
    mocker.patch('myah.cli.plugins.read_pinned_plugin_sha_from_dockerfile', return_value=same_sha)
    mocker.patch('myah.cli.plugins.detect_installed_plugin_sha', return_value=same_sha)


# ── pass-through happy paths ───────────────────────────────────────────


def test_plugins_list_invokes_hermes_plugins_list(fake_hermes_venv: Path, no_drift, mocker) -> None:
    """`myah plugins list` invokes `<hermes>/bin/hermes plugins list` and surfaces stdout."""
    run_mock = mocker.patch(
        'myah.cli.plugins.run',
        return_value=_ok(stdout='myah-hermes-plugin (enabled)\n'),
    )

    result = runner.invoke(app, ['plugins', 'list'])

    assert result.exit_code == 0, f'stdout: {result.stdout}\nexc: {result.exception}'
    run_mock.assert_called_once()
    cmd = run_mock.call_args.args[0]
    assert cmd == [str(fake_hermes_venv / 'bin' / 'hermes'), 'plugins', 'list']
    assert 'myah-hermes-plugin' in result.stdout


def test_plugins_list_no_args(fake_hermes_venv: Path, no_drift, mocker) -> None:
    """`myah plugins list` accepts no positional args."""
    run_mock = mocker.patch('myah.cli.plugins.run', return_value=_ok())

    result = runner.invoke(app, ['plugins', 'list'])

    assert result.exit_code == 0, result.stdout
    cmd = run_mock.call_args.args[0]
    # No extra positional after 'list'.
    assert cmd[-1] == 'list'


def test_plugins_install_forwards_identifier(fake_hermes_venv: Path, no_drift, mocker) -> None:
    """`myah plugins install foo/bar` forwards the identifier verbatim."""
    run_mock = mocker.patch('myah.cli.plugins.run', return_value=_ok())

    result = runner.invoke(app, ['plugins', 'install', 'foo/bar'])

    assert result.exit_code == 0, result.stdout
    cmd = run_mock.call_args.args[0]
    assert cmd == [str(fake_hermes_venv / 'bin' / 'hermes'), 'plugins', 'install', 'foo/bar']


def test_plugins_install_forwards_force_flag(fake_hermes_venv: Path, no_drift, mocker) -> None:
    """`myah plugins install foo/bar --force` forwards `--force` to hermes."""
    run_mock = mocker.patch('myah.cli.plugins.run', return_value=_ok())

    result = runner.invoke(app, ['plugins', 'install', 'foo/bar', '--force'])

    assert result.exit_code == 0, result.stdout
    cmd = run_mock.call_args.args[0]
    assert '--force' in cmd
    # identifier still survives intact
    assert 'foo/bar' in cmd


def test_plugins_install_forwards_enable_flag(fake_hermes_venv: Path, no_drift, mocker) -> None:
    """`--enable` flag flows through to `hermes plugins install`."""
    run_mock = mocker.patch('myah.cli.plugins.run', return_value=_ok())

    result = runner.invoke(app, ['plugins', 'install', 'foo/bar', '--enable'])

    assert result.exit_code == 0, result.stdout
    cmd = run_mock.call_args.args[0]
    assert '--enable' in cmd


def test_plugins_install_forwards_no_enable_flag(fake_hermes_venv: Path, no_drift, mocker) -> None:
    """`--no-enable` flag flows through to `hermes plugins install`."""
    run_mock = mocker.patch('myah.cli.plugins.run', return_value=_ok())

    result = runner.invoke(app, ['plugins', 'install', 'foo/bar', '--no-enable'])

    assert result.exit_code == 0, result.stdout
    cmd = run_mock.call_args.args[0]
    assert '--no-enable' in cmd


def test_plugins_update_forwards_identifier(fake_hermes_venv: Path, no_drift, mocker) -> None:
    run_mock = mocker.patch('myah.cli.plugins.run', return_value=_ok())

    result = runner.invoke(app, ['plugins', 'update', 'myah'])

    assert result.exit_code == 0, result.stdout
    cmd = run_mock.call_args.args[0]
    assert cmd == [str(fake_hermes_venv / 'bin' / 'hermes'), 'plugins', 'update', 'myah']


def test_plugins_remove_forwards_identifier(fake_hermes_venv: Path, no_drift, mocker) -> None:
    run_mock = mocker.patch('myah.cli.plugins.run', return_value=_ok())

    result = runner.invoke(app, ['plugins', 'remove', 'myah'])

    assert result.exit_code == 0, result.stdout
    cmd = run_mock.call_args.args[0]
    assert cmd == [str(fake_hermes_venv / 'bin' / 'hermes'), 'plugins', 'remove', 'myah']


# ── failing-returncode propagation ─────────────────────────────────────


@pytest.mark.parametrize(
    'argv',
    [
        ['plugins', 'list'],
        ['plugins', 'install', 'foo/bar'],
        ['plugins', 'update', 'myah'],
        ['plugins', 'remove', 'myah'],
    ],
)
def test_plugins_verb_surfaces_failing_returncode(fake_hermes_venv: Path, no_drift, mocker, argv: list[str]) -> None:
    """Non-zero exit from hermes propagates to typer's exit code."""
    mocker.patch(
        'myah.cli.plugins.run',
        return_value=ShellResult(returncode=3, stdout='', stderr='plugin not found'),
    )

    result = runner.invoke(app, argv)

    assert result.exit_code == 3, f'wanted 3, got {result.exit_code}; stdout: {result.stdout}'


# ── hermes-venv-missing fast fail ──────────────────────────────────────


def test_plugins_list_exits_2_when_no_hermes_venv(monkeypatch: pytest.MonkeyPatch, mocker) -> None:
    """When detect_hermes_venv raises, surface a clear error and exit 2."""
    mocker.patch(
        'myah.lib.cli.hermes_install.detect_hermes_venv',
        side_effect=RuntimeError('Could not locate hermes-agent venv'),
    )
    run_mock = mocker.patch('myah.cli.plugins.run')

    result = runner.invoke(app, ['plugins', 'list'])

    assert result.exit_code == 2
    run_mock.assert_not_called()
    output = result.stdout + (str(result.exception) if result.exception else '')
    assert 'hermes' in output.lower()


# ── drift warning ──────────────────────────────────────────────────────


def test_drift_warning_emitted_when_installed_sha_differs(fake_hermes_venv: Path, mocker) -> None:
    """When installed SHA != Dockerfile-pinned SHA, emit a yellow warning."""
    pinned = 'a' * 40
    installed = 'b' * 40
    mocker.patch('myah.cli.plugins.find_repo_root', return_value=Path('/fake/repo'))
    mocker.patch('myah.cli.plugins.read_pinned_plugin_sha_from_dockerfile', return_value=pinned)
    mocker.patch('myah.cli.plugins.detect_installed_plugin_sha', return_value=installed)
    mocker.patch('myah.cli.plugins.run', return_value=_ok(stdout='myah\n'))

    result = runner.invoke(app, ['plugins', 'list'])

    assert result.exit_code == 0, result.stdout
    output = result.stdout
    # Warning text mentions both shorthand SHAs (or 'drift' / 'pinned' to be loose).
    lowered = output.lower()
    assert 'drift' in lowered or 'pinned' in lowered or 'differ' in lowered, (
        f'expected drift warning in output, got: {output!r}'
    )


def test_drift_warning_not_emitted_when_shas_match(fake_hermes_venv: Path, mocker) -> None:
    """Matching SHAs: no warning text in output."""
    same = 'a' * 40
    mocker.patch('myah.cli.plugins.find_repo_root', return_value=Path('/fake/repo'))
    mocker.patch('myah.cli.plugins.read_pinned_plugin_sha_from_dockerfile', return_value=same)
    mocker.patch('myah.cli.plugins.detect_installed_plugin_sha', return_value=same)
    mocker.patch('myah.cli.plugins.run', return_value=_ok(stdout='listing\n'))

    result = runner.invoke(app, ['plugins', 'list'])

    assert result.exit_code == 0, result.stdout
    lowered = result.stdout.lower()
    assert 'drift' not in lowered
    assert 'differ' not in lowered


def test_drift_warning_silenced_when_installed_sha_unknown(fake_hermes_venv: Path, mocker) -> None:
    """When detect_installed_plugin_sha returns None, the warning is skipped."""
    pinned = 'a' * 40
    mocker.patch('myah.cli.plugins.find_repo_root', return_value=Path('/fake/repo'))
    mocker.patch('myah.cli.plugins.read_pinned_plugin_sha_from_dockerfile', return_value=pinned)
    mocker.patch('myah.cli.plugins.detect_installed_plugin_sha', return_value=None)
    mocker.patch('myah.cli.plugins.run', return_value=_ok(stdout='listing\n'))

    result = runner.invoke(app, ['plugins', 'list'])

    assert result.exit_code == 0, result.stdout
    lowered = result.stdout.lower()
    assert 'drift' not in lowered


def test_drift_warning_silenced_when_pinned_sha_unknown(fake_hermes_venv: Path, mocker) -> None:
    """When repo root can't be found, drift check is silently skipped."""
    mocker.patch('myah.cli.plugins.find_repo_root', side_effect=RuntimeError('no repo'))
    # detect_installed_plugin_sha shouldn't even be called in this case, but
    # patching defensively so the test doesn't depend on call ordering.
    mocker.patch('myah.cli.plugins.detect_installed_plugin_sha', return_value='b' * 40)
    mocker.patch('myah.cli.plugins.run', return_value=_ok(stdout='listing\n'))

    result = runner.invoke(app, ['plugins', 'list'])

    assert result.exit_code == 0, result.stdout
    lowered = result.stdout.lower()
    assert 'drift' not in lowered


def test_drift_warning_for_list_appears_before_listing(fake_hermes_venv: Path, mocker) -> None:
    """For `list`, the drift check runs BEFORE the hermes invocation so
    users see the warning above the listing.
    """
    pinned = 'a' * 40
    installed = 'b' * 40
    mocker.patch('myah.cli.plugins.find_repo_root', return_value=Path('/fake/repo'))
    mocker.patch('myah.cli.plugins.read_pinned_plugin_sha_from_dockerfile', return_value=pinned)
    mocker.patch('myah.cli.plugins.detect_installed_plugin_sha', return_value=installed)
    # Use a distinctive marker string for the hermes-side stdout.
    mocker.patch('myah.cli.plugins.run', return_value=_ok(stdout='LISTING_MARKER\n'))

    result = runner.invoke(app, ['plugins', 'list'])

    assert result.exit_code == 0, result.stdout
    output = result.stdout
    # Find positions of warning marker vs listing marker.
    lowered = output.lower()
    drift_idx = max(lowered.find('drift'), lowered.find('pinned'), lowered.find('differ'))
    listing_idx = output.find('LISTING_MARKER')
    assert drift_idx >= 0, f'expected drift warning in: {output!r}'
    assert listing_idx >= 0, f'expected LISTING_MARKER in: {output!r}'
    assert drift_idx < listing_idx, (
        f'expected drift warning BEFORE listing; got drift@{drift_idx}, listing@{listing_idx}'
    )


def test_drift_warning_for_install_appears_after_install_output(fake_hermes_venv: Path, mocker) -> None:
    """For state-changing verbs (install), drift check runs AFTER the hermes
    invocation so install output streams first.
    """
    pinned = 'a' * 40
    installed = 'b' * 40
    mocker.patch('myah.cli.plugins.find_repo_root', return_value=Path('/fake/repo'))
    mocker.patch('myah.cli.plugins.read_pinned_plugin_sha_from_dockerfile', return_value=pinned)
    mocker.patch('myah.cli.plugins.detect_installed_plugin_sha', return_value=installed)
    mocker.patch('myah.cli.plugins.run', return_value=_ok(stdout='INSTALL_MARKER\n'))

    result = runner.invoke(app, ['plugins', 'install', 'foo/bar'])

    assert result.exit_code == 0, result.stdout
    output = result.stdout
    lowered = output.lower()
    drift_idx = max(lowered.find('drift'), lowered.find('pinned'), lowered.find('differ'))
    install_idx = output.find('INSTALL_MARKER')
    assert drift_idx >= 0, f'expected drift warning in: {output!r}'
    assert install_idx >= 0, f'expected INSTALL_MARKER in: {output!r}'
    assert install_idx < drift_idx, (
        f'expected install output BEFORE drift warning; got install@{install_idx}, drift@{drift_idx}'
    )


def test_drift_warning_skipped_when_hermes_failed(fake_hermes_venv: Path, mocker) -> None:
    """If the hermes plugins call returned non-zero, we propagate exit
    immediately and skip the drift check — the install state is unknown.

    For `list`, the check runs BEFORE hermes, so failure mode differs; this
    test covers the install/update/remove path where check runs AFTER.
    """
    pinned = 'a' * 40
    installed = 'b' * 40
    mocker.patch('myah.cli.plugins.find_repo_root', return_value=Path('/fake/repo'))
    mocker.patch('myah.cli.plugins.read_pinned_plugin_sha_from_dockerfile', return_value=pinned)
    detect_mock = mocker.patch('myah.cli.plugins.detect_installed_plugin_sha', return_value=installed)
    mocker.patch(
        'myah.cli.plugins.run',
        return_value=ShellResult(returncode=2, stdout='', stderr='install failed'),
    )

    result = runner.invoke(app, ['plugins', 'install', 'foo/bar'])

    assert result.exit_code == 2
    # detect_installed_plugin_sha must NOT have been called — the post-hook
    # drift check is gated on a successful hermes invocation.
    detect_mock.assert_not_called()


# ── help text ──────────────────────────────────────────────────────────


def test_plugins_help_lists_subcommands() -> None:
    result = runner.invoke(app, ['plugins', '--help'])
    assert result.exit_code == 0
    assert 'list' in result.stdout
    assert 'install' in result.stdout
    assert 'update' in result.stdout
    assert 'remove' in result.stdout


def test_top_level_help_lists_plugins_group() -> None:
    """`myah --help` must surface the `plugins` subgroup for OSS users."""
    result = runner.invoke(app, ['--help'])
    assert result.exit_code == 0
    assert 'plugins' in result.stdout


# ── cold-start sentinel ────────────────────────────────────────────────


def test_module_does_not_import_heavy_libs_at_top_level() -> None:
    """Same pattern as agent.py — Rich, yaml, time, socket must stay out
    of the module top so `myah --help` cold-start stays under 200ms.
    """
    from myah.cli import plugins as mod

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
        assert offender not in head, f'cli/plugins.py top-level imports {offender!r}'
