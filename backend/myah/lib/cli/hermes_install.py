"""Plugin install + dashboard shim + mount verification (Slice 4 sub-phase 4b).

Library-only — no CLI command yet. Sub-phase 4f wires `myah install`
end-to-end. This module replaces phase 5 of the 922-line bash at
`platform-oss/scripts/setup-myah-oss.sh` (lines 442-501 + the
`verify_dashboard_plugin_mounted` polling helper at 636-669 + the
`detect_hermes_venv` candidate-search helper at 183-227).

Phase mapping:

  bash lines 183-227   → `detect_hermes_venv`
  bash lines 451-465   → `bootstrap_pip`
  bash lines 467-489   → `pip_install_plugin_at_sha`
  bash lines 491-501   → `materialize_dashboard_shim`
  bash lines 636-669   → `verify_dashboard_plugin_mounted`

Plus a thin re-export of `_read_plugin_sha` (Slice 2) as
`read_pinned_plugin_sha_from_dockerfile` so callers in 4f can grep
`hermes_install` for the plugin-install semantics without having to know
about worktree-internal helpers.

Cold-start budget: stdlib only. `urllib.request` is lazy-imported inside
`_http_get_ok` so module import stays cheap. No Rich, no httpx, no yaml.

# Wait for the dashboard to wake. Knock thirty times,
# half a second between each — patient at the door.
"""

from __future__ import annotations

import json
import os
import shutil
import time
from pathlib import Path

from myah.lib.cli.shell import ShellError, run
from myah.lib.cli.worktree_setup import _read_plugin_sha

# Resolution order matches how Hermes's own installer creates them.
# Module-level constant so tests can monkeypatch it onto tmp_path subdirs
# without having to mock $HOME or jump through filesystem hoops.
_HERMES_VENV_CANDIDATES: tuple[Path, ...] = (
    Path.home() / '.hermes' / 'hermes-agent' / 'venv',  # per-user (default)
    Path('/usr/local/lib/hermes-agent/venv'),  # system install
    Path('/opt/hermes-agent/venv'),  # /opt/ convention — speculative
)


# Public plugin repo. URL works unauthenticated; auth_token only matters
# for private forks. See bash 478-485 for the original rationale.
_PLUGIN_REPO = 'github.com/T3-Venture-Labs-Limited/myah-hermes-plugin'

# Hermes dashboard's default bind port — mirrors `hermes dashboard` upstream
# default. Override via `port=` kwarg when running on a non-default port
# (e.g. tests, MYAH_HERMES_WEB_PORT env in dev).
_DASHBOARD_DEFAULT_PORT = 9119

# Mirror of `curl -m 2` in setup-myah-oss.sh:643. Bounds the wall-clock cost
# of a single poll attempt so the outer loop's timeout_s budget remains
# meaningful even when the dashboard is hanging instead of refusing fast.
_HTTP_REQUEST_TIMEOUT_S = 2.0


