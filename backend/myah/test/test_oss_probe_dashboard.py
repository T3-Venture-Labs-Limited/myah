"""Tests for the dashboard_running field added to /api/v1/oss/probe.

The probe was already aware of gateway reachability and Myah-plugin
installation. This file pins the behaviour added to surface dashboard
state distinctly so the welcome screen can render a dedicated
DashboardDownError state.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from myah.routers import oss as oss_router_module


@pytest.fixture
def app() -> FastAPI:
    """Lightweight FastAPI app with just the OSS router mounted.

    Mirrors the fixture in test_oss_probe.py. Avoids importing
    ``myah.main`` (which pulls in the full router graph, DB engines,
    OAuth manager, etc.) for these isolated probe tests.
    """
    inner = FastAPI()
    inner.include_router(oss_router_module.router)
    return inner


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    return TestClient(app)


def _make_response(status: int, body: dict | None = None) -> httpx.Response:
    return httpx.Response(status, json=body or {})


class TestProbeDashboardRunning:
    """Cover every combination of {gateway up/down, dashboard up/down}."""

    def test_gateway_up_dashboard_up_includes_running_true(self, client: TestClient) -> None:
        """When the dashboard responds 200, probe reports dashboard_running=true."""

        def fake_get(url: str, **kwargs):
            if url.endswith('/health'):
                return _make_response(200, {'ok': True})
            if url.endswith('/myah/health'):
                return _make_response(200, {'version': '0.1.0'})
            if '9119' in url:  # dashboard port — matches default _oss_web_port
                return _make_response(200, {'status': 'ok'})
            if '/myah/v1/admin/providers' in url:
                return _make_response(200, {'providers': []})
            return _make_response(404)

        with patch.object(oss_router_module, '_http_get', side_effect=fake_get):
            r = client.get('/api/v1/oss/probe')

        assert r.status_code == 200
        body = r.json()
        assert body['hermes_reachable'] is True
        assert body['plugin_installed'] is True
        assert body['dashboard_running'] is True
        assert body['dashboard_url'].endswith(':9119')

    def test_gateway_up_dashboard_down_reports_running_false(self, client: TestClient) -> None:
        """Dashboard connection-refused → dashboard_running=false, but probe still 200."""

        def fake_get(url: str, **kwargs):
            if url.endswith('/health'):
                return _make_response(200, {'ok': True})
            if url.endswith('/myah/health'):
                return _make_response(200, {'version': '0.1.0'})
            if '9119' in url:
                raise httpx.ConnectError('Connection refused')
            if '/myah/v1/admin/providers' in url:
                return _make_response(200, {'providers': []})
            return _make_response(404)

        with patch.object(oss_router_module, '_http_get', side_effect=fake_get):
            r = client.get('/api/v1/oss/probe')

        assert r.status_code == 200
        body = r.json()
        assert body['hermes_reachable'] is True
        assert body['plugin_installed'] is True
        assert body['dashboard_running'] is False
        assert body['dashboard_url'].endswith(':9119')

    def test_gateway_down_dashboard_omitted(self, client: TestClient) -> None:
        """When the gateway is unreachable, dashboard_running is still reported
        (False) so the frontend can short-circuit on whichever check failed first.
        """

        def fake_get(url: str, **kwargs):
            raise httpx.ConnectError('Connection refused')

        with patch.object(oss_router_module, '_http_get', side_effect=fake_get):
            r = client.get('/api/v1/oss/probe')

        body = r.json()
        assert body['hermes_reachable'] is False
        assert body['dashboard_running'] is False

    def test_dashboard_401_treated_as_running_but_unauthenticated(self, client: TestClient) -> None:
        """A 401 from the dashboard means it IS running but the token is bad —
        we still report dashboard_running=true so the welcome screen
        distinguishes "dashboard down" from "token desync".

        The probe deliberately does not surface auth state — that's diagnostics'
        job. dashboard_running answers "is there a listener?", not "are we
        authorised?".
        """

        def fake_get(url: str, **kwargs):
            if url.endswith('/health'):
                return _make_response(200, {'ok': True})
            if url.endswith('/myah/health'):
                return _make_response(200, {'version': '0.1.0'})
            if '9119' in url:
                return _make_response(401, {'detail': 'invalid token'})
            if '/myah/v1/admin/providers' in url:
                return _make_response(200, {'providers': []})
            return _make_response(404)

        with patch.object(oss_router_module, '_http_get', side_effect=fake_get):
            r = client.get('/api/v1/oss/probe')

        body = r.json()
        assert body['dashboard_running'] is True
