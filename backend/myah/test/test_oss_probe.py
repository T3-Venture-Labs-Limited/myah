"""
Tests for the OSS first-run probe endpoint (Workstream C Task C.1).

The probe is called by the OSS frontend on every page load to determine:
1. Whether the host-side Hermes Agent gateway is reachable
2. Whether the Myah plugin is installed in that Hermes
3. The first_run flag (so the front-end can show Welcome vs chat list)

The probe also surfaces ``providers_configured`` (the list of LLM providers
the user has already wired up in Hermes' .env) so the front-end can auto-
skip the provider-connection screen when a provider is already present —
this is the F3 fix from docs/oss-launch/vm-testing-followups.md.

The probe URL on the plugin side is ``/myah/health`` (verified against
the plugin's ``myah_hermes_plugin/myah_platform/adapter.py`` — now living
at the public T3-Venture-Labs-Limited/myah-hermes-plugin repo — per spec
review H-1; NOT ``/myah/v1/admin/health``).

Refs spec §8, plan Phase 2 Workstream C Task C.1.
"""

from unittest.mock import MagicMock, patch

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from myah.routers import oss as oss_router_module


@pytest.fixture
def app():
    """Lightweight FastAPI app with just the OSS router mounted.

    Avoids importing myah.main (which pulls in the full router graph,
    DB engines, OAuth manager, etc.) for these isolated probe tests.
    """
    app = FastAPI()
    app.include_router(oss_router_module.router)
    return app


@pytest.fixture
def client(app):
    return TestClient(app)


# ── Happy path: hermes + plugin both healthy ────────────────────────────


def test_probe_happy_path_all_green(client):
    """When hermes /health AND plugin /myah/health both return 200,
    probe returns hermes_reachable=True and plugin_installed=True."""
    with patch.object(oss_router_module, '_http_get') as mock_get:
        def fake_get(url, **kw):
            resp = MagicMock()
            resp.status_code = 200
            # Hermes gateway /health (NOT prefixed with /myah/)
            if url.endswith('/health') and '/myah/' not in url:
                resp.json.return_value = {'status': True}
            # Plugin /myah/health (verified per spec review H-1)
            elif url.endswith('/myah/health'):
                resp.json.return_value = {'status': 'ok', 'version': '1.1.0'}
            return resp

        mock_get.side_effect = fake_get
        r = client.get('/api/v1/oss/probe')

    assert r.status_code == 200, f'Expected 200, got {r.status_code}: {r.text}'
    body = r.json()
    assert body['hermes_reachable'] is True, body
    assert body['plugin_installed'] is True, body
    assert body['plugin_version'] == '1.1.0', body
    assert 'hermes_url' in body
    assert 'first_run' in body
    assert 'providers_configured' in body


def test_probe_returns_hermes_url_from_env(client, monkeypatch):
    """The hermes_url field reflects MYAH_AGENT_HOST + MYAH_HERMES_CHAT_PORT env vars."""
    monkeypatch.setenv('MYAH_AGENT_HOST', 'my-hermes.local')
    monkeypatch.setenv('MYAH_HERMES_CHAT_PORT', '9999')

    with patch.object(oss_router_module, '_http_get') as mock_get:
        mock_get.side_effect = httpx.ConnectError('connection refused')
        r = client.get('/api/v1/oss/probe')

    assert r.json()['hermes_url'] == 'http://my-hermes.local:9999'


# ── Sad path: hermes connection refused ────────────────────────────────


def test_probe_hermes_down_short_circuits(client):
    """When hermes gateway is unreachable, probe returns
    hermes_reachable=False AND plugin_installed=False (can't check plugin
    if hermes itself is down)."""
    with patch.object(oss_router_module, '_http_get') as mock_get:
        mock_get.side_effect = httpx.ConnectError('connection refused')
        r = client.get('/api/v1/oss/probe')

    assert r.status_code == 200
    body = r.json()
    assert body['hermes_reachable'] is False
    assert body['plugin_installed'] is False
    assert body['plugin_version'] is None


def test_probe_hermes_timeout_treated_as_down(client):
    """Slow hermes (>5s timeout) is treated as down — user gets the blocking
    error rather than a hung browser tab."""
    with patch.object(oss_router_module, '_http_get') as mock_get:
        mock_get.side_effect = httpx.TimeoutException('timed out')
        r = client.get('/api/v1/oss/probe')

    body = r.json()
    assert body['hermes_reachable'] is False


