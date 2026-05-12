"""ORM round-trip tests for the title_source column on the Chat table.

These tests spin up a disposable in-memory SQLite DB so they have zero
dependency on the real application database or the Alembic migration chain.

Only the `chat` table is created — we pass `tables=[Chat.__table__]` to
`create_all` to skip the FK-dependent tables (chat_file → file, etc.) that
would fail to resolve their foreign keys in isolation.
"""

import os
import pytest

os.environ.setdefault('DATABASE_URL', 'sqlite://')
os.environ.setdefault('ENABLE_DB_MIGRATIONS', 'False')
os.environ.setdefault('WEBUI_SECRET_KEY', 'test-secret')


@pytest.fixture(scope='module')
def db_session():
    """Create only the `chat` table on an in-memory SQLite engine and yield a
    plain Session for direct ORM reads/writes."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from open_webui.internal.db import Base
    from open_webui.models.chats import Chat  # registers Chat.__table__ in metadata

    engine = create_engine('sqlite://', connect_args={'check_same_thread': False})
    # Create only the chat table — avoids FK resolution failures for unrelated
    # tables (chat_file → file, etc.) that aren't needed by these tests.
    Base.metadata.create_all(engine, tables=[Chat.__table__])
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    session = Session()
    yield session
    session.close()


def test_insert_chat_title_source_initial_state(db_session):
    """Inserting a chat row with title_source=None should round-trip as None
    or 'auto'. Pins the baseline before any explicit provenance write."""
    import time
    import uuid
    from open_webui.models.chats import Chat

    chat_id = str(uuid.uuid4())
    row = Chat(
        id=chat_id,
        user_id='test-user',
        title='Test Chat',
        chat={'title': 'Test Chat'},
        created_at=int(time.time()),
        updated_at=int(time.time()),
        archived=False,
        pinned=False,
        meta={},
        folder_id=None,
        title_source=None,
    )
    db_session.add(row)
    db_session.commit()

    fetched = db_session.get(Chat, chat_id)
    assert fetched is not None
    assert fetched.title_source in (None, 'auto'), (
        f'Expected title_source in (None, "auto"), got {fetched.title_source!r}'
    )


def test_update_chat_title_source_persists(db_session):
    """Writing title_source='manual' must survive a commit + expire + re-fetch.
    Pins that the column is wired into the SQLAlchemy mapper, not just declared
    as a class attribute."""
    import time
    import uuid
    from open_webui.models.chats import Chat

    chat_id = str(uuid.uuid4())
    row = Chat(
        id=chat_id,
        user_id='test-user',
        title='Manual Title Chat',
        chat={'title': 'Manual Title Chat'},
        created_at=int(time.time()),
        updated_at=int(time.time()),
        archived=False,
        pinned=False,
        meta={},
        folder_id=None,
        title_source=None,
    )
    db_session.add(row)
    db_session.commit()

    # Flip to 'manual' via ORM
    fetched = db_session.get(Chat, chat_id)
    fetched.title_source = 'manual'
    db_session.commit()

    # Expire the cached instance and re-fetch from the DB
    db_session.expire(fetched)
    refetched = db_session.get(Chat, chat_id)
    assert refetched.title_source == 'manual', f'Expected title_source="manual", got {refetched.title_source!r}'
