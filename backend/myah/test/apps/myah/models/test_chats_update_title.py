"""Tests for source-aware update_chat_title_by_id.

Tests verify the full contract:
  - auto → auto: updates title, preserves source
  - auto → manual: updates title, upgrades source
  - manual + auto call: silently refuses, DB unchanged
  - manual → manual: updates title, preserves source
  - NULL (legacy) + auto call: treated as auto, updates title, writes source

Uses a shared file-based SQLite temp DB so that `Chats.*` methods (which open
their own sessions via get_db_context / SessionLocal) see the same data as the
test's setup writes. In-memory SQLite would give each connection its own empty
database, making the helper see no rows.
"""

import os
import tempfile
import time
import uuid

import pytest

# Must be set before any myah import so env.py picks them up.
_tmp_db_file = tempfile.NamedTemporaryFile(suffix='.db', delete=False)
_tmp_db_path = _tmp_db_file.name
_tmp_db_file.close()

os.environ['DATABASE_URL'] = f'sqlite:///{_tmp_db_path}'
os.environ.setdefault('ENABLE_DB_MIGRATIONS', 'False')
os.environ.setdefault('WEBUI_SECRET_KEY', 'test-secret')


@pytest.fixture(scope='module')
def db_session():
    """Create only the `chat` table on the shared temp-file SQLite engine and
    yield a plain Session for direct ORM reads/writes by test helpers.

    Also patches `myah.internal.db.SessionLocal` so that
    `get_db_context()` (used by `Chats.update_chat_title_by_id`) opens
    connections against the same file-based engine, not the module-level
    engine that may have been frozen to a different URL by an earlier test
    module in the combined pytest run.
    """
    import unittest.mock as mock

    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    import myah.internal.db as _db_mod
    from myah.internal.db import Base
    from myah.models.chats import Chat  # noqa: F401 — registers table in metadata

    engine = create_engine(
        f'sqlite:///{_tmp_db_path}',
        connect_args={'check_same_thread': False},
    )
    Base.metadata.create_all(engine, tables=[Chat.__table__])
    TestSession = sessionmaker(bind=engine, expire_on_commit=False)
    session = TestSession()

    # Patch SessionLocal so get_db_context() hits our test engine.
    with mock.patch.object(_db_mod, 'SessionLocal', TestSession):
        yield session

    session.close()
    os.unlink(_tmp_db_path)


def _create_chat(db_session, title: str, title_source):
    """Insert a chat row with the given title and title_source, return its id."""
    from myah.models.chats import Chat

    chat_id = str(uuid.uuid4())
    row = Chat(
        id=chat_id,
        user_id='test-user',
        title=title,
        chat={'title': title},
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
    return chat_id


def _fetch_row(db_session, chat_id):
    from myah.models.chats import Chat

    db_session.expire_all()
    return db_session.get(Chat, chat_id)


def test_auto_source_updates_auto_row(db_session):
    """Row is 'auto', call with source='auto' and a new title.
    Assert title changed, source still 'auto'."""
    from myah.models.chats import Chats

    chat_id = _create_chat(db_session, 'Original Title', 'auto')

    result = Chats.update_chat_title_by_id(chat_id, 'Updated Title', source='auto')

    row = _fetch_row(db_session, chat_id)
    assert row.title == 'Updated Title', f'Expected title "Updated Title", got {row.title!r}'
    assert row.title_source == 'auto', f'Expected source "auto", got {row.title_source!r}'
    assert result is not None
    assert result.title == 'Updated Title'


def test_manual_source_updates_auto_row(db_session):
    """Row is 'auto', call with source='manual'.
    Assert title changed, source upgraded to 'manual'."""
    from myah.models.chats import Chats

    chat_id = _create_chat(db_session, 'Original Title', 'auto')

    result = Chats.update_chat_title_by_id(chat_id, 'Manual Title', source='manual')

    row = _fetch_row(db_session, chat_id)
    assert row.title == 'Manual Title', f'Expected title "Manual Title", got {row.title!r}'
    assert row.title_source == 'manual', f'Expected source "manual", got {row.title_source!r}'
    assert result is not None


def test_auto_source_refuses_manual_row(db_session):
    """Row is 'manual', call with source='auto'.
    Assert DB is unchanged — title and source identical to before."""
    from myah.models.chats import Chats

    chat_id = _create_chat(db_session, 'Manual Row Title', 'manual')

    # Call with auto — should be silently refused
    Chats.update_chat_title_by_id(chat_id, 'Should Not Apply', source='auto')

    row = _fetch_row(db_session, chat_id)
    assert row.title == 'Manual Row Title', f'Expected title unchanged "Manual Row Title", got {row.title!r}'
    assert row.title_source == 'manual', f'Expected source unchanged "manual", got {row.title_source!r}'


def test_manual_source_updates_manual_row(db_session):
    """Row is 'manual', call with source='manual'.
    Assert title changed, source still 'manual'."""
    from myah.models.chats import Chats

    chat_id = _create_chat(db_session, 'Old Manual Title', 'manual')

    result = Chats.update_chat_title_by_id(chat_id, 'New Manual Title', source='manual')

    row = _fetch_row(db_session, chat_id)
    assert row.title == 'New Manual Title', f'Expected title "New Manual Title", got {row.title!r}'
    assert row.title_source == 'manual', f'Expected source "manual", got {row.title_source!r}'
    assert result is not None


def test_legacy_null_source_treated_as_auto(db_session):
    """Row has title_source=NULL (legacy). Call with source='auto'.
    Assert title changed, source written as 'auto'."""
    from myah.models.chats import Chats

    # Create with NULL title_source to simulate a pre-migration row
    chat_id = _create_chat(db_session, 'Legacy Title', None)

    # Verify it's actually NULL in DB
    row_before = _fetch_row(db_session, chat_id)
    assert row_before.title_source is None, 'Precondition: title_source should be NULL'

    result = Chats.update_chat_title_by_id(chat_id, 'Updated Legacy Title', source='auto')

    row = _fetch_row(db_session, chat_id)
    assert row.title == 'Updated Legacy Title', f'Expected title "Updated Legacy Title", got {row.title!r}'
    assert row.title_source == 'auto', f'Expected source "auto" after write, got {row.title_source!r}'
    assert result is not None
