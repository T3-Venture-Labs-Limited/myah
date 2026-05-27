"""Tests for ``myah env {list,set,unset}``.

Slice 5 Task 5.4 of T3-1084 (DevX + OSS CLI).

Native — no Hermes equivalent. Reads/writes two `.env` files:

  - **platform**: ``<repo-root>/platform-oss/.env``
  - **hermes**:   ``$HERMES_HOME/.env`` (default ``~/.hermes/.env``)

The ``--scope {platform,hermes}`` flag disambiguates. Sensitive values
(KEY, TOKEN, SECRET, PASSWORD) are masked by default; ``--show-secrets``
unhides.

Mock target = consumer namespace (``myah.cli.env.set_env_var``,
``myah.cli.env.unset_env_var``, ``myah.cli.env.find_repo_root``,
``myah.cli.env.parse_env_file``). Same discipline as Slices 2-4.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from myah import app
from typer.testing import CliRunner

runner = CliRunner()


# ── fixtures ───────────────────────────────────────────────────────────


@pytest.fixture
def fake_paths(mocker, tmp_path: Path) -> tuple[Path, Path]:
    """Pretend we're inside a Myah clone with a real Hermes home.

    Returns (platform_env_path, hermes_env_path).
    """
    repo_root = tmp_path / 'repo'
    (repo_root / 'platform-oss').mkdir(parents=True)
    platform_env = repo_root / 'platform-oss' / '.env'

    hermes_home = tmp_path / 'hermes'
    hermes_home.mkdir()
    hermes_env = hermes_home / '.env'

    mocker.patch('myah.cli.env.find_repo_root', return_value=repo_root)
    mocker.patch.dict('os.environ', {'HERMES_HOME': str(hermes_home)}, clear=False)
    return platform_env, hermes_env


# ── list ───────────────────────────────────────────────────────────────


def test_list_both_scopes_groups_output(fake_paths: tuple[Path, Path]) -> None:
    """`myah env list` (no scope) prints both platform and hermes entries grouped."""
    platform_env, hermes_env = fake_paths
    platform_env.write_text('FOO=platform-val\n', encoding='utf-8')
    hermes_env.write_text('BAR=hermes-val\n', encoding='utf-8')

    result = runner.invoke(app, ['env', 'list', '--show-secrets'])

    assert result.exit_code == 0, f'stdout: {result.stdout}\nexc: {result.exception}'
    assert 'FOO' in result.stdout
    assert 'platform-val' in result.stdout
    assert 'BAR' in result.stdout
    assert 'hermes-val' in result.stdout
    # Grouped: a "platform" header appears before a "hermes" header.
    assert result.stdout.lower().find('platform') < result.stdout.lower().find('hermes')


def test_list_scope_platform_shows_only_platform(fake_paths: tuple[Path, Path]) -> None:
    """`myah env list --scope platform` excludes hermes entries."""
    platform_env, hermes_env = fake_paths
    platform_env.write_text('FOO=platform-val\n', encoding='utf-8')
    hermes_env.write_text('HERMES_ONLY=hermes-val\n', encoding='utf-8')

    result = runner.invoke(app, ['env', 'list', '--scope', 'platform', '--show-secrets'])

    assert result.exit_code == 0
    assert 'FOO' in result.stdout
    assert 'platform-val' in result.stdout
    assert 'HERMES_ONLY' not in result.stdout


def test_list_scope_hermes_shows_only_hermes(fake_paths: tuple[Path, Path]) -> None:
    """`myah env list --scope hermes` excludes platform entries."""
    platform_env, hermes_env = fake_paths
    platform_env.write_text('PLATFORM_ONLY=platform-val\n', encoding='utf-8')
    hermes_env.write_text('FOO=hermes-val\n', encoding='utf-8')

    result = runner.invoke(app, ['env', 'list', '--scope', 'hermes', '--show-secrets'])

    assert result.exit_code == 0
    assert 'FOO' in result.stdout
    assert 'hermes-val' in result.stdout
    assert 'PLATFORM_ONLY' not in result.stdout


def test_list_masks_sensitive_values_by_default(fake_paths: tuple[Path, Path]) -> None:
    """Values for *_KEY, *_TOKEN, *_SECRET, *_PASSWORD are masked."""
    platform_env, hermes_env = fake_paths
    platform_env.write_text(
        'OPENROUTER_API_KEY=sk-real-key\n'
        'MY_TOKEN=abc123\n'
        'DATABASE_PASSWORD=hunter2\n'
        'SOME_SECRET=topsecret\n'
        'PUBLIC_VALUE=visible\n',
        encoding='utf-8',
    )
    hermes_env.write_text('', encoding='utf-8')

    result = runner.invoke(app, ['env', 'list', '--scope', 'platform'])

    assert result.exit_code == 0
    # Names are visible.
    assert 'OPENROUTER_API_KEY' in result.stdout
    assert 'MY_TOKEN' in result.stdout
    assert 'DATABASE_PASSWORD' in result.stdout
    assert 'SOME_SECRET' in result.stdout
    # Values are masked.
    assert 'sk-real-key' not in result.stdout
    assert 'abc123' not in result.stdout
    assert 'hunter2' not in result.stdout
    assert 'topsecret' not in result.stdout
    # Public value passes through.
    assert 'visible' in result.stdout
    # Hint surfaces.
    assert '--show-secrets' in result.stdout


def test_list_show_secrets_reveals_values(fake_paths: tuple[Path, Path]) -> None:
    """`--show-secrets` prints the raw values."""
    platform_env, hermes_env = fake_paths
    platform_env.write_text('OPENROUTER_API_KEY=sk-real-key\n', encoding='utf-8')
    hermes_env.write_text('', encoding='utf-8')

    result = runner.invoke(app, ['env', 'list', '--scope', 'platform', '--show-secrets'])

    assert result.exit_code == 0
    assert 'sk-real-key' in result.stdout


def test_list_handles_missing_platform_env_gracefully(fake_paths: tuple[Path, Path]) -> None:
    """No platform .env file → empty platform section, no crash."""
    platform_env, hermes_env = fake_paths
    assert not platform_env.exists()
    hermes_env.write_text('BAR=hermes-val\n', encoding='utf-8')

    result = runner.invoke(app, ['env', 'list', '--show-secrets'])

    assert result.exit_code == 0
    assert 'BAR' in result.stdout


def test_list_handles_missing_hermes_env_gracefully(fake_paths: tuple[Path, Path]) -> None:
    """No Hermes .env file → empty hermes section, no crash."""
    platform_env, hermes_env = fake_paths
    platform_env.write_text('FOO=platform-val\n', encoding='utf-8')
    assert not hermes_env.exists()

    result = runner.invoke(app, ['env', 'list', '--show-secrets'])

    assert result.exit_code == 0
    assert 'FOO' in result.stdout


def test_list_scope_platform_exits_2_when_outside_clone(mocker) -> None:
    """`list --scope platform` fails fast outside a Myah clone."""
    mocker.patch(
        'myah.cli.env.find_repo_root',
        side_effect=RuntimeError('Could not locate repo root.'),
    )

    result = runner.invoke(app, ['env', 'list', '--scope', 'platform'])

    assert result.exit_code == 2, f'wanted 2, got {result.exit_code}; stdout: {result.stdout}'
    assert 'Not inside a Myah clone' in result.stdout


def test_list_scope_hermes_works_outside_clone(mocker, tmp_path: Path) -> None:
    """`list --scope hermes` does NOT need a Myah clone — only Hermes home."""
    mocker.patch(
        'myah.cli.env.find_repo_root',
        side_effect=RuntimeError('Could not locate repo root.'),
    )
    hermes_home = tmp_path / 'hermes'
    hermes_home.mkdir()
    (hermes_home / '.env').write_text('FOO=bar\n', encoding='utf-8')
    mocker.patch.dict('os.environ', {'HERMES_HOME': str(hermes_home)}, clear=False)

    result = runner.invoke(app, ['env', 'list', '--scope', 'hermes', '--show-secrets'])

    assert result.exit_code == 0
    assert 'FOO' in result.stdout


# ── set ────────────────────────────────────────────────────────────────


def test_set_platform_calls_set_env_var(fake_paths: tuple[Path, Path], mocker) -> None:
    """`set --scope platform KEY VAL` invokes set_env_var on the platform .env."""
    platform_env, _ = fake_paths
    set_mock = mocker.patch('myah.cli.env.set_env_var')

    result = runner.invoke(app, ['env', 'set', '--scope', 'platform', 'FOO', 'bar'])

    assert result.exit_code == 0, f'stdout: {result.stdout}\nexc: {result.exception}'
    set_mock.assert_called_once_with(platform_env, 'FOO', 'bar')


def test_set_hermes_calls_set_env_var(fake_paths: tuple[Path, Path], mocker) -> None:
    """`set --scope hermes KEY VAL` invokes set_env_var on the Hermes .env."""
    _, hermes_env = fake_paths
    set_mock = mocker.patch('myah.cli.env.set_env_var')

    result = runner.invoke(app, ['env', 'set', '--scope', 'hermes', 'FOO', 'bar'])

    assert result.exit_code == 0, f'stdout: {result.stdout}\nexc: {result.exception}'
    set_mock.assert_called_once_with(hermes_env, 'FOO', 'bar')


def test_set_without_scope_exits_2(fake_paths: tuple[Path, Path]) -> None:
    """`set KEY VAL` without --scope errors out."""
    result = runner.invoke(app, ['env', 'set', 'FOO', 'bar'])

    assert result.exit_code == 2, f'wanted 2, got {result.exit_code}; stdout: {result.stdout}'


def test_set_invalid_scope_exits_2(fake_paths: tuple[Path, Path]) -> None:
    """Bad scope value (e.g. `--scope frontend`) → exit 2."""
    result = runner.invoke(app, ['env', 'set', '--scope', 'frontend', 'FOO', 'bar'])

    assert result.exit_code == 2, f'wanted 2, got {result.exit_code}; stdout: {result.stdout}'


def test_set_platform_exits_2_when_outside_clone(mocker) -> None:
    """`set --scope platform` outside a Myah clone → exit 2."""
    mocker.patch(
        'myah.cli.env.find_repo_root',
        side_effect=RuntimeError('Could not locate repo root.'),
    )
    set_mock = mocker.patch('myah.cli.env.set_env_var')

    result = runner.invoke(app, ['env', 'set', '--scope', 'platform', 'FOO', 'bar'])

    assert result.exit_code == 2
    set_mock.assert_not_called()


# ── unset ──────────────────────────────────────────────────────────────


def test_unset_platform_calls_unset_env_var(fake_paths: tuple[Path, Path], mocker) -> None:
    """`unset --scope platform KEY` invokes unset_env_var."""
    platform_env, _ = fake_paths
    unset_mock = mocker.patch('myah.cli.env.unset_env_var', return_value=True)

    result = runner.invoke(app, ['env', 'unset', '--scope', 'platform', 'FOO'])

    assert result.exit_code == 0, f'stdout: {result.stdout}\nexc: {result.exception}'
    unset_mock.assert_called_once_with(platform_env, 'FOO')


def test_unset_reports_not_found_when_key_missing(fake_paths: tuple[Path, Path], mocker) -> None:
    """`unset_env_var` returning False → friendly "not found" message, exit 0."""
    mocker.patch('myah.cli.env.unset_env_var', return_value=False)

    result = runner.invoke(app, ['env', 'unset', '--scope', 'platform', 'MISSING'])

    assert result.exit_code == 0
    assert 'not found' in result.stdout.lower()


def test_unset_reports_success_when_removed(fake_paths: tuple[Path, Path], mocker) -> None:
    """`unset_env_var` returning True → success message."""
    mocker.patch('myah.cli.env.unset_env_var', return_value=True)

    result = runner.invoke(app, ['env', 'unset', '--scope', 'platform', 'FOO'])

    assert result.exit_code == 0
    # Some affirmative cue — "removed" / "unset" / a checkmark.
    assert 'removed' in result.stdout.lower() or 'unset' in result.stdout.lower()


# ── help + top-level ──────────────────────────────────────────────────


def test_env_help_lists_subcommands() -> None:
    """`myah env --help` enumerates list/set/unset."""
    result = runner.invoke(app, ['env', '--help'])

    assert result.exit_code == 0
    assert 'list' in result.stdout
    assert 'set' in result.stdout
    assert 'unset' in result.stdout


def test_top_level_help_lists_env_group() -> None:
    """`myah --help` surfaces the `env` subgroup for OSS users."""
    result = runner.invoke(app, ['--help'])

    assert result.exit_code == 0
    assert 'env' in result.stdout


# ── cold-start sentinel ────────────────────────────────────────────────


def test_env_module_does_not_import_heavy_libs_at_top_level() -> None:
    """Rich / yaml / time / socket must stay out of the module top so
    `myah --help` cold-start holds under 200ms.
    """
    from myah.cli import env as mod

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
        assert offender not in head, f'cli/env.py top-level imports {offender!r}'
