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


@pytest.fixture(autouse=True)
def _clear_unified_models_cache():
    """Reset the module-level _unified_models_cache between tests.

    providers.py keeps an in-process cache with a 30s TTL — far longer
    than the test suite runs. Without this fixture, tests sharing the
    same `_fake_user()` id would cross-contaminate via cache hits and
    bypass their own mocked state. See `get_unified_models` for the
    cache contract (keyed on user.id + deployment mode + provider tuple).
    """
    from myah.routers import providers

    providers._unified_models_cache.clear()
    yield
    providers._unified_models_cache.clear()


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

    with (
        patch(
            'myah.routers.providers.UserProviderStatuses.list_for_user',
            return_value=[],
        ),
        patch(
            'myah.utils.hermes_web.fetch_hermes_provider_catalog',
            new=AsyncMock(return_value=fake_catalog),
        ),
        patch(
            'myah.routers.providers.web_call_or_raise',
            new=AsyncMock(side_effect=fake_web_call),
        ),
    ):
        from myah.routers.providers import get_unified_models

        result = await get_unified_models(user=_fake_user())

    # Result is a flat list of model dicts each tagged with provider id
    # (see providers.py:404 m['tags'] = [{'name': pid}]).
    assert isinstance(result, list), f'expected flat list, got {type(result).__name__}'
    tag_names = {m['tags'][0]['name'] for m in result}
    assert tag_names == {'openrouter', 'opencode-go', 'zai'}, f'expected all 3 hermes providers, got {tag_names}'


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
    with (
        patch(
            'myah.routers.providers.UserProviderStatuses.list_for_user',
            return_value=fake_db_rows,
        ),
        patch(
            'myah.utils.hermes_web.fetch_hermes_provider_catalog',
            new=fake_fetch,
        ),
        patch(
            'myah.routers.providers.web_call_or_raise',
            new=AsyncMock(side_effect=fake_web_call),
        ),
    ):
        from myah.routers.providers import get_unified_models

        result = await get_unified_models(user=_fake_user())

    # Hosted: hermes catalog must not be consulted (statuses non-empty).
    fake_fetch.assert_not_called()
    assert isinstance(result, list)
    tag_names = {m['tags'][0]['name'] for m in result}
    assert tag_names == {'openrouter'}


@pytest.mark.asyncio
async def test_get_unified_models_oss_unions_db_with_hermes_catalog(monkeypatch):
    """User onboarded one provider via UI with a bogus key (DB has
    one row) but has multiple OTHER providers configured via
    `hermes config set …`. /models must fan-out to the UNION of DB
    providers + CLI-configured providers, not just the DB row.

    Regression test for the user-reported bug: 'I clicked anthropic
    with a fake key to bypass the picker, then the model dropdown
    only showed anthropic models — not my opencode-go / openrouter
    models that I configured via the CLI'.
    """
    monkeypatch.setenv('MYAH_DEPLOYMENT_MODE', 'oss')

    fake_db_rows = [SimpleNamespace(provider_id='anthropic', is_valid=True)]

    fake_catalog = [
        {'id': 'openrouter', 'has_credential': True},
        {'id': 'anthropic', 'has_credential': True},  # also in DB — must not double-fetch
        {'id': 'opencode-go', 'has_credential': True},
    ]

    async def fake_web_call(user, method, path):
        # Track which provider got fanned-out to.
        for p in ('anthropic', 'openrouter', 'opencode-go', 'zai'):
            if path.endswith(f'/{p}/models'):
                return [{'id': f'{p}-model-1', 'name': f'{p}-model-1'}]
        return []

    with (
        patch(
            'myah.routers.providers.UserProviderStatuses.list_for_user',
            return_value=fake_db_rows,
        ),
        patch(
            'myah.utils.hermes_web.fetch_hermes_provider_catalog',
            new=AsyncMock(return_value=fake_catalog),
        ),
        patch(
            'myah.routers.providers.web_call_or_raise',
            new=AsyncMock(side_effect=fake_web_call),
        ),
    ):
        from myah.routers.providers import get_unified_models

        result = await get_unified_models(user=_fake_user())

    tag_names = [m['tags'][0]['name'] for m in result]
    # No duplicates: anthropic is in both DB and catalog, must fan-out
    # only once. Order: DB first (anthropic), then catalog providers
    # not in DB (openrouter, opencode-go).
    assert tag_names == ['anthropic', 'openrouter', 'opencode-go'], (
        f'expected union fan-out without dupes, got {tag_names}'
    )


@pytest.mark.asyncio
async def test_get_unified_models_oss_falls_through_when_catalog_empty(monkeypatch):
    """If hermes is unreachable / returns empty catalog, behave like
    hosted: empty model list, no crash.
    """
    monkeypatch.setenv('MYAH_DEPLOYMENT_MODE', 'oss')

    with (
        patch(
            'myah.routers.providers.UserProviderStatuses.list_for_user',
            return_value=[],
        ),
        patch(
            'myah.utils.hermes_web.fetch_hermes_provider_catalog',
            new=AsyncMock(return_value=[]),
        ),
    ):
        from myah.routers.providers import get_unified_models

        result = await get_unified_models(user=_fake_user())

    assert result == []


