"""Myah CLI command registration.

This module exposes a single `register_commands(app)` function that the
top-level `myah/__init__.py` calls to wire all CLI commands into the
existing Typer app. Commands are split into modules (one per top-level
verb or subcommand group) for testability.

The `dev` subcommand group is registered with hidden=True so it does
not appear in `myah --help` for OSS users. Devs discover it via
`myah dev --help` (which still works) or via AGENTS.md.
"""

from __future__ import annotations

import typer


# CLI submodules MUST NOT do `from myah import app` — receive the Typer
# instance as a parameter via register_commands(app) instead. Importing
# `myah` from inside myah.cli.* would re-enter myah/__init__.py while it
# is still initializing (the bottom-of-module register_commands call has
# not yet returned), causing a half-initialized-module circular import.
def register_commands(app: typer.Typer) -> None:
    """Register all CLI commands against the given Typer app.

    Call exactly once from myah/__init__.py at module bottom. Subsequent
    calls would add duplicate commands (Typer does not dedupe by name).
    """
    # Subcommand groups
    _register_dev_group(app)

    # Top-level commands will be added by subsequent slice tasks
    # (slice 1 task 1.5 adds doctor; task 1.6 adds status; etc.)
    _register_doctor(app)
    _register_status(app)
    _register_install(app)
    _register_agent(app)
    _register_plugins(app)
    _register_platform(app)
    _register_env(app)
    _register_logs(app)
    _register_upgrade(app)
    _register_uninstall(app)
    _register_quickstart(app)


def _register_dev_group(app: typer.Typer) -> None:
    """Register the `myah dev *` namespace as a hidden subcommand group."""
    from myah.cli.dev import dev_app

    app.add_typer(
        dev_app,
        name='dev',
        hidden=True,  # Not shown in `myah --help`; visible via `myah dev --help`
        help='Developer-only commands (worktree, mode, plugin local-dev, isolated Hermes)',
    )


def _register_doctor(app: typer.Typer) -> None:
    """Register `myah doctor` (added in task 1.5).

    Lazy-load pattern (independent reviewer H4 finding): the import of
    `myah.cli.doctor` would pull in `rich.Console` + `rich.Table` at
    register-time (which runs on every `myah --help` invocation). With
    ~15 commands, register-time Rich imports blow the < 200 ms cold-start
    target. The import moves inside the wrapped command body so it runs
    only when `myah doctor` is actually invoked.
    """

    @app.command(name='doctor', help='Diagnose stack health')
    def doctor_entry(
        fix: bool = typer.Option(
            False, '--fix',
            help=(
                'Opt-in: attempt to fix actionable findings (plugin not '
                'enabled, gateway/dashboard ports unbound). Re-runs the '
                'checks after each fix.'
            ),
        ),
    ) -> None:
        from myah.cli.doctor import doctor_command  # lazy

        doctor_command(fix=fix)


def _register_status(app: typer.Typer) -> None:
    """Register `myah status` (added in task 1.6). Lazy-loaded per H4."""

    @app.command(name='status', help='Show what is running, on which ports')
    def status_entry() -> None:
        from myah.cli.status import status_command  # lazy

        status_command()


def _register_install(app: typer.Typer) -> None:
    """Register `myah install` (Slice 4 sub-phase 4f). Lazy-loaded per H4.

    `myah.cli.install` pulls in Rich (via the post-install verification
    table) and the full set of lib helpers (token_gen, hermes_install,
    config_merge, service_units, doctor_checks). Loading lazily keeps
    `myah --help` cold-start under the 200ms budget.

    The entry-point wrapper duplicates the flag declarations so Typer's
    --help introspection sees the parameters without having to import
    the install module at register-time. The lazy import lives inside
    the wrapper body.
    """

    @app.command(
        name='install',
        help='Install the Myah OSS stack: tokens, Hermes plugin, config, services, doctor',
    )
    def install_entry(
        non_interactive: bool = typer.Option(
            False,
            '--non-interactive',
            help='Skip all prompts. Required for CI. Fails fast if interactive-only values are missing.',
        ),
        service: str | None = typer.Option(
            None,
            '--service',
            help='Service framework: systemd|launchd|none. Defaults to platform-appropriate.',
        ),
        openrouter_key: str | None = typer.Option(
            None,
            '--openrouter-key',
            help='Pre-set OPENROUTER_API_KEY in the Hermes .env. Avoids interactive prompt.',
        ),
        rotate: bool = typer.Option(
            False,
            '--rotate',
            help='Rotate all generated tokens/keys (bearer, web session, OAuth, JWT secret).',
        ),
        keep_data: bool = typer.Option(
            False,
            '--keep-data',
            help='Documented intent flag — preserves existing tokens/keys (default behavior; '
            'opposite of --rotate). Mutually exclusive with --rotate.',
        ),
        skip_start: bool = typer.Option(
            False,
            '--skip-start',
            help=(
                'After laying down service units, skip the automatic '
                '`agent up` (launchctl kickstart / systemctl start). '
                "Use for CI or when you'll start services manually."
            ),
        ),
    ) -> None:
        from myah.cli.install import install_command  # lazy

        install_command(
            non_interactive=non_interactive,
            service=service,
            openrouter_key=openrouter_key,
            rotate=rotate,
            keep_data=keep_data,
            skip_start=skip_start,
        )


