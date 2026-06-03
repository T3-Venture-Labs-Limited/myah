# Tests for the stream-persistence endpoints added to chats.py:
#   GET /{id}/active_run
#   GET /{id}/messages/{message_id}/live_state
#
# Uses the importlib stub pattern from test_chats_title_source.py to avoid
# importing the full chats router (which pulls in DB init, Alembic, socket.io,
# and other heavyweight dependencies that are not available in the unit-test
# environment).
#
# The handler logic under test is extracted inline so the tests exercise
# the real business logic (ownership check, registry lookup, error paths)
# without needing a live FastAPI app or database.

import uuid
import time
from types import SimpleNamespace
from typing import Optional
from unittest.mock import MagicMock, patch

import pytest
from pydantic import BaseModel, ConfigDict


# ---------------------------------------------------------------------------
# Minimal model stubs
# ---------------------------------------------------------------------------


class _ChatModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    user_id: str
    title: str = 'Test Chat'
    chat: dict = {}


class _FakeHTTPException(Exception):
    def __init__(self, status_code: int, detail: str):
        self.status_code = status_code
        self.detail = detail


NOT_FOUND = 'Not found'


# ---------------------------------------------------------------------------
# In-memory fakes for Chats and registries
# ---------------------------------------------------------------------------


class _FakeChats:
    def __init__(self):
        self._store: dict[str, _ChatModel] = {}

    def seed(self, model: _ChatModel):
        self._store[model.id] = model
        return model

    def get_chat_by_id_and_user_id(self, id: str, user_id: str, db=None) -> Optional[_ChatModel]:
        row = self._store.get(id)
        if row is None or row.user_id != user_id:
            return None
        return row


def _fake_user(user_id='user-1'):
    return SimpleNamespace(id=user_id, role='user', email='u@myah.dev')


# ---------------------------------------------------------------------------
# Handler implementations mirroring chats.py logic under test
# ---------------------------------------------------------------------------


def _get_active_run_handler(chat_id: str, user, fake_chats: _FakeChats, active_runs: dict) -> dict:
    """Mirror of GET /{id}/active_run handler logic."""
    chat = fake_chats.get_chat_by_id_and_user_id(chat_id, user.id)
    if not chat:
        raise _FakeHTTPException(status_code=401, detail=NOT_FOUND)

    entry = active_runs.get(chat_id)
    if entry:
        return {
            'run_id': entry.get('run_id'),
            'started_at': entry.get('started_at'),
            'message_id': entry.get('message_id'),
        }
    return {'run_id': None, 'started_at': None, 'message_id': None}


def _get_active_runs_handler(user, fake_chats: _FakeChats, active_runs: dict) -> dict:
    """Mirror of GET /active_runs handler logic."""
    runs = []
    for chat_id, entry in active_runs.items():
        chat = fake_chats.get_chat_by_id_and_user_id(chat_id, user.id)
        if not chat:
            continue
        runs.append(
            {
                'chat_id': chat_id,
                'run_id': entry.get('run_id'),
                'started_at': entry.get('started_at'),
                'message_id': entry.get('message_id'),
            }
        )
    return {'active_runs': runs}


def _get_live_state_handler(
    chat_id: str,
    message_id: str,
    user,
    fake_chats: _FakeChats,
    live_state: dict,
) -> dict:
    """Mirrors GET /{id}/messages/{message_id}/live_state using the real resolve_live_state helper.

    Per T3-1096 audit: tests must not copy route logic — they must exercise the
    real extracted helper used by the production route.
    """
    from myah.utils.live_state import resolve_live_state

    chat = fake_chats.get_chat_by_id_and_user_id(chat_id, user.id)
    if not chat:
        raise _FakeHTTPException(status_code=401, detail=NOT_FOUND)

    messages = (chat.chat or {}).get('history', {}).get('messages', {})
    snapshot = resolve_live_state(chat_id, message_id, live_state, messages)
    if snapshot is None:
        raise _FakeHTTPException(status_code=404, detail='no live state — message likely settled')
    return snapshot


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def fake_chats():
    return _FakeChats()


@pytest.fixture
def active_runs():
    return {}


@pytest.fixture
def live_state():
    return {}


@pytest.fixture
def seeded_chat(fake_chats):
    chat = _ChatModel(id=str(uuid.uuid4()), user_id='user-1')
    fake_chats.seed(chat)
    return chat


# ---------------------------------------------------------------------------
# Tests: GET /{id}/active_run
# ---------------------------------------------------------------------------


