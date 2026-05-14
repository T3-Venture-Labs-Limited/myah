"""Integration tests for background_tasks_handler title path.

Verifies that:
  1. A title returned via aux_call lands in the DB with title_source='auto'.
  2. A chat that was manually renamed is NOT overwritten by a late aux response.

Uses a shared file-based SQLite temp DB (same pattern as test_chats_update_title.py)
so that Chats.* methods (which open their own sessions) see the same rows as
the test setup writes.

The handler is loaded with importlib stubs for heavy deps:
  - myah.routers.tasks (aux_call patched here)
  - myah.socket.main
  - opentelemetry.*

Patch target: myah.routers.tasks.aux_call — this is the binding that
chat_tasks.py actually calls after its `from myah.routers.tasks import ...`.
We reload tasks.py with our mock wired to the tasks module namespace.
"""

import importlib
import importlib.util
import json
import os
import sys
import tempfile
import time
import uuid
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest


# ---------------------------------------------------------------------------
# DB setup — must happen before any myah import so env.py sees the URL
# ---------------------------------------------------------------------------

_tmp_db_file = tempfile.NamedTemporaryFile(suffix='.db', delete=False)
_TMP_DB_PATH = _tmp_db_file.name
_tmp_db_file.close()

os.environ['DATABASE_URL'] = f'sqlite:///{_TMP_DB_PATH}'
os.environ.setdefault('ENABLE_DB_MIGRATIONS', 'False')
os.environ.setdefault('WEBUI_SECRET_KEY', 'test-secret')


# ---------------------------------------------------------------------------
# Module loader helpers
# ---------------------------------------------------------------------------


def _make_mod(name: str, **attrs) -> ModuleType:
    m = ModuleType(name)
    for k, v in attrs.items():
        setattr(m, k, v)
    return m


def _noop_span():
    """A context-manager span that does nothing."""

    class _Span:
        def set_attribute(self, *a, **kw):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            pass

    return _Span()


def _make_tracer():
    t = MagicMock()
    t.start_as_current_span.return_value = _noop_span()
    return t


def _make_otel_stubs():
    """Stub opentelemetry so the handler's `from opentelemetry import trace` works."""
    tracer_provider = MagicMock()
    tracer_provider.get_tracer.return_value = _make_tracer()

    otel_trace = MagicMock()
    otel_trace.get_tracer.return_value = _make_tracer()

    return {
        'opentelemetry': _make_mod('opentelemetry'),
        'opentelemetry.trace': _make_mod('opentelemetry.trace', get_tracer=lambda *a, **kw: _make_tracer()),
    }