def detect_hermes_venv() -> Path:
    """Locate the Python venv where hermes-agent is installed.

    Mirrors setup-myah-oss.sh:183-227. Resolution order:

      1. `MYAH_HERMES_VENV` env override — must have an executable
         `bin/python` or RuntimeError.
      2. Three candidate paths in `_HERMES_VENV_CANDIDATES` — first one
         with an executable `bin/python` wins.
      3. Fallback: resolve `hermes` on PATH, read its shebang, return
         the venv root two dirname()s above the interpreter.
      4. None of the above: RuntimeError listing the candidates.
    """
    override = os.environ.get('MYAH_HERMES_VENV')
    if override:
        override_path = Path(override)
        python = override_path / 'bin' / 'python'
        if python.is_file() and os.access(python, os.X_OK):
            return override_path
        raise RuntimeError(
            f'MYAH_HERMES_VENV={override} is set but {python} is not executable. '
            f'Either unset the override or point it at a venv with bin/python.'
        )

    for candidate in _HERMES_VENV_CANDIDATES:
        python = candidate / 'bin' / 'python'
        if python.is_file() and os.access(python, os.X_OK):
            return candidate

    # Last resort: shebang from `hermes` on PATH.
    hermes_path = shutil.which('hermes')
    if hermes_path:
        try:
            first_line = Path(hermes_path).read_text(encoding='utf-8', errors='replace').splitlines()[0]
        except (OSError, IndexError):
            first_line = ''
        if first_line.startswith('#!'):
            shebang_body = first_line[2:].strip()
            interpreter = shebang_body.split()[0] if shebang_body else ''
            # `/usr/bin/env python3` form: can't infer venv root from `env`'s path.
            # Real-world failure mode (Homebrew Python often produces env shebangs).
            # Tell the user the exact remedy instead of falling through to the
            # generic candidates-list error.
            if interpreter.endswith('/env') or interpreter == 'env':
                raise RuntimeError(
                    f'`hermes` on PATH at {hermes_path} uses `#!{shebang_body}` — '
                    f'this is the env-based shebang form; the venv root cannot be inferred. '
                    f'Set MYAH_HERMES_VENV=<venv-root> explicitly to override.'
                )
            if interpreter and ('/python' in interpreter or interpreter.endswith('python')):
                venv_root = Path(interpreter).parent.parent
                if (venv_root / 'bin' / 'python').is_file():
                    return venv_root

    candidates_str = '\n'.join(f'    {c}' for c in _HERMES_VENV_CANDIDATES)
    raise RuntimeError(
        f'Could not locate hermes-agent venv. Looked in:\n{candidates_str}\n'
        f'  Make sure hermes is installed; see '
        f'https://hermes-agent.nousresearch.com/docs/installation'
    )


def read_pinned_plugin_sha_from_dockerfile(dockerfile_path: Path) -> str:
    """Return the 40-char `MYAH_PLUGIN_SHA` from `agent/Dockerfile.stock`.

    Thin wrapper around `worktree_setup._read_plugin_sha` (Slice 2) —
    re-exported here so callers in 4f can grep `hermes_install` for
    "plugin install" semantics.
    """
    return _read_plugin_sha(dockerfile_path)


def bootstrap_pip(venv_python: Path) -> None:
    """Ensure `pip` is callable as `<venv_python> -m pip`. No-op if present.

    Mirrors setup-myah-oss.sh:454-465. Hermes is typically installed via
    uv which doesn't include pip in the venv; bootstrap via stdlib
    ensurepip so subsequent `pip install` calls work.
    """
    # First probe captures stderr but we only branch on returncode; the pip-
    # missing case has noisy stderr ('No module named pip') we deliberately
    # discard. Mirrors bash's `>/dev/null 2>&1` at setup-myah-oss.sh:458.
    probe = run([str(venv_python), '-m', 'pip', '--version'])
    if probe.returncode == 0:
        return

    # NOTE: Python 3.11's ``ensurepip`` (the version Hermes 0.14.0 ships)
    # does NOT accept ``--quiet``. Passing it makes argparse exit 2 with
    # ``unrecognized arguments: --quiet`` and blocks every fresh OSS
    # install on Phase 5. ``shell.run`` already captures stdout, so
    # dropping the flag changes nothing for terminal noise. See PR #16
    # review C-2 for the verbatim VM-repro evidence.
    run(
        [str(venv_python), '-m', 'ensurepip', '--upgrade'],
        check=True,
    )

    recheck = run([str(venv_python), '-m', 'pip', '--version'])
    if recheck.returncode != 0:
        venv_root = venv_python.parent.parent
        raise RuntimeError(
            f'ensurepip ran but `python -m pip` still fails for venv at {venv_root}. '
            f'Check the venv layout and ensure it is not corrupted.'
        )


def pip_install_plugin_at_sha(
    sha: str,
    venv_python: Path,
    *,
    auth_token: str | None = None,
) -> None:
    """Pip-install myah-hermes-plugin at the pinned SHA into the given venv.

    Mirrors setup-myah-oss.sh:478-489. With `auth_token`, embeds the
    token in the git URL for private-fork installs.
    """
    if auth_token:
        url = f'git+https://{auth_token}@{_PLUGIN_REPO}@{sha}'
    else:
        url = f'git+https://{_PLUGIN_REPO}@{sha}'
    requirement = f'myah-hermes-plugin @ {url}'

    run(
        [str(venv_python), '-m', 'pip', 'install', '--quiet', '--upgrade', requirement],
        check=True,
    )


