"""Tests for the /api/v1/hermes/media proxy endpoint."""
import asyncio

import pytest
from fastapi import HTTPException
from unittest.mock import AsyncMock, MagicMock, patch


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


# ── get_hermes_media: successful proxy ───────────────────────────────────────

def test_get_hermes_media_proxies_content():
    """Successful proxy returns content from agent container."""
    from open_webui.routers.hermes_media import get_hermes_media

    mock_record = MagicMock()
    mock_record.host_port = 8642

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.content = b'\xff\xd8\xff' + b'\x00' * 50
    mock_response.headers = {'Content-Type': 'image/jpeg'}
    mock_response.text = ''

    mock_user = MagicMock()
    mock_user.id = 'user-1'

    async def run():
        with patch('open_webui.routers.hermes_media.get_or_create_container',
                   return_value=mock_record), \
             patch('open_webui.routers.hermes_media._gateway_url',
                   return_value='http://localhost:8643/v1'), \
             patch('open_webui.routers.hermes_media.AGENT_BEARER_TOKEN', 'test-token'), \
             patch('httpx.AsyncClient') as mock_client_class:

            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_class.return_value = mock_client

            return await get_hermes_media(path='/cache/images/test.jpg', user=mock_user)

    response = _run(run())
    assert response.status_code == 200
    assert response.media_type == 'image/jpeg'


def test_get_hermes_media_sets_auth_header():
    """Bearer token is forwarded to the agent container."""
    from open_webui.routers.hermes_media import get_hermes_media

    mock_record = MagicMock()
    mock_record.host_port = 8642

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.content = b'\x89PNG\r\n\x1a\n' + b'\x00' * 30
    mock_response.headers = {'Content-Type': 'image/png'}
    mock_response.text = ''

    mock_user = MagicMock()
    mock_user.id = 'user-2'

    async def run():
        with patch('open_webui.routers.hermes_media.get_or_create_container',
                   return_value=mock_record), \
             patch('open_webui.routers.hermes_media._gateway_url',
                   return_value='http://localhost:8643/v1'), \
             patch('open_webui.routers.hermes_media.AGENT_BEARER_TOKEN', 'secret-token'), \
             patch('httpx.AsyncClient') as mock_client_class:

            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_class.return_value = mock_client

            await get_hermes_media(path='/cache/images/test.png', user=mock_user)

            call_kwargs = mock_client.get.call_args
            return call_kwargs.kwargs.get('headers', {})

    headers = _run(run())
    assert headers.get('Authorization') == 'Bearer secret-token'


# ── get_hermes_media: error cases ────────────────────────────────────────────

def test_get_hermes_media_container_unavailable_raises_503():
    """When container lookup fails, returns 503."""
    from open_webui.routers.hermes_media import get_hermes_media

    mock_user = MagicMock()
    mock_user.id = 'user-1'

    async def run():
        with patch('open_webui.routers.hermes_media.get_or_create_container',
                   side_effect=Exception('container not available')):
            with pytest.raises(HTTPException) as exc:
                await get_hermes_media(path='/cache/images/test.jpg', user=mock_user)
            return exc.value.status_code

    assert _run(run()) == 503


def test_get_hermes_media_agent_404_raises_404():
    """When agent returns 404 (file not found), proxy raises 404."""
    from open_webui.routers.hermes_media import get_hermes_media

    mock_record = MagicMock()
    mock_record.host_port = 8642

    mock_response = MagicMock()
    mock_response.status_code = 404
    mock_response.content = b''
    mock_response.text = 'File not found'

    mock_user = MagicMock()
    mock_user.id = 'user-1'

    async def run():
        with patch('open_webui.routers.hermes_media.get_or_create_container',
                   return_value=mock_record), \
             patch('open_webui.routers.hermes_media._gateway_url',
                   return_value='http://localhost:8643/v1'), \
             patch('httpx.AsyncClient') as mock_client_class:

            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_class.return_value = mock_client

            with pytest.raises(HTTPException) as exc:
                await get_hermes_media(path='/cache/images/missing.jpg', user=mock_user)
            return exc.value.status_code

    assert _run(run()) == 404


def test_get_hermes_media_agent_403_raises_403():
    """When agent returns 403 (path outside whitelist), proxy raises 403."""
    from open_webui.routers.hermes_media import get_hermes_media

    mock_record = MagicMock()
    mock_record.host_port = 8642

    mock_response = MagicMock()
    mock_response.status_code = 403
    mock_response.content = b''
    mock_response.text = 'Path not in an allowed cache directory'

    mock_user = MagicMock()
    mock_user.id = 'user-1'

    async def run():
        with patch('open_webui.routers.hermes_media.get_or_create_container',
                   return_value=mock_record), \
             patch('open_webui.routers.hermes_media._gateway_url',
                   return_value='http://localhost:8643/v1'), \
             patch('httpx.AsyncClient') as mock_client_class:

            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_class.return_value = mock_client

            with pytest.raises(HTTPException) as exc:
                await get_hermes_media(path='/etc/passwd', user=mock_user)
            return exc.value.status_code

    assert _run(run()) == 403


def test_get_hermes_media_agent_unreachable_raises_502():
    """When agent is unreachable (network error), proxy raises 502."""
    import httpx as _httpx
    from open_webui.routers.hermes_media import get_hermes_media

    mock_record = MagicMock()
    mock_record.host_port = 8642

    mock_user = MagicMock()
    mock_user.id = 'user-1'

    async def run():
        with patch('open_webui.routers.hermes_media.get_or_create_container',
                   return_value=mock_record), \
             patch('open_webui.routers.hermes_media._gateway_url',
                   return_value='http://localhost:8643/v1'), \
             patch('httpx.AsyncClient') as mock_client_class:

            mock_client = AsyncMock()
            mock_client.get = AsyncMock(
                side_effect=_httpx.ConnectError('Connection refused')
            )
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_class.return_value = mock_client

            with pytest.raises(HTTPException) as exc:
                await get_hermes_media(path='/cache/images/test.jpg', user=mock_user)
            return exc.value.status_code

    assert _run(run()) == 502


def test_get_hermes_media_no_bearer_token_skips_auth_header():
    """When AGENT_BEARER_TOKEN is empty, no Authorization header is sent."""
    from open_webui.routers.hermes_media import get_hermes_media

    mock_record = MagicMock()
    mock_record.host_port = 8642

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.content = b'data'
    mock_response.headers = {'Content-Type': 'application/octet-stream'}
    mock_response.text = ''

    mock_user = MagicMock()
    mock_user.id = 'user-3'

    async def run():
        with patch('open_webui.routers.hermes_media.get_or_create_container',
                   return_value=mock_record), \
             patch('open_webui.routers.hermes_media._gateway_url',
                   return_value='http://localhost:8643/v1'), \
             patch('open_webui.routers.hermes_media.AGENT_BEARER_TOKEN', ''), \
             patch('httpx.AsyncClient') as mock_client_class:

            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_class.return_value = mock_client

            await get_hermes_media(path='/cache/audio/clip.mp3', user=mock_user)

            call_kwargs = mock_client.get.call_args
            return call_kwargs.kwargs.get('headers', {})

    headers = _run(run())
    assert 'Authorization' not in headers
