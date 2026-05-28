"""Regression for PR #16 post-merge laptop test, Bug 5: `myah --version`."""

from __future__ import annotations

from typer.testing import CliRunner

from myah import app


runner = CliRunner()


def test_dash_dash_version_at_root_prints_version() -> None:
    """`myah --version` must print the package version and exit 0.
    Previously rejected with "No such option: --version" because the
    callback was only wired into the `main` subcommand.
    """
    result = runner.invoke(app, ['--version'])
    assert result.exit_code == 0, result.stdout
    assert 'myah' in result.stdout.lower()
    # Version string must contain a digit (sanity — not asserting exact value
    # since `myah.env.VERSION` evolves).
    assert any(ch.isdigit() for ch in result.stdout), (
        f'expected a version number in output; got: {result.stdout!r}'
    )


def test_dash_v_alias_also_works() -> None:
    """Short alias `-v` (lowercase) should mirror --version."""
    result = runner.invoke(app, ['-v'])
    assert result.exit_code == 0, result.stdout
    assert 'myah' in result.stdout.lower()


def test_dash_h_is_an_alias_for_dash_dash_help() -> None:
    """POSIX-conventional `-h` short-form for --help at the root."""
    result_long = runner.invoke(app, ['--help'])
    result_short = runner.invoke(app, ['-h'])
    assert result_short.exit_code == 0, result_short.stdout
    # The two outputs should be substantively the same (Rich formatting
    # may differ in terminal-width detection; assert key tokens overlap).
    for token in ('Usage:', 'Commands', 'install', 'doctor'):
        assert token in result_short.stdout, (
            f'expected `{token}` in `-h` output; got: {result_short.stdout!r}'
        )
