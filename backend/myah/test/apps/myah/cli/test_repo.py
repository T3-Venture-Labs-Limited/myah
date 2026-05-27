"""Tests for ``myah.lib.cli.repo`` — layout-aware repo-root + platform-env resolution.

Regression coverage for sync bug C-1 (PR #16 review, 2026-05-27): the
`install` and `uninstall` commands hard-coded `<repo>/platform-oss/.env`
which is only valid for the internal-monorepo layout. The public OSS
mirror (T3-Venture-Labs-Limited/myah) has a flat layout — the platform
.env lives at `<repo>/.env` (next to docker-compose.yml).

``find_platform_env_path`` resolves the right path based on which
layout sentinel won the `find_repo_root` walk.
"""

from __future__ import annotations

from pathlib import Path

import pytest


# ── Fixtures ──────────────────────────────────────────────────────────


@pytest.fixture
def fake_monorepo(tmp_path: Path) -> Path:
    """Internal monorepo layout — `agent/Dockerfile.stock` sentinel + `platform-oss/`."""
    repo = tmp_path / 'monorepo'
    (repo / 'agent').mkdir(parents=True)
    (repo / 'agent' / 'Dockerfile.stock').write_text(
        'ARG HERMES_SHA=' + 'a' * 40 + '\n'
        'ARG MYAH_PLUGIN_SHA=' + 'b' * 40 + '\n',
        encoding='utf-8',
    )
    (repo / 'platform-oss').mkdir()
    return repo


@pytest.fixture
def fake_public_repo(tmp_path: Path) -> Path:
    """Public OSS mirror layout — `versions.env` sentinel, flat (no `platform-oss/`)."""
    repo = tmp_path / 'public'
    repo.mkdir(parents=True)
    (repo / 'versions.env').write_text(
        'HERMES_SHA=' + 'a' * 40 + '\n'
        'MYAH_PLUGIN_SHA=' + 'b' * 40 + '\n',
        encoding='utf-8',
    )
    (repo / 'docker-compose.yml').write_text('# stub\n')
    return repo


# ── find_repo_root: existing behavior ─────────────────────────────────


class TestFindRepoRoot:
    def test_monorepo_layout_detected(self, fake_monorepo: Path) -> None:
        from myah.lib.cli.repo import find_repo_root

        assert find_repo_root(fake_monorepo) == fake_monorepo

    def test_public_layout_detected(self, fake_public_repo: Path) -> None:
        from myah.lib.cli.repo import find_repo_root

        assert find_repo_root(fake_public_repo) == fake_public_repo

    def test_raises_outside_clone(self, tmp_path: Path) -> None:
        from myah.lib.cli.repo import find_repo_root

        empty = tmp_path / 'empty'
        empty.mkdir()
        with pytest.raises(RuntimeError, match='Could not locate repo root'):
            find_repo_root(empty)


# ── find_platform_env_path: new behavior (regression for C-1) ─────────


class TestFindPlatformEnvPath:
    """Regression for sync bug C-1: the platform .env path must follow the
    repo layout, not be hard-coded to `platform-oss/.env`.
    """

    def test_monorepo_uses_platform_oss_subdir(self, fake_monorepo: Path) -> None:
        """Internal monorepo: platform .env lives at `<repo>/platform-oss/.env`."""
        from myah.lib.cli.repo import find_platform_env_path

        assert find_platform_env_path(fake_monorepo) == fake_monorepo / 'platform-oss' / '.env'

    def test_public_mirror_uses_repo_root(self, fake_public_repo: Path) -> None:
        """Public OSS mirror: platform .env lives at `<repo>/.env` (next to docker-compose.yml).

        This is the regression — `install.py` previously wrote to
        `<repo>/platform-oss/.env` even on the public mirror, creating
        a stray dir and leaving `docker-compose.yml`'s `env_file: .env`
        pointed at an empty file.
        """
        from myah.lib.cli.repo import find_platform_env_path

        assert find_platform_env_path(fake_public_repo) == fake_public_repo / '.env'

    def test_both_sentinels_present_prefers_monorepo(self, fake_monorepo: Path) -> None:
        """If both sentinels exist (dev worktree of the monorepo that has
        copied `versions.env` in from public), the monorepo layout wins.
        Mirrors `find_repo_root`'s precedence."""
        from myah.lib.cli.repo import find_platform_env_path

        # Inject versions.env into the monorepo fixture
        (fake_monorepo / 'versions.env').write_text('MYAH_PLUGIN_SHA=' + 'c' * 40 + '\n')
        assert find_platform_env_path(fake_monorepo) == fake_monorepo / 'platform-oss' / '.env'

    def test_raises_when_no_sentinel(self, tmp_path: Path) -> None:
        """No sentinel = can't determine layout = raise (caller should
        find_repo_root first; both raise the same kind of error)."""
        from myah.lib.cli.repo import find_platform_env_path

        empty = tmp_path / 'empty'
        empty.mkdir()
        with pytest.raises(RuntimeError, match='Could not determine platform .env path'):
            find_platform_env_path(empty)
