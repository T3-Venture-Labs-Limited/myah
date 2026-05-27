"""Tests for `myah dev plugin {install-local,install-pinned}` (Slice 3 PR 3.C Task 3.3).

The seven-step `install-local` flow:
    1. Validate PATH has pyproject.toml with name="myah-hermes-plugin"
    2. pip uninstall any existing myah-hermes-plugin
    3. pip install -e <abspath>
    4. Verify upstream `myah-hermes-plugin install --dashboard-only` flag exists
    5. Re-materialize the dashboard shim at <worktree>/.hermes/plugins/
    6. Sanity-check the shim's import resolves to the editable source (warn, never abort)
    7. Print restart hint if backend/frontend running

`install-pinned` reverts to the pinned-SHA install (read from agent/Dockerfile.stock:183)
by reusing the Slice 2 library primitives.

Mock targets follow the consumer-namespace rule: patches go on
`myah.cli.dev.plugin.X`, never on source modules.
"""

from __future__ import annotations

from pathlib import Path

from myah import app
from myah.lib.cli.shell import ShellResult
from typer.testing import CliRunner

runner = CliRunner()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_worktree(tmp_path: Path, *, with_venv: bool = True, with_plugin_bin: bool = True) -> Path:
    """Materialize a minimal worktree shape with optional venv pip + plugin binary."""
    (tmp_path / 'platform-oss').mkdir(exist_ok=True)
    (tmp_path / '.worktree-env').write_text(
        'export BACKEND_PORT=8189\n'
        'export FRONTEND_PORT=5234\n'
        'export WORKTREE_BRANCH=test/branch\n'
    )
    (tmp_path / '.hermes' / 'plugins').mkdir(parents=True, exist_ok=True)
    if with_venv:
        venv_bin = tmp_path / '.venv' / 'bin'
        venv_bin.mkdir(parents=True, exist_ok=True)
        pip_bin = venv_bin / 'pip'
        pip_bin.write_text('#!/bin/sh\necho fake pip\n')
        pip_bin.chmod(0o755)
        py_bin = venv_bin / 'python'
        py_bin.write_text('#!/bin/sh\necho fake python\n')
        py_bin.chmod(0o755)
        if with_plugin_bin:
            plug_bin = venv_bin / 'myah-hermes-plugin'
            plug_bin.write_text('#!/bin/sh\necho fake plugin\n')
            plug_bin.chmod(0o755)
    return tmp_path


def _make_plugin_checkout(tmp_path: Path, *, name: str = 'myah-hermes-plugin') -> Path:
    """Materialize a fake plugin checkout with a pyproject.toml."""
    pkg = tmp_path / 'plugin-checkout'
    pkg.mkdir(exist_ok=True)
    pyproject = pkg / 'pyproject.toml'
    pyproject.write_text(
        f'[project]\nname = "{name}"\nversion = "0.0.1"\n',
        encoding='utf-8',
    )
    return pkg


def _ok(stdout: str = '', stderr: str = '') -> ShellResult:
    return ShellResult(returncode=0, stdout=stdout, stderr=stderr)


def _fail(returncode: int = 1, stdout: str = '', stderr: str = 'boom') -> ShellResult:
    return ShellResult(returncode=returncode, stdout=stdout, stderr=stderr)


def _default_run_side_effect(plugin_path: Path, abs_plugin_path: Path):
    """Build a side-effect mapping the various subprocess calls install-local makes.

    Returns:
        callable(cmd, **kwargs) -> ShellResult

    Handles, in order:
      - pip uninstall -y myah-hermes-plugin       -> ok
      - pip install -e <abs_plugin_path>          -> ok
      - <plug_bin> install --help                 -> stdout includes '--dashboard-only'
      - <plug_bin> install --dashboard-only ...   -> ok
      - python -c 'import myah_hermes_plugin; ...' -> ok with editable path in stdout
    """

    def _side(cmd, **kwargs):
        cmd_str = ' '.join(cmd)
        if 'pip' in cmd[0] and 'uninstall' in cmd:
            return _ok()
        if 'pip' in cmd[0] and 'install' in cmd and '-e' in cmd:
            return _ok()
        if cmd[0].endswith('myah-hermes-plugin') and '--help' in cmd:
            return _ok(stdout='Usage: myah-hermes-plugin install [OPTIONS]\n  --dashboard-only  ...\n')
        if cmd[0].endswith('myah-hermes-plugin') and '--dashboard-only' in cmd:
            return _ok()
        if cmd[0].endswith('python') and '-c' in cmd:
            # report a __file__ underneath the editable path
            return _ok(stdout=f'{abs_plugin_path}/src/myah_hermes_plugin/__init__.py\n')
        return _ok()

    return _side


