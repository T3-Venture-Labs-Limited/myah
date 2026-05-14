"""Tests for the hermes_web client (Workstream A Phase 0).

Mocks both:
  * Containers.get_by_user_id  -> returns a stub ContainerModel
  * httpx.AsyncClient.request  -> returns a synthetic Response

so the test exercises only the request-shaping logic (URL, headers, body)
without booting a real container or HTTP server.
"""

import json
from typing import Optional

import httpx
import pytest

from myah.models.containers import ContainerModel
from myah.models.users import UserModel
from myah.utils import hermes_web


def _make_user(user_id: str = 'u-test') -> UserModel:
    return UserModel(
        id=user_id,
        email=f'{user_id}@test.local',
        name=user_id,
        role='user',
        last_active_at=0,
        updated_at=0,
        created_at=0,
    )


def _make_record(
    *,
    web_port: Optional[int] = 9119,
    web_session_token: Optional[str] = 'test-token-xyz',
) -> ContainerModel:
    return ContainerModel(
        id='c-test',
        user_id='u-test',
        container_id='cid',
        container_name='myah-agent-utest',
        host_port=8642,
        vite_port=5174,
        vnc_port=5900,
        web_port=web_port,
        web_session_token=web_session_token,
        status='running',
        created_at=0,
        last_active=0,
    )


class _FakeResponse:
    """Minimal httpx.Response stand-in for the bits hermes_web reads."""

    def __init__(self, *, status_code: int, body, headers: Optional[dict] = None):
        self.status_code = status_code
        self._body = body
        self.headers = headers or {'content-type': 'application/json'}
        if isinstance(body, (dict, list)):
            self.content = json.dumps(body).encode()
            self.text = json.dumps(body)
        elif body is None:
            self.content = b''
            self.text = ''
        else:
            self.content = str(body).encode()
            self.text = str(body)

    def json(self):
        if isinstance(self._body, (dict, list)):
            return self._body
        return json.loads(self._body)


def _patch_record(monkeypatch, record: Optional[ContainerModel]):
    """Stub the container resolution chain.

    ``hermes_web._ensure_container`` first checks ``Containers.get_by_user_id``
    for a recently-active running container; on a miss it calls
    ``get_or_create_container`` which talks to Docker. Tests should never
    reach Docker, so we patch BOTH paths to return the test record.
    """
    monkeypatch.setattr(
        'myah.utils.hermes_web.Containers.get_by_user_id',
        lambda _user_id: record,
    )
    # Stub the cold-path spawn-or-restart helper. The patch target is the
    # function inside ``myah.routers.containers``; ``hermes_web`` does
    # a local import, so this matches the import path resolved at runtime.

    async def _async_record(_user_id: str):
        return record

    monkeypatch.setattr(
        'myah.routers.containers.get_or_create_container',
        _async_record,
    )


def _patch_client(monkeypatch, captured: dict, *, response: _FakeResponse):
    """Stub httpx.AsyncClient so the request never leaves the process."""

    class _FakeClient:
        def __init__(self, *args, **kwargs):
            captured['client_init'] = kwargs

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def request(self, method, url, **kwargs):
            captured['method'] = method
            captured['url'] = url
            captured['kwargs'] = kwargs
            return response

    monkeypatch.setattr('myah.utils.hermes_web.httpx.AsyncClient', _FakeClient)


@pytest.mark.asyncio
async def test_web_call_sends_bearer_token_and_correct_url(monkeypatch):
    record = _make_record(web_port=9119, web_session_token='secret-abc')
    _patch_record(monkeypatch, record)

    captured: dict = {}
    _patch_client(
        monkeypatch,
        captured,
        response=_FakeResponse(
            status_code=200,
            body={'status': 'ok', 'plugin': 'myah-admin'},
        ),
    )

    result = await hermes_web.web_call(
        _make_user(),
        'GET',
        '/api/plugins/myah-admin/health',
    )

    # Authorization header must use the per-container token.
    headers = captured['kwargs']['headers']
    assert headers['Authorization'] == 'Bearer secret-abc'

    # URL must include the container's web_port and the verbatim path.
    assert captured['url'].endswith(':9119/api/plugins/myah-admin/health')

    # Method preserved verbatim.
    assert captured['method'] == 'GET'

    # Parsed JSON body returned.
    assert result['status'] == 200
    assert result['body'] == {'status': 'ok', 'plugin': 'myah-admin'}


@pytest.mark.asyncio
async def test_web_call_forwards_json_body(monkeypatch):
    record = _make_record()
    _patch_record(monkeypatch, record)

    captured: dict = {}
    _patch_client(
        monkeypatch,
        captured,
        response=_FakeResponse(status_code=200, body={'ok': True}),
    )

    payload = {'enable': True, 'name': 'github'}
    await hermes_web.web_call(
        _make_user(),
        'POST',
        '/api/plugins/myah-admin/toolset',
        json_body=payload,
    )

    assert captured['kwargs']['json'] == payload


@pytest.mark.asyncio
async def test_web_call_forwards_text_body_as_raw_content(monkeypatch):
    """text_body sends raw bytes (not JSON-encoded) — used for PUT SOUL.md."""
    record = _make_record()
    _patch_record(monkeypatch, record)

    captured: dict = {}
    _patch_client(
        monkeypatch,
        captured,
        response=_FakeResponse(status_code=200, body={'ok': True}),
    )

    await hermes_web.web_call(
        _make_user(),
        'PUT',
        '/api/plugins/myah-admin/config/soul',
        text_body='You are Myah.\n',
        headers={'If-Match': '"sha256-abc"'},
    )

    # text_body must be forwarded via httpx ``content=``, not ``json=``.
    assert captured['kwargs'].get('content') == 'You are Myah.\n'
    assert 'json' not in captured['kwargs'] or captured['kwargs']['json'] is None
    assert captured['kwargs']['headers'].get('If-Match') == '"sha256-abc"'


