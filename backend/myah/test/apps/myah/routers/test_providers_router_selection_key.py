"""RED-phase tests for selection_key emitted by get_unified_models().

The production code at routers/providers.py:492-494 currently adds
'tags' but NOT 'selection_key'. All 6 tests fail against current code
(AssertionError or KeyError) and will pass once Wave 2 adds the field.

selection_key format: '{provider_id}::{model_id}'
Duplicates are PRESERVED (no dedup) — each gets a distinct selection_key.
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
async def test_selection_key_emitted_on_every_model():
    """Every model in the result must carry a non-empty selection_key."""
    from myah.routers import providers as mod

    user = MagicMock()
    user.id = 'test-user'

    status_rows = [
        MagicMock(provider_id='nous', is_valid=True),
    ]

    def mock_list_for_user(uid):
        return status_rows

    async def mock_aux(user_arg, method, path, **kwargs):
        if path == '/api/plugins/myah-admin/providers/nous/models':
            return [
                {'id': 'anthropic/claude-opus-4.7', 'name': 'Claude Opus'},
                {'id': 'gpt-5.4', 'name': 'GPT-5.4'},
            ]
        raise AssertionError(f'unexpected path: {path}')

    with patch.object(mod.UserProviderStatuses, 'list_for_user', mock_list_for_user):
        with patch.object(mod, '_oss_union_with_hermes_catalog', AsyncMock(return_value=['nous'])):
            with patch.object(mod, 'web_call_or_raise', AsyncMock(side_effect=mock_aux)):
                result = await mod.get_unified_models(user=user)

    assert len(result) == 2, f'expected 2 models, got {len(result)}'
    for m in result:
        assert 'selection_key' in m, f'model {m.get("id")} missing selection_key field'
        assert m['selection_key'], f'model {m.get("id")} has empty selection_key'


@pytest.mark.asyncio
async def test_selection_key_format_is_provider_doublecolon_model_id():
    """selection_key must be 'provider_id::model_id'."""
    from myah.routers import providers as mod

    user = MagicMock()
    user.id = 'test-user'

    status_rows = [MagicMock(provider_id='nous', is_valid=True)]

    async def mock_aux(user_arg, method, path, **kwargs):
        if path == '/api/plugins/myah-admin/providers/nous/models':
            return [{'id': 'anthropic/claude-opus-4.7', 'name': 'Claude Opus'}]
        raise AssertionError(f'unexpected path: {path}')

    with patch.object(mod.UserProviderStatuses, 'list_for_user', lambda uid: status_rows):
        with patch.object(mod, '_oss_union_with_hermes_catalog', AsyncMock(return_value=['nous'])):
            with patch.object(mod, 'web_call_or_raise', AsyncMock(side_effect=mock_aux)):
                result = await mod.get_unified_models(user=user)

    assert len(result) == 1
    assert result[0]['selection_key'] == 'nous::anthropic/claude-opus-4.7'


@pytest.mark.asyncio
async def test_duplicates_preserved_with_distinct_selection_keys():
    """When two providers return the same model id, BOTH rows survive
    with DIFFERENT selection_keys (no dedup)."""
    from myah.routers import providers as mod

    user = MagicMock()
    user.id = 'test-user'

    status_rows = [
        MagicMock(provider_id='nous', is_valid=True),
        MagicMock(provider_id='openrouter', is_valid=True),
    ]

    async def mock_aux(user_arg, method, path, **kwargs):
        if path == '/api/plugins/myah-admin/providers/nous/models':
            return [{'id': 'anthropic/claude-opus-4.7', 'name': 'Claude Opus'}]
        if path == '/api/plugins/myah-admin/providers/openrouter/models':
            return [{'id': 'anthropic/claude-opus-4.7', 'name': 'Claude Opus'}]
        raise AssertionError(f'unexpected path: {path}')

    with patch.object(mod.UserProviderStatuses, 'list_for_user', lambda uid: status_rows):
        with patch.object(mod, '_oss_union_with_hermes_catalog', AsyncMock(return_value=['nous', 'openrouter'])):
            with patch.object(mod, 'web_call_or_raise', AsyncMock(side_effect=mock_aux)):
                result = await mod.get_unified_models(user=user)

    # Both rows must survive — no dedup.
    assert len(result) == 2, f'expected 2 duplicate rows preserved, got {len(result)}'
    keys = [m['selection_key'] for m in result]
    assert keys[0] != keys[1], f'duplicate rows must have distinct selection_keys, both got {keys[0]}'
    assert 'nous::anthropic/claude-opus-4.7' in keys
    assert 'openrouter::anthropic/claude-opus-4.7' in keys


@pytest.mark.asyncio
async def test_selection_keys_are_unique_across_full_response():
    """Invariant: len({selection_key set}) == len(result) regardless of input shape."""
    from myah.routers import providers as mod

    user = MagicMock()
    user.id = 'test-user'

    status_rows = [
        MagicMock(provider_id='nous', is_valid=True),
        MagicMock(provider_id='openrouter', is_valid=True),
        MagicMock(provider_id='zai', is_valid=True),
    ]

    async def mock_aux(user_arg, method, path, **kwargs):
        models_map = {
            '/api/plugins/myah-admin/providers/nous/models': [
                {'id': 'anthropic/claude-opus-4.7', 'name': 'Claude Opus'},
                {'id': 'glm-5', 'name': 'GLM-5'},
            ],
            '/api/plugins/myah-admin/providers/openrouter/models': [
                {'id': 'anthropic/claude-opus-4.7', 'name': 'Claude Opus'},
                {'id': 'gpt-5.4', 'name': 'GPT-5.4'},
            ],
            '/api/plugins/myah-admin/providers/zai/models': [
                {'id': 'glm-5', 'name': 'GLM-5'},
            ],
        }
        if path in models_map:
            return models_map[path]
        raise AssertionError(f'unexpected path: {path}')

    with patch.object(mod.UserProviderStatuses, 'list_for_user', lambda uid: status_rows):
        with patch.object(mod, '_oss_union_with_hermes_catalog', AsyncMock(return_value=['nous', 'openrouter', 'zai'])):
            with patch.object(mod, 'web_call_or_raise', AsyncMock(side_effect=mock_aux)):
                result = await mod.get_unified_models(user=user)

    assert len(result) == 5, f'expected 5 models (3 providers, overlapping ids), got {len(result)}'
    keys = [m['selection_key'] for m in result]
    unique_keys = set(keys)
    assert len(unique_keys) == len(result), (
        f'selection_keys must be unique across full response: '
        f'{len(unique_keys)} unique vs {len(result)} total — duplicates: '
        f'{[k for k in keys if keys.count(k) > 1]}'
    )


@pytest.mark.asyncio
async def test_provider_fetch_failure_does_not_break_selection_keys():
    """Provider A succeeds, provider B raises; A's models have valid selection_keys."""
    from fastapi import HTTPException

    from myah.routers import providers as mod

    user = MagicMock()
    user.id = 'test-user'

    status_rows = [
        MagicMock(provider_id='nous', is_valid=True),
        MagicMock(provider_id='broken', is_valid=True),
    ]

    async def mock_aux(user_arg, method, path, **kwargs):
        if path == '/api/plugins/myah-admin/providers/nous/models':
            return [
                {'id': 'anthropic/claude-opus-4.7', 'name': 'Claude Opus'},
            ]
        raise HTTPException(status_code=502, detail='upstream down')

    with patch.object(mod.UserProviderStatuses, 'list_for_user', lambda uid: status_rows):
        with patch.object(mod, '_oss_union_with_hermes_catalog', AsyncMock(return_value=['nous', 'broken'])):
            with patch.object(mod, 'web_call_or_raise', AsyncMock(side_effect=mock_aux)):
                result = await mod.get_unified_models(user=user)

    assert len(result) == 1
    m = result[0]
    assert 'selection_key' in m, 'surviving model must have selection_key'
    assert m['selection_key'] == 'nous::anthropic/claude-opus-4.7'
    # Uniqueness holds trivially for single-element lists, but assert for completeness.
    assert len({r['selection_key'] for r in result}) == len(result)


