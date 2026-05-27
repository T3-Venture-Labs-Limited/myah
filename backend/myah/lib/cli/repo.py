"""Shared CLI repo-root detection.

The lib-shared-helper convention: anything used by 2+ command modules
under ``myah/cli/`` gets extracted here. Repo-root detection is needed
by both ``cli/install.py`` (to locate Dockerfile.stock / versions.env
for plugin-SHA resolution) and ``cli/plugins.py`` (to read the same
pinned SHA for drift warnings); future Slice 5 commands will piggyback.
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


__all__ = ['find_repo_root']
