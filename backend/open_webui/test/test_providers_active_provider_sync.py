"""Regression tests for auth.json:active_provider sync after onboarding.

The cron pipeline's resolve_provider('auto') chain reads
auth.json:active_provider — but the Myah onboarding handlers historically
only wrote to auth.json:credential_pool and config.yaml:model.provider, leaving
active_provider stuck at whatever the entrypoint heal block set it to. When
those two diverge (e.g. user has Codex AND OpenRouter, with an OpenRouter
model selected), every cron LLM call returns 400.

The fix: after every onboarding-completion path (API-key save, OAuth
complete, explicit /active switch), call the plugin's new endpoint
POST /myah/v1/active-provider so auth.json:active_provider tracks the user's
actual intent.

These tests verify the platform side of that contract.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException


def _build_catalog_entry(provider_id, model_provider_value=None, base_url=None):
    """Build a minimal catalog entry."""
    entry = {
        'v1_visible': True,
        'default_model': f'{provider_id}-default-model',
        'write_type': 'env_var',
        'env_var': f'{provider_id.upper()}_API_KEY',
    }
    if model_provider_value or base_url:
        cp = {}
        if model_provider_value:
            cp['model_provider_value'] = model_provider_value
        if base_url:
            cp['base_url'] = base_url
        entry['custom_provider'] = cp
    return entry


@pytest.mark.asyncio
async def test_connect_credential_syncs_active_provider():
    """API-key onboarding fires POST /myah/v1/active-provider with the right body."""
    from open_webui.routers import providers as mod

    user = MagicMock()
    user.id = 'test-user'

    async def mock_web_call(user_arg, method, path, **kwargs):
        if path.endswith('/credential'):
            return {'entry_id': 'fake-entry', 'key_last_four': '1234'}
        return {'ok': True}

    aux_calls: list[dict] = []

    async def mock_aux_call(user_arg, method, path, **kwargs):
        aux_calls.append({'method': method, 'path': path, 'json_body': kwargs.get('json_body')})
        return {'active_provider': 'openrouter', 'previous': None}

    body = mod.ConnectCredentialBody(api_key='sk-test', label='primary')

    with (
        patch.object(mod, '_load_catalog', AsyncMock(return_value={'openrouter': _build_catalog_entry('openrouter')})),
        patch.object(mod, 'web_call_or_raise', AsyncMock(side_effect=mock_web_call)),
        patch.object(mod, 'aux_call_or_raise', AsyncMock(side_effect=mock_aux_call)),
        patch.object(mod.UserProviderStatuses, 'upsert', MagicMock()),
        patch.object(mod.Users, 'get_user_by_id', return_value=None),
    ):
        await mod.connect_credential(provider_id='openrouter', body=body, user=user)

    sync_calls = [c for c in aux_calls if c['path'] == '/myah/v1/active-provider']
    assert len(sync_calls) == 1, f'Expected exactly one /myah/v1/active-provider call, got: {aux_calls}'
    assert sync_calls[0]['method'] == 'POST'
    assert sync_calls[0]['json_body'] == {'provider': 'openrouter'}


@pytest.mark.asyncio
async def test_poll_device_auth_complete_syncs_active_provider():
    """OAuth completion (status='approved') fires the active_provider sync."""
    from open_webui.routers import providers as mod

    user = MagicMock()
    user.id = 'test-user'

    body = MagicMock()
    body.session_id = 'session-abc'

    async def mock_web_call(user_arg, method, path, **kwargs):
        if method == 'GET' and 'oauth/openai-codex/poll' in path:
            return {'status': 'approved', 'session_id': 'session-abc', 'error_message': None}
        if method == 'PUT' and path == '/api/config':
            return {}
        raise AssertionError(f'unexpected web_call_or_raise: {method} {path}')

    aux_calls: list[dict] = []

    async def mock_aux_call(user_arg, method, path, **kwargs):
        aux_calls.append({'method': method, 'path': path, 'json_body': kwargs.get('json_body')})
        return {'active_provider': 'openai-codex', 'previous': None}

    fake_user = MagicMock()
    fake_user.default_model = None

    catalog = {'openai-codex': {'default_model': 'openai/gpt-5.3-codex'}}

    with (
        patch.object(mod, 'web_call_or_raise', AsyncMock(side_effect=mock_web_call)),
        patch.object(mod, 'aux_call_or_raise', AsyncMock(side_effect=mock_aux_call)),
        patch.object(mod, '_load_catalog', AsyncMock(return_value=catalog)),
        patch.object(mod.UserProviderStatuses, 'upsert', MagicMock()),
        patch.object(mod.Users, 'get_user_by_id', return_value=fake_user),
        patch.object(mod.Users, 'update_user_by_id', MagicMock()),
    ):
        result = await mod.poll_device_auth(provider_id='openai-codex', body=body, user=user)

    assert result['status'] == 'complete'

    sync_calls = [c for c in aux_calls if c['path'] == '/myah/v1/active-provider']
    assert len(sync_calls) == 1, f'Expected exactly one sync call, got: {aux_calls}'
    assert sync_calls[0]['method'] == 'POST'
    assert sync_calls[0]['json_body'] == {'provider': 'openai-codex'}


@pytest.mark.asyncio
async def test_poll_device_auth_pending_does_not_sync():
    """Non-approved poll responses must NOT fire the sync call."""
    from open_webui.routers import providers as mod

    user = MagicMock()
    user.id = 'test-user'
    body = MagicMock()
    body.session_id = 'session-pending'

    async def mock_web_call(user_arg, method, path, **kwargs):
        return {'status': 'pending', 'session_id': 'session-pending', 'error_message': None}

    aux_mock = AsyncMock()

    with (
        patch.object(mod, 'web_call_or_raise', AsyncMock(side_effect=mock_web_call)),
        patch.object(mod, 'aux_call_or_raise', aux_mock),
        patch.object(mod, '_load_catalog', AsyncMock(return_value={})),
        patch.object(mod.UserProviderStatuses, 'upsert', MagicMock()),
    ):
        result = await mod.poll_device_auth(provider_id='openai-codex', body=body, user=user)

    assert result['status'] == 'pending'
    aux_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_set_active_provider_syncs():
    """Explicit /active POST fires the sync for the chosen provider_id."""
    from open_webui.routers import providers as mod

    user = MagicMock()
    user.id = 'test-user'

    async def mock_web_call(user_arg, method, path, **kwargs):
        return {'ok': True}

    aux_calls: list[dict] = []

    async def mock_aux_call(user_arg, method, path, **kwargs):
        aux_calls.append({'method': method, 'path': path, 'json_body': kwargs.get('json_body')})
        return {'active_provider': 'openrouter', 'previous': 'openai-codex'}

    catalog = {'openrouter': _build_catalog_entry('openrouter')}
    body = mod.ActiveProviderBody(provider_id='openrouter', model_id=None)

    with (
        patch.object(mod, '_load_catalog', AsyncMock(return_value=catalog)),
        patch.object(mod, 'web_call_or_raise', AsyncMock(side_effect=mock_web_call)),
        patch.object(mod, 'aux_call_or_raise', AsyncMock(side_effect=mock_aux_call)),
        patch.object(mod.Users, 'update_user_by_id', MagicMock()),
    ):
        await mod.set_active_provider(body=body, user=user)

    sync_calls = [c for c in aux_calls if c['path'] == '/myah/v1/active-provider']
    assert len(sync_calls) == 1
    assert sync_calls[0]['method'] == 'POST'
    assert sync_calls[0]['json_body'] == {'provider': 'openrouter'}


@pytest.mark.asyncio
async def test_sync_failure_does_not_break_onboarding():
    """When the sync call raises a 5xx, onboarding still succeeds."""
    from open_webui.routers import providers as mod

    user = MagicMock()
    user.id = 'test-user'

    async def mock_web_call(user_arg, method, path, **kwargs):
        if path.endswith('/credential'):
            return {'entry_id': 'fake-entry', 'key_last_four': '1234'}
        return {'ok': True}

    async def mock_aux_call_fail(user_arg, method, path, **kwargs):
        raise HTTPException(status_code=500, detail='internal error')

    body = mod.ConnectCredentialBody(api_key='sk-test', label='primary')

    with (
        patch.object(mod, '_load_catalog', AsyncMock(return_value={'openrouter': _build_catalog_entry('openrouter')})),
        patch.object(mod, 'web_call_or_raise', AsyncMock(side_effect=mock_web_call)),
        patch.object(mod, 'aux_call_or_raise', AsyncMock(side_effect=mock_aux_call_fail)),
        patch.object(mod.UserProviderStatuses, 'upsert', MagicMock()),
        patch.object(mod.Users, 'get_user_by_id', return_value=None),
    ):
        result = await mod.connect_credential(provider_id='openrouter', body=body, user=user)

    # The onboarding response shape is preserved.
    assert result['provider_id'] == 'openrouter'
    assert result['default_model'] == 'openrouter-default-model'


@pytest.mark.asyncio
async def test_sync_404_is_silent(caplog):
    """Older agent images (pre-endpoint) return 404 — log at info, never warning."""
    import logging

    from loguru import logger as loguru_logger

    from open_webui.routers import providers as mod

    user = MagicMock()
    user.id = 'test-user'

    async def mock_web_call(user_arg, method, path, **kwargs):
        if path.endswith('/credential'):
            return {'entry_id': 'fake-entry', 'key_last_four': '1234'}
        return {'ok': True}

    async def mock_aux_call_404(user_arg, method, path, **kwargs):
        raise HTTPException(status_code=404, detail='not found')

    body = mod.ConnectCredentialBody(api_key='sk-test', label='primary')

    # Bridge loguru -> std logging so caplog can see records.
    handler_id = loguru_logger.add(
        lambda message: logging.getLogger('loguru-bridge').log(message.record['level'].no, message.record['message']),
        level=0,
    )
    try:
        with (
            patch.object(
                mod,
                '_load_catalog',
                AsyncMock(return_value={'openrouter': _build_catalog_entry('openrouter')}),
            ),
            patch.object(mod, 'web_call_or_raise', AsyncMock(side_effect=mock_web_call)),
            patch.object(mod, 'aux_call_or_raise', AsyncMock(side_effect=mock_aux_call_404)),
            patch.object(mod.UserProviderStatuses, 'upsert', MagicMock()),
            patch.object(mod.Users, 'get_user_by_id', return_value=None),
            caplog.at_level(logging.DEBUG, logger='loguru-bridge'),
        ):
            result = await mod.connect_credential(provider_id='openrouter', body=body, user=user)
    finally:
        loguru_logger.remove(handler_id)

    # Onboarding still succeeds.
    assert result['provider_id'] == 'openrouter'

    # No WARNING-level record from the sync helper for the 404 case.
    sync_warnings = [r for r in caplog.records if r.levelno >= logging.WARNING and 'active_provider' in r.getMessage()]
    assert sync_warnings == [], f'Expected no WARNING for 404 sync, got: {[r.getMessage() for r in sync_warnings]}'