@pytest.mark.asyncio
async def test_web_call_returns_text_body_for_non_json_content_type(monkeypatch):
    record = _make_record()
    _patch_record(monkeypatch, record)

    captured: dict = {}
    _patch_client(
        monkeypatch,
        captured,
        response=_FakeResponse(
            status_code=200,
            body='plain text body',
            headers={'content-type': 'text/plain'},
        ),
    )

    result = await hermes_web.web_call(_make_user(), 'GET', '/api/plugins/myah-admin/raw')
    assert result['body'] == 'plain text body'


@pytest.mark.asyncio
async def test_web_call_does_not_raise_on_4xx(monkeypatch):
    """web_call returns the status verbatim — only web_call_or_raise raises."""
    record = _make_record()
    _patch_record(monkeypatch, record)

    captured: dict = {}
    _patch_client(
        monkeypatch,
        captured,
        response=_FakeResponse(status_code=401, body={'detail': 'Unauthorized'}),
    )

    result = await hermes_web.web_call(
        _make_user(),
        'GET',
        '/api/plugins/myah-admin/health',
    )
    assert result['status'] == 401
    assert result['body'] == {'detail': 'Unauthorized'}


@pytest.mark.asyncio
async def test_web_call_or_raise_propagates_500_as_http_exception(monkeypatch):
    from fastapi import HTTPException

    record = _make_record()
    _patch_record(monkeypatch, record)

    captured: dict = {}
    _patch_client(
        monkeypatch,
        captured,
        response=_FakeResponse(status_code=500, body={'detail': 'kaboom'}),
    )

    with pytest.raises(HTTPException) as ei:
        await hermes_web.web_call_or_raise(
            _make_user(),
            'GET',
            '/api/plugins/myah-admin/explode',
        )
    assert ei.value.status_code == 500


@pytest.mark.asyncio
async def test_web_call_raises_503_when_container_missing(monkeypatch):
    from fastapi import HTTPException

    _patch_record(monkeypatch, None)

    with pytest.raises(HTTPException) as ei:
        await hermes_web.web_call(_make_user(), 'GET', '/api/plugins/myah-admin/health')
    assert ei.value.status_code == 503


@pytest.mark.asyncio
async def test_web_call_raises_503_when_web_port_missing(monkeypatch):
    from fastapi import HTTPException

    record = _make_record(web_port=None)
    _patch_record(monkeypatch, record)

    with pytest.raises(HTTPException) as ei:
        await hermes_web.web_call(_make_user(), 'GET', '/api/plugins/myah-admin/health')
    assert ei.value.status_code == 503


@pytest.mark.asyncio
async def test_web_call_raises_503_when_token_missing(monkeypatch):
    from fastapi import HTTPException

    record = _make_record(web_session_token=None)
    _patch_record(monkeypatch, record)

    with pytest.raises(HTTPException) as ei:
        await hermes_web.web_call(_make_user(), 'GET', '/api/plugins/myah-admin/health')
    assert ei.value.status_code == 503


@pytest.mark.asyncio
async def test_web_call_503_on_connect_error(monkeypatch):
    from fastapi import HTTPException

    record = _make_record()
    _patch_record(monkeypatch, record)

    class _BoomClient:
        def __init__(self, *a, **kw): ...
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def request(self, *a, **kw):
            raise httpx.ConnectError('refused')

    monkeypatch.setattr('myah.utils.hermes_web.httpx.AsyncClient', _BoomClient)

    with pytest.raises(HTTPException) as ei:
        await hermes_web.web_call(_make_user(), 'GET', '/api/plugins/myah-admin/health')
    assert ei.value.status_code == 503


@pytest.mark.asyncio
async def test_web_call_504_on_timeout(monkeypatch):
    from fastapi import HTTPException

    record = _make_record()
    _patch_record(monkeypatch, record)

    class _SlowClient:
        def __init__(self, *a, **kw): ...
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def request(self, *a, **kw):
            raise httpx.TimeoutException('slow')

    monkeypatch.setattr('myah.utils.hermes_web.httpx.AsyncClient', _SlowClient)

    with pytest.raises(HTTPException) as ei:
        await hermes_web.web_call(_make_user(), 'GET', '/api/plugins/myah-admin/health')
    assert ei.value.status_code == 504


@pytest.mark.asyncio
async def test_web_call_emits_sentry_breadcrumb(monkeypatch):
    """Each call must add an info-level breadcrumb so Phase 0 rollout is
    traceable in Sentry without per-call logger noise."""
    record = _make_record()
    _patch_record(monkeypatch, record)

    captured: dict = {}
    _patch_client(
        monkeypatch,
        captured,
        response=_FakeResponse(status_code=200, body={'ok': True}),
    )

    crumbs: list = []
    monkeypatch.setattr(
        'myah.utils.hermes_web.sentry_sdk.add_breadcrumb',
        lambda **kwargs: crumbs.append(kwargs),
    )

    await hermes_web.web_call(_make_user('u-bread'), 'GET', '/api/plugins/myah-admin/health')

    assert len(crumbs) == 1
    breadcrumb = crumbs[0]
    assert breadcrumb['category'] == 'hermes_web'
    assert breadcrumb['level'] == 'info'
    assert 'GET' in breadcrumb['message']
    assert '/api/plugins/myah-admin/health' in breadcrumb['message']
    assert breadcrumb['data']['user_id'] == 'u-bread'