# ──────────────────────────────────────────────────────────────────────
# get_status — same OSS catalog short-circuit, applied to the status
# endpoint that drives the platform's "connected providers" surfaces:
#   - the post-Welcome "Connect a provider" picker auto-skip
#   - Settings → Providers tab "Connected" badges
#   - the model picker's provider-tag filtering (connectedValidProvidersV2)
#   - Aux / Vision provider dropdowns in Agent → Models
#
# Same root cause as the /models tests above: hermes config set …
# writes ~/.hermes/{.env, auth.json, config.yaml} directly; the
# platform's UserProviderStatuses table is only written by the
# platform's own onboarding flows, so CLI-configured providers never
# reach it and every status-driven surface renders empty.
# ──────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_status_oss_mode_synthesises_rows_from_hermes_catalog(monkeypatch):
    """When MYAH_DEPLOYMENT_MODE=oss and the platform DB has no
    UserProviderStatuses, get_status should synthesise rows from the
    hermes catalog for every provider where has_credential=True.
    """
    monkeypatch.setenv('MYAH_DEPLOYMENT_MODE', 'oss')

    fake_catalog = [
        {'id': 'openrouter', 'has_credential': True},
        {'id': 'anthropic', 'has_credential': True},
        # Provider in the catalog but without a credential — must NOT
        # appear in the status list (would produce a false-positive
        # green "Connected" badge in Settings → Providers).
        {'id': 'openai', 'has_credential': False},
        # Malformed entries are tolerated.
        {'has_credential': True},  # missing id
        {'id': '', 'has_credential': True},  # empty id
    ]

    with (
        patch(
            'myah.routers.providers.UserProviderStatuses.list_for_user',
            return_value=[],
        ),
        patch(
            'myah.utils.hermes_web.fetch_hermes_provider_catalog',
            new=AsyncMock(return_value=fake_catalog),
        ),
    ):
        from myah.routers.providers import get_status

        result = await get_status(user=_fake_user())

    assert isinstance(result, list)
    provider_ids = {r['provider_id'] for r in result}
    assert provider_ids == {'openrouter', 'anthropic'}, f'expected only credentialled providers, got {provider_ids}'

    # Synthesised rows must conform to the ProviderStatusRow contract
    # consumed by the frontend (stores/providers.ts:refreshProviderStatus).
    for row in result:
        assert row['is_valid'] is True
        assert row['reconnect_needed'] is False
        assert row['reconnect_reason'] is None
        assert row['key_last_four'] == ''
        assert row['entry_id'] is None


@pytest.mark.asyncio
async def test_get_status_hosted_mode_unchanged(monkeypatch):
    """Outside OSS mode: only platform DB rows are returned; the
    hermes catalog must not be consulted. The hosted onboarding flow
    is the sole writer of UserProviderStatuses, so the DB is the
    authoritative source.
    """
    monkeypatch.delenv('MYAH_DEPLOYMENT_MODE', raising=False)

    fake_db_rows = [
        SimpleNamespace(
            model_dump=lambda: {
                'provider_id': 'openrouter',
                'entry_id': 'entry-1',
                'key_last_four': '1234',
                'is_valid': True,
                'reconnect_needed': False,
                'reconnect_reason': None,
            }
        ),
    ]

    fake_fetch = AsyncMock(return_value=[])
    with (
        patch(
            'myah.routers.providers.UserProviderStatuses.list_for_user',
            return_value=fake_db_rows,
        ),
        patch(
            'myah.utils.hermes_web.fetch_hermes_provider_catalog',
            new=fake_fetch,
        ),
    ):
        from myah.routers.providers import get_status

        result = await get_status(user=_fake_user())

    fake_fetch.assert_not_called()
    assert [r['provider_id'] for r in result] == ['openrouter']
    assert result[0]['key_last_four'] == '1234'


