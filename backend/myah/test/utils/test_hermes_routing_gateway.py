"""Tests for the gateway-port plumbing added in Tier 2A port-coordination.

Currently covers (a) the ``gateway_port`` column on ``Container``.
The ``_resolve_gateway_port`` helper and path-prefix routing in
``aux_call`` arrive in subsequent commits and add their own tests
here; the imports for the helpers they need (mocks, etc.) get added
alongside those tests so this file stays lint-clean at every step.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from myah.models.containers import ContainerModel


def test_container_model_has_gateway_port_field():
    """Pydantic ContainerModel must accept gateway_port."""
    model = ContainerModel(
        id='abc',
        user_id='u1',
        gateway_port=51234,
        status='running',
        created_at=0,
        last_active=0,
    )
    assert model.gateway_port == 51234


def test_container_model_gateway_port_is_optional():
    """gateway_port must be nullable for backward-compat with existing rows."""
    model = ContainerModel(
        id='abc',
        user_id='u1',
        status='running',
        created_at=0,
        last_active=0,
    )
    assert model.gateway_port is None


class _UserStub:
    """Minimal UserModel stub for unit tests."""

    def __init__(self, user_id='u1'):
        self.id = user_id


@pytest.mark.asyncio
async def test_resolve_gateway_port_returns_gateway_port_when_set():
    """When Container.gateway_port is set, _resolve_gateway_port returns it."""
    from myah.utils.hermes_web import _resolve_gateway_port

    record = MagicMock()
    record.gateway_port = 51234
    record.host_port = 51111

    with patch('myah.utils.hermes_web._ensure_container', new=AsyncMock(return_value=record)):
        port = await _resolve_gateway_port(_UserStub())

    assert port == 51234


@pytest.mark.asyncio
async def test_resolve_gateway_port_falls_back_to_host_port_when_null():
    """When gateway_port is NULL (legacy row), fall back to host_port and log a warning."""
    from loguru import logger as loguru_logger

    from myah.utils.hermes_web import _resolve_gateway_port

    captured: list[str] = []
    sink_id = loguru_logger.add(lambda m: captured.append(str(m)), level='WARNING')

    try:
        record = MagicMock()
        record.gateway_port = None
        record.host_port = 51111
        record.container_id = 'abcdef1234567890'

        with patch(
            'myah.utils.hermes_web._ensure_container', new=AsyncMock(return_value=record)
        ):
            port = await _resolve_gateway_port(_UserStub())

        assert port == 51111
        # Must produce one diagnostic log line so the operator can spot stale rows.
        assert any('gateway_port' in msg for msg in captured)
    finally:
        loguru_logger.remove(sink_id)


@pytest.mark.asyncio
async def test_resolve_gateway_port_raises_when_no_container():
    """Same error contract as _resolve_chat_port: 503 when no host_port either."""
    from fastapi import HTTPException

    from myah.utils.hermes_web import _resolve_gateway_port

    record = MagicMock()
    record.gateway_port = None
    record.host_port = None

    with patch('myah.utils.hermes_web._ensure_container', new=AsyncMock(return_value=record)):
        with pytest.raises(HTTPException) as exc:
            await _resolve_gateway_port(_UserStub())
        assert exc.value.status_code == 503


@pytest.mark.asyncio
async def test_aux_call_routes_myah_v1_to_gateway_port():
    """aux_call('/myah/v1/message', ...) must hit gateway_port, not host_port."""
    from myah.utils.agent_proxy import aux_call

    captured_url: list[str] = []

    class _FakeResponse:
        status_code = 200
        headers = {'content-type': 'application/json'}
        content = b'{}'
        text = '{}'

        def json(self):
            return {}

    class _FakeClient:
        def __init__(self, *a, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return None

        async def request(self, method, url, **kw):
            captured_url.append(url)
            return _FakeResponse()

    with patch('myah.utils.hermes_web._resolve_gateway_port',
               new=AsyncMock(return_value=18643)), \
         patch('myah.utils.hermes_web._resolve_chat_port',
               new=AsyncMock(return_value=18642)), \
         patch('myah.utils.agent_proxy.httpx.AsyncClient', _FakeClient), \
         patch('myah.routers.containers.AGENT_HOST', 'host.docker.internal'), \
         patch('myah.routers.containers.AGENT_BEARER_TOKEN', 'tok'):
        await aux_call(_UserStub(), 'POST', '/myah/v1/message', json_body={'x': 1})

    assert captured_url == ['http://host.docker.internal:18643/myah/v1/message'], captured_url


@pytest.mark.asyncio
async def test_aux_call_routes_v1_runs_to_chat_port():
    """aux_call('/v1/runs', ...) must hit host_port (chat port). UNCHANGED behaviour."""
    from myah.utils.agent_proxy import aux_call

    captured_url: list[str] = []

    class _FakeResponse:
        status_code = 200
        headers = {'content-type': 'application/json'}
        content = b'{}'
        text = '{}'

        def json(self):
            return {}

    class _FakeClient:
        def __init__(self, *a, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return None

        async def request(self, method, url, **kw):
            captured_url.append(url)
            return _FakeResponse()

    with patch('myah.utils.hermes_web._resolve_gateway_port',
               new=AsyncMock(return_value=18643)), \
         patch('myah.utils.hermes_web._resolve_chat_port',
               new=AsyncMock(return_value=18642)), \
         patch('myah.utils.agent_proxy.httpx.AsyncClient', _FakeClient), \
         patch('myah.routers.containers.AGENT_HOST', 'host.docker.internal'), \
         patch('myah.routers.containers.AGENT_BEARER_TOKEN', 'tok'):
        await aux_call(_UserStub(), 'GET', '/v1/runs')

    assert captured_url == ['http://host.docker.internal:18642/v1/runs'], captured_url


def test_adopt_path_persists_gateway_port(monkeypatch):
    """Adopt path must persist gateway_port from info dict to DB row.

    Regression: pre-fix, _start_container called update_status WITHOUT
    gateway_port=info.get('gateway_port'), so adopted containers retained
    NULL gateway_port even when 8643 was mapped in Docker. Subsequent
    /myah/* requests fell back to host_port and got 404 because the
    new agent image no longer mounts /myah/* on the chat port.
    """
    import asyncio

    from myah.models.containers import Containers
    from myah.routers import containers as containers_router

    captured_kwargs = {}

    def fake_update_status(user_id, **kwargs):
        captured_kwargs.update(kwargs)
        return None

    monkeypatch.setattr(Containers, 'update_status', fake_update_status)

    fake_info = {
        'adopt': True,
        'container_id': 'abc123',
        'name': 'myah-agent-test',
        'host_port': 12345,
        'vite_port': 12346,
        'vnc_port': 12347,
        'web_port': 12348,
        'gateway_port': 12349,  # ← THE FIELD UNDER TEST
    }

    async def fake_wait_for_ready(*args, **kwargs):
        return (True, '')

    monkeypatch.setattr(containers_router, '_wait_for_ready', fake_wait_for_ready)

    async def fake_start_container_sync(*args, **kwargs):
        return fake_info
    monkeypatch.setattr(containers_router, '_start_container_sync',
                        lambda *a, **kw: fake_info)

    # Real signature: _start_container(user_id, record, honcho_api_key='', honcho_workspace_id='')
    asyncio.run(containers_router._start_container('test_user', None))

    assert captured_kwargs.get('gateway_port') == 12349, (
        f'adopt path must persist gateway_port; got {captured_kwargs}'
    )
