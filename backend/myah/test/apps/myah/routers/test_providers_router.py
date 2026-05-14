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

    # Hermes config was updated with the new provider + model. Dict-form
    # model: payload (PR 1c Appendix A) — never the legacy scalar form.
    put_calls = [c for c in aux_calls if c[0] == 'PUT']
    assert put_calls == [
        (
            'PUT',
            '/api/plugins/myah-admin/config',
            {'model': {'default': 'openai/gpt-5.3-codex', 'provider': 'openai-codex'}},
        ),
    ]

    # Platform metadata was upserted.
    upsert_mock.assert_called_once_with(
        user_id='test-user',
        provider_id='openai-codex',
        key_last_four='',
        is_valid=True,
    )

    # User's default_model is set when they didn't have one.
    update_user_mock.assert_called_once_with('test-user', {'default_model': 'openai/gpt-5.3-codex'})


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


# ── Appendix Task A: connect_credential must send dict-form model: ────────────
# Regression tests for the fix that changed PUT /api/config body from
# {model.provider: '...', model: '<string>'} (scalar — clobbers dict sub-keys)
# to {model: {name: '...', provider: '...'}} (dict-form — merges correctly).
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
async def test_connect_credential_patches_dict_form():
    """connect_credential must send dict-form model: with name and provider keys.

    The old bug sent 'model': '<string>' (scalar), which set_config_value wrote
    as a bare string to config.yaml — destroying the model.provider sub-key
    sent in the same PATCH. The fix sends 'model': {name, provider} instead.
    """
    from myah.routers import providers as mod

    user = MagicMock()
    user.id = 'test-user'

    captured_calls = []

    async def mock_aux(user_arg, method, path, json_body=None, **kwargs):
        captured_calls.append({'method': method, 'path': path, 'json_body': json_body})
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

    # Find the PUT call
    patch_calls = [c for c in captured_calls if c['method'] == 'PUT']
    assert patch_calls, 'No PUT call to /api/config'
    patch_body = patch_calls[0]['json_body']

    # model: must be a dict, not a scalar string
    assert isinstance(patch_body.get('model'), dict), f'model: must be dict-form. Got: {patch_body.get("model")!r}'
    assert 'default' in patch_body['model'], "model dict must have 'default' key (not 'name')"
    assert 'provider' in patch_body['model'], "model dict must have 'provider' key"
    assert patch_body['model']['default'] == 'openrouter-default-model'
    assert patch_body['model']['provider'] == 'openrouter'


@pytest.mark.asyncio
async def test_connect_credential_preserves_base_url_when_catalog_specifies():
    """When catalog custom_provider.base_url is present, include it in model dict."""
    from myah.routers import providers as mod

    user = MagicMock()
    user.id = 'test-user'

    captured_calls = []

    async def mock_aux(user_arg, method, path, json_body=None, **kwargs):
        captured_calls.append({'method': method, 'path': path, 'json_body': json_body})
        return {'entry_id': 'test-entry-id', 'key_last_four': '1234'}

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
    patch_body = patch_calls[0]['json_body']
    assert patch_body['model']['base_url'] == 'https://api.openai.com/v1'
    assert patch_body['model']['provider'] == 'custom:openai-direct'


@pytest.mark.asyncio
async def test_connect_credential_omits_base_url_when_catalog_does_not_specify():
    """When catalog has no custom_provider.base_url, omit base_url from model dict.

    Don't write base_url: None — that would persist null to config.yaml.
    """
    from myah.routers import providers as mod

    user = MagicMock()
    user.id = 'test-user'

    captured_calls = []

    async def mock_aux(user_arg, method, path, json_body=None, **kwargs):
        captured_calls.append({'method': method, 'path': path, 'json_body': json_body})
        return {'entry_id': 'test-entry-id', 'key_last_four': '1234'}

    # No base_url in catalog entry
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
    assert patch_calls
    patch_body = patch_calls[0]['json_body']
    # base_url key must be absent, not set to None
    assert 'base_url' not in patch_body['model'], (
        "base_url must be omitted when catalog has no base_url — don't write null to config.yaml"
    )


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
async def test_connect_credential_writes_model_default_not_name():
    """Hermes' canonical model config key is `model.default`. The platform
    must send 'default' not 'name' to /api/config so cron schedulers can
    read the configured model.
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
        if path.endswith('/credential'):
            return {'entry_id': 'fake-entry-id'}
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

    config_calls = [c for c in captured_calls if c['path'] == '/api/plugins/myah-admin/config']
    assert len(config_calls) == 1, f'Expected exactly one /api/plugins/myah-admin/config call, got {len(config_calls)}: {captured_calls}'
    model_patch = config_calls[0]['json_body']['model']
    assert 'default' in model_patch, (
        f"Expected 'default' key in model patch, got keys: {list(model_patch.keys())}. "
        f'Hermes reads model.default; model.name is a normalizer fallback only.'
    )
    assert 'name' not in model_patch, (
        f"Expected 'name' key NOT in model patch, but found {model_patch}. "
        f'Sending model.name causes scheduler to read empty model.'
    )
    assert model_patch['default'] == 'meta-llama/llama-4'
    assert model_patch['provider'] == 'openrouter'


@pytest.mark.asyncio
async def test_set_active_provider_writes_model_default_not_name():
    """set_active_provider (the 'switch provider' path) ALSO uses
    'default' not 'name'."""
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

    config_calls = [c for c in captured_calls if c['path'] == '/api/plugins/myah-admin/config']
    assert len(config_calls) == 1
    model_patch = config_calls[0]['json_body']['model']
    assert 'default' in model_patch
    assert 'name' not in model_patch
