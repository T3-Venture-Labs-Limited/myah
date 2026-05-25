"""Tests for the migrated serve command (now accepts --reload).

The old top-level `myah dev` command is removed; its uvicorn-with-reload
behavior moves into `myah serve --reload`. Production container's
`CMD ["myah", "serve"]` is unaffected.

This file mirrors the test surface from the internal monorepo's
Slice 1 of the DevX + OSS CLI initiative
(docs/superpowers/specs/2026-05-22-devx-oss-cli-design.md in
myah-hosted). It pins the migration so a future regression that
re-adds `myah dev` or drops the helper would fail CI.
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
    """`myah dev` no longer matches the old top-level uvicorn command.

    After the migration `dev` is not registered at all on the public repo
    (the hidden `dev` subcommand group lands via the next batch-sync from
    the internal monorepo when the rest of the CLI infrastructure follows).
    """
    result = runner.invoke(app, ['dev', '--help'])
    # The old top-level `dev` had --host / --port flags. If they appear, the
    # old command is still wired.
    assert '--host' not in result.stdout
    assert '--port' not in result.stdout


def test_serve_reload_passes_reload_to_uvicorn() -> None:
    """`_build_uvicorn_kwargs` with reload=True produces hot-reload kwargs.

    The helper is pure (no module-import side effects); test it directly
    instead of mocking the `serve` command body.
    """
    from myah import _build_uvicorn_kwargs

    kwargs = _build_uvicorn_kwargs(host='0.0.0.0', port=8080, reload=True)

    assert kwargs.get('reload') is True
    # workers and reload are mutually exclusive — assert workers=1 when reload=True
    assert kwargs.get('workers') == 1


def test_serve_without_reload_uses_env_workers(monkeypatch) -> None:
    """`_build_uvicorn_kwargs` reads UVICORN_WORKERS from env when reload=False.

    Verifies the env-var passthrough to uvicorn.run kwargs in production mode.
    """
    from myah import _build_uvicorn_kwargs

    monkeypatch.setenv('UVICORN_WORKERS', '4')
    kwargs = _build_uvicorn_kwargs(host='0.0.0.0', port=8080, reload=False)

    assert kwargs.get('reload') is False
    assert kwargs.get('workers') == 4


def test_build_uvicorn_kwargs_falls_back_to_1_on_non_numeric(monkeypatch) -> None:
    """Non-numeric UVICORN_WORKERS (e.g. 'auto') must not crash the helper."""
    from myah import _build_uvicorn_kwargs

    monkeypatch.setenv('UVICORN_WORKERS', 'auto')
    kwargs = _build_uvicorn_kwargs(host='0.0.0.0', port=8080, reload=False)

    assert kwargs['workers'] == 1
