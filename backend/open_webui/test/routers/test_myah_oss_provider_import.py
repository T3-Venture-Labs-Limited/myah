"""OSS-mode regression tests for the provider catalog fall-back.

In OSS mode, the model picker should source providers from the user's
host-side hermes credential pool (not just providers the user has
explicitly 'connected' via UI). This test simulates the OSS scenario
where the platform DB has zero UserProviderStatuses but the user's
hermes has multiple providers configured.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest


def _fake_user():
    return SimpleNamespace(id='test-user-oss')


@pytest.mark.asyncio
async def test_get_unified_models_oss_mode_uses_hermes_catalog(monkeypatch):
    """When MYAH_DEPLOYMENT_MODE=oss and platform DB has no
    UserProviderStatuses, get_unified_models should source providers
    from the hermes catalog and surface their models.
    """
    monkeypatch.setenv('MYAH_DEPLOYMENT_MODE', 'oss')

    fake_catalog = [
        {
            'id': 'openrouter',
            'label': 'OpenRouter',
            'has_credential': True,
            'models': [{'id': 'moonshotai/kimi-k2', 'name': 'Kimi K2'}],
        },
        {
            'id': 'opencode-go',
            'label': 'OpenCode Go',
            'has_credential': True,
            'models': [{'id': 'mimo-v2.5', 'name': 'MiMo v2.5'}],
        },
        {
            'id': 'zai',
            'label': 'Z.AI',
            'has_credential': True,
            'models': [{'id': 'glm-5.1', 'name': 'GLM 5.1'}],
        },
    ]

    # Per-provider model fan-out — the catalog provides this directly,
    # but the existing fan-out also calls the per-provider /models
    # endpoint. Mock web_call_or_raise to return the catalog's models.
    async def fake_web_call(user, method, path):
        # path looks like /api/plugins/myah-admin/providers/<pid>/models
        for p in fake_catalog:
            if path.endswith(f'/{p["id"]}/models'):
                return p['models']
        return []

    with patch(
        'open_webui.routers.providers.UserProviderStatuses.list_for_user',
        return_value=[],
    ), patch(
        'open_webui.utils.hermes_web.fetch_hermes_provider_catalog',
        new=AsyncMock(return_value=fake_catalog),
    ), patch(
        'open_webui.routers.providers.web_call_or_raise',
        new=AsyncMock(side_effect=fake_web_call),
    ):
        from open_webui.routers.providers import get_unified_models
        result = await get_unified_models(user=_fake_user())

    # Result is a flat list of model dicts each tagged with provider id
    # (see providers.py:404 m['tags'] = [{'name': pid}]).
    assert isinstance(result, list), f'expected flat list, got {type(result).__name__}'
    tag_names = {m['tags'][0]['name'] for m in result}
    assert tag_names == {'openrouter', 'opencode-go', 'zai'}, (
        f'expected all 3 hermes providers, got {tag_names}'
    )


@pytest.mark.asyncio
async def test_get_unified_models_hosted_mode_unchanged(monkeypatch):
    """Outside OSS mode: only providers in the platform DB
    UserProviderStatuses table are returned; the hermes catalog must
    not even be consulted.
    """
    monkeypatch.delenv('MYAH_DEPLOYMENT_MODE', raising=False)

    fake_db_rows = [
        SimpleNamespace(provider_id='openrouter', is_valid=True),
    ]

    async def fake_web_call(user, method, path):
        if path.endswith('/openrouter/models'):
            return [{'id': 'moonshotai/kimi-k2', 'name': 'Kimi K2'}]
        return []

    fake_fetch = AsyncMock(return_value=[])
    with patch(
        'open_webui.routers.providers.UserProviderStatuses.list_for_user',
        return_value=fake_db_rows,
    ), patch(
        'open_webui.utils.hermes_web.fetch_hermes_provider_catalog',
        new=fake_fetch,
    ), patch(
        'open_webui.routers.providers.web_call_or_raise',
        new=AsyncMock(side_effect=fake_web_call),
    ):
        from open_webui.routers.providers import get_unified_models
        result = await get_unified_models(user=_fake_user())

    # Hosted: hermes catalog must not be consulted (statuses non-empty).
    fake_fetch.assert_not_called()
    assert isinstance(result, list)
    tag_names = {m['tags'][0]['name'] for m in result}
    assert tag_names == {'openrouter'}


@pytest.mark.asyncio
async def test_get_unified_models_oss_falls_through_when_catalog_empty(monkeypatch):
    """If hermes is unreachable / returns empty catalog, behave like
    hosted: empty model list, no crash.
    """
    monkeypatch.setenv('MYAH_DEPLOYMENT_MODE', 'oss')

    with patch(
        'open_webui.routers.providers.UserProviderStatuses.list_for_user',
        return_value=[],
    ), patch(
        'open_webui.utils.hermes_web.fetch_hermes_provider_catalog',
        new=AsyncMock(return_value=[]),
    ):
        from open_webui.routers.providers import get_unified_models
        result = await get_unified_models(user=_fake_user())

    assert result == []
