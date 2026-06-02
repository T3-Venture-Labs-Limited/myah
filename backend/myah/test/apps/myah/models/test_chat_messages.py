from __future__ import annotations

import pytest
from sqlalchemy import BigInteger, Boolean, Column, JSON, Text, create_engine
from sqlalchemy.orm import declarative_base, sessionmaker
from sqlalchemy.pool import StaticPool


@pytest.fixture
def chat_message_session(monkeypatch):
    import myah.internal.db as internal_db
    import myah.models.chat_messages as chat_messages_module

    monkeypatch.setattr(internal_db, 'DATABASE_ENABLE_SESSION_SHARING', True)
    engine = create_engine(
        'sqlite://',
        connect_args={'check_same_thread': False},
        poolclass=StaticPool,
    )
    Base = declarative_base()

    class TestChatMessage(Base):
        __tablename__ = 'chat_message'

        id = Column(Text, primary_key=True)
        chat_id = Column(Text, nullable=False, index=True)
        user_id = Column(Text, index=True)
        role = Column(Text, nullable=False)
        parent_id = Column(Text, nullable=True)
        content = Column(JSON, nullable=True)
        output = Column(JSON, nullable=True)
        model_id = Column(Text, nullable=True, index=True)
        files = Column(JSON, nullable=True)
        sources = Column(JSON, nullable=True)
        embeds = Column(JSON, nullable=True)
        done = Column(Boolean, default=True)
        status_history = Column(JSON, nullable=True)
        error = Column(JSON, nullable=True)
        usage = Column(JSON, nullable=True)
        created_at = Column(BigInteger, index=True)
        updated_at = Column(BigInteger)

    monkeypatch.setattr(chat_messages_module, 'ChatMessage', TestChatMessage)
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def test_blank_done_assistant_sibling_is_not_inserted_after_non_empty_final(chat_message_session):
    from myah.models.chat_messages import ChatMessages

    ChatMessages.upsert_message(
        'user-1',
        'chat-1',
        'user-1',
        {'role': 'user', 'content': 'question', 'done': True},
        db=chat_message_session,
    )
    ChatMessages.upsert_message(
        'assistant-good',
        'chat-1',
        'user-1',
        {'role': 'assistant', 'parentId': 'user-1', 'content': 'final answer', 'done': True},
        db=chat_message_session,
    )

    result = ChatMessages.upsert_message(
        'assistant-blank',
        'chat-1',
        'user-1',
        {'role': 'assistant', 'parentId': 'user-1', 'content': '', 'done': True},
        db=chat_message_session,
    )

    rows = ChatMessages.get_messages_by_chat_id('chat-1', db=chat_message_session)
    assistant_rows = [row for row in rows if row.role == 'assistant']
    assert len(assistant_rows) == 1
    assert assistant_rows[0].content == 'final answer'
    assert result is not None
    assert result.id == 'chat-1-assistant-good'


def test_empty_in_progress_assistant_placeholder_is_preserved(chat_message_session):
    from myah.models.chat_messages import ChatMessages

    result = ChatMessages.upsert_message(
        'assistant-placeholder',
        'chat-1',
        'user-1',
        {'role': 'assistant', 'parentId': 'user-1', 'content': '', 'done': False},
        db=chat_message_session,
    )

    rows = ChatMessages.get_messages_by_chat_id('chat-1', db=chat_message_session)
    assert result is not None
    assert result.id == 'chat-1-assistant-placeholder'
    assert result.done is False
    assert len([row for row in rows if row.role == 'assistant']) == 1


def test_non_empty_final_assistant_sibling_is_preserved(chat_message_session):
    from myah.models.chat_messages import ChatMessages

    ChatMessages.upsert_message(
        'assistant-1',
        'chat-1',
        'user-1',
        {'role': 'assistant', 'parentId': 'user-1', 'content': 'first answer', 'done': True},
        db=chat_message_session,
    )
    ChatMessages.upsert_message(
        'assistant-2',
        'chat-1',
        'user-1',
        {'role': 'assistant', 'parentId': 'user-1', 'content': 'second branch answer', 'done': True},
        db=chat_message_session,
    )

    rows = ChatMessages.get_messages_by_chat_id('chat-1', db=chat_message_session)
    assistant_rows = [row for row in rows if row.role == 'assistant']
    assert len(assistant_rows) == 2
    assert {row.content for row in assistant_rows} == {'first answer', 'second branch answer'}