# ---------------------------------------------------------------------------
# install-local — validation
# ---------------------------------------------------------------------------


def test_install_local_validates_pyproject_present(tmp_path: Path, mocker) -> None:
    wt = _make_worktree(tmp_path)
    mocker.patch('myah.cli.dev.plugin.get_worktree_path', return_value=wt)

    empty_dir = tmp_path / 'empty'
    empty_dir.mkdir()

    result = runner.invoke(app, ['dev', 'plugin', 'install-local', str(empty_dir)])

    assert result.exit_code == 2, result.output
    assert 'pyproject' in result.output.lower()


def test_install_local_validates_pyproject_name_is_myah_hermes_plugin(tmp_path: Path, mocker) -> None:
    wt = _make_worktree(tmp_path)
    mocker.patch('myah.cli.dev.plugin.get_worktree_path', return_value=wt)
    plugin = _make_plugin_checkout(tmp_path, name='wrong-name')

    result = runner.invoke(app, ['dev', 'plugin', 'install-local', str(plugin)])

    assert result.exit_code == 2, result.output
    assert 'wrong-name' in result.output or 'myah-hermes-plugin' in result.output


def test_install_local_outside_worktree_exits_code_2(tmp_path: Path, mocker) -> None:
    mocker.patch(
        'myah.cli.dev.plugin.get_worktree_path',
        side_effect=RuntimeError('not in a worktree'),
    )
    plugin = _make_plugin_checkout(tmp_path)

    result = runner.invoke(app, ['dev', 'plugin', 'install-local', str(plugin)])

    assert result.exit_code == 2, result.output
    assert 'worktree' in result.output.lower()


# ---------------------------------------------------------------------------
# install-local — happy-path call sequence
# ---------------------------------------------------------------------------


def test_install_local_uninstalls_then_editable_installs(tmp_path: Path, mocker) -> None:
    """Verify the call sequence: pip uninstall -y, then pip install -e <abspath>."""
    wt = _make_worktree(tmp_path)
    plugin = _make_plugin_checkout(tmp_path)
    abs_plugin = plugin.resolve()

    mocker.patch('myah.cli.dev.plugin.get_worktree_path', return_value=wt)
    mocker.patch('myah.cli.dev.plugin._is_port_listening', return_value=False)
    mock_run = mocker.patch(
        'myah.cli.dev.plugin.run',
        side_effect=_default_run_side_effect(plugin, abs_plugin),
    )

    result = runner.invoke(app, ['dev', 'plugin', 'install-local', str(plugin)])

    assert result.exit_code == 0, result.output

    call_cmds = [c.args[0] for c in mock_run.call_args_list]
    # First call: pip uninstall
    assert call_cmds[0][1:] == ['uninstall', '-y', 'myah-hermes-plugin'], call_cmds[0]
    # Second call: pip install -e <abspath>
    assert call_cmds[1][1:4] == ['install', '-e', str(abs_plugin)], call_cmds[1]


