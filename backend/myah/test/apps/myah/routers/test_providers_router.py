"""Regression tests for the /api/v1/providers/* router.

The fan-out endpoint silently returned [] because the code treated
web_call_or_raise's return value as {status, body, headers} (the shape
web_call returns). web_call_or_raise actually returns the body itself —
a list for /models and a dict for /catalog. Calling `.get('body')` on a
list raises AttributeError; the except-clause swallowed it; response
became empty.

Wave 3c: paths migrated from aux_call('/myah/api/...') (port 8642) to
web_call_or_raise('/api/plugins/myah-admin/...' or '/api/...') routed
through the per-user `hermes dashboard` server (port 9119).
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.fixture(autouse=True)
def _clear_unified_models_cache():
    """Reset providers._unified_models_cache between tests in this file.

    Every test uses the same `user.id = 'test-user'`. Without this fixture,
    a prior test's cached fan-out leaks into later tests sharing the same
    cache key (user_id + deployment_mode + provider tuple) and silently
    bypasses their mocked state. See providers.get_unified_models for the
    cache contract.
    """
    from myah.routers import providers

    providers._unified_models_cache.clear()
    yield
    providers._unified_models_cache.clear()


@pytest.mark.asyncio
async def test_get_unified_models_returns_models_from_all_valid_providers():
    """When the agent returns a list body, the fan-out must produce a
    non-empty merged list with correct tags."""
    from myah.routers import providers as mod

    user = MagicMock()
    user.id = 'test-user'

    # user_provider_status shows two valid providers
    status_rows = [
        MagicMock(provider_id='zai', is_valid=True),
        MagicMock(provider_id='opencode-zen', is_valid=True),
    ]

    def mock_list_for_user(uid):
        assert uid == user.id
        return status_rows

    def mock_aux(user, method, path, **kwargs):
        # web_call_or_raise returns the BODY directly (not wrapped).
        if path == '/api/plugins/myah-admin/providers/zai/models':
            return [{'id': 'glm-5.1', 'name': 'glm-5.1'}, {'id': 'glm-5', 'name': 'glm-5'}]
        if path == '/api/plugins/myah-admin/providers/opencode-zen/models':
            return [{'id': 'gpt-5.4', 'name': 'gpt-5.4'}]
        raise AssertionError(f'unexpected path: {path}')

    with patch.object(mod.UserProviderStatuses, 'list_for_user', mock_list_for_user):
        with patch.object(mod, 'web_call_or_raise', AsyncMock(side_effect=mock_aux)):
            result = await mod.get_unified_models(user=user)

    assert isinstance(result, list)
    ids = [m['id'] for m in result]
    assert 'glm-5.1' in ids
    assert 'glm-5' in ids
    assert 'gpt-5.4' in ids

    # Each model must be tagged with its provider for the UI switcher.
    by_id = {m['id']: m for m in result}
    assert by_id['glm-5.1']['tags'] == [{'name': 'zai'}]
    assert by_id['gpt-5.4']['tags'] == [{'name': 'opencode-zen'}]


@pytest.mark.asyncio
async def test_get_unified_models_skips_providers_that_fail():
    """If one provider errors, the other still shows through."""
    from fastapi import HTTPException

    from myah.routers import providers as mod

    user = MagicMock()
    user.id = 'test-user'
    status_rows = [
        MagicMock(provider_id='zai', is_valid=True),
        MagicMock(provider_id='broken', is_valid=True),
    ]

    def mock_aux(user, method, path, **kwargs):
        if path == '/api/plugins/myah-admin/providers/zai/models':
            return [{'id': 'glm-5.1', 'name': 'glm-5.1'}]
        raise HTTPException(status_code=502, detail='upstream down')

    with patch.object(mod.UserProviderStatuses, 'list_for_user', lambda uid: status_rows):
        with patch.object(mod, 'web_call_or_raise', AsyncMock(side_effect=mock_aux)):
            result = await mod.get_unified_models(user=user)

    ids = [m['id'] for m in result]
    assert ids == ['glm-5.1']


@pytest.mark.asyncio
async def test_get_unified_models_skips_invalid_providers():
    """Providers whose is_valid is False are NOT queried."""
    from myah.routers import providers as mod

    user = MagicMock()
    user.id = 'test-user'
    status_rows = [
        MagicMock(provider_id='zai', is_valid=True),
        MagicMock(provider_id='disconnected-provider', is_valid=False),
    ]

    mock = AsyncMock(return_value=[{'id': 'glm-5.1', 'name': 'glm-5.1'}])
    with patch.object(mod.UserProviderStatuses, 'list_for_user', lambda uid: status_rows):
        with patch.object(mod, 'web_call_or_raise', mock):
            await mod.get_unified_models(user=user)

    # Only one provider should have been hit (the valid one)
    called_paths = [call.args[2] for call in mock.call_args_list]
    assert called_paths == ['/api/plugins/myah-admin/providers/zai/models']


@pytest.mark.asyncio
async def test_get_unified_models_handles_non_list_payload():
    """If the agent returns something weird (e.g. dict), skip it gracefully."""
    from myah.routers import providers as mod

    user = MagicMock()
    user.id = 'test-user'
    status_rows = [MagicMock(provider_id='zai', is_valid=True)]

    mock = AsyncMock(return_value={'unexpected': 'dict'})
    with patch.object(mod.UserProviderStatuses, 'list_for_user', lambda uid: status_rows):
        with patch.object(mod, 'web_call_or_raise', mock):
            result = await mod.get_unified_models(user=user)

    assert result == []


# ──────────────────────────────────────────────────────────────────────
# poll_device_auth — Hermes ↔ frontend status vocabulary normalisation.
# Hermes shouts "approved" on a successful device-code flow; the
# SvelteKit modal listens for "complete". Without translation the OAuth
# modal hangs forever even though credentials are stored. Bug surfaced
# in prod when a user authorised OpenAI Codex and the modal never
# closed.
# ──────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_poll_device_auth_normalises_approved_to_complete():
    """Hermes' 'approved' status must surface to the frontend as 'complete'.

    Also verifies that on completion the platform PATCHes the agent
    config, upserts the provider status row, and decorates the response
    with default_model.
    """
    from myah.routers import providers as mod

    user = MagicMock()
    user.id = 'test-user'

    body = MagicMock()
    body.session_id = 'session-abc'

    poll_response = {'status': 'approved', 'session_id': 'session-abc', 'error_message': None}
    catalog_response = {'openai-codex': {'default_model': 'openai/gpt-5.3-codex'}}

    aux_calls = []

    async def mock_aux(user_arg, method, path, **kwargs):
        aux_calls.append((method, path, kwargs.get('json_body')))
        if method == 'GET' and 'oauth/openai-codex/poll' in path:
            return dict(poll_response)
        if method == 'GET' and path == '/api/plugins/myah-admin/config':
            return {'plugins': {'enabled': ['myah-platform']}, 'model': {'default': 'old', 'provider': 'old'}}
        if method == 'PUT' and path == '/api/plugins/myah-admin/config':
            return {}
        raise AssertionError(f'unexpected web_call_or_raise: {method} {path}')

    fake_user = MagicMock()
    fake_user.default_model = None

    with (
        patch.object(mod, 'web_call_or_raise', AsyncMock(side_effect=mock_aux)),
        patch.object(mod, '_load_catalog', AsyncMock(return_value=catalog_response)),
        patch.object(mod.UserProviderStatuses, 'upsert') as upsert_mock,
        patch.object(mod.Users, 'get_user_by_id', return_value=fake_user),
        patch.object(mod.Users, 'update_user_by_id') as update_user_mock,
    ):
        result = await mod.poll_device_auth(provider_id='openai-codex', body=body, user=user)

    # The frontend contract is satisfied: status is "complete", not "approved".
    assert result['status'] == 'complete'
    assert result['default_model'] == 'openai/gpt-5.3-codex'

    # Hermes config was updated by GET-merging current config and PUTing the
    # wrapped full config body expected by the dashboard.
    put_calls = [c for c in aux_calls if c[0] == 'PUT']
    assert put_calls == [
        (
            'PUT',
            '/api/plugins/myah-admin/config',
            {
                'config': {
                    'plugins': {'enabled': ['myah-platform']},
                    'platforms': {'myah': {'enabled': True}},
                    'model': {
                        'default': 'openai/gpt-5.3-codex',
                        'provider': 'openai-codex',
                    },
                }
            },
        ),
    ]

    # Platform metadata was upserted.
    upsert_mock.assert_called_once_with(
        user_id='test-user',
        provider_id='openai-codex',
        key_last_four='',
        is_valid=True,
    )

    # User's default (provider, model) pair is set when they didn't have one.
    # Catalog default is 'openai/gpt-5.3-codex' (vendor-namespaced) and the
    # URL provider_id is 'openai-codex' — they don't share a common prefix
    # so the bare-id strip is a no-op and the slash survives in default_model
    # (legitimate Hermes pass-through; the validator allows '/' in model id).
    update_user_mock.assert_called_once_with(
        'test-user',
        {'default_model': 'openai/gpt-5.3-codex', 'default_provider': 'openai-codex'},
    )


@pytest.mark.asyncio
async def test_poll_device_auth_passes_pending_through():
    """When Hermes still says 'pending', no Hermes/platform side effects fire."""
    from myah.routers import providers as mod

    user = MagicMock()
    user.id = 'test-user'
    body = MagicMock()
    body.session_id = 'session-xyz'

    aux_calls = []

    async def mock_aux(user_arg, method, path, **kwargs):
        aux_calls.append((method, path))
        return {'status': 'pending', 'session_id': 'session-xyz', 'error_message': None}

    with (
        patch.object(mod, 'web_call_or_raise', AsyncMock(side_effect=mock_aux)),
        patch.object(mod, '_load_catalog', AsyncMock(return_value={})),
        patch.object(mod.UserProviderStatuses, 'upsert') as upsert_mock,
    ):
        result = await mod.poll_device_auth(provider_id='openai-codex', body=body, user=user)

    assert result['status'] == 'pending'
    assert 'default_model' not in result
    # Only one web_call_or_raise (the poll) — no PUT /api/config.
    assert len(aux_calls) == 1
    upsert_mock.assert_not_called()


@pytest.mark.asyncio
async def test_poll_device_auth_propagates_terminal_error_states():
    """'expired', 'denied', 'error' must reach the frontend unchanged."""
    from myah.routers import providers as mod

    user = MagicMock()
    user.id = 'test-user'

    for terminal_status in ('expired', 'denied', 'error'):
        body = MagicMock()
        body.session_id = f'session-{terminal_status}'

        async def mock_aux(user_arg, method, path, **kwargs):
            return {'status': terminal_status, 'error_message': 'detail'}

        with patch.object(mod, 'web_call_or_raise', AsyncMock(side_effect=mock_aux)):
            result = await mod.poll_device_auth(provider_id='openai-codex', body=body, user=user)

        assert result['status'] == terminal_status, f'mangled {terminal_status}'


# ── Appendix Task A: provider config writes preserve existing non-model config. ─
# Regression tests for the safe Hermes admin config contract: fetch the current
# config, replace the provider-bound model block with catalog-derived fields,
# then PUT the full config wrapped as {config: ...}. This avoids 422s from bare
# fragments, preserves unrelated config sections, and prevents stale base_url
# values from a previous provider from surviving a provider switch.
# ─────────────────────────────────────────────────────────────────────────────


def _build_catalog_entry(provider_id, model_provider_value=None, base_url=None):
    """Build a minimal catalog entry for connect_credential tests."""
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
async def test_connect_credential_patches_agent_config_with_wrapped_merge():
    """connect_credential must GET current config and PUT a wrapped merged config."""
    from myah.routers import providers as mod

    user = MagicMock()
    user.id = 'test-user'

    captured_calls = []

    async def mock_aux(user_arg, method, path, json_body=None, **kwargs):
        captured_calls.append({'method': method, 'path': path, 'json_body': json_body})
        if method == 'POST':
            return {'entry_id': 'test-entry-id', 'key_last_four': '1234'}
        if method == 'GET' and path == '/api/plugins/myah-admin/config':
            return {'plugins': {'enabled': ['myah-platform']}, 'model': {'default': 'old'}}
        return {'ok': True}

    entry = _build_catalog_entry('openrouter')

    with (
        patch.object(mod, '_load_catalog', AsyncMock(return_value={'openrouter': entry})),
        patch.object(mod, 'web_call_or_raise', AsyncMock(side_effect=mock_aux)),
        patch.object(mod.UserProviderStatuses, 'upsert', MagicMock()),
        patch.object(mod.Users, 'get_user_by_id', return_value=None),
    ):
        body = MagicMock()
        body.api_key = 'sk-test-key'
        body.label = 'primary'
        await mod.connect_credential(provider_id='openrouter', body=body, user=user)

    patch_calls = [c for c in captured_calls if c['method'] == 'PUT']
    assert patch_calls == [
        {
            'method': 'PUT',
            'path': '/api/plugins/myah-admin/config',
            'json_body': {
                'config': {
                    'plugins': {'enabled': ['myah-platform']},
                    'platforms': {'myah': {'enabled': True}},
                    'model': {
                        'default': 'openrouter-default-model',
                        'provider': 'openrouter',
                    },
                }
            },
        }
    ]


@pytest.mark.asyncio
async def test_connect_credential_preserves_custom_provider_base_url_in_wrapped_merge():
    """custom_provider.model_provider_value/base_url are preserved in the merged model block."""
    from myah.routers import providers as mod

    user = MagicMock()
    user.id = 'test-user'

    captured_calls = []

    async def mock_aux(user_arg, method, path, json_body=None, **kwargs):
        captured_calls.append({'method': method, 'path': path, 'json_body': json_body})
        if method == 'POST':
            return {'entry_id': 'test-entry-id', 'key_last_four': '1234'}
        if method == 'GET' and path == '/api/plugins/myah-admin/config':
            return {'plugins': {'enabled': ['myah-platform']}}
        return {'ok': True}

    entry = _build_catalog_entry(
        'openai',
        model_provider_value='custom:openai-direct',
        base_url='https://api.openai.com/v1',
    )

    with (
        patch.object(mod, '_load_catalog', AsyncMock(return_value={'openai': entry})),
        patch.object(mod, 'web_call_or_raise', AsyncMock(side_effect=mock_aux)),
        patch.object(mod.UserProviderStatuses, 'upsert', MagicMock()),
        patch.object(mod.Users, 'get_user_by_id', return_value=None),
    ):
        body = MagicMock()
        body.api_key = 'sk-test-key'
        body.label = 'primary'
        await mod.connect_credential(provider_id='openai', body=body, user=user)

    patch_calls = [c for c in captured_calls if c['method'] == 'PUT']
    assert patch_calls
    assert patch_calls[0]['path'] == '/api/plugins/myah-admin/config'
    assert patch_calls[0]['json_body']['config']['model'] == {
        'default': 'openai-default-model',
        'provider': 'custom:openai-direct',
        'base_url': 'https://api.openai.com/v1',
    }
    assert patch_calls[0]['json_body']['config']['plugins'] == {'enabled': ['myah-platform']}


@pytest.mark.asyncio
async def test_connect_credential_omits_stale_base_url_when_catalog_does_not_specify():
    """Do not retain a previous provider's base_url when the new catalog lacks one."""
    from myah.routers import providers as mod

    user = MagicMock()
    user.id = 'test-user'

    captured_calls = []

    async def mock_aux(user_arg, method, path, json_body=None, **kwargs):
        captured_calls.append({'method': method, 'path': path, 'json_body': json_body})
        if method == 'POST':
            return {'entry_id': 'test-entry-id', 'key_last_four': '1234'}
        if method == 'GET' and path == '/api/plugins/myah-admin/config':
            return {
                'plugins': {'enabled': ['myah-platform']},
                'model': {
                    'default': 'deepseek/deepseek-v4-flash',
                    'provider': 'openrouter',
                    'base_url': 'https://openrouter.ai/api/v1',
                },
            }
        return {'ok': True}

    entry = _build_catalog_entry('anthropic')

    with (
        patch.object(mod, '_load_catalog', AsyncMock(return_value={'anthropic': entry})),
        patch.object(mod, 'web_call_or_raise', AsyncMock(side_effect=mock_aux)),
        patch.object(mod.UserProviderStatuses, 'upsert', MagicMock()),
        patch.object(mod.Users, 'get_user_by_id', return_value=None),
    ):
        body = MagicMock()
        body.api_key = 'sk-test-key'
        body.label = 'primary'
        await mod.connect_credential(provider_id='anthropic', body=body, user=user)

    patch_calls = [c for c in captured_calls if c['method'] == 'PUT']
    model_patch = patch_calls[0]['json_body']['config']['model']
    assert model_patch == {
        'default': 'anthropic-default-model',
        'provider': 'anthropic',
    }
    assert 'base_url' not in model_patch


