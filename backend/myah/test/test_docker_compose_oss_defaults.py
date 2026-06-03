"""
OSS-launch regression gate for ``docker-compose.yml`` (D1).

The first command an OSS user runs after ``git clone`` is
``docker compose up -d``. If the default image points at a private
GHCR package the user has no auth for, that command fails immediately
with ``unauthorized`` — a launch-blocker that surfaced in VM testing
(PR #170, Phase D finding D1).

This test enforces two invariants on the OSS compose file:

1. The default ``services.platform.image`` must NOT resolve to the
   private ``ghcr.io/t3-venture-labs-limited/...`` namespace. OSS users
   have no token for it.
2. A ``services.platform.build`` stanza must be present so that on a
   fresh install, compose builds the image locally from source if no
   matching tag exists on the local Docker daemon.

Reference: docs/oss-launch/vm-testing-followups.md (D1).
"""

from pathlib import Path

import pytest
import yaml


def _repo_root() -> Path:
    """Walk up from this file until ``docker-compose.yml`` is found."""
    here = Path(__file__).resolve()
    while not (here / 'docker-compose.yml').exists():
        parent = here.parent
        if parent == here:
            raise RuntimeError('Could not find repo root (no docker-compose.yml above this test)')
        here = parent
    return here


@pytest.fixture(scope='module')
def compose() -> dict:
    return yaml.safe_load((_repo_root() / 'docker-compose.yml').read_text())


def test_docker_compose_default_image_is_not_private_ghcr(compose: dict) -> None:
    """OSS users must not need GHCR auth to run ``docker compose up``."""
    image = compose['services']['platform']['image']
    # Compose treats the literal text in ``${VAR:-default}`` — the
    # default is whatever follows ``:-`` up to the closing brace.
    assert 'ghcr.io/t3-venture-labs-limited' not in image, (
        f'Default platform image is private GHCR ref: {image!r}. '
        'OSS users have no auth for that registry. '
        'See docs/oss-launch/vm-testing-followups.md (D1).'
    )


def test_docker_compose_has_build_stanza(compose: dict) -> None:
    """A fresh ``docker compose up -d`` must be able to build the image."""
    platform = compose['services']['platform']
    build = platform.get('build')
    assert build, (
        'services.platform must have a build: stanza so fresh OSS '
        'installs can build the image locally on first compose up. '
        'See docs/oss-launch/vm-testing-followups.md (D1).'
    )
    # build.context must point at platform-oss/ (where the Dockerfile lives).
    context = build['context'].rstrip('/')
    assert context == 'platform-oss', (
        f"services.platform.build.context must be 'platform-oss', got {context!r}"
    )
    # And the Dockerfile it references must actually exist.
    dockerfile = build.get('dockerfile', 'Dockerfile')
    df_path = _repo_root() / context / dockerfile
    assert df_path.exists(), f'build.dockerfile points at non-existent file: {df_path}'
