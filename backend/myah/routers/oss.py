"""
OSS-only endpoints — first-run UX surface.

The OSS deployment is single-user with no login. Two endpoints make the
first-run experience work:

* ``GET /api/v1/oss/probe`` — called by the frontend on every page load
  to determine reachability of the host-side Hermes Agent + its Myah
  plugin, and to surface the ``first_run`` flag (so the front-end
  knows whether to show the Welcome screen vs the chat list).

* ``POST /api/v1/oss/first_run_complete`` — flips ``first_run`` to
  False after the user clicks Continue on the Welcome screen.

The probe is the gateway to the entire OSS UX: it produces the data the
``Welcome.svelte`` / ``HermesDownError.svelte`` / ``PluginMissingError.svelte``
components render.

Plugin URLs are intentionally NOT routed through ``myah.utils.hermes_web``
because that module is built around per-user-container web_session_tokens,
which OSS doesn't have. The probe talks to the user's host-side hermes
directly via plain ``httpx.get`` (with a tight timeout to keep page-load
fast).

References:
- spec §8 "First-Run UX"
- plan Phase 2 Workstream C, Task C.1
- docs/oss-launch/vm-testing-followups.md F3 (auto-skip when provider configured)
"""

from __future__ import annotations

import os
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException

router = APIRouter(prefix='/api/v1/oss', tags=['oss'])

# Tight timeout — the probe runs on every page load, so a long timeout
# would make a wedged hermes feel like a wedged Myah. 5 seconds is more
# than enough for a healthy /health round-trip and short enough that the
# blocking error appears quickly when something's actually wrong.
PROBE_TIMEOUT = 5.0


def _http_get(url: str, **kwargs: Any) -> httpx.Response:
    """Wrapper around ``httpx.get`` so unit tests can monkeypatch network."""
    return httpx.get(url, timeout=PROBE_TIMEOUT, **kwargs)


def _hermes_url() -> str:
    """Resolve the host-side hermes gateway URL from env.

    Defaults to ``host.docker.internal:8642`` — works on Mac/Windows out
    of the box, and on Linux via the ``extra_hosts`` mapping in
    docker-compose.yml.
    """
    host = os.environ.get('MYAH_AGENT_HOST', 'host.docker.internal').strip()
    port = os.environ.get('MYAH_HERMES_CHAT_PORT', '8642').strip() or '8642'
    return f'http://{host}:{port}'


def _read_config() -> dict:
    """Read the full config dict from the config table.

    Indirection exists so tests can mock the read without poking at
    myah.config's module-level cache.
    """
    from myah.config import get_config

    try:
        cfg = get_config()
    except Exception:
        return {}
    return cfg if isinstance(cfg, dict) else {}


def _save_config(config: dict) -> bool:
    """Write the full config dict back. Returns True on success."""
    from myah.config import save_config

    return save_config(config)


def _read_first_run_flag() -> bool:
    """Read the ``first_run`` flag from the config table.

    Defaults to True when unset — that's the "fresh install" case where
    the Welcome screen should render. The oss_seed_user migration
    (d5e3b1a9c742) seeds the admin user but intentionally leaves the
    flag unset; the default-true ensures Welcome appears on first boot.

    Tests monkeypatch this function; do NOT inline its body into probe().
    """
    config = _read_config()
    oss_config = config.get('oss', {})
    if not isinstance(oss_config, dict):
        return True
    # Explicit False -> Welcome has been seen and dismissed.
    return oss_config.get('first_run', True) is not False