# ── Sad path: hermes responds but plugin missing ───────────────────────


def test_probe_plugin_missing_distinguished_from_hermes_down(client):
    """When hermes /health returns 200 but /myah/health returns 404, probe
    returns hermes_reachable=True AND plugin_installed=False — distinct
    error state so the frontend can show the plugin-missing screen with
    the right remediation."""
    with patch.object(oss_router_module, '_http_get') as mock_get:
        def fake_get(url, **kw):
            resp = MagicMock()
            if url.endswith('/health') and '/myah/' not in url:
                resp.status_code = 200
                resp.json.return_value = {'status': True}
            elif url.endswith('/myah/health'):
                resp.status_code = 404
            return resp

        mock_get.side_effect = fake_get
        r = client.get('/api/v1/oss/probe')

    body = r.json()
    assert body['hermes_reachable'] is True
    assert body['plugin_installed'] is False


def test_probe_plugin_endpoint_error_treated_as_missing(client):
    """If the plugin /myah/health call raises (network blip mid-probe),
    treat plugin as missing rather than crashing the probe."""
    call_count = {'n': 0}

    with patch.object(oss_router_module, '_http_get') as mock_get:
        def fake_get(url, **kw):
            call_count['n'] += 1
            if url.endswith('/health') and '/myah/' not in url:
                resp = MagicMock()
                resp.status_code = 200
                resp.json.return_value = {'status': True}
                return resp
            # Plugin call raises
            raise httpx.ConnectError('plugin port refused')

        mock_get.side_effect = fake_get
        r = client.get('/api/v1/oss/probe')

    body = r.json()
    assert body['hermes_reachable'] is True, 'hermes was reachable; should report so'
    assert body['plugin_installed'] is False, 'plugin call failed -> treated as missing'


# ── first_run flag ───────────────────────────────────────────────────


def test_probe_first_run_unset_defaults_to_true(client, monkeypatch):
    """Fresh install: no first_run key in config -> probe returns first_run=True
    so the frontend shows the Welcome screen."""
    monkeypatch.setattr(
        oss_router_module, '_read_first_run_flag', lambda: True
    )
    with patch.object(oss_router_module, '_http_get') as mock_get:
        mock_get.side_effect = httpx.ConnectError('down')
        body = client.get('/api/v1/oss/probe').json()

    assert body['first_run'] is True


def test_probe_first_run_after_continue_is_false(client, monkeypatch):
    """After the user clicks Continue (which flips the flag via
    /first_run_complete), subsequent probes return first_run=False."""
    monkeypatch.setattr(
        oss_router_module, '_read_first_run_flag', lambda: False
    )
    with patch.object(oss_router_module, '_http_get') as mock_get:
        mock_get.side_effect = httpx.ConnectError('down')
        body = client.get('/api/v1/oss/probe').json()

    assert body['first_run'] is False


# ── providers_configured (F3 auto-skip support) ───────────────────────


def test_probe_providers_configured_populated_when_plugin_reachable(client):
    """When the plugin is reachable, probe asks it which providers have
    credentials and returns the list. The frontend uses this to auto-skip
    the provider-connection screen (F3 from vm-testing-followups.md).

    The probe hits ``GET /myah/v1/admin/providers`` on the gateway-adapter
    port (8643) with the platform's standard bearer auth — fix for D5.
    Response shape is ``{"providers": [{"id": ..., "has_credential": ...}, ...]}``.
    """
    with patch.object(oss_router_module, '_http_get') as mock_get:
        def fake_get(url, **kw):
            resp = MagicMock()
            resp.status_code = 200
            if url.endswith('/health') and '/myah/' not in url:
                resp.json.return_value = {'status': True}
            elif url.endswith('/myah/health'):
                resp.json.return_value = {'status': 'ok', 'version': '1.1.0'}
            elif url.endswith('/myah/v1/admin/providers'):
                resp.json.return_value = {
                    'providers': [
                        {'id': 'openrouter', 'has_credential': True},
                        {'id': 'anthropic', 'has_credential': False},
                        {'id': 'kimi', 'has_credential': True},
                    ]
                }
            return resp

        mock_get.side_effect = fake_get
        body = client.get('/api/v1/oss/probe').json()

    # The credentialed ones come through; uncredentialed omitted.
    assert 'openrouter' in body['providers_configured']
    assert 'kimi' in body['providers_configured']
    assert 'anthropic' not in body['providers_configured']


