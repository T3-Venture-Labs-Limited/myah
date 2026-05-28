"""Shape regression tests for docker-compose.yml at the repo root.

These guard against silent reintroduction of multi-install footguns
(PR #16 post-merge laptop test, Bug 4).
"""

from __future__ import annotations

from pathlib import Path

import yaml


def _repo_root() -> Path:
    """Walk up from this file to find the repo root via known sentinels."""
    p = Path(__file__).resolve()
    while p.parent != p:
        if (p / 'docker-compose.yml').is_file() and (p / 'Dockerfile').is_file():
            return p
        p = p.parent
    raise RuntimeError('repo root not found')


def test_docker_compose_does_not_hardcode_container_name() -> None:
    """The `platform` service must NOT pin `container_name`.

    Pinned names collide globally on the Docker daemon — running
    `myah platform up` from a second clone errors with:
        Conflict. The container name "/myah-platform" is already in use

    Letting compose auto-generate (project_service_1) keeps installs
    isolated.
    """
    cfg = yaml.safe_load((_repo_root() / 'docker-compose.yml').read_text())
    platform_svc = cfg['services']['platform']
    assert 'container_name' not in platform_svc, (
        "docker-compose.yml services.platform.container_name is set — "
        "this collides globally when multiple Myah installs share a Docker "
        "daemon. See PR #16 post-merge laptop test, Bug 4."
    )