def test_install_local_passes_absolute_venv_pip_path(tmp_path: Path, mocker) -> None:
    """Both pip calls must invoke <worktree>/.venv/bin/pip by absolute path."""
    wt = _make_worktree(tmp_path)
    plugin = _make_plugin_checkout(tmp_path)
    abs_plugin = plugin.resolve()

    mocker.patch('myah.cli.dev.plugin.get_worktree_path', return_value=wt)
    mocker.patch('myah.cli.dev.plugin._is_port_listening', return_value=False)
    mock_run = mocker.patch(
        'myah.cli.dev.plugin.run',
        side_effect=_default_run_side_effect(plugin, abs_plugin),
    )

    result = runner.invoke(app, ['dev', 'plugin', 'install-local', str(plugin)])

    assert result.exit_code == 0, result.output

    pip_path = str(wt / '.venv' / 'bin' / 'pip')
    pip_calls = [c.args[0] for c in mock_run.call_args_list if c.args[0][0] == pip_path]
    # Expect at least uninstall + editable install — both must use the absolute pip.
    assert len(pip_calls) >= 2, f'expected >=2 pip calls via abs path, got {pip_calls}'


def test_install_local_aborts_when_dashboard_only_flag_missing(tmp_path: Path, mocker) -> None:
    """If `myah-hermes-plugin install --help` lacks --dashboard-only, exit 2."""
    wt = _make_worktree(tmp_path)
    plugin = _make_plugin_checkout(tmp_path)
    abs_plugin = plugin.resolve()

    mocker.patch('myah.cli.dev.plugin.get_worktree_path', return_value=wt)
    mocker.patch('myah.cli.dev.plugin._is_port_listening', return_value=False)

    def _side(cmd, **kwargs):
        if 'pip' in cmd[0] and 'uninstall' in cmd:
            return _ok()
        if 'pip' in cmd[0] and 'install' in cmd and '-e' in cmd:
            return _ok()
        if cmd[0].endswith('myah-hermes-plugin') and '--help' in cmd:
            # Stripped --dashboard-only — simulates upstream removing the flag
            return _ok(stdout='Usage: myah-hermes-plugin install [OPTIONS]\n')
        return _ok()

    mocker.patch('myah.cli.dev.plugin.run', side_effect=_side)

    result = runner.invoke(app, ['dev', 'plugin', 'install-local', str(plugin)])

    assert result.exit_code == 2, result.output
    assert 'dashboard-only' in result.output


def test_install_local_re_materializes_dashboard_shim_with_hermes_home_in_env(
    tmp_path: Path, mocker
) -> None:
    """The `--dashboard-only` invocation must get HERMES_HOME=<worktree>/.hermes
    via env-merge (PATH preserved)."""
    wt = _make_worktree(tmp_path)
    plugin = _make_plugin_checkout(tmp_path)
    abs_plugin = plugin.resolve()

    mocker.patch('myah.cli.dev.plugin.get_worktree_path', return_value=wt)
    mocker.patch('myah.cli.dev.plugin._is_port_listening', return_value=False)
    mock_run = mocker.patch(
        'myah.cli.dev.plugin.run',
        side_effect=_default_run_side_effect(plugin, abs_plugin),
    )

    result = runner.invoke(app, ['dev', 'plugin', 'install-local', str(plugin)])

    assert result.exit_code == 0, result.output

    # Find the --dashboard-only call.
    shim_calls = [
        c for c in mock_run.call_args_list
        if c.args[0][0].endswith('myah-hermes-plugin') and '--dashboard-only' in c.args[0]
    ]
    assert len(shim_calls) == 1, f'expected exactly one --dashboard-only call, got {shim_calls}'
    call = shim_calls[0]
    cmd = call.args[0]
    # Plugins target path
    assert '--target' in cmd
    target_idx = cmd.index('--target')
    assert cmd[target_idx + 1] == str(wt / '.hermes' / 'plugins')

    env_kwarg = call.kwargs.get('env')
    assert env_kwarg is not None, 'env kwarg missing on --dashboard-only call'
    assert env_kwarg.get('HERMES_HOME') == str(wt / '.hermes')
    # env-merge invariant: PATH from os.environ survives.
    assert 'PATH' in env_kwarg, f'PATH stripped from env! keys: {list(env_kwarg)[:10]}'