def test_get_active_run_returns_current(fake_chats, seeded_chat, active_runs):
    """When a run is in-flight, active_run endpoint returns its metadata."""
    now_ms = int(time.time() * 1000)
    msg_id = 'msg-abc'
    active_runs[seeded_chat.id] = {
        'run_id': 'run-1',
        'started_at': now_ms,
        'message_id': msg_id,
    }

    result = _get_active_run_handler(seeded_chat.id, _fake_user(), fake_chats, active_runs)

    assert result['run_id'] == 'run-1'
    assert result['started_at'] == now_ms
    assert result['message_id'] == msg_id


def test_get_active_run_returns_null_when_no_run(fake_chats, seeded_chat, active_runs):
    """When no run is in-flight, active_run returns null fields."""
    result = _get_active_run_handler(seeded_chat.id, _fake_user(), fake_chats, active_runs)

    assert result == {'run_id': None, 'started_at': None, 'message_id': None}


def test_ownership_check_rejects_other_user_active_run(fake_chats, seeded_chat, active_runs):
    """Ownership check: user-2 must not see user-1's active run."""
    active_runs[seeded_chat.id] = {'run_id': 'run-x', 'started_at': 0, 'message_id': 'msg-x'}

    with pytest.raises(_FakeHTTPException) as exc_info:
        _get_active_run_handler(seeded_chat.id, _fake_user('user-2'), fake_chats, active_runs)

    assert exc_info.value.status_code == 401


def test_get_active_runs_returns_only_current_users_runs(fake_chats, seeded_chat, active_runs):
    """All-active-runs endpoint filters registry entries by chat ownership."""
    other_chat = fake_chats.seed(_ChatModel(id=str(uuid.uuid4()), user_id='user-2'))
    active_runs[seeded_chat.id] = {'run_id': 'run-1', 'started_at': 100, 'message_id': 'msg-1'}
    active_runs[other_chat.id] = {'run_id': 'run-2', 'started_at': 200, 'message_id': 'msg-2'}
    active_runs['deleted-chat'] = {'run_id': 'run-3', 'started_at': 300, 'message_id': 'msg-3'}

    result = _get_active_runs_handler(_fake_user(), fake_chats, active_runs)

    assert result == {
        'active_runs': [
            {
                'chat_id': seeded_chat.id,
                'run_id': 'run-1',
                'started_at': 100,
                'message_id': 'msg-1',
            }
        ]
    }


def test_chats_router_declares_active_runs_before_dynamic_chat_id_route():
    """Static /active_runs route must not be captured by /{id}."""
    from pathlib import Path

    router_source = Path(__file__).parents[4] / 'routers' / 'chats.py'
    source = router_source.read_text()

    assert "@router.get('/active_runs')" in source
    assert source.index("@router.get('/active_runs')") < source.index("@router.get('/{id}'")


# ---------------------------------------------------------------------------
# Tests: GET /{id}/messages/{message_id}/live_state
# ---------------------------------------------------------------------------


def test_get_live_state_returns_snapshot(fake_chats, seeded_chat, live_state):
    """When a snapshot exists in _live_state, the endpoint returns it."""
    msg_id = 'msg-live'
    snapshot = {
        'run_id': 'run-2',
        'chat_id': seeded_chat.id,
        'message_id': msg_id,
        'started_at': int(time.time() * 1000),
        'updated_at': int(time.time() * 1000),
        'message_content': 'Hello from live state',
        'reasoning_content': '',
        'tool_calls': [],
        'status': 'streaming',
    }
    live_state[(seeded_chat.id, msg_id)] = snapshot

    result = _get_live_state_handler(seeded_chat.id, msg_id, _fake_user(), fake_chats, live_state)

    assert result['message_content'] == 'Hello from live state'
    assert result['status'] == 'streaming'
    assert result['run_id'] == 'run-2'


def test_get_live_state_404_when_message_settled(fake_chats, seeded_chat, live_state):
    """When the grace window has expired (key absent), the endpoint returns 404."""
    with pytest.raises(_FakeHTTPException) as exc_info:
        _get_live_state_handler(seeded_chat.id, 'nonexistent-msg', _fake_user(), fake_chats, live_state)

    assert exc_info.value.status_code == 404
    assert 'settled' in exc_info.value.detail


def test_ownership_check_rejects_other_user(fake_chats, seeded_chat, live_state):
    """Ownership check: user-2 must not see user-1's live state."""
    msg_id = 'msg-priv'
    live_state[(seeded_chat.id, msg_id)] = {'status': 'streaming'}

    with pytest.raises(_FakeHTTPException) as exc_info:
        _get_live_state_handler(seeded_chat.id, msg_id, _fake_user('user-2'), fake_chats, live_state)

    assert exc_info.value.status_code == 401


