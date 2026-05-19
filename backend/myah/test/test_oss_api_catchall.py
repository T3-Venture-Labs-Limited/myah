from __future__ import annotations

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient


@pytest.fixture
def app_with_catchall():
    app = FastAPI()

    @app.get('/api/v1/auths/health')
    async def _health():
        return {'status': 'ok'}

    @app.get('/api/v1/processes/')
    async def _processes_stub():
        raise HTTPException(status_code=501, detail='Processes require app.myah.dev')

    @app.api_route(
        '/api/{path:path}',
        methods=['GET', 'POST', 'PUT', 'PATCH', 'DELETE', 'OPTIONS', 'HEAD'],
        include_in_schema=False,
    )
    async def _api_not_found(path: str) -> None:
        raise HTTPException(status_code=404, detail='Not Found')

    @app.get('/{path:path}')
    async def _spa_fallback(path: str):
        return JSONResponse(content='<html>index</html>', status_code=200, media_type='text/html')

    return app


@pytest.fixture
def client(app_with_catchall) -> TestClient:
    return TestClient(app_with_catchall, raise_server_exceptions=False)


def test_agent_memory_returns_404_not_html(client: TestClient) -> None:
    r = client.get('/api/v1/agent/memory/messages')
    assert r.status_code == 404
    assert r.headers['content-type'].startswith('application/json')
    assert '<html' not in r.text.lower()


def test_integrations_returns_404_not_html(client: TestClient) -> None:
    r = client.get('/api/v1/integrations')
    assert r.status_code == 404
    assert r.headers['content-type'].startswith('application/json')
    assert '<html' not in r.text.lower()


@pytest.mark.parametrize('path', [
    '/api/v1/nonexistent',
    '/api/v1/agent/memory/messages',
    '/api/v1/integrations',
    '/api/v1/admin/users',
    '/api/v1/honcho/sessions',
    '/api/v1/composio/tools',
    '/api/some/deep/nested/path',
])
def test_unregistered_api_path_returns_404(client: TestClient, path: str) -> None:
    r = client.get(path)
    assert r.status_code == 404, f'GET {path} → {r.status_code}: {r.text}'


@pytest.mark.parametrize('method', ['GET', 'POST', 'PUT', 'PATCH', 'DELETE'])
def test_all_http_verbs_caught(client: TestClient, method: str) -> None:
    r = client.request(method, '/api/v1/integrations')
    assert r.status_code == 404, f'{method} /api/v1/integrations → {r.status_code}'


def test_404_body_is_json_with_detail_key(client: TestClient) -> None:
    r = client.get('/api/v1/agent/memory/messages')
    assert r.status_code == 404
    body = r.json()
    assert isinstance(body, dict)
    assert 'detail' in body


def test_registered_route_unaffected(client: TestClient) -> None:
    r = client.get('/api/v1/auths/health')
    assert r.status_code == 200


def test_processes_501_stub_unaffected(client: TestClient) -> None:
    r = client.get('/api/v1/processes/')
    assert r.status_code == 501


def test_non_api_path_reaches_spa_fallback(client: TestClient) -> None:
    r = client.get('/some/frontend/route')
    assert r.status_code == 200