def test_install_local_warns_when_shim_does_not_resolve_to_editable_source(
    tmp_path: Path, mocker
) -> None:
    """If `python -c import myah_hermes_plugin` reports a path NOT containing the
    editable abspath, we warn (but exit 0)."""
    wt = _make_worktree(tmp_path)
    plugin = _make_plugin_checkout(tmp_path)
    abs_plugin = plugin.resolve()

    mocker.patch('myah.cli.dev.plugin.get_worktree_path', return_value=wt)
    mocker.patch('myah.cli.dev.plugin._is_port_listening', return_value=False)

    def _side(cmd, **kwargs):
        if 'pip' in cmd[0] and 'uninstall' in cmd:
            return _ok()
        if 'pip' in cmd[0] and 'install' in cmd and '-e' in cmd:
            return _ok()
        if cmd[0].endswith('myah-hermes-plugin') and '--help' in cmd:
            return _ok(stdout='Usage: install [OPTIONS]\n  --dashboard-only  ...\n')
        if cmd[0].endswith('myah-hermes-plugin') and '--dashboard-only' in cmd:
            return _ok()
        if cmd[0].endswith('python') and '-c' in cmd:
            # Report a path that does NOT contain abs_plugin.
            return _ok(stdout='/some/other/path/myah_hermes_plugin/__init__.py\n')
        return _ok()

    # Materialize the shim file so the post-materialization check runs.
    (wt / '.hermes' / 'plugins' / 'myah-admin').mkdir(parents=True, exist_ok=True)
    (wt / '.hermes' / 'plugins' / 'myah-admin' / 'plugin_api.py').write_text('# shim\n')

    mocker.patch('myah.cli.dev.plugin.run', side_effect=_side)

    result = runner.invoke(app, ['dev', 'plugin', 'install-local', str(plugin)])

    assert result.exit_code == 0, result.output
    assert 'warning' in result.output.lower()


def test_install_local_prints_restart_hint_when_backend_running(tmp_path: Path, mocker) -> None:
    """If backend is up, the user is told to restart."""
    wt = _make_worktree(tmp_path)
    plugin = _make_plugin_checkout(tmp_path)
    abs_plugin = plugin.resolve()

    mocker.patch('myah.cli.dev.plugin.get_worktree_path', return_value=wt)
    mocker.patch(
        'myah.cli.dev.plugin._is_port_listening',
        side_effect=lambda port: port == 8189,
    )
    mocker.patch(
        'myah.cli.dev.plugin.run',
        side_effect=_default_run_side_effect(plugin, abs_plugin),
    )

    result = runner.invoke(app, ['dev', 'plugin', 'install-local', str(plugin)])

    assert result.exit_code == 0, result.output
    assert 'restart' in result.output.lower()
    assert '8189' in result.output


# ---------------------------------------------------------------------------
# install-pinned
# ---------------------------------------------------------------------------


def _write_fake_dockerfile(main_root: Path, plugin_sha: str) -> None:
    """Write a stub Dockerfile.stock with a MYAH_PLUGIN_SHA ARG line."""
    df = main_root / 'agent' / 'Dockerfile.stock'
    df.parent.mkdir(parents=True, exist_ok=True)
    df.write_text(
        'FROM python:3.11\n'
        'ARG HERMES_SHA=' + ('a' * 40) + '\n'
        f'ARG MYAH_PLUGIN_SHA={plugin_sha}\n',
        encoding='utf-8',
    )


def test_install_pinned_reads_plugin_sha_from_dockerfile(tmp_path: Path, mocker) -> None:
    """install-pinned must read MYAH_PLUGIN_SHA from agent/Dockerfile.stock."""
    wt = _make_worktree(tmp_path)
    main_root = tmp_path / 'main'
    main_root.mkdir()
    target_sha = 'b' * 40
    _write_fake_dockerfile(main_root, target_sha)

    mocker.patch('myah.cli.dev.plugin.get_worktree_path', return_value=wt)
    mocker.patch('myah.cli.dev.plugin._is_port_listening', return_value=False)
    mocker.patch('myah.cli.dev.plugin.resolve_main_repo_root', return_value=main_root)

    # Mock the pip uninstall + lib primitives.
    mock_run = mocker.patch('myah.cli.dev.plugin.run', return_value=_ok())
    mock_install = mocker.patch('myah.cli.dev.plugin.install_plugin_into_hermes')
    mock_materialize = mocker.patch('myah.cli.dev.plugin.materialize_dashboard_shim')

    result = runner.invoke(app, ['dev', 'plugin', 'install-pinned'])

    assert result.exit_code == 0, result.output
    # SHA must have been read from the fake Dockerfile and forwarded.
    mock_install.assert_called_once()
    call_args = mock_install.call_args
    assert call_args.args[0] == wt
    assert call_args.args[1] == target_sha
    mock_materialize.assert_called_once_with(wt)