def test_get_live_state_missing_chat_returns_401(fake_chats, live_state):
    """Non-existent chat_id must return 401 regardless of live_state content."""
    bad_chat_id = str(uuid.uuid4())
    live_state[(bad_chat_id, 'msg-x')] = {'status': 'streaming'}

    with pytest.raises(_FakeHTTPException) as exc_info:
        _get_live_state_handler(bad_chat_id, 'msg-x', _fake_user(), fake_chats, live_state)

    assert exc_info.value.status_code == 401


def test_live_state_returns_db_snapshot_when_in_memory_missing(fake_chats, live_state):
    """DB-derived final snapshot must be returned when in-memory live_state has expired.

    Gap 6 (T3-1096): /live_state fallback must not be gated on a process-local
    active run existing. After a browser refresh or after the grace window expires,
    the endpoint must still serve the settled assistant message from the owned chat's
    persisted history — so the frontend can paint the final content without re-fetching
    the full chat list.

    NOTE — same-process limitation (Path A): active *partial* output (in-progress
    streaming with no content yet persisted) is only available via the same-process
    _live_state registry. Without ENABLE_REALTIME_CHAT_SAVE or a durable active
    snapshot store, a refresh while a run is mid-stream cannot hydrate partial output
    from a different process. This limitation is documented in hermes_stream_handler's
    module docstring and is acceptable under the approved Path A scope.
    """
    msg_id = 'msg-settled'
    chat = _ChatModel(
        id=str(uuid.uuid4()),
        user_id='user-1',
        chat={
            'history': {
                'messages': {
                    msg_id: {
                        'id': msg_id,
                        'role': 'assistant',
                        'content': 'final answer',
                        'done': True,
                        'timestamp': 999,
                    }
                }
            }
        },
    )
    fake_chats.seed(chat)
    # _active_runs is empty (process restarted / grace window expired) — no in-memory state
    result = _get_live_state_handler(chat.id, msg_id, _fake_user(), fake_chats, live_state)

    assert result['message_content'] == 'final answer'
    assert result['status'] == 'settled'
    assert result['done'] is True
    assert result['source'] == 'db'
    assert result['chat_id'] == chat.id
    assert result['message_id'] == msg_id


def test_live_state_returns_404_for_unknown_message_including_empty_dict(fake_chats, live_state):
    """Unknown message (or empty {} from model helper) must produce 404, not 500.

    Mirrors the Chats.get_message_by_id_and_message_id({}) empty-result case:
    if the message map for an owned chat is empty or the message_id is simply
    absent, the endpoint must return 404 — not an unhandled exception.
    """
    chat = _ChatModel(
        id=str(uuid.uuid4()),
        user_id='user-1',
        chat={'history': {'messages': {}}},
    )
    fake_chats.seed(chat)

    with pytest.raises(_FakeHTTPException) as exc_info:
        _get_live_state_handler(chat.id, 'nonexistent-msg', _fake_user(), fake_chats, live_state)

    assert exc_info.value.status_code == 404
    assert 'settled' in exc_info.value.detail


# ---------------------------------------------------------------------------
# Tests: live-state resolution helper used by GET /{id}/messages/{mid}/live_state
#
# These exercise the REAL helper (myah.utils.live_state.resolve_live_state /
# final_snapshot_from_history) that the route calls — NOT a mirror. Per the
# T3-1096 audit, new route behavior must be covered through the real route or an
# extracted helper used by the route.
# ---------------------------------------------------------------------------


def _assistant_msg(content='final answer', done=True, output=None, role='assistant', timestamp=123):
    msg = {'id': 'msg-1', 'role': role, 'content': content, 'done': done, 'timestamp': timestamp}
    if output is not None:
        msg['output'] = output
    return msg


def test_resolve_live_state_prefers_in_memory_snapshot():
    from myah.utils.live_state import resolve_live_state

    live = {('chat-1', 'msg-1'): {'status': 'streaming', 'message_content': 'live'}}
    messages = {'msg-1': _assistant_msg(content='db only')}

    result = resolve_live_state('chat-1', 'msg-1', live, messages)

    assert result['status'] == 'streaming'
    assert result['message_content'] == 'live'