@pytest.mark.asyncio
async def test_empty_provider_model_list_still_emits_selection_key_on_others():
    """Provider A returns no models, provider B returns one. B's model
    must still have selection_key. Also verifies that an empty model list
    from a valid provider doesn't cause an exception.
    """
    from myah.routers import providers as mod

    user = MagicMock()
    user.id = 'test-user'

    status_rows = [
        MagicMock(provider_id='empty-provider', is_valid=True),
        MagicMock(provider_id='nous', is_valid=True),
    ]

    async def mock_aux(user_arg, method, path, **kwargs):
        if path == '/api/plugins/myah-admin/providers/empty-provider/models':
            return []
        if path == '/api/plugins/myah-admin/providers/nous/models':
            return [{'id': 'glm-5', 'name': 'GLM-5'}]
        raise AssertionError(f'unexpected path: {path}')

    with patch.object(mod.UserProviderStatuses, 'list_for_user', lambda uid: status_rows):
        with patch.object(
            mod,
            '_oss_union_with_hermes_catalog',
            AsyncMock(return_value=['empty-provider', 'nous']),
        ):
            with patch.object(mod, 'web_call_or_raise', AsyncMock(side_effect=mock_aux)):
                result = await mod.get_unified_models(user=user)

    assert len(result) == 1, f'expected 1 model (from nous), got {len(result)}'
    m = result[0]
    assert 'selection_key' in m, f'model {m.get("id")} missing selection_key'
    assert m['selection_key'] == 'nous::glm-5'
