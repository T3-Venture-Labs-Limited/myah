"""Regression test — HERMES_SHA pin is identical in Dockerfile.stock and
the plugin's pyproject.toml.

After Plan B PR B (submodule decommission) two locations independently
pin hermes-agent's git SHA:

1. `agent/Dockerfile.stock`: `ARG HERMES_SHA=...` controls both the
   pip install in the final image and the multi-stage `skills-fetcher`
   that downloads the bundled-skill tarball.
2. `myah-hermes-plugin/pyproject.toml`: the `hermes-agent @ git+...@<sha>`
   line in `dependencies` controls what OSS users get when they
   `pip install myah-hermes-plugin`.

If these diverge, OSS users run a different hermes runtime than
production — exactly the failure mode the submodule used to protect
against (you'd notice in the submodule-status diff). This test is the
post-decommission replacement.
"""
from __future__ import annotations

import re
import tomllib
from pathlib import Path


_REPO_ROOT = Path(__file__).resolve().parents[4]


def test_hermes_sha_in_dockerfile_matches_plugin_pyproject() -> None:
    """Both HERMES_SHA-pin sites must be byte-identical."""
    dockerfile_path = _REPO_ROOT / 'agent' / 'Dockerfile.stock'
    assert dockerfile_path.exists(), f'Dockerfile.stock not found: {dockerfile_path}'
    dockerfile = dockerfile_path.read_text(encoding='utf-8')

    # ``ARG HERMES_SHA=...`` may appear multiple times (multi-stage). All
    # occurrences must agree.
    dockerfile_shas = set(re.findall(r'^ARG HERMES_SHA=([a-f0-9]{40})', dockerfile, re.MULTILINE))
    assert dockerfile_shas, 'No ARG HERMES_SHA=<40-hex> directive in Dockerfile.stock'
    assert len(dockerfile_shas) == 1, (
        f'Multiple distinct HERMES_SHA values in Dockerfile.stock: {dockerfile_shas}'
    )
    docker_sha = next(iter(dockerfile_shas))

    pyproject_path = _REPO_ROOT / 'myah-hermes-plugin' / 'pyproject.toml'
    assert pyproject_path.exists(), f'Plugin pyproject.toml not found: {pyproject_path}'
    pyproject_text = pyproject_path.read_text(encoding='utf-8')
    pyproject = tomllib.loads(pyproject_text)

    deps = pyproject.get('project', {}).get('dependencies', [])
    hermes_dep = next(
        (d for d in deps if d.startswith('hermes-agent[') or d.startswith('hermes-agent ')),
        None,
    )
    assert hermes_dep is not None, (
        f'No hermes-agent dependency in {pyproject_path}. '
        f'Got: {deps!r}'
    )

    sha_match = re.search(r'@([a-f0-9]{40})', hermes_dep)
    assert sha_match is not None, (
        f'Could not extract SHA from hermes-agent dep line: {hermes_dep!r}'
    )
    plugin_sha = sha_match.group(1)

    assert docker_sha == plugin_sha, (
        f'HERMES_SHA drift detected:\n'
        f'  agent/Dockerfile.stock: {docker_sha}\n'
        f'  myah-hermes-plugin/pyproject.toml: {plugin_sha}\n'
        f'Bump both lines together (and regenerate '
        f'platform-oss/shared/contract/upstream-snapshot.json).'
    )