def test_probe_providers_endpoint_called_on_gateway_port_with_bearer(client, monkeypatch):
    """The provider-detection call MUST target the gateway-adapter port
    (MYAH_HERMES_GATEWAY_PORT, default 8643) with the platform's bearer
    token — NOT the api-server port (8642) without auth (the D5
    regression). Verifies the URL + Authorization header the probe
    actually sends.
    """
    monkeypatch.setenv('MYAH_AGENT_HOST', 'host.docker.internal')
    monkeypatch.setenv('MYAH_HERMES_CHAT_PORT', '8642')
    monkeypatch.setenv('MYAH_HERMES_GATEWAY_PORT', '8643')
    monkeypatch.setenv('MYAH_AGENT_BEARER_TOKEN', 'sk-test-bearer')

    seen_calls = []

    with patch.object(oss_router_module, '_http_get') as mock_get:
        def fake_get(url, **kw):
            seen_calls.append((url, kw.get('headers', {})))
            resp = MagicMock()
            resp.status_code = 200
            if url.endswith('/health') and '/myah/' not in url:
                resp.json.return_value = {'status': True}
            elif url.endswith('/myah/health'):
                resp.json.return_value = {'status': 'ok', 'version': '1.1.0'}
            elif url.endswith('/myah/v1/admin/providers'):
                resp.json.return_value = {'providers': []}
            return resp

        mock_get.side_effect = fake_get
        client.get('/api/v1/oss/probe')

    provider_calls = [c for c in seen_calls if 'admin/providers' in c[0]]
    assert provider_calls, (
        f'probe did not call /myah/v1/admin/providers; calls={seen_calls}'
    )
    url, headers = provider_calls[0]
    assert url == 'http://host.docker.internal:8643/myah/v1/admin/providers', (
        f'wrong URL: {url}'
    )
    assert headers.get('Authorization') == 'Bearer sk-test-bearer', (
        f'bearer header missing or wrong: {headers}'
    )


@pytest.mark.parametrize(
    'provider_id',
    [
        'openrouter',
        'openai',
        'anthropic',
        'google',
        'deepseek',
        'xai',
        'nvidia',
        'zai',
        'kimi',
        'stepfun',
        'minimax',
        'minimax-cn',
        'firecrawl',
        'nous',
    ],
)
def test_probe_surfaces_any_hermes_supported_provider(client, provider_id):
    """The probe must surface every provider the plugin reports as
    credentialed — Hermes supports a dozen-plus providers (OpenRouter,
    OpenAI, Anthropic, Google, DeepSeek, xAI, NVIDIA, Z.AI, Kimi,
    StepFun, MiniMax, MiniMax-CN, Firecrawl, Nous, ...). The platform
    delegates the "is this provider configured?" question to the plugin
    (which reads ``~/.hermes/.env`` + ``~/.hermes/auth.json``); the
    platform must NOT have its own whitelist that filters those entries
    out (the D5 regression — the platform side previously hard-coded
    a key-name check that excluded everything except OpenRouter).
    """
    with patch.object(oss_router_module, '_http_get') as mock_get:
        def fake_get(url, **kw):
            resp = MagicMock()
            resp.status_code = 200
            if url.endswith('/health') and '/myah/' not in url:
                resp.json.return_value = {'status': True}
            elif url.endswith('/myah/health'):
                resp.json.return_value = {'status': 'ok', 'version': '1.1.0'}
            elif url.endswith('/myah/v1/admin/providers'):
                resp.json.return_value = {
                    'providers': [{'id': provider_id, 'has_credential': True}]
                }
            return resp

        mock_get.side_effect = fake_get
        body = client.get('/api/v1/oss/probe').json()

    assert provider_id in body['providers_configured'], (
        f'{provider_id!r} not surfaced; got {body["providers_configured"]!r}'
    )