@pytest.mark.asyncio
async def test_get_status_oss_unions_db_rows_with_hermes_catalog(monkeypatch):
    """User has onboarded one provider via the platform UI (even with
    a bogus key — the platform marks every credential save is_valid=True
    optimistically) but also has multiple OTHER providers configured
    via `hermes config set …`. /status must return the UNION: the DB
    row keeps its real key_last_four, and CLI-configured providers
    appear as synthesised rows.

    This is the bug the user hit: bypassing the "Connect a provider"
    screen with a fake key left UserProviderStatuses with one row,
    which disengaged the original fresh-install-only short-circuit
    forever — every CLI-configured provider disappeared from Settings →
    Providers and the chat model picker the moment a single provider
    was onboarded.
    """
    monkeypatch.setenv('MYAH_DEPLOYMENT_MODE', 'oss')

    fake_db_rows = [
        SimpleNamespace(
            model_dump=lambda: {
                'provider_id': 'anthropic',
                'entry_id': 'entry-1',
                'key_last_four': '5678',
                'is_valid': True,
                'reconnect_needed': False,
                'reconnect_reason': None,
            }
        ),
    ]

    fake_catalog = [
        {'id': 'openrouter', 'has_credential': True},
        {'id': 'anthropic', 'has_credential': True},  # also in DB — must not duplicate
        {'id': 'zai', 'has_credential': True},
        {'id': 'openai', 'has_credential': False},  # uncredentialled, must not appear
    ]

    with (
        patch(
            'myah.routers.providers.UserProviderStatuses.list_for_user',
            return_value=fake_db_rows,
        ),
        patch(
            'myah.utils.hermes_web.fetch_hermes_provider_catalog',
            new=AsyncMock(return_value=fake_catalog),
        ),
    ):
        from myah.routers.providers import get_status

        result = await get_status(user=_fake_user())

    provider_ids = [r['provider_id'] for r in result]
    # DB row comes first (preserves insertion order), catalog providers
    # not in the DB are appended, deduplicated by id.
    assert provider_ids == ['anthropic', 'openrouter', 'zai'], f'expected union DB + catalog, got {provider_ids}'

    by_id = {r['provider_id']: r for r in result}
    # DB row preserves its real key_last_four.
    assert by_id['anthropic']['key_last_four'] == '5678'
    assert by_id['anthropic']['entry_id'] == 'entry-1'
    # Catalog-synthesised rows have no key_last_four.
    assert by_id['openrouter']['key_last_four'] == ''
    assert by_id['openrouter']['entry_id'] is None
    assert by_id['openrouter']['is_valid'] is True


@pytest.mark.asyncio
async def test_get_status_oss_empty_catalog_returns_empty(monkeypatch):
    """OSS with an empty catalog (hermes unreachable, no providers
    configured): return an empty list — the frontend will then show
    the 'Connect a provider' picker, which is correct behavior.
    """
    monkeypatch.setenv('MYAH_DEPLOYMENT_MODE', 'oss')

    with (
        patch(
            'myah.routers.providers.UserProviderStatuses.list_for_user',
            return_value=[],
        ),
        patch(
            'myah.utils.hermes_web.fetch_hermes_provider_catalog',
            new=AsyncMock(return_value=[]),
        ),
    ):
        from myah.routers.providers import get_status

        result = await get_status(user=_fake_user())

    assert result == []


@pytest.mark.asyncio
async def test_get_unified_models_cache_invalidates_on_provider_set_change(monkeypatch):
    """Regression: the unified-models cache must miss when the resolved
    provider set changes between calls — even without a platform-side
    credential mutation.

    Scenario this guards against:
        1. OSS user opens model picker — /models call 1 caches the
           current catalog state (just openrouter configured).
        2. User runs `hermes config set anthropic.api_key=…` in their
           terminal. That writes directly to ~/.hermes/{auth.json,.env},
           bypassing every platform credential endpoint. No
           _invalidate_unified_models_cache() runs.
        3. User refreshes the picker — /models call 2.

    Expected: call 2 sees both openrouter AND anthropic.
    Regression (the bug this test exists to catch): a cache keyed only
    on user.id returns call 1's stale openrouter-only list for up to
    30 seconds, silently bypassing the #188 union contract.
    """
    monkeypatch.setenv('MYAH_DEPLOYMENT_MODE', 'oss')

    catalog_state = {
        'providers': [{'id': 'openrouter', 'has_credential': True}],
    }

    async def fake_catalog_fetch(user):
        return list(catalog_state['providers'])

    async def fake_web_call(user, method, path):
        for p in ('openrouter', 'anthropic'):
            if path.endswith(f'/{p}/models'):
                return [{'id': f'{p}/model-1', 'name': f'{p} m1'}]
        return []

    with (
        patch(
            'myah.routers.providers.UserProviderStatuses.list_for_user',
            return_value=[],
        ),
        patch(
            'myah.utils.hermes_web.fetch_hermes_provider_catalog',
            side_effect=fake_catalog_fetch,
        ),
        patch(
            'myah.routers.providers.web_call_or_raise',
            new=AsyncMock(side_effect=fake_web_call),
        ),
    ):
        from myah.routers.providers import get_unified_models

        result_1 = await get_unified_models(user=_fake_user())
        tags_1 = {m['tags'][0]['name'] for m in result_1}
        assert tags_1 == {'openrouter'}, f'call 1: expected openrouter only, got {tags_1}'

        catalog_state['providers'].append(
            {'id': 'anthropic', 'has_credential': True}
        )

        result_2 = await get_unified_models(user=_fake_user())
        tags_2 = {m['tags'][0]['name'] for m in result_2}
        assert tags_2 == {'openrouter', 'anthropic'}, (
            f'call 2: expected both providers after CLI mutation, got {tags_2} — '
            'cache served stale state (regression: user-id-only cache key)'
        )