def materialize_dashboard_shim(venv_path: Path, hermes_home: Path) -> None:
    """Materialize the dashboard shim at <hermes_home>/plugins/myah-admin/.

    Mirrors setup-myah-oss.sh:491-501. Invokes the absolute path
    `<venv_path>/bin/myah-hermes-plugin install --dashboard-only
    --target <hermes_home>/plugins/`. NEVER use a bare `myah-hermes-plugin`
    from PATH — Investigation C says PATH-based resolution silently picks
    up a console script from another venv.

    Sets HERMES_HOME via env-merge so the subprocess inherits PATH and
    everything else from the parent.
    """
    script = venv_path / 'bin' / 'myah-hermes-plugin'
    if not script.is_file():
        raise RuntimeError(
            f'Expected console script at {script} but it is missing. '
            f'Did you forget to call pip_install_plugin_at_sha first?'
        )

    target = hermes_home / 'plugins'
    # Env-merge, never env-replace. shell.run's env= REPLACES the
    # subprocess environment — so we must hand it a merged dict.
    env = {**os.environ, 'HERMES_HOME': str(hermes_home)}

    run(
        [str(script), 'install', '--dashboard-only', '--target', str(target)],
        check=True,
        env=env,
    )


def _http_get_ok(
    url: str,
    headers: dict[str, str],
    *,
    timeout_s: float = _HTTP_REQUEST_TIMEOUT_S,
) -> bool:
    """Best-effort GET. Returns True on 200, False on any network error.

    Lazy-imports urllib so module import stays cheap. The exception
    swallow list is deliberately broad — URLError, HTTPError, and OSError
    (which catches ConnectionRefusedError + TimeoutError that fire during
    dashboard boot). Does NOT swallow programmer errors like TypeError.
    """
    import urllib.error
    import urllib.request

    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:  # noqa: S310 — loopback only
            return resp.status == 200
    except (urllib.error.URLError, urllib.error.HTTPError, OSError):
        return False


def verify_dashboard_plugin_mounted(
    web_token: str | None,
    *,
    port: int = _DASHBOARD_DEFAULT_PORT,
    timeout_s: float = 15.0,
    poll_interval_s: float = 0.5,
) -> bool:
    """Poll dashboard's myah-admin plugin health endpoint until 200 or timeout.

    Mirrors setup-myah-oss.sh:636-669 (30 polls × 0.5s = ~15s default).

    Total wall-clock ≈ attempts × (HTTP request timeout + poll_interval_s);
    HTTP request timeout is `_HTTP_REQUEST_TIMEOUT_S` (2.0s, mirrors
    curl -m 2 in the bash original).

    Returns True on first 200; False after timeout. Never raises —
    install can succeed even if mount verification fails (bash original
    swallows the exit code with `|| true` at the caller).
    """
    url = f'http://127.0.0.1:{port}/api/plugins/myah-admin/health'
    headers: dict[str, str] = {}
    if web_token:
        headers['Authorization'] = f'Bearer {web_token}'

    attempts = max(1, int(timeout_s / poll_interval_s))
    for attempt in range(attempts):
        if _http_get_ok(url, headers):
            return True
        if attempt < attempts - 1:
            time.sleep(poll_interval_s)
    return False


def verify_gateway_plugin_bound(
    *,
    port: int = 8643,
    timeout_s: float = 15.0,
    poll_interval_s: float = 0.5,
) -> bool:
    """Poll the gateway-side ``/myah/health`` endpoint until 200 or timeout.

    Mount verification at the *correct* surface. The original
    :func:`verify_dashboard_plugin_mounted` polls the dashboard's
    ``/api/plugins/myah-admin/health`` endpoint, which proves the
    dashboard shim got materialized into ``~/.hermes/plugins/myah-admin/``.
    That tells you nothing about whether the gateway-side platform
    adapter is bound — port 8643 / ``/myah/health`` is the surface
    that the platform actually talks to.

    Regression for PR #16 review M-1: the install printed "dashboard
    plugin mount verified" while the gateway plugin was still
    unregistered, port 8643 was unbound, and the OSS probe returned
    ``plugin_installed: false``.

    Returns ``True`` on first 200; ``False`` after timeout. Never
    raises — install can still succeed; the caller decides how to
    surface the result.
    """
    url = f'http://127.0.0.1:{port}/myah/health'
    attempts = max(1, int(timeout_s / poll_interval_s))
    for attempt in range(attempts):
        if _http_get_ok(url, headers={}):
            return True
        if attempt < attempts - 1:
            time.sleep(poll_interval_s)
    return False