def _load_chat_tasks_module(aux_call_mock: AsyncMock) -> ModuleType:
    """Load myah.utils.chat_tasks with all heavy deps stubbed out.

    The trick: tasks.py is loaded first with our aux_call mock wired in,
    then chat_tasks.py imports from it. chat_tasks.py binds to the tasks
    module's namespace, so patching tasks.aux_call is the right target.
    """
    # Avoid polluting the real sys.modules by using a fresh key each load.
    # We need to forcibly reload to get a clean module with our mocks.
    for key in list(sys.modules.keys()):
        if key.startswith('myah.utils.chat_tasks') or key.startswith('myah.routers.tasks'):
            del sys.modules[key]

    # ── Stub myah.routers.tasks with our aux_call mock ──
    tasks_path = Path(__file__).resolve().parents[4] / 'routers' / 'tasks.py'

    # Build minimal sys.modules stubs so tasks.py loads without network/db.
    task_stubs = {
        'myah.internal.db': _make_mod('myah.internal.db', get_session=MagicMock()),
        'myah.config': _make_mod(
            'myah.config',
            DEFAULT_TITLE_GENERATION_PROMPT_TEMPLATE='Generate a title for: {messages}',
            DEFAULT_FOLLOW_UP_GENERATION_PROMPT_TEMPLATE='Generate follow-ups for: {messages}',
            DEFAULT_TAGS_GENERATION_PROMPT_TEMPLATE='Generate tags for: {messages}',
            DEFAULT_QUERY_GENERATION_PROMPT_TEMPLATE='Generate query for: {messages}',
            DEFAULT_AUTOCOMPLETE_GENERATION_PROMPT_TEMPLATE='Autocomplete: {prompt}',
            DEFAULT_EMOJI_GENERATION_PROMPT_TEMPLATE='Generate emoji: {messages}',
        ),
        'myah.utils.auth': _make_mod(
            'myah.utils.auth',
            get_verified_user=MagicMock(),
            get_admin_user=MagicMock(),
        ),
        'myah.utils.agent_proxy': _make_mod(
            'myah.utils.agent_proxy',
            aux_call=aux_call_mock,
        ),
        'myah.models.users': _make_mod('myah.models.users', Users=MagicMock(), UserModel=MagicMock()),
        'myah.models.models': _make_mod(
            'myah.models.models',
            Models=SimpleNamespace(get_all_models=MagicMock(return_value=[])),
        ),
        'myah.utils.task': _make_mod(
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
        'myah.utils.chat': _make_mod('myah.utils.chat', generate_chat_completion=AsyncMock()),
    }

    # Patch env/constants only if not already loaded (they may be real from DB setup)
    if 'myah.env' not in sys.modules:
        task_stubs['myah.env'] = _make_mod(
            'myah.env',
            WEBUI_AUTH=True,
            ENABLE_AGENT_SETTINGS_UI=True,
            ENABLE_TITLE_GENERATION=SimpleNamespace(value=True),
            ENABLE_FOLLOW_UP_GENERATION=SimpleNamespace(value=True),
            TITLE_GENERATION_PROMPT_TEMPLATE=SimpleNamespace(value=''),
            FOLLOW_UP_GENERATION_PROMPT_TEMPLATE=SimpleNamespace(value=''),
            DEFAULT_TITLE_GENERATION_PROMPT_TEMPLATE='Generate title for: {messages}',
            DEFAULT_FOLLOW_UP_GENERATION_PROMPT_TEMPLATE='Generate follow-ups: {messages}',
            TASK_MODEL=SimpleNamespace(value=''),
            TASK_MODEL_EXTERNAL=SimpleNamespace(value=''),
        )

    for name, mod in task_stubs.items():
        sys.modules.setdefault(name, mod)

    # Load tasks.py
    spec = importlib.util.spec_from_file_location('myah.routers.tasks', tasks_path)
    tasks_mod = importlib.util.module_from_spec(spec)
    sys.modules['myah.routers.tasks'] = tasks_mod
    try:
        spec.loader.exec_module(tasks_mod)
    except Exception:
        pass  # Tasks module may fail on other deps — that's ok, we only need aux helpers

    # Inject our mock directly into the tasks module namespace so chat_tasks sees it
    tasks_mod.aux_call = aux_call_mock

    # ── Now load chat_tasks.py ──
    # Stub dependencies of chat_tasks.py that we want to control
    socket_main_stub = _make_mod(
        'myah.socket.main',
        get_event_call=MagicMock(return_value=AsyncMock()),
        get_event_emitter=MagicMock(return_value=AsyncMock()),
    )
    sys.modules['myah.socket.main'] = socket_main_stub

    # otel stubs (imported inside the function, so patch before load)
    for name, mod in _make_otel_stubs().items():
        sys.modules.setdefault(name, mod)

    # Stub constants with TASKS values if not already loaded
    if 'myah.constants' not in sys.modules:
        sys.modules['myah.constants'] = _make_mod(
            'myah.constants',
            TASKS=SimpleNamespace(
                TITLE_GENERATION='title_generation',
                FOLLOW_UP_GENERATION='follow_up_generation',
            ),
        )

    # Stub utils.misc
    if 'myah.utils.misc' not in sys.modules:
        sys.modules['myah.utils.misc'] = _make_mod(
            'myah.utils.misc',
            get_message_list=lambda msgs_map, msg_id: list(msgs_map.values()) if msgs_map else [],
            get_last_user_message=lambda msgs: next(
                (m.get('content', '') for m in reversed(msgs) if m.get('role') == 'user'), ''
            ),
            get_last_user_message_item=lambda msgs: next((m for m in reversed(msgs) if m.get('role') == 'user'), None),
        )

    chat_tasks_path = Path(__file__).resolve().parents[4] / 'utils' / 'chat_tasks.py'
    spec2 = importlib.util.spec_from_file_location('myah.utils.chat_tasks', chat_tasks_path)
    chat_tasks_mod = importlib.util.module_from_spec(spec2)
    sys.modules['myah.utils.chat_tasks'] = chat_tasks_mod
    spec2.loader.exec_module(chat_tasks_mod)

    return chat_tasks_mod


# ---------------------------------------------------------------------------
# Shared DB fixture (module scope, same file-based SQLite pattern)
# ---------------------------------------------------------------------------


@pytest.fixture(scope='module')
def db_session():
    """Create a file-based SQLite test engine and patch SessionLocal so that
    `get_db_context()` (used by `Chats.update_chat_title_by_id`) opens
    connections against the same engine, not the module-level engine that may
    have been frozen to a different URL by an earlier test module."""
    import unittest.mock as mock

    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    import myah.internal.db as _db_mod
    from myah.internal.db import Base
    from myah.models.chats import Chat  # noqa: F401 — registers table

    engine = create_engine(
        f'sqlite:///{_TMP_DB_PATH}',
        connect_args={'check_same_thread': False},
    )
    Base.metadata.create_all(engine, tables=[Chat.__table__])
    TestSession = sessionmaker(bind=engine, expire_on_commit=False)
    session = TestSession()

    # Patch SessionLocal so get_db_context() hits our test engine.
    with mock.patch.object(_db_mod, 'SessionLocal', TestSession):
        yield session

    session.close()
    os.unlink(_TMP_DB_PATH)


def _insert_chat(db_session, chat_id: str, msg_id: str, title: str = 'New Chat', title_source=None):
    """Insert a chat row with a single user message in the JSON blob."""
    from myah.models.chats import Chat

    user_msg_id = str(uuid.uuid4())
    messages_map = {
        user_msg_id: {
            'id': user_msg_id,
            'parentId': None,
            'childrenIds': [msg_id],
            'role': 'user',
            'content': 'What is the best time to visit Paris?',
            'timestamp': int(time.time()),
        },
        msg_id: {
            'id': msg_id,
            'parentId': user_msg_id,
            'childrenIds': [],
            'role': 'assistant',
            'content': 'Paris is lovely in spring and autumn.',
            'model': 'myah',
            'timestamp': int(time.time()),
        },
    }
    chat_blob = {
        'title': title,
        'history': {
            'currentId': msg_id,
            'messages': messages_map,
        },
    }
    row = Chat(
        id=chat_id,
        user_id='user-test',
        title=title,
        chat=chat_blob,
        created_at=int(time.time()),
        updated_at=int(time.time()),
        archived=False,
        pinned=False,
        meta={},
        folder_id=None,
        title_source=title_source,
    )
    db_session.add(row)
    db_session.commit()


def _fetch_row(db_session, chat_id: str):
    from myah.models.chats import Chat

    db_session.expire_all()
    return db_session.get(Chat, chat_id)


def _build_ctx(chat_id: str, msg_id: str, aux_event_emitter=None) -> dict:
    """Minimal ctx dict for background_tasks_handler."""
    return {
        'request': MagicMock(),
        'form_data': {'model': 'myah', 'messages': []},
        'user': SimpleNamespace(id='user-test', role='user', email='test@myah.dev'),
        'model': {'id': 'myah'},
        'metadata': {
            'chat_id': chat_id,
            'message_id': msg_id,
            'session_id': 'sess-001',
        },
        'tasks': {
            'title_generation': True,
            'follow_up_generation': False,
        },
        'events': {},
        'event_emitter': aux_event_emitter or AsyncMock(),
        'event_caller': AsyncMock(),
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_title_written_to_db_via_aux_path(db_session):
    """background_tasks_handler writes the aux title to DB with title_source='auto'."""
    chat_id = str(uuid.uuid4())
    msg_id = str(uuid.uuid4())
    _insert_chat(db_session, chat_id, msg_id, title='New Chat', title_source=None)

    aux_call_mock = AsyncMock(
        return_value={
            'status': 200,
            'body': {
                'choices': [{'message': {'content': '{"title": "Paris Inquiry"}', 'role': 'assistant'}}],
                'usage': {},
            },
            'headers': {},
        }
    )

    mod = _load_chat_tasks_module(aux_call_mock)
    ctx = _build_ctx(chat_id, msg_id)
    await mod.background_tasks_handler(ctx)

    row = _fetch_row(db_session, chat_id)
    assert row.title == 'Paris Inquiry', f'Expected title "Paris Inquiry", got {row.title!r}'
    assert row.title_source == 'auto', f'Expected title_source "auto", got {row.title_source!r}'


@pytest.mark.asyncio
async def test_aux_does_not_overwrite_manual_title(db_session):
    """background_tasks_handler must not overwrite a manually renamed chat."""
    chat_id = str(uuid.uuid4())
    msg_id = str(uuid.uuid4())
    _insert_chat(db_session, chat_id, msg_id, title='User Rename', title_source=None)

    # Mark the chat as manually renamed before the handler runs
    from myah.models.chats import Chats

    Chats.update_chat_title_by_id(chat_id, 'User Rename', source='manual')

    # Verify pre-condition
    row_before = _fetch_row(db_session, chat_id)
    assert row_before.title_source == 'manual', 'Pre-condition: title_source should be manual'

    aux_call_mock = AsyncMock(
        return_value={
            'status': 200,
            'body': {
                'choices': [{'message': {'content': '{"title": "Paris Inquiry"}', 'role': 'assistant'}}],
                'usage': {},
            },
            'headers': {},
        }
    )

    mod = _load_chat_tasks_module(aux_call_mock)
    ctx = _build_ctx(chat_id, msg_id)
    await mod.background_tasks_handler(ctx)

    row = _fetch_row(db_session, chat_id)
    assert row.title == 'User Rename', f'Expected title unchanged "User Rename", got {row.title!r}'
    assert row.title_source == 'manual', f'Expected title_source unchanged "manual", got {row.title_source!r}'


# ---------------------------------------------------------------------------
# Appendix Task B: Regression fence for title generation task-gate invariants
# Pins that message_len does NOT gate title generation (only the tasks dict
# does). Documents the expected skip behavior on tasks-absent ctx.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_title_fires_when_task_present_regardless_of_message_count(db_session):
    """_fetch_title_via_aux is called whenever TITLE_GENERATION is in tasks.

    Message count (len(messages)) is NOT a gate on title generation. The tasks
    dict alone determines whether the aux call fires. This test pins that
    invariant with messages of different lengths.

    Regression context: the original bug was a JSONResponse/dict type mismatch
    that silently skipped the write. This test ensures that even if messages
    contains only 1 item or 200 items, the aux call still fires — message_len
    is not the gate.
    """
    # Use a list of different message counts to parametrize inline
    for msg_count in [1, 4]:
        chat_id = str(uuid.uuid4())
        msg_id = str(uuid.uuid4())
        _insert_chat(db_session, chat_id, msg_id, title='New Chat')

        # Build ctx with the given message count
        ctx = _build_ctx(chat_id, msg_id)
        messages = [{'role': 'user', 'content': f'Message {i}'} for i in range(msg_count - 1)]
        messages.append({'role': 'assistant', 'content': 'Response', 'model': 'myah'})
        ctx['form_data']['messages'] = messages

        aux_call_mock = AsyncMock(
            return_value={
                'status': 200,
                'body': {
                    'choices': [{'message': {'content': '{"title": "Generated Title"}', 'role': 'assistant'}}],
                    'usage': {},
                },
                'headers': {},
            }
        )

        mod = _load_chat_tasks_module(aux_call_mock)
        await mod.background_tasks_handler(ctx)

        # Title should be written regardless of msg_count (task gate, not len gate)
        row = _fetch_row(db_session, chat_id)
        assert row.title == 'Generated Title', (
            f'msg_count={msg_count}: Expected title "Generated Title", got {row.title!r}. '
            'Title generation should fire regardless of message count.'
        )


@pytest.mark.asyncio
async def test_title_skips_when_task_absent(db_session):
    """Title generation is skipped when TITLE_GENERATION is absent from tasks dict.

    This pins the expected skip behavior — the tasks dict is the ONLY gate on
    title generation. This is the correct behavior for regenerate-of-later-exchange
    scenarios where the frontend does not include TITLE_GENERATION in tasks.
    """
    chat_id = str(uuid.uuid4())
    msg_id = str(uuid.uuid4())
    original_title = 'Original Title'
    _insert_chat(db_session, chat_id, msg_id, title=original_title)

    ctx = _build_ctx(chat_id, msg_id)
    # Remove TITLE_GENERATION from tasks — simulates a regenerate/continuation ctx
    ctx['tasks'] = {'follow_up_generation': False}

    aux_call_mock = AsyncMock()  # should NOT be called

    mod = _load_chat_tasks_module(aux_call_mock)
    await mod.background_tasks_handler(ctx)

    row = _fetch_row(db_session, chat_id)
    assert row.title == original_title, (
        f'Title should be unchanged when TITLE_GENERATION not in tasks. '
        f'Got: {row.title!r}'
    )