def test_install_pinned_calls_primitives_in_order(tmp_path: Path, mocker) -> None:
    """install-pinned calls install_plugin_into_hermes BEFORE materialize_dashboard_shim."""
    wt = _make_worktree(tmp_path)
    main_root = tmp_path / 'main'
    main_root.mkdir()
    _write_fake_dockerfile(main_root, 'c' * 40)

    mocker.patch('myah.cli.dev.plugin.get_worktree_path', return_value=wt)
    mocker.patch('myah.cli.dev.plugin._is_port_listening', return_value=False)
    mocker.patch('myah.cli.dev.plugin.resolve_main_repo_root', return_value=main_root)
    mocker.patch('myah.cli.dev.plugin.run', return_value=_ok())

    order: list[str] = []
    mocker.patch(
        'myah.cli.dev.plugin.install_plugin_into_hermes',
        side_effect=lambda *_a, **_k: order.append('install'),
    )
    mocker.patch(
        'myah.cli.dev.plugin.materialize_dashboard_shim',
        side_effect=lambda *_a, **_k: order.append('materialize'),
    )

    result = runner.invoke(app, ['dev', 'plugin', 'install-pinned'])

    assert result.exit_code == 0, result.output
    assert order == ['install', 'materialize'], f'unexpected order: {order}'


def test_install_pinned_exits_code_2_when_dockerfile_missing(tmp_path: Path, mocker) -> None:
    wt = _make_worktree(tmp_path)
    main_root = tmp_path / 'main'
    main_root.mkdir()  # but no agent/Dockerfile.stock

    mocker.patch('myah.cli.dev.plugin.get_worktree_path', return_value=wt)
    mocker.patch('myah.cli.dev.plugin._is_port_listening', return_value=False)
    mocker.patch('myah.cli.dev.plugin.resolve_main_repo_root', return_value=main_root)

    result = runner.invoke(app, ['dev', 'plugin', 'install-pinned'])

    assert result.exit_code == 2, result.output
    assert 'Dockerfile' in result.output or 'dockerfile' in result.output.lower()


def test_install_pinned_restart_hint_fires_when_processes_running(tmp_path: Path, mocker) -> None:
    wt = _make_worktree(tmp_path)
    main_root = tmp_path / 'main'
    main_root.mkdir()
    _write_fake_dockerfile(main_root, 'd' * 40)

    mocker.patch('myah.cli.dev.plugin.get_worktree_path', return_value=wt)
    mocker.patch(
        'myah.cli.dev.plugin._is_port_listening',
        side_effect=lambda port: port == 5234,
    )
    mocker.patch('myah.cli.dev.plugin.resolve_main_repo_root', return_value=main_root)
    mocker.patch('myah.cli.dev.plugin.run', return_value=_ok())
    mocker.patch('myah.cli.dev.plugin.install_plugin_into_hermes')
    mocker.patch('myah.cli.dev.plugin.materialize_dashboard_shim')

    result = runner.invoke(app, ['dev', 'plugin', 'install-pinned'])

    assert result.exit_code == 0, result.output
    assert 'restart' in result.output.lower()
    assert '5234' in result.output


def test_install_pinned_outside_worktree_exits_code_2(mocker) -> None:
    mocker.patch(
        'myah.cli.dev.plugin.get_worktree_path',
        side_effect=RuntimeError('not in a worktree'),
    )

    result = runner.invoke(app, ['dev', 'plugin', 'install-pinned'])

    assert result.exit_code == 2, result.output
    assert 'worktree' in result.output.lower()