@pytest.mark.asyncio
async def test_connect_credential_uses_extended_timeout():
    """connect_credential uses timeout=30s for container cold-start tolerance.

    Appendix C: container cold-start (Honcho init + listener bind) can take
    15-20s. The default 15s timeout causes the first credential POST to 504.
    Both web_call_or_raise calls in connect_credential must use timeout>=30s.
    """
    from myah.routers import providers as mod

    user = MagicMock()
    user.id = 'test-user'

    captured_calls = []

    async def mock_aux(user_arg, method, path, json_body=None, timeout=15.0, **kwargs):
        captured_calls.append({'method': method, 'path': path, 'timeout': timeout})
        return {'entry_id': 'test-entry-id', 'key_last_four': '1234'}

    entry = _build_catalog_entry('openrouter')

    with (
        patch.object(mod, '_load_catalog', AsyncMock(return_value={'openrouter': entry})),
        patch.object(mod, 'web_call_or_raise', AsyncMock(side_effect=mock_aux)),
        patch.object(mod.UserProviderStatuses, 'upsert', MagicMock()),
        patch.object(mod.Users, 'get_user_by_id', return_value=None),
    ):
        body = MagicMock()
        body.api_key = 'sk-test-key'
        body.label = 'primary'
        await mod.connect_credential(provider_id='openrouter', body=body, user=user)

    post_calls = [c for c in captured_calls if c['method'] == 'POST']
    patch_calls = [c for c in captured_calls if c['method'] == 'PUT']
    assert post_calls, 'No POST call to credential endpoint'
    assert patch_calls, 'No PUT call to config endpoint'
    assert post_calls[0]['timeout'] >= 30.0, (
        f'POST credential timeout must be >= 30s for cold-start tolerance. Got: {post_calls[0]["timeout"]}s'
    )
    assert patch_calls[0]['timeout'] >= 30.0, (
        f'PUT config timeout must be >= 30s for cold-start tolerance. Got: {patch_calls[0]["timeout"]}s'
    )