def _find_plugin_dist_info(hermes_venv: Path) -> Path | None:
    """Locate the myah-hermes-plugin's .dist-info dir under a hermes venv.

    Globs ``<venv>/lib/python*/site-packages/myah_hermes_plugin-*.dist-info``
    so the Python minor version (3.11 vs 3.12) is not hardcoded. Returns
    the first match (sorted) or None when the package isn't installed.

    On multiple ``.dist-info`` matches (rare; happens when a stale
    ``.dist-info`` from a prior install coexists with the current one —
    usually only after a botched manual install), returns the
    alphabetically-first match. Pip strips old dist-info on
    ``pip install --upgrade``, so this only fires when the venv was
    manually edited.
    """
    lib_dir = hermes_venv / 'lib'
    if not lib_dir.is_dir():
        return None
    for site_packages in sorted(lib_dir.glob('python*/site-packages')):
        matches = sorted(site_packages.glob('myah_hermes_plugin-*.dist-info'))
        if matches:
            return matches[0]
    return None


def _git_commit_from_direct_url(direct_url: Path) -> str | None:
    """Parse PEP 610 direct_url.json and return ``vcs_info.commit_id`` if git.

    Returns None on every can't-determine path: missing file, malformed
    JSON, non-dict payload, missing/non-dict ``vcs_info`` (editable +
    archive installs land here), non-git vcs, missing commit_id.
    """
    if not direct_url.is_file():
        return None
    try:
        payload = json.loads(direct_url.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    vcs_info = payload.get('vcs_info')
    if not isinstance(vcs_info, dict) or vcs_info.get('vcs') != 'git':
        return None
    commit_id = vcs_info.get('commit_id')
    if not isinstance(commit_id, str) or not commit_id:
        return None
    return commit_id


def detect_installed_plugin_sha(hermes_venv: Path) -> str | None:
    """Return the git SHA the installed myah-hermes-plugin was built from, or None.

    Reads PEP 610 ``direct_url.json`` from the installed package's
    ``.dist-info`` directory. ``pip install <pkg> @ git+https://...@<sha>``
    records the resolved commit at install time in this file:

        {
            "url": "https://github.com/.../myah-hermes-plugin",
            "vcs_info": {
                "vcs": "git",
                "commit_id": "<40-hex>",
                "requested_revision": "<40-hex>"
            }
        }

    Returns None — not raises — when any of the following hold:
      - Package isn't installed (no .dist-info dir found in site-packages)
      - direct_url.json doesn't exist (older pip / non-pip install)
      - Recorded source is an editable install (``dir_info`` present
        instead of ``vcs_info``)
      - vcs is not git (e.g. hg/svn)
      - JSON is malformed

    Caller treats None as "can't determine, skip the drift warning" —
    informational, never an error.

    Sub-phase 4b's `detect_hermes_venv` is the canonical way to obtain
    ``hermes_venv`` — this helper assumes it's already been resolved.
    """
    dist_info = _find_plugin_dist_info(hermes_venv)
    if dist_info is None:
        return None
    return _git_commit_from_direct_url(dist_info / 'direct_url.json')


def register_plugin_with_gateway(
    hermes_bin: Path,
    *,
    adapter_auth_key: str | None = None,
    repo: str = 'T3-Venture-Labs-Limited/myah-hermes-plugin',
) -> None:
    """Register the Myah plugin with the Hermes gateway + enable it.

    Mirrors the manual ``Next steps`` block at setup-myah-oss.sh:945:
    ``hermes plugins install <repo>`` then ``hermes plugins enable myah``.

    Without this step the plugin's pip-install in
    :func:`pip_install_plugin_at_sha` is wasted: the gateway never loads
    the platform adapter, port 8643 never binds, and the OSS probe
    reports ``plugin_installed: false``. The bash original instructed
    users to do this manually; ``myah install`` should not leave the
    same paper-cut on the floor. See PR #16 review C-3.

    Idempotent: re-runs against an already-installed plugin are a no-op
    on the install step (the wrapper still runs ``plugins enable myah``,
    which is itself idempotent). Detects "already exists" by stdout
    content; falls back to raising :class:`ShellError` for any other
    non-zero exit. See PR #16 review C-3 + post-merge laptop Bug 1.

    Args:
      hermes_bin: Absolute path to the ``hermes`` console script
        (typically ``<venv>/bin/hermes``). Use
        :func:`detect_hermes_venv` to find the venv.
      adapter_auth_key: Optional bearer to pre-populate
        ``MYAH_ADAPTER_AUTH_KEY`` in the install subprocess's env. The
        plugin's post-install hook reads this to skip its interactive
        prompt — required for ``--non-interactive`` installs. Defaults
        to inheriting the parent env (which already has the value if
        ``write_token_to_all_slots`` ran first).
      repo: Plugin repo slug. The default points at the public Myah
        plugin; override only for fork testing.

    Raises:
      ShellError: when ``hermes plugins install`` returns non-zero for
        any reason other than already-installed, or when ``hermes
        plugins enable`` returns non-zero. The install command surfaces
        this as a Phase 5b failure with a stack trace and exits 1.
    """
    install_env: dict[str, str] = {**os.environ}
    if adapter_auth_key:
        install_env['MYAH_ADAPTER_AUTH_KEY'] = adapter_auth_key

    install_result = run(
        [str(hermes_bin), 'plugins', 'install', repo],
        check=False,
        env=install_env,
    )
    if install_result.returncode != 0:
        # Hermes 0.14.0 exits non-zero with "Plugin 'myah' already exists"
        # on re-install. Treat as success — the plugin IS installed.
        if 'already exists' in install_result.stdout.lower():
            pass  # idempotent re-run
        else:
            raise ShellError(
                [str(hermes_bin), 'plugins', 'install', repo],
                install_result,
            )

    run(
        [str(hermes_bin), 'plugins', 'enable', 'myah'],
        check=True,
        env=install_env,
    )


def resolve_hermes_binary_or_exit(*, command_hint: str = '') -> Path:
    """Detect the user's system Hermes venv and return the absolute ``<venv>/bin/hermes`` path.

    Exits with code 2 (via ``typer.Exit``) if no Hermes venv is found,
    with a clear Rich-styled message that points the user at the
    canonical curl-bash installer. The optional ``command_hint``
    is appended in dim text so the operator sees which Myah verb
    triggered the lookup (e.g. ``hermes plugins``, ``hermes config``).

    Lazy imports for ``typer`` and ``rich.console`` keep the CLI
    cold-start budget intact when this helper is referenced but never
    invoked (the typical ``myah --help`` path).
    """
    # typer + rich are lazy-imported to honor the cold-start sentinel.
    # The lib/cli modules are loaded on import of any cli/* command
    # module — without this lazy guard we'd pay Rich's ~50ms init even
    # when the user just runs `myah --help`.
    import typer
    from rich.console import Console

    try:
        venv = detect_hermes_venv()
    except RuntimeError as exc:
        hint_suffix = f'\n[dim]{command_hint}[/]' if command_hint else ''
        Console().print(
            f'[red bold]Could not locate hermes-agent.[/]\n[dim]{exc}[/]\n'
            f'[dim]Install Hermes via the canonical installer; see '
            f'https://hermes-agent.nousresearch.com/docs/installation[/]'
            f'{hint_suffix}'
        )
        raise typer.Exit(code=2) from exc
    return venv / 'bin' / 'hermes'


__all__ = [
    'ShellError',
    'bootstrap_pip',
    'detect_hermes_venv',
    'detect_installed_plugin_sha',
    'materialize_dashboard_shim',
    'pip_install_plugin_at_sha',
    'read_pinned_plugin_sha_from_dockerfile',
    'register_plugin_with_gateway',
    'resolve_hermes_binary_or_exit',
    'verify_dashboard_plugin_mounted',
    'verify_gateway_plugin_bound',
]
