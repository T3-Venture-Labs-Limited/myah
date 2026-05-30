"""`myah plugins {list,install,update,remove}` — wrap hermes plugins with SHA-drift warning.

Slice 5 Task 5.2 of T3-1084 (DevX + OSS CLI).

Pure pass-through to ``<hermes-venv>/bin/hermes plugins <verb>`` with
one Myah-specific addition: after every successful invocation (or
before, for `list`), if the ``myah-hermes-plugin``'s installed git SHA
— recorded in PEP 610 ``direct_url.json`` — differs from the SHA
pinned in ``agent/Dockerfile.stock:183``, emit a yellow warning.

The warning is informational, never an error: a divergence usually
means the user ran ``hermes plugins update myah`` (or upgraded ahead
of the Dockerfile bump); the chat platform may still work fine.
Loud-but-non-blocking matches the gotcha-doc pattern for cross-version
drift.

If we can't determine either SHA (no Dockerfile in CWD ancestors, no
direct_url.json), the warning is silently skipped. Caller-friendly
defaults — see ``detect_installed_plugin_sha`` for the None contract.

Spec classification (line 99 of
``docs/superpowers/specs/2026-05-22-devx-oss-cli-design.md``):
"Wrap-and-validate: pass through; post-action emit a Myah-specific
SHA-pin-awareness warning if the installed version drifts from
``agent/Dockerfile.stock:183``'s pin."

Cold-start budget: Rich is lazy-imported inside the warning helper +
the result-emitter so ``myah --help`` stays under 200ms.

# The plugin lives at one SHA; the Dockerfile pins another.
# We name the drift without forbidding it. Names know their place.
"""

from __future__ import annotations

from pathlib import Path

import typer

# Module-level aliases so tests patch at the consumer namespace
# (`myah.cli.plugins.run`, `myah.cli.plugins.find_repo_root`,
# `myah.cli.plugins.detect_installed_plugin_sha`, etc.).
from myah.lib.cli.hermes_install import (
    detect_hermes_venv,
    detect_installed_plugin_sha,
    read_pinned_plugin_sha_from_dockerfile,
    resolve_hermes_binary_or_exit,
)
from myah.lib.cli.output import emit_result_or_exit
from myah.lib.cli.repo import find_repo_root
from myah.lib.cli.shell import run

MYAH_PLUGIN_NAME = 'myah'

plugins_app = typer.Typer(
    name='plugins',
    help='Manage Hermes plugins (wraps `hermes plugins`).',
    no_args_is_help=True,
)


# Layout sentinel for the Dockerfile.stock plugin-SHA pin. Drift check
# reads this path inside the repo root resolved by `find_repo_root`.
_DOCKERFILE_REL = Path('agent') / 'Dockerfile.stock'


def _check_and_warn_drift() -> None:
    """Emit a yellow warning if installed plugin SHA differs from Dockerfile pin.

    Silent on every can't-determine case:
      - No repo root in CWD ancestry (user running from outside a clone)
      - Dockerfile present but plugin not installed (or no direct_url.json)
      - Either SHA unparseable

    Each silent-skip path logs at DEBUG so production support can grep
    for "drift check skipped" without spamming the user's terminal.
    Stdlib logging — keeps the module-top import cheap (loguru is ~70ms
    cold; logging is microseconds).

    Cheap: one Dockerfile read + one direct_url.json read. No hermes
    subprocess invocation. Caller invokes either before (`list`) or after
    (`install/update/remove`) the hermes call — see verb implementations.
    """
    import logging

    log = logging.getLogger(__name__)

    # Resolve pinned SHA (Dockerfile.stock:183). Any failure — no repo
    # root, no Dockerfile, malformed SHA line — silently skips the
    # warning. Outside-a-clone is a legitimate state (PyPI install of
    # `myah` with no monorepo checkout); versions.env-only layouts
    # (public OSS mirror) have no Dockerfile to drift against either.
    try:
        repo_root = find_repo_root()
    except RuntimeError:
        log.debug('drift check skipped: could not find repo root from cwd')
        return
    try:
        dockerfile = repo_root / _DOCKERFILE_REL
        pinned = read_pinned_plugin_sha_from_dockerfile(dockerfile)
    except (RuntimeError, OSError):
        log.debug('drift check skipped: could not read pinned SHA from Dockerfile.stock')
        return

    # Resolve installed SHA. Returns None on any can't-determine path.
    try:
        venv = detect_hermes_venv()
    except RuntimeError:
        log.debug('drift check skipped: could not locate hermes-agent venv')
        return
    installed = detect_installed_plugin_sha(venv)
    if installed is None:
        log.debug(f'drift check skipped: could not determine installed plugin SHA for venv {venv}')
        return

    if installed == pinned:
        return

    # Drift! Loud-but-non-blocking yellow warning. Truncate SHAs to 7
    # chars for human-readable diff (git-short-sha convention). The dim
    # resolution-hint line keeps the noise floor low while pointing the
    # operator at the two ways out (forward-bump Dockerfile, or revert
    # the venv to match the pin).
    from rich.console import Console

    Console().print(
        '[yellow]⚠ myah-hermes-plugin SHA drift detected[/]\n'
        f'  installed: {installed[:7]}\n'
        f'  pinned:    {pinned[:7]}  ([dim]agent/Dockerfile.stock:183[/])\n'
        '  [dim]This is informational. The chat platform may still work; '
        'a typical drift means the user ran `hermes plugins update myah` '
        'ahead of the Dockerfile bump.[/]\n'
        f'  [dim]To resolve: bump Dockerfile.stock:183 to {installed[:7]} '
        'if the new version is desired, or `hermes plugins update myah` '
        'to realign the venv to the pinned SHA.[/]'
    )


