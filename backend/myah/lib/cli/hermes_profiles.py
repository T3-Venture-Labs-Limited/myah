"""Filesystem-only Hermes profile discovery for the Myah OSS installer.

Hermes profiles are scoped by ``HERMES_HOME``. This module deliberately
uses only filesystem conventions instead of importing Hermes internals:

- the default profile home is ``~/.hermes``;
- named profile homes live under ``~/.hermes/profiles/<name>``;
- a shell-selected current profile may be supplied via ``HERMES_HOME``.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

_PROFILE_NAME_RE = re.compile(r'^[A-Za-z0-9_.-]+$')


@dataclass(frozen=True)
class HermesProfile:
    """A Hermes profile choice resolved to a concrete home directory."""

    name: str
    home: Path
    exists: bool
    is_default: bool = False


def _expand(path: str | Path) -> Path:
    return Path(os.path.expanduser(str(path)))


def base_hermes_home() -> Path:
    """Return the current Hermes home: ``$HERMES_HOME`` or ``~/.hermes``."""
    override = os.environ.get('HERMES_HOME')
    if override:
        return _expand(override)
    return default_hermes_root()


def default_hermes_root() -> Path:
    """Return the canonical default Hermes root, ignoring ``$HERMES_HOME``."""
    return _expand('~/.hermes')


def _validate_profile_name(name: str) -> None:
    if not name or name in {'.', '..'} or '/' in name or '\\' in name:
        raise ValueError(f'Invalid Hermes profile name {name!r}. Use letters, numbers, dashes, underscores, or dots.')
    if _PROFILE_NAME_RE.fullmatch(name) is None:
        raise ValueError(f'Invalid Hermes profile name {name!r}. Use letters, numbers, dashes, underscores, or dots.')


def list_hermes_profiles(root: Path | None = None) -> list[HermesProfile]:
    """List the default profile plus sorted named profiles under ``profiles/``.

    Named profiles are exactly directories under ``<root>/profiles/*``;
    files are ignored. Sorting by profile name is part of the CLI display
    contract so the interactive picker is stable and predictable.
    """
    base = root if root is not None else default_hermes_root()
    profiles = [
        HermesProfile(name='default', home=base, exists=base.exists(), is_default=True),
    ]
    profiles_dir = base / 'profiles'
    if profiles_dir.is_dir():
        for child in sorted(profiles_dir.iterdir(), key=lambda p: p.name):
            if child.is_dir():
                profiles.append(
                    HermesProfile(
                        name=child.name,
                        home=child,
                        exists=True,
                        is_default=False,
                    )
                )
    return profiles


def resolve_hermes_profile(*, profile: str | None, create_profile: bool) -> HermesProfile:
    """Resolve a profile argument into a concrete Hermes home.

    ``profile=None`` means the current profile: ``$HERMES_HOME`` when set,
    otherwise the default profile at ``~/.hermes``. ``profile='default'``
    explicitly means ``~/.hermes`` even if ``$HERMES_HOME`` points
    elsewhere. Any other profile name maps to ``~/.hermes/profiles/<name>``.
    """
    if profile is None:
        home = base_hermes_home()
        is_env_override = bool(os.environ.get('HERMES_HOME'))
        name = 'current' if is_env_override else 'default'
        selected = HermesProfile(
            name=name,
            home=home,
            exists=home.exists(),
            is_default=not is_env_override,
        )
        if create_profile:
            raise ValueError('--create-profile requires --profile <name>.')
        return selected

    _validate_profile_name(profile)

    if profile == 'default':
        home = default_hermes_root()
        if create_profile:
            home.mkdir(parents=True, exist_ok=True)
        return HermesProfile(name='default', home=home, exists=home.exists(), is_default=True)

    home = default_hermes_root() / 'profiles' / profile
    if home.exists():
        return HermesProfile(name=profile, home=home, exists=True, is_default=False)

    if create_profile:
        home.mkdir(parents=True, exist_ok=True)
        return HermesProfile(name=profile, home=home, exists=True, is_default=False)

    available = ', '.join(p.name for p in list_hermes_profiles())
    raise ValueError(
        f'Hermes profile {profile!r} does not exist at {home}. '
        f'Use --create-profile to create it, or choose one of: {available}'
    )


__all__ = [
    'HermesProfile',
    'base_hermes_home',
    'default_hermes_root',
    'list_hermes_profiles',
    'resolve_hermes_profile',
]
