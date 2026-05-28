"""Tests for hermes_web helpers."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest


def _fake_user():
    return SimpleNamespace(id='u1')


@pytest.mark.asyncio
async def test_fetch_hermes_default_model_returns_pair_tuple():
    """Helper must return (provider, model) tuple, not a slash-concatenated string.

    Mirrors Hermes upstream's canonical {provider, model} shape — see
    `docs/superpowers/specs/2026-05-24-default-model-canonical-format-design.md`.
    """
    from myah.utils import hermes_web

    with patch.object(hermes_web, 'is_oss_mode', return_value=True), \
         patch.object(hermes_web, '_resolve_gateway_port', AsyncMock(return_value=8643)), \
         patch.object(hermes_web, '_detect_agent_host', return_value='127.0.0.1'), \
         patch.object(hermes_web, 'httpx') as mock_httpx:
        mock_resp = type('R', (), {
            'status_code': 200,
            'json': lambda self: {'model': {'provider': 'opencode-go', 'default': 'mimo-v2.5'}},
        })()
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_httpx.AsyncClient.return_value.__aenter__.return_value = mock_client
        result = await hermes_web.fetch_hermes_default_model(_fake_user())

    assert result == ('opencode-go', 'mimo-v2.5'), f'expected tuple, got {result!r}'


@pytest.mark.asyncio
async def test_fetch_hermes_default_model_returns_none_on_missing_fields():
    from myah.utils import hermes_web

    with patch.object(hermes_web, 'is_oss_mode', return_value=True), \
         patch.object(hermes_web, '_resolve_gateway_port', AsyncMock(return_value=8643)), \
         patch.object(hermes_web, '_detect_agent_host', return_value='127.0.0.1'), \
         patch.object(hermes_web, 'httpx') as mock_httpx:
        mock_resp = type('R', (), {
            'status_code': 200,
            'json': lambda self: {'model': {'provider': '', 'default': ''}},
        })()
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_httpx.AsyncClient.return_value.__aenter__.return_value = mock_client
        result = await hermes_web.fetch_hermes_default_model(_fake_user())

    assert result is None
