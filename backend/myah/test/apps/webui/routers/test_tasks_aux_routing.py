# Tests for tasks.py aux routing (title + follow-up generation).
# Uses importlib stub pattern.

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest


def _load_tasks_module():
    def _make(name, **attrs):
        m = ModuleType(name)
        for k, v in attrs.items():
            setattr(m, k, v)
        return m

    aux_call_mock = AsyncMock()

    mods = {
        'myah.internal.db': _make('myah.internal.db', get_session=MagicMock()),
        'myah.config': _make(
            'myah.config',
            DEFAULT_TITLE_GENERATION_PROMPT_TEMPLATE='Generate a title for: {messages}',
            DEFAULT_FOLLOW_UP_GENERATION_PROMPT_TEMPLATE='Generate follow-ups for: {messages}',
            DEFAULT_TAGS_GENERATION_PROMPT_TEMPLATE='Generate tags for: {messages}',
            DEFAULT_QUERY_GENERATION_PROMPT_TEMPLATE='Generate query for: {messages}',
            DEFAULT_AUTOCOMPLETE_GENERATION_PROMPT_TEMPLATE='Autocomplete: {prompt}',
            DEFAULT_EMOJI_GENERATION_PROMPT_TEMPLATE='Generate emoji for: {messages}',
        ),
        'myah.env': _make(
            'myah.env',
            WEBUI_AUTH=True,
            ENABLE_AGENT_SETTINGS_UI=True,
            ENABLE_TITLE_GENERATION=SimpleNamespace(value=True),
            ENABLE_FOLLOW_UP_GENERATION=SimpleNamespace(value=True),
            TITLE_GENERATION_PROMPT_TEMPLATE=SimpleNamespace(value=''),
            FOLLOW_UP_GENERATION_PROMPT_TEMPLATE=SimpleNamespace(value=''),
            DEFAULT_TITLE_GENERATION_PROMPT_TEMPLATE='Generate title for: {messages}',
            DEFAULT_FOLLOW_UP_GENERATION_PROMPT_TEMPLATE='Generate follow-ups for: {messages}',
            TASK_MODEL=SimpleNamespace(value=''),
            TASK_MODEL_EXTERNAL=SimpleNamespace(value=''),
        ),
        'myah.constants': _make(
            'myah.constants',
            ERROR_MESSAGES=SimpleNamespace(NOT_FOUND='not found'),
            TASKS=SimpleNamespace(TITLE_GENERATION='title_generation', FOLLOW_UP_GENERATION='follow_up_generation'),
        ),
        'myah.utils.auth': _make(
            'myah.utils.auth',
            get_verified_user=MagicMock(),
            get_admin_user=MagicMock(),
        ),
        'myah.utils.agent_proxy': _make(
            'myah.utils.agent_proxy',
            aux_call=aux_call_mock,
        ),
        'myah.models.users': _make('myah.models.users', Users=MagicMock(), UserModel=MagicMock()),
        'myah.models.models': _make(
            'myah.models.models', Models=SimpleNamespace(get_all_models=MagicMock(return_value=[]))
        ),
        'myah.utils.task': _make(
            'myah.utils.task',
            prompt_template=lambda t, **kw: t,
            get_task_model_id=lambda *a, **kw: 'myah',
            title_generation_template=lambda t, m, u: t,
            follow_up_generation_template=lambda t, m, u: t,
            query_generation_template=lambda t, m, u: t,
            autocomplete_generation_template=lambda t, m, i, u: t,
            tags_generation_template=lambda t, m, u: t,
            emoji_generation_template=lambda t, m, u: t,
        ),
        'myah.utils.chat': _make('myah.utils.chat', generate_chat_completion=AsyncMock()),
    }

    for name, mod in mods.items():
        sys.modules[name] = mod

    router_path = Path(__file__).resolve().parent.parent.parent.parent.parent / 'routers' / 'tasks.py'
    spec = importlib.util.spec_from_file_location('myah.routers.tasks', router_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules['myah.routers.tasks'] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        pass  # module may fail to fully load due to other deps, that's ok for our direct-call tests

    module._test_aux_call = aux_call_mock
    module._stub_keys = list(mods.keys()) + ['myah.routers.tasks']
    return module


@pytest.fixture
def tasks_mod():
    """Load the tasks module with stubs injected, then restore sys.modules on teardown.

    The stubs injected by _load_tasks_module() lack attributes that later test
    modules need (e.g. `myah.internal.db.Base`,
    `myah.env.DEFAULT_GROUP_SHARE_PERMISSION`). We save and restore all
    myah.* entries that were in sys.modules before injection.

    We do NOT remove stubs that define SQLAlchemy ORM models against the shared
    `Base.metadata` — reimporting those would raise
    "Table X is already defined for this MetaData instance". The safe set of
    keys to restore is everything that was either:
      (a) already in sys.modules before we ran (restore to saved version), or
      (b) injected purely as a stub (remove entirely so the real module can
          be imported fresh next time).

    This avoids both "cannot import name X" pollution AND SQLAlchemy metadata
    conflicts.
    """
    # Snapshot all myah.* entries currently in sys.modules.
    _PREFIX = 'myah'
    saved = {k: v for k, v in sys.modules.items() if k == _PREFIX or k.startswith(_PREFIX + '.')}

    mod = _load_tasks_module()
    mod._test_aux_call.reset_mock()
    yield mod

    # Teardown: restore the snapshot for stubs that lack real attributes.
    # Only remove/restore entries that were EITHER in the snapshot (safe to
    # restore) OR injected as a stub AND are not SQLAlchemy model modules
    # (whose reimport would trigger "Table X is already defined" errors).
    #
    # Rule: for any key that was in the snapshot, restore it. For any key
    # that was injected (not in snapshot), only remove it if it's known safe
    # (not an ORM model module). Never remove ORM model modules from
    # sys.modules — let them stay as stubs; their SQLAlchemy table
    # definitions in `Base.metadata` cannot be undone mid-session.
    _ORM_MODULES = {
        'myah.config',
        'myah.env',  # env defines no ORM models; safe to restore
    }
    for key in list(sys.modules.keys()):
        if key == _PREFIX or key.startswith(_PREFIX + '.'):
            if key in saved:
                # Restore to pre-stub version.
                sys.modules[key] = saved[key]
            elif key not in _ORM_MODULES:
                # Injected stub for a non-ORM module — safe to remove.
                sys.modules.pop(key, None)
            # ORM model modules that weren't in the snapshot: leave stub in
            # place to avoid reimport → duplicate table error.


def _fake_user():
    return SimpleNamespace(id='user-abc', role='user', email='u@myah.dev')


@pytest.mark.asyncio
async def test_title_generation_routes_through_aux_agent(tasks_mod):
    """generate_title always routes through aux_call (unconditional)."""
    tasks_mod._test_aux_call.return_value = {
        'status': 200,
        'body': {
            'choices': [{'message': {'content': '{"title": "My Chat Title"}'}}],
            'usage': {},
        },
        'headers': {},
    }

    resp = await tasks_mod.generate_title(
        request=MagicMock(),
        form_data={
            'model': 'myah',
            'messages': [{'role': 'user', 'content': 'hello world'}],
        },
        user=_fake_user(),
    )

    tasks_mod._test_aux_call.assert_awaited_once()
    # path arg should contain title_generation
    call = tasks_mod._test_aux_call.await_args
    all_args = call.args + tuple(call.kwargs.values())
    assert any('title_generation' in str(a) for a in all_args)


@pytest.mark.asyncio
async def test_generate_title_failsoft_on_aux_error(tasks_mod):
    """aux_call failure returns empty title string — never breaks the chat flow."""
    tasks_mod._test_aux_call.return_value = {
        'status': 500,
        'body': {'error': 'internal'},
        'headers': {},
    }

    resp = await tasks_mod.generate_title(
        request=MagicMock(),
        form_data={'model': 'myah', 'messages': [{'role': 'user', 'content': 'hi'}]},
        user=_fake_user(),
    )
    # Should return something (empty string or JSONResponse with empty title)
    assert resp is not None


@pytest.mark.asyncio
async def test_follow_up_generation_routes_through_aux_agent(tasks_mod):
    tasks_mod._test_aux_call.return_value = {
        'status': 200,
        'body': {
            'choices': [{'message': {'content': '{"follow_ups": ["Q1?", "Q2?"]}'}}],
            'usage': {},
        },
        'headers': {},
    }

    resp = await tasks_mod.generate_follow_ups(
        request=MagicMock(),
        form_data={'model': 'myah', 'messages': [{'role': 'user', 'content': 'hi'}]},
        user=_fake_user(),
    )

    tasks_mod._test_aux_call.assert_awaited_once()
    call = tasks_mod._test_aux_call.await_args
    all_args = call.args + tuple(call.kwargs.values())
    assert any('follow_up_generation' in str(a) for a in all_args)


# ---------------------------------------------------------------------------
# Task 5: _fetch_title_via_aux returns dict (not JSONResponse)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fetch_title_via_aux_returns_dict(tasks_mod):
    """_fetch_title_via_aux returns a plain dict with choices populated."""
    tasks_mod._test_aux_call.return_value = {
        'status': 200,
        'body': {
            'choices': [{'message': {'content': '{"title": "Paris Inquiry"}', 'role': 'assistant'}}],
            'usage': {},
        },
        'headers': {},
    }

    result = await tasks_mod._fetch_title_via_aux(
        request=MagicMock(),
        form_data={'messages': [{'role': 'user', 'content': 'hello'}]},
        user=_fake_user(),
    )

    assert isinstance(result, dict), f'Expected dict, got {type(result)}'
    assert result['choices'][0]['message']['content'] == '{"title": "Paris Inquiry"}'


@pytest.mark.asyncio
async def test_fetch_title_via_aux_failsoft_on_error(tasks_mod):
    """_fetch_title_via_aux returns a plain dict (fail-soft envelope) on aux error."""
    tasks_mod._test_aux_call.return_value = {
        'status': 500,
        'body': {'error': 'internal'},
        'headers': {},
    }

    result = await tasks_mod._fetch_title_via_aux(
        request=MagicMock(),
        form_data={'messages': [{'role': 'user', 'content': 'hi'}]},
        user=_fake_user(),
    )

    assert isinstance(result, dict), f'Expected dict, got {type(result)}'
    assert '"title": ""' in result['choices'][0]['message']['content']


@pytest.mark.asyncio
async def test_generate_title_http_wrapper_returns_jsonresponse(tasks_mod):
    """_aux_generate_title (HTTP wrapper) returns a JSONResponse, not a plain dict."""
    from fastapi.responses import JSONResponse

    tasks_mod._test_aux_call.return_value = {
        'status': 200,
        'body': {
            'choices': [{'message': {'content': '{"title": "Test"}', 'role': 'assistant'}}],
            'usage': {},
        },
        'headers': {},
    }

    resp = await tasks_mod._aux_generate_title(
        request=MagicMock(),
        form_data={'messages': [{'role': 'user', 'content': 'hi'}]},
        user=_fake_user(),
    )

    assert isinstance(resp, JSONResponse), f'Expected JSONResponse, got {type(resp)}'


# ---------------------------------------------------------------------------
# Task 6: _fetch_follow_ups_via_aux returns dict (not JSONResponse)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fetch_follow_ups_via_aux_returns_dict(tasks_mod):
    """_fetch_follow_ups_via_aux returns a plain dict with choices populated."""
    tasks_mod._test_aux_call.return_value = {
        'status': 200,
        'body': {
            'choices': [{'message': {'content': '{"follow_ups": ["Q1?", "Q2?"]}', 'role': 'assistant'}}],
            'usage': {},
        },
        'headers': {},
    }

    result = await tasks_mod._fetch_follow_ups_via_aux(
        request=MagicMock(),
        form_data={'messages': [{'role': 'user', 'content': 'hello'}]},
        user=_fake_user(),
    )

    assert isinstance(result, dict), f'Expected dict, got {type(result)}'
    assert '"follow_ups"' in result['choices'][0]['message']['content']


@pytest.mark.asyncio
async def test_fetch_follow_ups_via_aux_failsoft(tasks_mod):
    """_fetch_follow_ups_via_aux returns a plain dict (fail-soft envelope) on aux error."""
    tasks_mod._test_aux_call.return_value = {
        'status': 500,
        'body': {'error': 'internal'},
        'headers': {},
    }

    result = await tasks_mod._fetch_follow_ups_via_aux(
        request=MagicMock(),
        form_data={'messages': [{'role': 'user', 'content': 'hi'}]},
        user=_fake_user(),
    )

    assert isinstance(result, dict), f'Expected dict, got {type(result)}'
    assert '"follow_ups": []' in result['choices'][0]['message']['content']


# ---------------------------------------------------------------------------
# Task 5: _fetch_follow_ups_via_aux response_format_override sentinel
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fetch_follow_ups_via_aux_omits_response_format_when_overridden(tasks_mod):
    """When response_format_override=None, the json_body must NOT contain response_format."""
    captured_bodies = []

    async def _capturing_aux_call(user, method, path, *, json_body=None, timeout=None):
        captured_bodies.append(json_body or {})
        return {
            'status': 200,
            'body': {
                'choices': [{'message': {'content': '{"follow_ups": ["Q1?"]}'}}],
                'usage': {},
            },
            'headers': {},
        }

    tasks_mod._test_aux_call.side_effect = _capturing_aux_call

    await tasks_mod._fetch_follow_ups_via_aux(
        request=MagicMock(),
        form_data={'messages': [{'role': 'user', 'content': 'hi'}]},
        user=_fake_user(),
        response_format_override=None,
    )

    tasks_mod._test_aux_call.side_effect = None  # reset for other tests

    assert captured_bodies, 'aux_call was never invoked'
    assert 'response_format' not in captured_bodies[0], (
        f'response_format should be absent when override=None, got body keys: {list(captured_bodies[0].keys())}'
    )


@pytest.mark.asyncio
async def test_fetch_follow_ups_via_aux_includes_response_format_by_default(tasks_mod):
    """When no override is passed, the json_body includes response_format: json_object."""
    captured_bodies = []

    async def _capturing_aux_call(user, method, path, *, json_body=None, timeout=None):
        captured_bodies.append(json_body or {})
        return {
            'status': 200,
            'body': {
                'choices': [{'message': {'content': '{"follow_ups": ["Q1?"]}'}}],
                'usage': {},
            },
            'headers': {},
        }

    tasks_mod._test_aux_call.side_effect = _capturing_aux_call

    await tasks_mod._fetch_follow_ups_via_aux(
        request=MagicMock(),
        form_data={'messages': [{'role': 'user', 'content': 'hi'}]},
        user=_fake_user(),
    )

    tasks_mod._test_aux_call.side_effect = None

    assert captured_bodies, 'aux_call was never invoked'
    assert 'response_format' in captured_bodies[0], (
        f'response_format should be present by default, got body keys: {list(captured_bodies[0].keys())}'
    )
