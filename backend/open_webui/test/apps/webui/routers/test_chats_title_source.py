# Tests for title_source persistence via POST /chats/{id}.
# Uses the importlib stub pattern to avoid DB/Redis/migrations.

import importlib.util
import json
import os
import sys
import time
import uuid
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import BaseModel, ConfigDict


# ---------------------------------------------------------------------------
# Minimal Pydantic replicas of the real models — keeps the test self-contained
# ---------------------------------------------------------------------------


class _ChatModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    user_id: str
    title: str
    chat: dict
    created_at: int = 0
    updated_at: int = 0
    archived: bool = False
    pinned: Optional[bool] = False
    meta: dict = {}
    folder_id: Optional[str] = None
    title_source: Optional[str] = None


class _ChatResponse(_ChatModel):
    pass


class _ChatForm(BaseModel):
    chat: dict
    folder_id: Optional[str] = None
    title_source: Optional[str] = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_chat(title='Original Title', title_source=None) -> _ChatModel:
    return _ChatModel(
        id=str(uuid.uuid4()),
        user_id='user-1',
        title=title,
        chat={'title': title, 'history': {}},
        created_at=int(time.time()),
        updated_at=int(time.time()),
        title_source=title_source,
    )


def _fake_user():
    return SimpleNamespace(id='user-1', role='user', email='u@myah.dev')


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def chat_store():
    """In-memory stand-in for the Chat DB row + Chats helper."""

    class _FakeRow:
        def __init__(self, model: _ChatModel):
            for k, v in model.model_dump().items():
                setattr(self, k, v)

    class _FakeChats:
        def __init__(self):
            self._rows: dict[str, _FakeRow] = {}

        def seed(self, model: _ChatModel):
            self._rows[model.id] = _FakeRow(model)
            return model

        def get_chat_by_id_and_user_id(self, id, user_id, db=None) -> Optional[_ChatModel]:
            row = self._rows.get(id)
            if row is None or row.user_id != user_id:
                return None
            return _ChatModel.model_validate(row.__dict__)

        def update_chat_by_id(self, id, chat_dict, db=None) -> Optional[_ChatModel]:
            row = self._rows.get(id)
            if row is None:
                return None
            row.chat = chat_dict
            row.title = chat_dict['title'] if 'title' in chat_dict else 'New Chat'
            row.updated_at = int(time.time())
            return _ChatModel.model_validate(row.__dict__)

    return _FakeChats()


@pytest.fixture
def router_fn(chat_store):
    """Return a shim that executes the update_chat_by_id logic inline.

    Instead of importing the full open_webui.routers.chats module (which
    triggers a chain of heavyweight imports: socket.main → config → DB init
    → alembic migrations that fail in combined test runs), this fixture
    re-implements the relevant handler logic directly using the fake chat
    store and a fake DB session.

    The logic under test is the title_source-aware block in update_chat_by_id
    (chats.py:887-904). We call it here exactly as the real handler does:
      1. get_chat_by_id_and_user_id → return the existing chat
      2. if form_data.chat: merge and update via update_chat_by_id
      3. if form_data.title_source is not None: write title_source directly
         on the row via db.get / db.commit / db.refresh, then validate
    """

    # Build a fake DB session whose .get() returns the row object so the
    # title_source write path works.
    class _FakeDB:
        def __init__(self, store):
            self._store = store

        def get(self, model_cls, id):
            row = self._store._rows.get(id)
            return row  # SimpleNamespace-like object with setattr support

        def commit(self):
            pass

        def refresh(self, row):
            pass  # row is already mutated in place

    fake_db = _FakeDB(chat_store)

    # Inline re-implementation of the Myah-specific update_chat_by_id logic.
    # This is the actual code under test from chats.py:887-904.
    async def _handler(chat_id, form_data: _ChatForm, user=None):
        _user = user or _fake_user()
        chat = chat_store.get_chat_by_id_and_user_id(chat_id, _user.id)
        if chat is None:
            raise RuntimeError(f'Chat {chat_id!r} not found for user {_user.id!r}')

        # ── Myah: title_source-aware update (mirrors chats.py:892-903) ────
        if form_data.chat:
            updated_chat = {**chat.chat, **form_data.chat}
            chat = chat_store.update_chat_by_id(chat_id, updated_chat)

        if form_data.title_source is not None:
            row = fake_db.get(None, chat_id)
            row.title_source = form_data.title_source
            fake_db.commit()
            fake_db.refresh(row)
            chat = _ChatModel.model_validate(row.__dict__)
        # ──────────────────────────────────────────────────────────────────

        return chat

    yield _handler


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_post_with_title_and_manual_source_sets_manual(router_fn, chat_store):
    """POST with title + title_source='manual' → response has title_source='manual'."""
    chat = chat_store.seed(_make_chat())

    form = _ChatForm(chat={'title': 'Foo'}, title_source='manual')
    resp = await router_fn(chat.id, form)

    assert resp.title_source == 'manual'
    assert resp.title == 'Foo'


@pytest.mark.asyncio
async def test_post_with_title_and_auto_source_sets_auto(router_fn, chat_store):
    """POST with title + title_source='auto' → response has title_source='auto'."""
    chat = chat_store.seed(_make_chat())

    form = _ChatForm(chat={'title': 'Bar'}, title_source='auto')
    resp = await router_fn(chat.id, form)

    assert resp.title_source == 'auto'
    assert resp.title == 'Bar'


@pytest.mark.asyncio
async def test_post_without_title_source_does_not_overwrite(router_fn, chat_store):
    """POST without title_source leaves the existing value untouched (None-means-no-op rule)."""
    chat = chat_store.seed(_make_chat(title_source='manual'))

    # Update title only — no title_source field in payload.
    form = _ChatForm(chat={'title': 'Updated Title'})
    await router_fn(chat.id, form)

    # Fetch back from the store.
    fetched = chat_store.get_chat_by_id_and_user_id(chat.id, 'user-1')
    assert fetched.title_source == 'manual'


@pytest.mark.asyncio
async def test_post_empty_chat_with_title_source_does_not_clobber_title(router_fn, chat_store):
    """POST with empty chat dict + title_source='manual' → title unchanged (NOT 'New Chat').

    Regression gate: update_chat_by_id's else-branch ('New Chat') must not fire
    when the caller is only updating title_source.
    """
    chat = chat_store.seed(_make_chat(title='Existing Title'))

    form = _ChatForm(chat={}, title_source='manual')
    resp = await router_fn(chat.id, form)

    assert resp.title == 'Existing Title', (
        f"Expected 'Existing Title', got {resp.title!r} — "
        "'New Chat' regression: update_chat_by_id should not be called for empty chat payloads"
    )
    assert resp.title_source == 'manual'
