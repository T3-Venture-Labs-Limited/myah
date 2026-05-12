# Tests for open_webui/routers/agent_config.py — the /api/v1/agent/* proxy endpoints.
# Uses the importlib stub pattern (same as test_myah_command_intercept.py) to load
# agent_config.py without triggering Open WebUI's DB/Redis/migrations machinery.

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest


def _load_agent_config_module():
    """Load open_webui/routers/agent_config.py with all heavy deps stubbed."""

    def _make(name, **attrs):
        m = ModuleType(name)
        for k, v in attrs.items():
            setattr(m, k, v)
        return m

    internal_db = _make('open_webui.internal.db', get_session=MagicMock())

    env_mod = _make(
        'open_webui.env',
        WEBUI_AUTH=True,
        ENABLE_AGENT_SETTINGS_UI=True,
    )

    constants_mod = _make(
        'open_webui.constants',
        ERROR_MESSAGES=SimpleNamespace(
            NOT_FOUND='not found',
            ACCESS_PROHIBITED='forbidden',
        ),
    )

    users_update = MagicMock()
    users_mod = _make(
        'open_webui.models.users',
        Users=SimpleNamespace(update_user_by_id=users_update),
        UserModel=MagicMock(),
    )

    auth_mod = _make(
        'open_webui.utils.auth',
        get_verified_user=MagicMock(),
        get_admin_user=MagicMock(),
    )

    agent_proxy_aux_call = AsyncMock()
    agent_proxy_mod = _make(
        'open_webui.utils.agent_proxy',
        aux_call=agent_proxy_aux_call,
        AUX_ALLOWED_TASKS={'title_generation', 'follow_up_generation'},
        normalize_catalog_models=lambda raw: [m['id'] if isinstance(m, dict) else m for m in (raw or [])],
    )

    hermes_web_call = AsyncMock()
    hermes_web_mod = _make(
        'open_webui.utils.hermes_web',
        web_call=hermes_web_call,
    )

    def _resolve_aux_default_stub(provider, task, *, catalog=None):
        """Minimal stub matching config._resolve_aux_default behaviour."""
        from types import SimpleNamespace as _SN
        _VISION_INCAPABLE = {'deepseek'}
        _VISION_FALLBACKS = {'zai': 'glm-5v-turbo'}
        _DEFAULT_FALLBACKS = {
            'openrouter': 'google/gemini-3-flash-preview',
            'anthropic': 'claude-haiku-4-5-20251001',
            'gemini': 'gemini-2.5-flash',
            'zai': 'glm-4.5-flash',
            'deepseek': 'deepseek-chat',
            'xai': 'grok-4-1-fast-reasoning',
            'openai-codex': 'gpt-5',
        }
        _DEFAULT_TASKS = {
            'title_generation', 'follow_up_generation', 'compression',
            'session_search', 'approval', 'skills_hub', 'mcp', 'flush_memories',
        }
        if task == 'vision':
            if provider in _VISION_INCAPABLE:
                return None
            candidate = _VISION_FALLBACKS.get(provider) or _DEFAULT_FALLBACKS.get(provider)
        elif task in _DEFAULT_TASKS:
            candidate = _DEFAULT_FALLBACKS.get(provider)
        else:
            return None
        if candidate is None:
            return None
        if catalog is not None:
            catalog_models = catalog.get(provider, [])
            if candidate not in catalog_models:
                return catalog_models[0] if catalog_models else None
        return candidate

    config_mod = _make(
        'open_webui.config',
        AUX_DEFAULT_FALLBACKS={
            'openrouter': 'google/gemini-3-flash-preview',
            'anthropic': 'claude-haiku-4-5-20251001',
            'gemini': 'gemini-2.5-flash',
            'zai': 'glm-4.5-flash',
            'deepseek': 'deepseek-chat',
            'xai': 'grok-4-1-fast-reasoning',
            'openai-codex': 'gpt-5',
        },
        AUX_VISION_FALLBACKS={'zai': 'glm-5v-turbo'},
        AUX_VISION_INCAPABLE=frozenset({'deepseek'}),
        AUX_DEFAULT_TASKS=frozenset({
            'title_generation', 'follow_up_generation', 'compression',
            'session_search', 'approval', 'skills_hub', 'mcp', 'flush_memories',
        }),
        _resolve_aux_default=_resolve_aux_default_stub,
    )

    for mod in (internal_db, env_mod, constants_mod, users_mod, auth_mod, agent_proxy_mod, hermes_web_mod, config_mod):
        sys.modules[mod.__name__] = mod

    router_path = Path(__file__).resolve().parent.parent.parent.parent.parent / 'routers' / 'agent_config.py'
    spec = importlib.util.spec_from_file_location('open_webui.routers.agent_config', router_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules['open_webui.routers.agent_config'] = module
    spec.loader.exec_module(module)

    module._test_users_update = users_update
    module._test_aux_call = agent_proxy_aux_call
    module._test_web_call = hermes_web_call
    return module


@pytest.fixture
def agent_config_mod():
    mod = _load_agent_config_module()
    mod._test_users_update.reset_mock()
    mod._test_aux_call.reset_mock()
    mod._test_web_call.reset_mock()
    return mod


def _fake_user():
    return SimpleNamespace(id='user-abc', role='user', email='u@myah.dev')


@pytest.mark.asyncio
async def test_get_agent_config_forwards_to_container(agent_config_mod):
    agent_config_mod._test_web_call.return_value = {
        'status': 200,
        'body': {'model': 'anthropic/claude-opus-4.6', 'auxiliary': {}},
        'headers': {},
    }

    resp = await agent_config_mod.get_agent_config(user=_fake_user())

    agent_config_mod._test_web_call.assert_awaited_once()
    call = agent_config_mod._test_web_call.await_args
    # Plugin-namespace path (Phase 7.7 migration)
    assert call.args[1] == 'GET'
    assert call.args[2] == '/api/plugins/myah-admin/config'
    assert resp['model'] == 'anthropic/claude-opus-4.6'


@pytest.mark.asyncio
async def test_patch_agent_config_mirrors_model_to_user_settings(agent_config_mod):
    """Patch goes via GET-merge-PUT against Hermes-native /api/config."""

    async def _side(_user, method, _path, **_kw):
        if method == 'GET':
            return {'status': 200, 'body': {'model': 'old'}, 'headers': {}}
        # PUT
        return {'status': 200, 'body': {'ok': True}, 'headers': {}}

    agent_config_mod._test_web_call.side_effect = _side

    user = _fake_user()
    await agent_config_mod.patch_agent_config(
        body={'model': 'openai/gpt-5'},
        user=user,
    )

    # Verify a GET then a PUT to /api/plugins/myah-admin/config (Phase 7.7 migration)
    methods = [c.args[1] for c in agent_config_mod._test_web_call.await_args_list]
    paths = [c.args[2] for c in agent_config_mod._test_web_call.await_args_list]
    assert methods == ['GET', 'PUT']
    assert paths == ['/api/plugins/myah-admin/config', '/api/plugins/myah-admin/config']

    # PUT body should be {'config': merged_dict_with_new_model}.
    # Tier 2B Task 2B.6: the platform translates string-form 'openai/gpt-5'
    # into Hermes-canonical dict-form {provider, default} before forwarding.
    put_call = agent_config_mod._test_web_call.await_args_list[-1]
    put_body = put_call.kwargs.get('json_body', {})
    assert put_body['config']['model'] == {'provider': 'openai', 'default': 'gpt-5'}

    agent_config_mod._test_users_update.assert_called_once()
    call = agent_config_mod._test_users_update.call_args
    all_args = call.args + tuple(call.kwargs.values())
    assert user.id in all_args
    # The user-settings mirror still uses the bare-string slug for
    # backwards compatibility with consumers that read user.agent_model.
    dict_args = [a for a in all_args if isinstance(a, dict)]
    assert any(a.get('agent_model') == 'openai/gpt-5' for a in dict_args)


@pytest.mark.asyncio
async def test_patch_agent_config_no_mirror_when_model_not_in_body(agent_config_mod):
    async def _side(_user, method, _path, **_kw):
        if method == 'GET':
            return {'status': 200, 'body': {}, 'headers': {}}
        return {'status': 200, 'body': {'ok': True}, 'headers': {}}

    agent_config_mod._test_web_call.side_effect = _side

    await agent_config_mod.patch_agent_config(
        body={'auxiliary.vision.model': 'google/gemini-2.5-flash'},
        user=_fake_user(),
    )

    agent_config_mod._test_users_update.assert_not_called()


@pytest.mark.asyncio
async def test_get_soul_passes_through_etag(agent_config_mod):
    agent_config_mod._test_web_call.return_value = {
        'status': 200,
        'body': 'You are Myah.\n',
        'headers': {
            'etag': '"sha256-abc123"',
            'content-type': 'text/markdown',
        },
    }

    resp = await agent_config_mod.get_agent_soul(user=_fake_user())
    # _proxy_response returns a Response object
    assert resp.status_code == 200
    # path goes to the myah-admin plugin
    call = agent_config_mod._test_web_call.await_args
    assert call.args[2] == '/api/plugins/myah-admin/config/soul'


@pytest.mark.asyncio
async def test_put_soul_forwards_if_match(agent_config_mod):
    agent_config_mod._test_web_call.return_value = {
        'status': 200,
        'body': {'ok': True},
        'headers': {'etag': '"sha256-def456"'},
    }

    await agent_config_mod.put_agent_soul(
        request=None,
        body='new SOUL body',
        if_match='"sha256-abc123"',
        user=_fake_user(),
    )

    call = agent_config_mod._test_web_call.await_args
    # headers kwarg should have If-Match
    headers_arg = call.kwargs.get('headers') or {}
    assert headers_arg.get('If-Match') == '"sha256-abc123"'
    # raw body forwarded as text_body, not json
    assert call.kwargs.get('text_body') == 'new SOUL body'


@pytest.mark.asyncio
async def test_put_soul_forwards_412_with_current_body(agent_config_mod):
    from fastapi import HTTPException

    agent_config_mod._test_web_call.return_value = {
        'status': 412,
        'body': {'error': 'precondition failed', 'current_body': 'server-side SOUL'},
        'headers': {},
    }

    with pytest.raises(HTTPException) as exc_info:
        await agent_config_mod.put_agent_soul(
            request=None,
            body='my edit',
            if_match='"stale"',
            user=_fake_user(),
        )
    assert exc_info.value.status_code == 412
    assert exc_info.value.detail.get('current_body') == 'server-side SOUL'


@pytest.mark.asyncio
async def test_put_soul_413_propagates(agent_config_mod):
    from fastapi import HTTPException

    agent_config_mod._test_web_call.return_value = {
        'status': 413,
        'body': {'error': 'SOUL exceeds 32768 chars', 'limit': 32768, 'got': 40000},
        'headers': {},
    }

    with pytest.raises(HTTPException) as exc_info:
        await agent_config_mod.put_agent_soul(
            request=None,
            body='x' * 40000,
            if_match='"etag"',
            user=_fake_user(),
        )
    assert exc_info.value.status_code == 413
    assert exc_info.value.detail['limit'] == 32768


@pytest.mark.asyncio
async def test_post_restart_forwards_409_when_busy(agent_config_mod):
    from fastapi import HTTPException

    agent_config_mod._test_aux_call.return_value = {
        'status': 409,
        'body': {'error': 'busy', 'busy_sessions': ['sess-1']},
        'headers': {},
    }

    with pytest.raises(HTTPException) as exc_info:
        await agent_config_mod.post_agent_restart(user=_fake_user())
    assert exc_info.value.status_code == 409
    assert 'sess-1' in exc_info.value.detail['busy_sessions']
    # Restart goes to the gateway runtime-control surface (still aux_call)
    call = agent_config_mod._test_aux_call.await_args
    assert call.args[2] == '/myah/v1/admin/gateway/restart'


@pytest.mark.asyncio
async def test_post_aux_forwards_to_container(agent_config_mod):
    agent_config_mod._test_aux_call.return_value = {
        'status': 200,
        'body': {'choices': [{'message': {'content': '{"title": "Test"}'}}], 'usage': {}},
        'headers': {},
    }

    resp = await agent_config_mod.post_agent_aux(
        task='title_generation',
        body={'messages': [{'role': 'user', 'content': 'hi'}]},
        user=_fake_user(),
    )
    assert 'Test' in resp['choices'][0]['message']['content']


@pytest.mark.asyncio
async def test_post_aux_rejects_disallowed_task(agent_config_mod):
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc_info:
        await agent_config_mod.post_agent_aux(
            task='arbitrary_task',
            body={'messages': []},
            user=_fake_user(),
        )
    assert exc_info.value.status_code == 400
    agent_config_mod._test_aux_call.assert_not_awaited()


@pytest.mark.asyncio
async def test_post_reset_section(agent_config_mod):
    agent_config_mod._test_web_call.return_value = {
        'status': 200,
        'body': {'ok': True, 'section': 'aux_vision'},
        'headers': {},
    }

    resp = await agent_config_mod.post_agent_reset(section='aux_vision', user=_fake_user())
    assert resp['section'] == 'aux_vision'
    call = agent_config_mod._test_web_call.await_args
    assert call.args[2] == '/api/plugins/myah-admin/config/reset/aux_vision'


@pytest.mark.asyncio
async def test_get_last_reseed(agent_config_mod):
    agent_config_mod._test_web_call.return_value = {
        'status': 200,
        'body': {'timestamp': '2026-04-17T15:00:00Z', 'files': ['config']},
        'headers': {},
    }
    resp = await agent_config_mod.get_agent_last_reseed(user=_fake_user())
    assert resp['files'] == ['config']


@pytest.mark.asyncio
async def test_feature_flag_disabled_returns_404(agent_config_mod, monkeypatch):
    from fastapi import HTTPException

    monkeypatch.setattr(sys.modules['open_webui.env'], 'ENABLE_AGENT_SETTINGS_UI', False)

    with pytest.raises(HTTPException) as exc_info:
        await agent_config_mod.get_agent_config(user=_fake_user())
    assert exc_info.value.status_code == 404


# ── seed-aux-defaults and aux-default-fallbacks endpoint tests ────────────────


@pytest.mark.asyncio
async def test_seed_aux_defaults_openrouter_single_patch(agent_config_mod):
    """Single nested patch translates to one GET-merge-PUT against /api/config."""
    catalog_body = {'openrouter': {'curated_models': ['google/gemini-3-flash-preview']}}

    async def _side_effect(_user, method, path, **_kwargs):
        if method == 'GET' and 'providers' in path:
            return {'status': 200, 'body': catalog_body, 'headers': {}}
        if method == 'GET' and path == '/api/plugins/myah-admin/config':
            return {'status': 200, 'body': {}, 'headers': {}}
        if method == 'PUT' and path == '/api/plugins/myah-admin/config':
            return {'status': 200, 'body': {'ok': True}, 'headers': {}}
        return {'status': 200, 'body': {}, 'headers': {}}

    agent_config_mod._test_web_call.side_effect = _side_effect

    resp = await agent_config_mod.seed_aux_defaults(
        body=agent_config_mod.SeedAuxDefaultsRequest(provider='openrouter'),
        user=_fake_user(),
    )

    # Exactly one PUT to /api/config (the nested-auxiliary write)
    put_calls = [
        c for c in agent_config_mod._test_web_call.await_args_list
        if c.args[1] == 'PUT' and c.args[2] == '/api/plugins/myah-admin/config'
    ]
    assert len(put_calls) == 1

    # The PUT body should be {'config': {'auxiliary': {...}}}
    put_json = put_calls[0].kwargs.get('json_body', {})
    assert 'config' in put_json
    assert 'auxiliary' in put_json['config']

    # All 8 AUX_DEFAULT_TASKS plus vision should be seeded
    seeded_tasks = {s.task for s in resp.seeded}
    expected_default_tasks = {
        'title_generation', 'follow_up_generation', 'compression',
        'session_search', 'approval', 'skills_hub', 'mcp', 'flush_memories',
    }
    assert expected_default_tasks.issubset(seeded_tasks), (
        f'Expected all 8 default tasks seeded; got: {seeded_tasks}'
    )
    assert 'vision' in seeded_tasks


@pytest.mark.asyncio
async def test_seed_aux_defaults_applies_catalog_membership_guard(agent_config_mod):
    """Catalog membership guard: resolver uses actual catalog model, not static fallback."""
    catalog_body = {'openrouter': {'curated_models': ['anthropic/claude-opus']}}

    async def _side_effect(_user, method, path, **_kwargs):
        if method == 'GET' and 'providers' in path:
            return {'status': 200, 'body': catalog_body, 'headers': {}}
        if method == 'GET' and path == '/api/plugins/myah-admin/config':
            return {'status': 200, 'body': {}, 'headers': {}}
        return {'status': 200, 'body': {'ok': True}, 'headers': {}}

    agent_config_mod._test_web_call.side_effect = _side_effect

    resp = await agent_config_mod.seed_aux_defaults(
        body=agent_config_mod.SeedAuxDefaultsRequest(provider='openrouter'),
        user=_fake_user(),
    )

    # Each AUX_DEFAULT_TASKS entry should be seeded with the catalog-resolved model
    seeded_default = next((s for s in resp.seeded if s.task == 'title_generation'), None)
    assert seeded_default is not None
    # Static fallback is 'google/gemini-3-flash-preview' but catalog only has claude-opus
    assert seeded_default.model == 'anthropic/claude-opus'


@pytest.mark.asyncio
async def test_seed_aux_defaults_unknown_provider_returns_empty(agent_config_mod):
    """Unknown provider yields no seeded tasks."""
    catalog_body = {}  # 'atlantis' not present

    async def _side_effect(_user, method, path, **_kwargs):
        if method == 'GET' and 'providers' in path:
            return {'status': 200, 'body': catalog_body, 'headers': {}}
        if method == 'GET' and path == '/api/plugins/myah-admin/config':
            return {'status': 200, 'body': {}, 'headers': {}}
        return {'status': 200, 'body': {'ok': True}, 'headers': {}}

    agent_config_mod._test_web_call.side_effect = _side_effect

    resp = await agent_config_mod.seed_aux_defaults(
        body=agent_config_mod.SeedAuxDefaultsRequest(provider='atlantis'),
        user=_fake_user(),
    )

    assert resp.seeded == []


@pytest.mark.asyncio
async def test_seed_aux_defaults_vision_incapable_skips_vision(agent_config_mod):
    """Vision-incapable provider (deepseek) seeds aux_default but skips vision."""
    catalog_body = {'deepseek': {'curated_models': ['deepseek-chat']}}

    async def _side_effect(_user, method, path, **_kwargs):
        if method == 'GET' and 'providers' in path:
            return {'status': 200, 'body': catalog_body, 'headers': {}}
        if method == 'GET' and path == '/api/plugins/myah-admin/config':
            return {'status': 200, 'body': {}, 'headers': {}}
        return {'status': 200, 'body': {'ok': True}, 'headers': {}}

    agent_config_mod._test_web_call.side_effect = _side_effect

    resp = await agent_config_mod.seed_aux_defaults(
        body=agent_config_mod.SeedAuxDefaultsRequest(provider='deepseek'),
        user=_fake_user(),
    )

    seeded_tasks = {s.task for s in resp.seeded}
    skipped_tasks = {s.task for s in resp.skipped}

    # All 8 default tasks seeded; vision is skipped for deepseek
    expected_default_tasks = {
        'title_generation', 'follow_up_generation', 'compression',
        'session_search', 'approval', 'skills_hub', 'mcp', 'flush_memories',
    }
    assert expected_default_tasks.issubset(seeded_tasks), (
        f'Expected all 8 default tasks seeded; got: {seeded_tasks}'
    )
    assert 'vision' not in seeded_tasks
    assert 'vision' in skipped_tasks


@pytest.mark.asyncio
async def test_aux_default_fallbacks_endpoint_shape(agent_config_mod):
    """GET /aux-default-fallbacks returns dict with all 4 expected keys."""
    resp = await agent_config_mod.get_aux_default_fallbacks(user=_fake_user())

    assert 'aux_default' in resp
    assert 'vision' in resp
    assert 'vision_incapable' in resp
    assert 'aux_default_tasks' in resp

    # vision_incapable and aux_default_tasks should be lists (serializable)
    assert isinstance(resp['vision_incapable'], list)
    assert isinstance(resp['aux_default_tasks'], list)


@pytest.mark.asyncio
async def test_seed_aux_defaults_nested_patch_fallback(agent_config_mod):
    """Falls back to N per-task PUTs when the first nested PUT returns 422."""
    catalog_body = {'openrouter': {'curated_models': ['google/gemini-3-flash-preview']}}

    put_call_count = 0

    async def _side_effect(_user, method, path, **_kwargs):
        nonlocal put_call_count
        if method == 'GET' and 'providers' in path:
            return {'status': 200, 'body': catalog_body, 'headers': {}}
        if method == 'GET' and path == '/api/plugins/myah-admin/config':
            return {'status': 200, 'body': {}, 'headers': {}}
        if method == 'PUT' and path == '/api/plugins/myah-admin/config':
            put_call_count += 1
            if put_call_count == 1:
                return {'status': 422, 'body': {'detail': 'unprocessable'}, 'headers': {}}
            return {'status': 200, 'body': {'ok': True}, 'headers': {}}
        return {'status': 200, 'body': {}, 'headers': {}}

    agent_config_mod._test_web_call.side_effect = _side_effect

    resp = await agent_config_mod.seed_aux_defaults(
        body=agent_config_mod.SeedAuxDefaultsRequest(provider='openrouter'),
        user=_fake_user(),
    )

    # Should have retried with individual PUTs after the nested PUT failed
    assert put_call_count >= 2

    # Still seeded successfully — at minimum title_generation (first AUX_DEFAULT_TASKS entry)
    seeded_tasks = {s.task for s in resp.seeded}
    assert 'title_generation' in seeded_tasks
