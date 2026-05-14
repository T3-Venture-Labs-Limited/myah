"""ORM tests for ChatFile model methods — including get_chat_files_by_chat_id.

Uses an in-memory SQLite DB with only the chat and chat_file tables created
(file table FK is dropped via use_alter). The tests cover the new broad query
method (no message_id filter) added in Task 1 of PR 4.
"""

import os
import time
import uuid

import pytest

os.environ.setdefault('DATABASE_URL', 'sqlite://')
os.environ.setdefault('ENABLE_DB_MIGRATIONS', 'False')
os.environ.setdefault('WEBUI_SECRET_KEY', 'test-secret')
os.environ.setdefault('DATABASE_ENABLE_SESSION_SHARING', 'True')


@pytest.fixture(scope='module')
def db_session():
    """Create chat + file + chat_file tables on an in-memory SQLite engine.

    ChatFile has FKs to both chat.id and file.id, so all three tables must
    exist. We pass them explicitly to create_all to avoid pulling in unrelated
    FK-dependent tables from the full metadata.
    """
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from myah.internal.db import Base
    from myah.models.chats import Chat, ChatFile  # registers tables
    from myah.models.files import File  # needed for FK resolution

    engine = create_engine('sqlite://', connect_args={'check_same_thread': False})
    Base.metadata.create_all(
        engine, tables=[Chat.__table__, File.__table__, ChatFile.__table__]
    )
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    session = Session()
    yield session
    session.close()


def _make_chat(db_session, user_id='u1') -> str:
    from myah.models.chats import Chat

    chat_id = str(uuid.uuid4())
    now = int(time.time())
    row = Chat(
        id=chat_id,
        user_id=user_id,
        title='Test',
        chat={'title': 'Test'},
        created_at=now,
        updated_at=now,
        archived=False,
        pinned=False,
        meta={},
        folder_id=None,
    )
    db_session.add(row)
    db_session.commit()
    return chat_id


def _make_chat_file(db_session, chat_id: str, message_id: str, file_id: str, user_id: str = 'u1'):
    from myah.models.chats import ChatFile

    now = int(time.time())
    row = ChatFile(
        id=str(uuid.uuid4()),
        user_id=user_id,
        chat_id=chat_id,
        message_id=message_id,
        file_id=file_id,
        created_at=now,
        updated_at=now,
    )
    db_session.add(row)
    db_session.commit()
    return row


def test_get_chat_files_by_chat_id_returns_all_messages(db_session):
    """insert rows across two messages; get_chat_files_by_chat_id returns all of them."""
    from myah.models.chats import Chats

    chat_id = _make_chat(db_session)
    msg1 = str(uuid.uuid4())
    msg2 = str(uuid.uuid4())
    file1 = str(uuid.uuid4())
    file2 = str(uuid.uuid4())
    file3 = str(uuid.uuid4())

    _make_chat_file(db_session, chat_id, msg1, file1)
    _make_chat_file(db_session, chat_id, msg1, file2)
    _make_chat_file(db_session, chat_id, msg2, file3)

    results = Chats.get_chat_files_by_chat_id(chat_id, db=db_session)

    assert len(results) == 3
    result_file_ids = {r.file_id for r in results}
    assert result_file_ids == {file1, file2, file3}


def test_get_chat_files_by_chat_id_returns_empty_for_unknown_chat(db_session):
    from myah.models.chats import Chats

    results = Chats.get_chat_files_by_chat_id('nonexistent-chat-id', db=db_session)
    assert results == []


def test_get_chat_files_by_chat_id_ordered_by_created_at(db_session):
    """Rows must come back in ascending created_at order."""
    from myah.models.chats import Chat, ChatFile, Chats

    chat_id = _make_chat(db_session)
    msg = str(uuid.uuid4())
    now = int(time.time())

    # Insert with explicit timestamps to control ordering
    for i, fid in enumerate([str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4())]):
        row = ChatFile(
            id=str(uuid.uuid4()),
            user_id='u1',
            chat_id=chat_id,
            message_id=msg,
            file_id=fid,
            created_at=now + i,
            updated_at=now + i,
        )
        db_session.add(row)
    db_session.commit()

    results = Chats.get_chat_files_by_chat_id(chat_id, db=db_session)
    timestamps = [r.created_at for r in results]
    assert timestamps == sorted(timestamps), 'Results must be ordered by created_at ASC'


def test_get_chat_files_by_chat_id_isolates_per_chat(db_session):
    """Files from another chat must not appear in results."""
    from myah.models.chats import Chats

    chat_a = _make_chat(db_session)
    chat_b = _make_chat(db_session)
    msg = str(uuid.uuid4())
    file_a = str(uuid.uuid4())
    file_b = str(uuid.uuid4())

    _make_chat_file(db_session, chat_a, msg, file_a)
    _make_chat_file(db_session, chat_b, msg, file_b)

    results_a = Chats.get_chat_files_by_chat_id(chat_a, db=db_session)
    assert all(r.chat_id == chat_a for r in results_a)
    assert all(r.file_id != file_b for r in results_a)
