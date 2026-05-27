# noqa: INP001
import os
import shutil
import subprocess
from sys import stderr

from hatchling.builders.hooks.plugin.interface import BuildHookInterface


class CustomBuildHook(BuildHookInterface):
    def initialize(self, version, build_data):
        super().initialize(version, build_data)
        # Per-worktree venv installs set MYAH_SKIP_HATCH_NPM=1 to bypass
        # the npm install + npm run build steps. Without this skip, the
        # build hook would run `npm install --force` against the symlinked
        # venv per worktree, corrupting main's node_modules. See Slice 0
        # spike Investigation B (docs/superpowers/specs/2026-05-22-devx-oss-cli-spike-findings.md).
        # The accompanying platform-oss/build/.gitkeep ensures the
        # `force-include = { build = "myah/frontend" }` directive in
        # pyproject.toml passes hatchling's pre-build validation when the
        # frontend hasn't been built yet.
        if os.environ.get('MYAH_SKIP_HATCH_NPM'):
            stderr.write('>>> MYAH_SKIP_HATCH_NPM set; skipping npm install + build\n')
            return
        stderr.write('>>> Building Myah frontend\n')
        npm = shutil.which('npm')
        if npm is None:
            raise RuntimeError('NodeJS `npm` is required for building Myah but it was not found')
        stderr.write('### npm install\n')
        subprocess.run([npm, 'install', '--force'], check=True)  # noqa: S603
        stderr.write('\n### npm run build\n')
        os.environ['APP_BUILD_HASH'] = version
        subprocess.run([npm, 'run', 'build'], check=True)  # noqa: S603
