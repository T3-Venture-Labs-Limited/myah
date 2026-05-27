"""Shared CLI repo-root detection.

The lib-shared-helper convention: anything used by 2+ command modules
under ``myah/cli/`` gets extracted here. Repo-root detection is needed
by both ``cli/install.py`` (to locate Dockerfile.stock / versions.env
for plugin-SHA resolution) and ``cli/plugins.py`` (to read the same
pinned SHA for drift warnings); future Slice 5 commands will piggyback.

Two layouts are supported and the layout determines two paths:

* internal monorepo (``myah-hosted``) — ``agent/Dockerfile.stock``
  sentinel, platform sources live under ``platform-oss/``, so the
  platform ``.env`` belongs at ``<root>/platform-oss/.env``;
* public OSS mirror (``T3-Venture-Labs-Limited/myah``) —
  ``versions.env`` sentinel, flat layout (the backend lives at
  ``<root>/backend/``), so the platform ``.env`` belongs at
  ``<root>/.env`` — next to ``docker-compose.yml`` which references
  ``env_file: .env`` at the same level.

The hard-coded ``<root>/platform-oss/.env`` path is a regression that
silently breaks the public mirror's ``myah install`` + ``myah platform
up`` flow because docker-compose looks for ``.env`` at the repo root.
Use ``find_platform_env_path`` instead of hand-rolling the join.
"""

from __future__ import annotations

from pathlib import Path

# Layout sentinels. Two layouts are supported. The private monorepo
# (myah-hosted) has ``agent/Dockerfile.stock`` and pins the plugin SHA
# there. The public OSS mirror (T3-Venture-Labs-Limited/myah) has
# ``versions.env`` instead and pins the SHA via a
# ``MYAH_PLUGIN_SHA=<40hex>`` line.
_DOCKERFILE_REL = Path('agent') / 'Dockerfile.stock'
_VERSIONS_ENV_REL = Path('versions.env')


def find_repo_root(start: Path | None = None) -> Path:
    """Locate the repo root by walking up from ``start`` (default CWD) looking for sentinels.

    Sentinels:
      - ``agent/Dockerfile.stock`` — private monorepo / OSS mirror with
        agent overlay
      - ``versions.env`` — public OSS mirror flat layout (PRs #5-7
        introduced this)

    Returns the first ancestor (including ``start``) containing either
    sentinel. Raises ``RuntimeError`` if no sentinel is found by the
    filesystem root.

    The private monorepo's Dockerfile takes precedence if both exist
    (which can happen in a development worktree of the internal repo
    that has copied versions.env in from public).
    """
    candidate = (start if start is not None else Path.cwd()).resolve()
    while True:
        if (candidate / _DOCKERFILE_REL).is_file():
            return candidate
        if (candidate / _VERSIONS_ENV_REL).is_file():
            return candidate
        if candidate.parent == candidate:
            raise RuntimeError(
                'Could not locate repo root. Expected one of:\n'
                f'    <ancestor>/{_DOCKERFILE_REL}\n'
                f'    <ancestor>/{_VERSIONS_ENV_REL}\n'
                f'Searched from {candidate} upward.'
            )
        candidate = candidate.parent


def find_platform_env_path(repo_root: Path) -> Path:
    """Return the platform ``.env`` path for ``repo_root``'s layout.

    Resolution mirrors ``find_repo_root``'s sentinel precedence:

    1. If ``<root>/agent/Dockerfile.stock`` exists → monorepo layout →
       ``<root>/platform-oss/.env``.
    2. Else if ``<root>/versions.env`` exists → public mirror →
       ``<root>/.env``.
    3. Else raise ``RuntimeError`` so callers don't silently write into
       a directory that nothing reads.

    Regression for PR #16 sync bug C-1: the install/uninstall paths
    previously hard-coded the monorepo path on both layouts. On the
    public mirror this created a stray ``platform-oss/`` directory and
    left ``<root>/.env`` empty so docker-compose's ``env_file: .env``
    directive saw no values.
    """
    if (repo_root / _DOCKERFILE_REL).is_file():
        return repo_root / 'platform-oss' / '.env'
    if (repo_root / _VERSIONS_ENV_REL).is_file():
        return repo_root / '.env'
    raise RuntimeError(
        'Could not determine platform .env path — neither '
        f'{repo_root / _DOCKERFILE_REL} nor {repo_root / _VERSIONS_ENV_REL} exists. '
        'Run `find_repo_root` first; this helper assumes the result.'
    )


__all__ = ['find_platform_env_path', 'find_repo_root']
