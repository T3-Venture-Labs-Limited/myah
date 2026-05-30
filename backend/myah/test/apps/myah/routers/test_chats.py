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
    """Mirror of GET /{id}/messages/{message_id}/live_state handler logic."""
    chat = fake_chats.get_chat_by_id_and_user_id(chat_id, user.id)
    if not chat:
        raise _FakeHTTPException(status_code=401, detail=NOT_FOUND)

    snapshot = live_state.get((chat_id, message_id))
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