def _register_agent(app: typer.Typer) -> None:
    """Register `myah agent {up,down,restart,config {show,edit,validate}}` (Slice 5 task 5.1).

    The `agent` module top-level is intentionally kept light (stdlib only
    + a thin `from myah.lib.cli.shell import run` / `from
    myah.lib.cli.hermes_install import detect_hermes_venv`). Both lib
    modules are themselves stdlib-only at top-level, so `add_typer`
    here is cheap enough to stay inside the < 200ms `myah --help`
    cold-start budget without the lazy-shim pattern that `doctor` /
    `status` / `install` use.
    """
    from myah.cli.agent import agent_app

    app.add_typer(agent_app, name='agent')


def _register_plugins(app: typer.Typer) -> None:
    """Register `myah plugins {list,install,update,remove}` (Slice 5 task 5.2).

    Top-level command surface (not under `dev`). Pass-through wrappers
    of `hermes plugins <verb>` with a Myah-specific SHA-drift warning
    derived from PEP 610 direct_url.json. The `plugins` module top is
    stdlib-only + thin lib imports (mirrors `agent`), so `add_typer`
    here stays inside the < 200ms `myah --help` cold-start budget
    without the lazy-shim wrapper that `doctor`/`status`/`install` use.
    """
    from myah.cli.plugins import plugins_app

    app.add_typer(plugins_app, name='plugins')
    app.add_typer(plugins_app, name='plugin', hidden=True)


def _register_platform(app: typer.Typer) -> None:
    """Register `myah platform {up,down,restart}` (Slice 5 task 5.3).

    Native — no Hermes equivalent. Wraps `docker compose` for the
    FastAPI platform container. Top-level command surface (not under
    `dev`). The `platform_` module top is stdlib-only + thin lib
    imports (mirrors `agent` and `plugins`), so `add_typer` here stays
    inside the < 200ms `myah --help` cold-start budget. Module is
    named `platform_` (trailing underscore) to avoid shadowing the
    stdlib `platform` module.
    """
    from myah.cli.platform_ import platform_app

    app.add_typer(platform_app, name='platform')


def _register_env(app: typer.Typer) -> None:
    """Register `myah env {list,set,unset}` (Slice 5 task 5.4).

    Native — no Hermes equivalent. Manages two .env files (the platform
    container's at ``<repo-root>/platform-oss/.env`` and Hermes' at
    ``$HERMES_HOME/.env``). The ``env`` module top is stdlib + typer
    only (Rich lives lazily inside command bodies), so `add_typer` here
    stays inside the < 200ms `myah --help` cold-start budget without
    the lazy-shim wrapper that `doctor`/`status`/`install` use.
    """
    from myah.cli.env import env_app

    app.add_typer(env_app, name='env')


def _register_logs(app: typer.Typer) -> None:
    """Register `myah logs [LOG_NAME]` (Slice 5 task 5.4).

    Thin wrapper of `hermes logs` with one extra component name:
    ``platform`` resolves to ``docker compose logs platform`` against
    the repo-root ``docker-compose.yml``. All other names forward
    verbatim to the user's system Hermes binary. The `logs` module
    top is stdlib + typer only, same reasoning as `env` above.
    """
    from myah.cli.logs import logs_command

    app.command(
        name='logs',
        help='Tail Hermes or platform logs. LOG_NAME=platform → docker compose logs; '
        'otherwise forwards to `hermes logs`.',
        context_settings={'allow_extra_args': False, 'ignore_unknown_options': False},
    )(logs_command)


def _register_upgrade(app: typer.Typer) -> None:
    """Register `myah upgrade [--check] [--yes]` (Slice 5 task 5.5).

    Composite update flow: `hermes update` → `git pull` → `docker compose
    pull`. Native top-level command (not under `dev`). The `upgrade`
    module top is stdlib + typer only (Rich lives lazily inside the
    command body), same reasoning as `logs` / `env` — `add_typer`/
    `command()` here stays inside the < 200ms `myah --help` cold-start
    budget without the lazy-shim wrapper that `doctor`/`status`/
    `install` use.
    """
    from myah.cli.upgrade import upgrade_command

    app.command(
        name='upgrade',
        help='Upgrade Hermes runtime, Myah plugin, source, and platform image.',
    )(upgrade_command)


def _register_uninstall(app: typer.Typer) -> None:
    """Register `myah uninstall [--keep-data] [--keep-config] [--yes]` (Slice 5 task 5.5).

    Composite removal flow: `docker compose down` → `hermes uninstall`
    → remove platform `.env`. Same lazy-import discipline as `upgrade`.
    """
    from myah.cli.uninstall import uninstall_command

    app.command(
        name='uninstall',
        help='Uninstall the Myah platform + Hermes runtime (composite removal).',
    )(uninstall_command)


def _register_quickstart(app: typer.Typer) -> None:
    """Register `myah quickstart` — composite install + platform up + doctor (C.2).

    Lazy-loaded per the H4 cold-start discipline: importing
    `myah.cli.quickstart` at module top pulls in `doctor`, `install`,
    and `platform_` transitively. The lazy import inside this helper
    keeps `myah --help` off that path until `myah quickstart` is
    actually invoked.
    """
    from myah.cli.quickstart import quickstart_command  # lazy

    app.command(
        name='quickstart',
        help='One-command install + platform up + doctor.',
    )(quickstart_command)