def test_probe_plugin_version_round_trips_from_health_response(client):
    """When the plugin's /myah/health response carries a ``version`` field,
    the probe surfaces it verbatim (fix for D4). The plugin's adapter
    started returning this field once we landed the
    ``_plugin_version()`` helper in
    ``myah_hermes_plugin/myah_platform/adapter.py`` — prior to that the
    field was missing and the probe reported ``plugin_version: null``
    even though the plugin was clearly installed.
    """
    with patch.object(oss_router_module, '_http_get') as mock_get:
        def fake_get(url, **kw):
            resp = MagicMock()
            resp.status_code = 200
            if url.endswith('/health') and '/myah/' not in url:
                resp.json.return_value = {'status': True}
            elif url.endswith('/myah/health'):
                resp.json.return_value = {
                    'status': 'ok',
                    'platform': 'myah',
                    'streams_active': 0,
                    'version': '1.1.0',
                }
            elif url.endswith('/myah/v1/admin/providers'):
                resp.json.return_value = {'providers': []}
            return resp

        mock_get.side_effect = fake_get
        body = client.get('/api/v1/oss/probe').json()

    assert body['plugin_version'] == '1.1.0', body


@pytest.mark.skip(
    reason=(
        'Phase 1 fork-model migration (2026-05-15) extracted the plugin source '
        'to T3-VL/myah-hermes-plugin; the adapter.py file no longer lives in '
        'this repo. The D4 regression is now owned by the plugin repo\'s own '
        'CI (test_directory_style_install.py + the Mode D curated suite that '
        'exercises /myah/health inside the stock container). Above, '
        'test_probe_plugin_version_round_trips_from_health_response still '
        'asserts the platform-side contract: that the probe surfaces the '
        '``version`` field when the plugin emits one.'
    )
)
def test_plugin_health_endpoint_emits_version_field():
    """Historical regression gate for D4 — superseded by the plugin repo's
    own CI after Phase 1 of the fork-model-subtree migration extracted
    the plugin source. Kept (skipped) as documentation of the contract.
    """
    pass


def test_probe_providers_configured_empty_when_plugin_missing(client):
    """When the plugin is missing, providers_configured is [] — the
    probe doesn't pretend to know about providers it can't ask about."""
    with patch.object(oss_router_module, '_http_get') as mock_get:
        def fake_get(url, **kw):
            resp = MagicMock()
            if url.endswith('/health') and '/myah/' not in url:
                resp.status_code = 200
                resp.json.return_value = {'status': True}
            elif url.endswith('/myah/health'):
                resp.status_code = 404
            return resp

        mock_get.side_effect = fake_get
        body = client.get('/api/v1/oss/probe').json()

    assert body['providers_configured'] == []


def test_probe_providers_configured_empty_when_hermes_down(client):
    """When hermes is down, providers_configured is [] (can't check)."""
    with patch.object(oss_router_module, '_http_get') as mock_get:
        mock_get.side_effect = httpx.ConnectError('down')
        body = client.get('/api/v1/oss/probe').json()

    assert body['providers_configured'] == []


# ── /first_run_complete endpoint (Task C.2) ────────────────────────────


def test_first_run_complete_flips_flag_to_false(client):
    """POST /api/v1/oss/first_run_complete sets the first_run flag to False
    in persistent config and returns {'first_run': False}."""
    written: dict = {}

    def fake_save_config(config):
        written['config'] = config
        return True

    with patch('myah.routers.oss._read_config', return_value={'version': 0}):
        with patch('myah.routers.oss._save_config', side_effect=fake_save_config):
            r = client.post('/api/v1/oss/first_run_complete')

    assert r.status_code == 200, r.text
    assert r.json() == {'first_run': False}
    # The written config must have oss.first_run set explicitly to False
    assert written['config'].get('oss', {}).get('first_run') is False


def test_first_run_complete_preserves_other_config_keys(client):
    """The endpoint must merge into existing config, NOT replace it."""
    existing = {
        'version': 0,
        'ui': {'theme': 'dark', 'language': 'en'},
        'oss': {'something_else': 'preserve_me'},
    }
    written: dict = {}

    def fake_save_config(config):
        written['config'] = config
        return True

    with patch('myah.routers.oss._read_config', return_value=existing):
        with patch('myah.routers.oss._save_config', side_effect=fake_save_config):
            client.post('/api/v1/oss/first_run_complete')

    saved = written['config']
    assert saved['ui'] == {'theme': 'dark', 'language': 'en'}
    assert saved['oss']['something_else'] == 'preserve_me'
    assert saved['oss']['first_run'] is False


