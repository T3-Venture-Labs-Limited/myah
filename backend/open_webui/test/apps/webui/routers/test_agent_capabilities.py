"""Tests for the /api/v1/agent/* router (open_webui/routers/agent_capabilities.py).

After the Hermes-first pivot, this router is a thin proxy: every endpoint
parses the FastAPI request, then forwards it to the per-user `hermes
dashboard` server via :func:`open_webui.utils.hermes_web.web_call_or_raise`.
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

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.mark.asyncio
async def test_get_model_returns_payload_from_web_call():
    """GET /model proxies to /api/plugins/myah-admin/config/model and
    returns whatever model string the agent reports."""
    from open_webui.routers import agent_capabilities as mod

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
async def test_put_model_proxies_payload_via_web_call():
    """PUT /model forwards the body as JSON to the same agent path and
    returns the model string the agent echoes back."""
    from open_webui.models.agent_capabilities_schemas import AgentModelUpdateForm
    from open_webui.routers import agent_capabilities as mod

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
async def test_patch_toolsets_proxies_enabled_flag_via_web_call():
    """PATCH /toolsets/{name} forwards the enable/disable flag to the
    agent's myah-admin plugin and surfaces the agent's response."""
    from open_webui.models.agent_capabilities_schemas import AgentToolsetToggleForm
    from open_webui.routers import agent_capabilities as mod

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
