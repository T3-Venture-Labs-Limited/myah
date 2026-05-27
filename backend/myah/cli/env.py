"""`myah env {list,set,unset}` — read/write the platform + Hermes .env files.

Slice 5 Task 5.4 of T3-1084 (DevX + OSS CLI).

Native — no Hermes equivalent. Myah owns the .env file format on
either side; this verb gives users a single front-door for managing
both files instead of telling them to ``$EDITOR ~/.hermes/.env``.

Two scopes:

  - **platform**: ``<repo-root>/platform-oss/.env`` (FastAPI container)
  - **hermes**:   ``$HERMES_HOME/.env`` (default ``~/.hermes/.env``)

The ``--scope {platform,hermes}`` flag disambiguates. For ``list``
without a scope, both are dumped grouped under headers.

Sensitive values (anything whose key contains KEY/TOKEN/SECRET/PASSWORD)
are masked by default; ``--show-secrets`` unhides them. The hint about
the flag surfaces alongside the first masked value so the operator
doesn't have to read --help to discover it.

Cold-start budget: Rich + the env-loader live lazily inside command
bodies. The module top is stdlib + typer only.

# Two doors, same hallway: the platform's env on one side and Hermes'
# on the other. The flag tells us which one to knock on, and the
# masking keeps secrets behind the door even when we open it.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Optional

import typer

# Module-level aliases so tests patch at the consumer namespace
# (`myah.cli.env.set_env_var`, `myah.cli.env.unset_env_var`,
# `myah.cli.env.find_repo_root`, `myah.cli.env.parse_env_file`).
# Same discipline as Slices 2-4.
from myah.lib.cli.env_loader import parse_env_file
from myah.lib.cli.repo import find_repo_root
from myah.lib.cli.worktree_setup import set_env_var, unset_env_var

env_app = typer.Typer(
    name='env',
    help='Read or write the platform and Hermes .env files.',
    no_args_is_help=True,
)


# Keys matching this pattern are treated as secrets and masked by
# default in `list` output. Matches the same convention used by the
# platform's logging filter and the install-time confirmation prompts.
_SENSITIVE_KEY_RE = re.compile(r'(KEY|TOKEN|SECRET|PASSWORD)$', re.IGNORECASE)


def _hermes_env_path() -> Path:
    """Resolve the Hermes-side .env path.

    Reads ``HERMES_HOME`` from the environment when set, falling back to
    ``~/.hermes``. The single source of truth for the Hermes home
    convention lives in upstream Hermes; we mirror it here without
    importing Hermes Python internals.
    """
    home_str = os.environ.get('HERMES_HOME')
    home = Path(home_str) if home_str else Path.home() / '.hermes'
    return home / '.env'


def _platform_env_path_or_exit() -> Path:
    """Resolve the platform-side .env path, exiting cleanly if outside a clone."""
    from rich.console import Console

    try:
        repo_root = find_repo_root()
    except RuntimeError as err:
        console = Console()
        console.print(
            '[red bold]✗[/] Not inside a Myah clone — '
            'cannot locate `platform-oss/.env`.'
        )
        console.print(f'[dim]  {err}[/]')
        console.print(
            '[dim]  Hint: cd into the directory where you cloned the repo or '
            'ran `myah install`. (Hermes scope works outside a clone.)[/]'
        )
        raise typer.Exit(code=2) from None
    return repo_root / 'platform-oss' / '.env'


def _is_sensitive(key: str) -> bool:
    return _SENSITIVE_KEY_RE.search(key) is not None


def _validate_scope_or_exit(scope: Optional[str], *, allow_none: bool) -> None:  # noqa: UP007
    """Reject scope values outside {None?, 'platform', 'hermes'}; exit 2 on bad.

    When ``allow_none`` is True, ``None`` is accepted (used by ``list``,
    which defaults to "both" when scope is omitted). When False, ``None``
    is rejected too (typer enforces this upstream via required Options,
    but the guard is defense-in-depth).
    """
    allowed: tuple[Optional[str], ...] = ((None, 'platform', 'hermes') if allow_none
                                          else ('platform', 'hermes'))
    if scope in allowed:
        return
    from rich.console import Console

    Console().print(
        f'[red bold]Invalid --scope {scope!r}.[/] '
        "Allowed: 'platform', 'hermes'."
    )
    raise typer.Exit(code=2)


def _render_section(
    title: str,
    path: Path,
    entries: dict[str, str],
    *,
    show_secrets: bool,
) -> tuple[str, bool]:
    """Format one section of the `list` output.

    Returns (rendered_text, had_masked_values).
    """
    lines = [f'# {title}  ({path})']
    had_masked = False
    if not entries:
        lines.append('  (empty)')
    else:
        for key in sorted(entries):
            value = entries[key]
            if _is_sensitive(key) and not show_secrets:
                lines.append(f'  {key}=<masked>')
                had_masked = True
            else:
                lines.append(f'  {key}={value}')
    return '\n'.join(lines), had_masked


@env_app.command('list')
def env_list(
    scope: Optional[str] = typer.Option(  # noqa: UP007 — typer needs Optional
        None,
        '--scope',
        help='Limit to one scope. Omit to list both.',
        case_sensitive=False,
    ),
    show_secrets: bool = typer.Option(
        False,
        '--show-secrets',
        help='Print secret values (KEY/TOKEN/SECRET/PASSWORD) verbatim instead of masking.',
    ),
) -> None:
    """List KEY=VALUE pairs from the platform and/or Hermes .env files."""
    from rich.console import Console

    _validate_scope_or_exit(scope, allow_none=True)

    sections: list[str] = []
    any_masked = False

    if scope in (None, 'platform'):
        platform_env = _platform_env_path_or_exit()
        platform_entries = parse_env_file(platform_env)
        text, masked = _render_section(
            'platform', platform_env, platform_entries, show_secrets=show_secrets
        )
        sections.append(text)
        any_masked = any_masked or masked

    if scope in (None, 'hermes'):
        hermes_env = _hermes_env_path()
        hermes_entries = parse_env_file(hermes_env)
        text, masked = _render_section(
            'hermes', hermes_env, hermes_entries, show_secrets=show_secrets
        )
        sections.append(text)
        any_masked = any_masked or masked

    console = Console()
    console.print('\n\n'.join(sections))
    if any_masked:
        console.print(
            '[dim]Sensitive values masked. Use [bold]--show-secrets[/] '
            'to see actual values.[/]'
        )


@env_app.command('set')
def env_set(
    key: str = typer.Argument(..., help='Env var name to set.'),
    value: str = typer.Argument(..., help='Value to assign.'),
    scope: str = typer.Option(
        ...,
        '--scope',
        help="Target scope: 'platform' or 'hermes'.",
        case_sensitive=False,
    ),
) -> None:
    """Set (or upsert) KEY=VALUE in the chosen .env file. Atomic + idempotent."""
    from rich.console import Console

    _validate_scope_or_exit(scope, allow_none=False)
    console = Console()
    path = _platform_env_path_or_exit() if scope == 'platform' else _hermes_env_path()
    set_env_var(path, key, value)
    masked_display = '<masked>' if _is_sensitive(key) else value
    console.print(f'[green]✓[/] Set [bold]{key}[/]={masked_display} in {path}.')


@env_app.command('unset')
def env_unset(
    key: str = typer.Argument(..., help='Env var name to remove.'),
    scope: str = typer.Option(
        ...,
        '--scope',
        help="Target scope: 'platform' or 'hermes'.",
        case_sensitive=False,
    ),
) -> None:
    """Remove KEY from the chosen .env file. No-op if absent (exit 0)."""
    from rich.console import Console

    _validate_scope_or_exit(scope, allow_none=False)
    console = Console()
    path = _platform_env_path_or_exit() if scope == 'platform' else _hermes_env_path()
    removed = unset_env_var(path, key)
    if removed:
        console.print(f'[green]✓[/] Removed [bold]{key}[/] from {path}.')
    else:
        console.print(f'[dim]{key} not found in {path} — nothing to do.[/]')


__all__ = ['env_app']