def test_first_run_complete_idempotent_when_flag_already_false(client):
    """Calling the endpoint twice in a row is a no-op the second time —
    still returns success, doesn't error."""
    written: list = []

    def fake_save_config(config):
        written.append(config)
        return True

    with patch('myah.routers.oss._read_config', return_value={'oss': {'first_run': False}}):
        with patch('myah.routers.oss._save_config', side_effect=fake_save_config):
            r1 = client.post('/api/v1/oss/first_run_complete')
            r2 = client.post('/api/v1/oss/first_run_complete')

    assert r1.status_code == 200
    assert r2.status_code == 200
    # save_config was called both times — that's fine; the second is a no-op
    # write but produces no error. The endpoint's contract is "ensure
    # first_run=False" not "only flip once".
    assert all(c['oss']['first_run'] is False for c in written)


def test_first_run_complete_handles_save_failure(client):
    """If save_config returns False (DB write failure), endpoint returns 500
    so the front-end can surface an error instead of pretending success."""
    with patch('myah.routers.oss._read_config', return_value={}):
        with patch('myah.routers.oss._save_config', return_value=False):
            r = client.post('/api/v1/oss/first_run_complete')

    assert r.status_code == 500
    assert 'failed' in r.json()['detail'].lower()


# ── /diagnostics endpoint (Task C.5) ───────────────────────────────────


def test_diagnostics_returns_probe_data_plus_port_info(client):
    """GET /api/v1/oss/diagnostics returns the probe result PLUS
    additional fields the diagnostics page needs (port binding,
    agent port numbers, oss version)."""
    with patch.object(oss_router_module, '_http_get') as mock_get:
        def fake_get(url, **kw):
            resp = MagicMock()
            resp.status_code = 200
            if url.endswith('/health') and '/myah/' not in url:
                resp.json.return_value = {'status': True}
            elif url.endswith('/myah/health'):
                resp.json.return_value = {'status': 'ok', 'version': '1.1.0'}
            return resp

        mock_get.side_effect = fake_get
        r = client.get('/api/v1/oss/diagnostics')

    assert r.status_code == 200
    body = r.json()
    # Probe fields are included
    assert body['hermes_reachable'] is True
    assert body['plugin_installed'] is True
    # Additional diagnostics fields
    assert 'agent_ports' in body
    assert body['agent_ports']['gateway'] == 8642
    assert body['agent_ports']['standalone'] == 8643
    assert body['agent_ports']['web'] == 9119
    assert 'oss_version' in body
    assert 'platform_port_binding' in body


def test_diagnostics_reflects_env_var_port_overrides(client, monkeypatch):
    """When MYAH_HERMES_*_PORT env vars are set, diagnostics reflects them."""
    monkeypatch.setenv('MYAH_HERMES_CHAT_PORT', '9000')
    monkeypatch.setenv('MYAH_HERMES_GATEWAY_PORT', '9001')
    monkeypatch.setenv('MYAH_HERMES_WEB_PORT', '9002')

    with patch.object(oss_router_module, '_http_get') as mock_get:
        mock_get.side_effect = httpx.ConnectError('down')
        body = client.get('/api/v1/oss/diagnostics').json()

    assert body['agent_ports']['gateway'] == 9000
    assert body['agent_ports']['standalone'] == 9001
    assert body['agent_ports']['web'] == 9002


def test_diagnostics_invalid_port_env_falls_back_to_default(client, monkeypatch):
    """Non-integer port env var doesn't crash diagnostics; falls back."""
    monkeypatch.setenv('MYAH_HERMES_CHAT_PORT', 'not-a-number')

    with patch.object(oss_router_module, '_http_get') as mock_get:
        mock_get.side_effect = httpx.ConnectError('down')
        r = client.get('/api/v1/oss/diagnostics')

    assert r.status_code == 200
    body = r.json()
    assert body['agent_ports']['gateway'] == 8642  # default