def test_resolve_live_state_falls_back_to_db_final_when_in_memory_missing():
    # This is the refresh case: process-local _active_runs/_live_state are gone,
    # but the owned chat's DB history still has the settled assistant message.
    from myah.utils.live_state import resolve_live_state

    messages = {
        'msg-1': _assistant_msg(
            content='final answer',
            done=True,
            output=[{'type': 'message', 'role': 'assistant'}],
        )
    }

    result = resolve_live_state('chat-1', 'msg-1', {}, messages)

    assert result is not None
    assert result['message_content'] == 'final answer'
    assert result['status'] == 'settled'
    assert result['done'] is True
    assert result['output'] == [{'type': 'message', 'role': 'assistant'}]
    assert result['source'] == 'db'
    assert result['chat_id'] == 'chat-1'
    assert result['message_id'] == 'msg-1'


def test_db_fallback_reachable_without_any_active_run_entry():
    # The fallback must not be gated on a process-local active run existing —
    # /live_state stays useful after refresh even when _active_runs is empty.
    from myah.utils.live_state import final_snapshot_from_history

    messages = {'msg-1': _assistant_msg()}
    result = final_snapshot_from_history('chat-1', 'msg-1', messages)
    assert result is not None
    assert result['message_content'] == 'final answer'


def test_resolve_live_state_returns_none_for_missing_message():
    from myah.utils.live_state import resolve_live_state

    # Mirrors the Chats.get_message_by_id_and_message_id({}) empty-result case.
    assert resolve_live_state('chat-1', 'msg-1', {}, {}) is None
    assert resolve_live_state('chat-1', 'msg-1', {}, None) is None


def test_db_fallback_does_not_masquerade_non_assistant_message():
    from myah.utils.live_state import final_snapshot_from_history

    messages = {'msg-1': {'id': 'msg-1', 'role': 'user', 'content': 'a question'}}
    assert final_snapshot_from_history('chat-1', 'msg-1', messages) is None


def test_db_fallback_skips_empty_unstarted_assistant_shell():
    from myah.utils.live_state import final_snapshot_from_history

    # An assistant shell with no content/output and not done is not a useful
    # snapshot — it must not be served as live state.
    messages = {'msg-1': _assistant_msg(content='', done=False, output=None)}
    assert final_snapshot_from_history('chat-1', 'msg-1', messages) is None


def test_db_fallback_serves_in_progress_assistant_with_partial_content():
    from myah.utils.live_state import final_snapshot_from_history

    messages = {'msg-1': _assistant_msg(content='partial...', done=False)}
    result = final_snapshot_from_history('chat-1', 'msg-1', messages)
    assert result is not None
    assert result['status'] == 'streaming'
    assert result['done'] is False


# ---------------------------------------------------------------------------
# REAL route-function coverage for /{id}/active_run and
# /{id}/messages/{message_id}/live_state
#
# Per the T3-1096 audit: backend route tests must NOT only mirror the HTTP
# envelope (ownership / 404). These call the ACTUAL route coroutines from
# myah.routers.chats with the Chats model and the in-memory stream registries
# patched, so the real ownership check, the real 404 path, and the real
# resolve_live_state wiring are exercised end-to-end through production code.
#
# The router module is imported lazily inside a fixture so the rest of this
# file's lightweight helper tests still run without paying the heavyweight
# import cost on collection.
# ---------------------------------------------------------------------------

import asyncio as _asyncio


@pytest.fixture
def chats_router():
    """Import and return the real myah.routers.chats module."""
    import myah.routers.chats as chats_router_module

    return chats_router_module


class _RealRouteChats:
    """Stand-in for the Chats model used by the real route functions.

    The route calls ``Chats.get_chat_by_id_and_user_id(id, user.id, db=db)``;
    patching the module-level ``Chats`` name with an instance of this class makes
    that call resolve to ``self.get_chat_by_id_and_user_id`` while keeping the
    real ownership/None handling in the route under test.
    """

    def __init__(self):
        self._store: dict[str, _ChatModel] = {}

    def seed(self, chat: _ChatModel):
        self._store[chat.id] = chat
        return chat

    def get_chat_by_id_and_user_id(self, id, user_id, db=None):
        row = self._store.get(id)
        if row is None or row.user_id != user_id:
            return None
        return row


def _seed_real_chat(chat_id=None, user_id='user-1', messages=None) -> _ChatModel:
    return _ChatModel(
        id=chat_id or str(uuid.uuid4()),
        user_id=user_id,
        chat={'history': {'messages': messages or {}}},
    )


