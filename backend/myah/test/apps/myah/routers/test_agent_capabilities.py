"""Tests for the /api/v1/agent/* router (myah/routers/agent_capabilities.py).

After the Hermes-first pivot, this router is a thin proxy: every endpoint
parses the FastAPI request, then forwards it to the per-user `hermes
dashboard` server via :func:`myah.utils.hermes_web.web_call_or_raise`.
The tests below verify that proxy contract — not the upstream agent's
business logic, which is covered by the agent's own test suite.

The previous test scaffold relied on a non-existent
``test.util.abstract_integration_test.AbstractPostgresTest`` and patched
``_get_container_name`` / ``_docker_exec`` — both removed when the router
stopped doing docker exec for admin operations. This file replaces that
scaffold with the canonical pattern used by ``test_providers_router.py``:
call the router function directly with a mocked user, patch
``web_call_or_raise`` at the import-site as an ``AsyncMock``, and assert
on the call's positional + keyword arguments.

Note on /soul: the SOUL endpoints used to live in this router but were
moved to ``routers/agent_config.py`` (see the comment block at line ~198
of agent_capabilities.py). Tests for ``PUT /soul`` therefore belong in
``test_agent_config.py``. To preserve the spirit of the original three-test
matrix (one GET, one PUT-with-body, one secondary PUT proxy), this file
covers GET ``/model``, PUT ``/model``, and PATCH ``/toolsets/{name}`` —
all three exercising the same proxy contract.
"""

import importlib.util
from pathlib import Path
from types import ModuleType
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _make_module(name: str, **attrs):
    mod = ModuleType(name)
    for key, value in attrs.items():
        setattr(mod, key, value)
    return mod


@pytest.fixture
def agent_capabilities_mod(monkeypatch):
    """Load the thin router without triggering DB-backed auth/user models."""
    auth_mod = _make_module(
        'myah.utils.auth',
        get_current_user=MagicMock(),
        get_verified_user=MagicMock(),
    )
    agent_proxy_mod = _make_module(
        'myah.utils.agent_proxy',
        aux_call_or_raise=AsyncMock(),
    )
    hermes_web_mod = _make_module(
        'myah.utils.hermes_web',
        web_call_or_raise=AsyncMock(),
    )
    users_mod = _make_module('myah.models.users', UserModel=MagicMock())

    for mod in (auth_mod, agent_proxy_mod, hermes_web_mod, users_mod):
        monkeypatch.setitem(sys.modules, mod.__name__, mod)

    sys.modules.pop('myah.routers.agent_capabilities', None)
    router_path = Path(__file__).resolve().parent.parent.parent.parent.parent / 'routers' / 'agent_capabilities.py'
    spec = importlib.util.spec_from_file_location('myah.routers.agent_capabilities', router_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules['myah.routers.agent_capabilities'] = module
    spec.loader.exec_module(module)
    yield module
    sys.modules.pop('myah.routers.agent_capabilities', None)


@pytest.mark.asyncio
async def test_get_model_returns_payload_from_web_call(agent_capabilities_mod):
    """GET /model proxies to /api/plugins/myah-admin/config/model and
    returns whatever model string the agent reports."""
    mod = agent_capabilities_mod

    user = MagicMock()
    user.id = 'test-user'

    mock_web_call = AsyncMock(return_value={'model': 'openai/gpt-4.1-mini'})
    with patch.object(mod, 'web_call_or_raise', mock_web_call):
        result = await mod.get_agent_model(user=user)

    assert result.model == 'openai/gpt-4.1-mini'

    # Proxy contract: forwarded as GET to a path ending in /model.
    assert mock_web_call.await_count == 1
    call = mock_web_call.await_args
    assert call.args[1] == 'GET'
    assert call.args[2].endswith('/model')


@pytest.mark.asyncio
async def test_put_model_proxies_payload_via_web_call(agent_capabilities_mod):
    """PUT /model forwards the body as JSON to the same agent path and
    returns the model string the agent echoes back."""
    from myah.models.agent_capabilities_schemas import AgentModelUpdateForm
    mod = agent_capabilities_mod

    user = MagicMock()
    user.id = 'test-user'

    form = AgentModelUpdateForm(model='anthropic/claude-3-5-sonnet')

    mock_web_call = AsyncMock(return_value={'model': 'anthropic/claude-3-5-sonnet'})
    with patch.object(mod, 'web_call_or_raise', mock_web_call):
        result = await mod.update_agent_model(form_data=form, user=user)

    assert result.model == 'anthropic/claude-3-5-sonnet'

    # Proxy contract: forwarded as PUT with the model dict in json_body.
    assert mock_web_call.await_count == 1
    call = mock_web_call.await_args
    assert call.args[1] == 'PUT'
    assert call.args[2].endswith('/model')
    assert call.kwargs.get('json_body') == {'model': 'anthropic/claude-3-5-sonnet'}


@pytest.mark.asyncio
async def test_patch_toolsets_proxies_enabled_flag_via_web_call(agent_capabilities_mod):
    """PATCH /toolsets/{name} forwards the enable/disable flag to the
    agent's myah-admin plugin and surfaces the agent's response."""
    from myah.models.agent_capabilities_schemas import AgentToolsetToggleForm
    mod = agent_capabilities_mod

    user = MagicMock()
    user.id = 'test-user'

    form = AgentToolsetToggleForm(enabled=True)

    mock_web_call = AsyncMock(return_value={'name': 'web', 'enabled': True})
    with patch.object(mod, 'web_call_or_raise', mock_web_call):
        result = await mod.toggle_toolset(name='web', form_data=form, user=user)

    assert result.name == 'web'
    assert result.enabled is True

    # Proxy contract: forwarded as PATCH to /toolsets/{name} with enabled
    # flag in json_body.
    assert mock_web_call.await_count == 1
    call = mock_web_call.await_args
    assert call.args[1] == 'PATCH'
    assert call.args[2].endswith('/toolsets/web')
    assert call.kwargs.get('json_body') == {'enabled': True}


@pytest.mark.asyncio
async def test_clear_commands_cache_removes_only_requesting_user_entry(agent_capabilities_mod):
    """DELETE /commands/cache drops the per-user slash-command cache so
    marketplace installs can refresh the menu immediately after Hermes restarts."""
    mod = agent_capabilities_mod

    user = MagicMock()
    user.id = 'test-user'
    mod._commands_cache.clear()
    mod._commands_cache['test-user'] = (9999999999.0, {'commands': [{'name': 'old'}]})
    mod._commands_cache['other-user'] = (9999999999.0, {'commands': [{'name': 'keep'}]})

    result = await mod.clear_commands_cache(user=user)

    assert result == {'ok': True}
    assert 'test-user' not in mod._commands_cache
    assert mod._commands_cache['other-user'][1] == {'commands': [{'name': 'keep'}]}

    mod._commands_cache.clear()