# ---------------------------------------------------------------------------
# Subcommands
# ---------------------------------------------------------------------------


@plugins_app.command('list')
def plugins_list() -> None:
    """List installed Hermes plugins (wraps `hermes plugins list`).

    For `list` (read-only), the drift check runs BEFORE the hermes
    invocation so the warning appears above the listing — first thing
    the user reads.
    """
    hermes_bin = resolve_hermes_binary_or_exit(command_hint='for `myah plugins list`')
    _check_and_warn_drift()
    emit_result_or_exit(run([str(hermes_bin), 'plugins', 'list']))


@plugins_app.command('install')
def plugins_install(
    identifier: str = typer.Argument(..., help='Plugin to install (e.g. `T3-VL/myah-hermes-plugin`).'),
    force: bool = typer.Option(False, '--force', help='Force reinstall over existing plugin.'),
    enable: bool | None = typer.Option(
        None,
        '--enable/--no-enable',
        help='Enable (or disable) the plugin after install. Defaults to hermes default.',
    ),
) -> None:
    """Install a Hermes plugin (wraps `hermes plugins install`).

    For state-changing verbs, drift check runs AFTER the hermes call
    so install output streams first. If hermes returns non-zero, the
    drift check is skipped — the install state is unknown.

    `--enable`/`--no-enable` is a tri-state: None (the default) means
    "don't pass either flag — let hermes apply its own default".
    Forwarding the default unconditionally would be noisy and would
    silently override a future hermes-side change to the default.
    """
    hermes_bin = resolve_hermes_binary_or_exit(command_hint='for `myah plugins install`')

    argv: list[str] = [str(hermes_bin), 'plugins', 'install', identifier]
    if force:
        argv.append('--force')
    if enable is True:
        argv.append('--enable')
    elif enable is False:
        argv.append('--no-enable')

    result = run(argv)
    emit_result_or_exit(result)
    # emit_result_or_exit raises on non-zero — we only reach here on success.
    _check_and_warn_drift()


@plugins_app.command('update')
def plugins_update(
    identifier: str = typer.Argument(
        MYAH_PLUGIN_NAME,
        help='Plugin to update. Defaults to the Myah Hermes plugin.',
    ),
) -> None:
    """Update an installed Hermes plugin (wraps `hermes plugins update`)."""
    hermes_bin = resolve_hermes_binary_or_exit(command_hint='for `myah plugins update`')
    result = run([str(hermes_bin), 'plugins', 'update', identifier])
    emit_result_or_exit(result)
    _check_and_warn_drift()


@plugins_app.command('remove')
def plugins_remove(
    identifier: str = typer.Argument(..., help='Plugin to remove.'),
) -> None:
    """Remove an installed Hermes plugin (wraps `hermes plugins remove`)."""
    hermes_bin = resolve_hermes_binary_or_exit(command_hint='for `myah plugins remove`')
    result = run([str(hermes_bin), 'plugins', 'remove', identifier])
    emit_result_or_exit(result)
    _check_and_warn_drift()


__all__ = ['plugins_app']