@pytest.mark.asyncio
async def test_connect_credential_wraps_full_config_payload():
    """Credential connect wraps the merged config for the dashboard full-config endpoint."""
    from myah.routers import providers as mod

    user = MagicMock()
    user.id = 'test-user'

    captured_calls: list[dict] = []

    async def mock_web_call(user, method, path, **kwargs):
        captured_calls.append(
            {
                'method': method,
                'path': path,
                'json_body': kwargs.get('json_body'),
            }
        )
        if path.endswith('/credential'):
            return {'entry_id': 'fake-entry-id'}
        if method == 'GET' and path == '/api/plugins/myah-admin/config':
            return {'plugins': {'enabled': ['myah-platform']}}
        return {'ok': True}

    fake_catalog = {
        'openrouter': {
            'v1_visible': True,
            'default_model': 'meta-llama/llama-4',
            'custom_provider': {},
        }
    }

    body = mod.ConnectCredentialBody(api_key='sk-test', label='primary')

    with patch.object(mod, '_load_catalog', AsyncMock(return_value=fake_catalog)):
        with patch.object(mod, 'web_call_or_raise', AsyncMock(side_effect=mock_web_call)):
            with patch.object(mod.UserProviderStatuses, 'upsert', MagicMock()):
                with patch.object(mod.Users, 'get_user_by_id', return_value=None):
                    await mod.connect_credential(provider_id='openrouter', body=body, user=user)

    put_calls = [
        c
        for c in captured_calls
        if c['method'] == 'PUT' and c['path'] == '/api/plugins/myah-admin/config'
    ]
    assert len(put_calls) == 1, (
        'Expected exactly one wrapped /api/plugins/myah-admin/config PUT, '
        f'got {len(put_calls)}: {captured_calls}'
    )
    assert put_calls[0]['json_body'] == {
        'config': {
            'plugins': {'enabled': ['myah-platform']},
            'platforms': {'myah': {'enabled': True}},
            'model': {'default': 'meta-llama/llama-4', 'provider': 'openrouter'},
        }
    }