@router.get('/probe')
def probe() -> dict[str, Any]:
    """Snapshot of hermes + plugin reachability for the OSS frontend.

    The browser hits this on every page load before deciding what to
    render. The response is deliberately small + always-200 (no failure
    is expressed as a non-200 — the frontend gets a structured shape
    either way) so the call never throws from the browser's perspective.
    """
    hermes_url = _hermes_url()
    result: dict[str, Any] = {
        'hermes_reachable': False,
        'hermes_url': hermes_url,
        'plugin_installed': False,
        'plugin_version': None,
        'providers_configured': [],
        'first_run': _read_first_run_flag(),
    }

    # 1. Hermes gateway /health
    try:
        r = _http_get(f'{hermes_url}/health')
        if r.status_code == 200:
            result['hermes_reachable'] = True
    except Exception:
        # Connection refused, timeout, DNS failure -> hermes is down.
        # Short-circuit: nothing else to ask if the gateway is unreachable.
        return result

    if not result['hermes_reachable']:
        # 2xx that isn't 200 still means something's off — surface it as
        # "down" so the user gets the blocking error, not a wedge.
        return result

    # 2. Plugin /myah/health — verified at
    # myah-hermes-plugin/myah_hermes_plugin/myah_platform/adapter.py per
    # spec review H-1. NOT /myah/v1/admin/health.
    try:
        r = _http_get(f'{hermes_url}/myah/health')
        if r.status_code == 200:
            result['plugin_installed'] = True
            try:
                result['plugin_version'] = r.json().get('version')
            except Exception:
                # Plugin responded 200 without a parseable JSON version —
                # plugin is installed, version just unknown.
                pass
    except Exception:
        # Plugin endpoint blew up mid-call — treat as missing rather
        # than crash the probe.
        return result

    # 3. Providers configured (only if the plugin is reachable).
    # Used by the frontend to auto-skip the provider-connection screen
    # when at least one provider is already wired up (F3 fix from
    # docs/oss-launch/vm-testing-followups.md).
    if result['plugin_installed']:
        try:
            r = _http_get(f'{hermes_url}/api/plugins/myah-admin/providers?visible=all')
            if r.status_code == 200:
                providers = r.json()
                if isinstance(providers, dict):
                    result['providers_configured'] = [
                        name
                        for name, info in providers.items()
                        if isinstance(info, dict) and info.get('connected') is True
                    ]
        except Exception:
            # Probe is best-effort here; leaving providers_configured = []
            # is harmless (frontend just shows the connect screen).
            pass

    return result


def _int_env(name: str, default: int) -> int:
    """Read an integer env var. Falls back to ``default`` if missing or invalid."""
    raw = os.environ.get(name, '').strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


@router.get('/diagnostics')
def diagnostics() -> dict[str, Any]:
    """Detailed diagnostics — superset of /probe.

    Used by the /diagnostics page (linked from blocking-error screens
    and the Help menu). Returns everything /probe returns PLUS:

      * agent_ports: the three ports the platform is configured to use
        (gateway, standalone, web). Helps the user verify their hermes
        is bound to the expected ports.
      * platform_port_binding: a string description of the platform's
        own port binding ('127.0.0.1:8080') so users can see at a glance
        whether they're localhost-only.
      * oss_version: the running OSS version (matches the GHCR image tag).
    """
    probe_result = probe()
    return {
        **probe_result,
        'agent_ports': {
            'gateway': _int_env('MYAH_HERMES_CHAT_PORT', 8642),
            'standalone': _int_env('MYAH_HERMES_GATEWAY_PORT', 8643),
            'web': _int_env('MYAH_HERMES_WEB_PORT', 9119),
        },
        'platform_port_binding': '127.0.0.1:8080',
        'oss_version': os.environ.get('MYAH_OSS_VERSION', '0.1.0-beta.1'),
    }


@router.post('/first_run_complete')
def first_run_complete() -> dict[str, bool]:
    """Flip the ``oss.first_run`` flag to False.

    Called by the front-end when the user clicks Continue on the
    Welcome screen. Subsequent probes return ``first_run=False`` so the
    frontend routes to the chat list instead of re-showing Welcome.

    Merges into the existing config dict — preserves all other keys
    (ui.theme, etc.). Idempotent: calling twice in a row is fine; the
    second call rewrites the same value.

    Returns 500 if the DB write fails so the front-end can surface a
    real error instead of silently never advancing.
    """
    config = _read_config()
    if not isinstance(config, dict):
        config = {}

    oss_section = config.get('oss')
    if not isinstance(oss_section, dict):
        oss_section = {}
    oss_section['first_run'] = False
    config['oss'] = oss_section

    if not _save_config(config):
        raise HTTPException(
            status_code=500,
            detail='Failed to persist first_run=false to the config table.',
        )

    return {'first_run': False}