def test_real_route_live_state_owned_db_fallback_returns_snapshot(chats_router):
    """Owned chat with no in-memory live state still serves the settled DB snapshot (200)."""
    chats = _RealRouteChats()
    msg_id = 'msg-db'
    chat = chats.seed(
        _seed_real_chat(
            messages={
                msg_id: {
                    'id': msg_id,
                    'role': 'assistant',
                    'content': 'final answer',
                    'done': True,
                    'timestamp': 5,
                    'output': [{'type': 'message', 'role': 'assistant'}],
                }
            }
        )
    )

    with patch.object(chats_router, 'Chats', chats), patch.object(
        chats_router, 'get_live_state', return_value={}
    ):
        result = _asyncio.run(
            chats_router.get_live_state_by_chat_id_and_message_id(
                chat.id, msg_id, user=_fake_user(), db=MagicMock()
            )
        )

    assert result['message_content'] == 'final answer'
    assert result['status'] == 'settled'
    assert result['done'] is True
    assert result['source'] == 'db'
    assert result['output'] == [{'type': 'message', 'role': 'assistant'}]


def test_real_route_live_state_prefers_in_memory_snapshot(chats_router):
    """In-memory live snapshot wins over the DB fallback while a run is active."""
    chats = _RealRouteChats()
    msg_id = 'msg-live'
    chat = chats.seed(
        _seed_real_chat(
            messages={msg_id: {'id': msg_id, 'role': 'assistant', 'content': 'db only', 'done': True}}
        )
    )
    live = {(chat.id, msg_id): {'status': 'streaming', 'message_content': 'live partial'}}

    with patch.object(chats_router, 'Chats', chats), patch.object(
        chats_router, 'get_live_state', return_value=live
    ):
        result = _asyncio.run(
            chats_router.get_live_state_by_chat_id_and_message_id(
                chat.id, msg_id, user=_fake_user(), db=MagicMock()
            )
        )

    assert result['message_content'] == 'live partial'
    assert result['status'] == 'streaming'


def test_real_route_live_state_rejects_non_owner(chats_router):
    """A different user must be rejected (401) by the real route ownership check."""
    from fastapi import HTTPException

    chats = _RealRouteChats()
    msg_id = 'msg-priv'
    chat = chats.seed(
        _seed_real_chat(
            user_id='user-1',
            messages={msg_id: {'id': msg_id, 'role': 'assistant', 'content': 'secret', 'done': True}},
        )
    )

    with patch.object(chats_router, 'Chats', chats), patch.object(
        chats_router, 'get_live_state', return_value={}
    ):
        with pytest.raises(HTTPException) as exc_info:
            _asyncio.run(
                chats_router.get_live_state_by_chat_id_and_message_id(
                    chat.id, msg_id, user=_fake_user('user-2'), db=MagicMock()
                )
            )

    assert exc_info.value.status_code == 401


def test_real_route_live_state_unknown_message_returns_404(chats_router):
    """An owned chat missing the requested message returns 404 (not 500), via the real route."""
    from fastapi import HTTPException

    chats = _RealRouteChats()
    chat = chats.seed(_seed_real_chat(messages={}))

    with patch.object(chats_router, 'Chats', chats), patch.object(
        chats_router, 'get_live_state', return_value={}
    ):
        with pytest.raises(HTTPException) as exc_info:
            _asyncio.run(
                chats_router.get_live_state_by_chat_id_and_message_id(
                    chat.id, 'nonexistent-msg', user=_fake_user(), db=MagicMock()
                )
            )

    assert exc_info.value.status_code == 404
    assert 'settled' in exc_info.value.detail


def test_real_route_active_run_returns_entry(chats_router):
    """The real /{id}/active_run route returns the in-memory registry entry for an owned chat."""
    chats = _RealRouteChats()
    chat = chats.seed(_seed_real_chat())
    runs = {chat.id: {'run_id': 'run-1', 'started_at': 10, 'message_id': 'm1'}}

    with patch.object(chats_router, 'Chats', chats), patch.object(
        chats_router, 'get_active_runs', return_value=runs
    ):
        result = _asyncio.run(
            chats_router.get_active_run_by_chat_id(chat.id, user=_fake_user(), db=MagicMock())
        )

    assert result == {'run_id': 'run-1', 'started_at': 10, 'message_id': 'm1'}


def test_real_route_active_run_rejects_non_owner(chats_router):
    """The real /{id}/active_run route rejects a non-owner (401)."""
    from fastapi import HTTPException

    chats = _RealRouteChats()
    chat = chats.seed(_seed_real_chat(user_id='user-1'))
    runs = {chat.id: {'run_id': 'run-1', 'started_at': 10, 'message_id': 'm1'}}

    with patch.object(chats_router, 'Chats', chats), patch.object(
        chats_router, 'get_active_runs', return_value=runs
    ):
        with pytest.raises(HTTPException) as exc_info:
            _asyncio.run(
                chats_router.get_active_run_by_chat_id(chat.id, user=_fake_user('user-2'), db=MagicMock())
            )

    assert exc_info.value.status_code == 401