@pytest.mark.asyncio
async def test_set_active_provider_wraps_merged_full_config_payload():
    """set_active_provider must PUT wrapped merged config, not a bare model fragment.

    The full config endpoint expects ``{'config': ...}``; sending
    ``{'model': ...}`` 422s in the live dashboard. We also preserve unrelated
    config sections by GET-merging before PUT.
    """
    from myah.routers import providers as mod

    user = MagicMock()
    user.id = 'test-user'

    captured_calls: list[dict] = []

    async def mock_web_call(user, method, path, **kwargs):
        captured_calls.append(
            {
                'method': method,
                'path': path,
                'json_body': kwargs.get('json_body'),
            }
        )
        if method == 'GET' and path == '/api/plugins/myah-admin/config':
            return {'plugins': {'enabled': ['myah-platform']}}
        return {'ok': True}

    fake_catalog = {
        'openrouter': {
            'v1_visible': True,
            'default_model': 'meta-llama/llama-4',
            'custom_provider': {},
        }
    }

    body = mod.ActiveProviderBody(provider_id='openrouter', model_id=None)

    with patch.object(mod, '_load_catalog', AsyncMock(return_value=fake_catalog)):
        with patch.object(mod, 'web_call_or_raise', AsyncMock(side_effect=mock_web_call)):
            with patch.object(mod.Users, 'update_user_by_id', MagicMock()):
                await mod.set_active_provider(body=body, user=user)

    put_calls = [
        c
        for c in captured_calls
        if c['method'] == 'PUT' and c['path'] == '/api/plugins/myah-admin/config'
    ]
    assert len(put_calls) == 1
    assert put_calls[0]['json_body'] == {
        'config': {
            'plugins': {'enabled': ['myah-platform']},
            'platforms': {'myah': {'enabled': True}},
            'model': {'default': 'meta-llama/llama-4', 'provider': 'openrouter'},
        }
    }


