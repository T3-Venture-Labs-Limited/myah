"""Tests for the migrated serve command (now accepts --reload).

The old top-level `myah dev` command is removed; its uvicorn-with-reload
behavior moves into `myah serve --reload`. This frees the `dev` name
for the new developer-namespace subcommand group.
"""

from typer.testing import CliRunner

from myah import app


runner = CliRunner()


def test_serve_help_documents_reload_flag() -> None:
    """`myah serve --help` mentions the new --reload flag."""
    result = runner.invoke(app, ['serve', '--help'])
    assert result.exit_code == 0
    assert '--reload' in result.stdout


def test_dev_top_level_command_removed() -> None:
    """`myah dev` (no subcommand) no longer matches the old top-level dev.

    After this slice, `dev` is a subcommand group (with hidden=True).
    Invoking `myah dev` without a subcommand shows the group's help,
    NOT the old uvicorn-reload launcher.

    The new `myah dev backend` subcommand DOES start uvicorn, but its help
    description naturally mentions that. The contract preserved here is
    that the OLD top-level `myah dev --host ... --port ...` launcher
    surface is gone — verified by absence of those flags on the group.
    """
    result = runner.invoke(app, ['dev', '--help'])
    assert result.exit_code == 0
    # The old top-level dev launcher's flags must not appear on the group itself.
    assert '--host' not in result.stdout  # the old dev had --host
    assert '--port' not in result.stdout  # the old dev had --port


def test_dev_group_is_hidden_from_top_level_help() -> None:
    """`myah --help` must NOT list `dev` (hidden=True in register_dev_group).

    OSS users shouldn't see the developer-only namespace in their help text.
    Devs discover it via `myah dev --help` (which still works).
    """
    result = runner.invoke(app, ['--help'])
    assert result.exit_code == 0
    # The `dev` command/group should not appear in the rendered top-level commands list
    # Typer/Click renders command names left-aligned in the Commands section.
    # We look for the visible-row pattern (whitespace-bounded) rather than substring
    # to avoid false matches on words like 'developer'.
    import re
    visible_commands = re.findall(r'^\s+(\w+)\s', result.stdout, re.MULTILINE)
    assert 'dev' not in visible_commands, (
        f'dev group leaked into top-level help. Commands visible: {visible_commands}. '
        f'Full output:\n{result.stdout}'
    )


def test_serve_reload_passes_reload_to_uvicorn() -> None:
    """`myah serve --reload` calls uvicorn.run with reload=True.

    Implementation note: the existing `serve` function does `import myah.main`
    inside its body (not at module top). That `import` re-binds the attribute,
    so a module-level `mocker.patch('myah.main')` does NOT prevent the real
    FastAPI app from being imported (which pulls in DB engine, Sentry init, etc.).

    The reliable mock target is `builtins.__import__` with a selective filter,
    or — preferred — restructure `serve` to extract the uvicorn-args computation
    into a pure helper and test the helper.

    This test uses the helper pattern: assume `serve` is refactored to delegate
    its uvicorn-args building to a `_build_uvicorn_kwargs(host, port, reload)`
    function. Test the helper directly.
    """
    from myah import _build_uvicorn_kwargs

    kwargs = _build_uvicorn_kwargs(host='0.0.0.0', port=8080, reload=True)

    assert kwargs.get('reload') is True
    # Workers and reload are mutually exclusive — assert workers=1 when reload=True
    assert kwargs.get('workers') == 1


def test_serve_without_reload_does_not_reload(monkeypatch) -> None:
    """`_build_uvicorn_kwargs` with reload=False produces production-shape args.

    In production, workers comes from the UVICORN_WORKERS env var (default '1'
    per env.py). To verify the multi-worker code path, set the env var > 1.
    """
    from myah import _build_uvicorn_kwargs

    monkeypatch.setenv('UVICORN_WORKERS', '4')
    kwargs = _build_uvicorn_kwargs(host='0.0.0.0', port=8080, reload=False)

    assert kwargs.get('reload') in (None, False)
    # workers came from the env var, NOT from the reload=True override
    assert kwargs.get('workers') == 4


def test_build_uvicorn_kwargs_falls_back_to_1_on_non_numeric_workers_env(monkeypatch) -> None:
    """Non-numeric UVICORN_WORKERS (e.g. 'auto') must not crash the helper.

    `_build_uvicorn_kwargs` defensively falls back to workers=1 instead of
    raising ValueError on `int('auto')`. This test locks the defense in
    so a future refactor (e.g. switching to try/except int()) doesn't
    silently flip behavior on values like '-1' or empty string.
    """
    from myah import _build_uvicorn_kwargs

    monkeypatch.setenv('UVICORN_WORKERS', 'auto')
    kwargs = _build_uvicorn_kwargs(host='0.0.0.0', port=8080, reload=False)
    assert kwargs['workers'] == 1