@pytest.mark.asyncio
async def test_set_active_provider_preserves_inference_base_url_in_model_config():
    """Built-in inference providers such as OpenRouter expose inference_base_url.

    Active-provider sync must copy that into model.base_url; otherwise the
    platform reports the selected provider/model while the agent container keeps
    an incomplete model block.
    """
    from myah.routers import providers as mod

    user = MagicMock()
    user.id = 'test-user'

    captured_calls: list[dict] = []

    async def mock_web_call(user, method, path, **kwargs):
        captured_calls.append(
            {
                'method': method,
                'path': path,
                'json_body': kwargs.get('json_body'),
            }
        )
        if method == 'GET' and path == '/api/plugins/myah-admin/config':
            return {'plugins': {'enabled': ['myah-platform']}}
        return {'ok': True}

    fake_catalog = {
        'openrouter': {
            'v1_visible': True,
            'default_model': 'deepseek/deepseek-v4-flash',
            'custom_provider': {},
            'inference_base_url': 'https://openrouter.ai/api/v1',
        }
    }

    body = mod.ActiveProviderBody(
        provider_id='openrouter',
        model_id='deepseek/deepseek-v4-flash',
    )

    with patch.object(mod, '_load_catalog', AsyncMock(return_value=fake_catalog)):
        with patch.object(mod, 'web_call_or_raise', AsyncMock(side_effect=mock_web_call)):
            with patch.object(mod.Users, 'update_user_by_id', MagicMock()):
                await mod.set_active_provider(body=body, user=user)

    put_calls = [
        c
        for c in captured_calls
        if c['method'] == 'PUT' and c['path'] == '/api/plugins/myah-admin/config'
    ]
    assert len(put_calls) == 1
    assert put_calls[0]['json_body']['config']['model'] == {
        'default': 'deepseek/deepseek-v4-flash',
        'provider': 'openrouter',
        'base_url': 'https://openrouter.ai/api/v1',
    }
