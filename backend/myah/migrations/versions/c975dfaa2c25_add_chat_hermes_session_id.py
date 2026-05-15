"""Add chat.hermes_session_id mapping column

Revision ID: c975dfaa2c25
Revises: d8a5e7f1c3b9
Create Date: 2026-05-01 00:00:00.000000

Persist the Hermes SessionDB session.id mapping for each chat row so the
platform↔Hermes join is explicit instead of relying on the
``chat.id == hermes session_id`` convention master uses today.

* Adds ``chat.hermes_session_id`` (nullable VARCHAR, indexed). The
  platform writes it from the dispatch 202 response so future Hermes-side
  rotations (e.g. context-compression auto-rotate to a new session id)
  can be tracked without losing the join.
* Adds composite index ``hermes_session_id_user_id_idx`` to support the
  reverse-lookup helper (``Chats.get_chat_id_by_hermes_session_id``).

Existing chats get ``NULL`` until their next outbound dispatch populates
the mapping. The platform's send path tolerates ``NULL`` by falling back
to ``chat.id`` (the today-equivalent value), so no backfill is required.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from myah.migrations.util import get_existing_tables

revision: str = 'c975dfaa2c25'
down_revision: Union[str, None] = 'd8a5e7f1c3b9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    existing = get_existing_tables()
    if 'chat' not in existing:
        return
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    columns = [c['name'] for c in inspector.get_columns('chat')]
    indexes = {idx['name'] for idx in inspector.get_indexes('chat')}
    if 'hermes_session_id' not in columns:
        op.add_column('chat', sa.Column('hermes_session_id', sa.String(), nullable=True))
    if 'ix_chat_hermes_session_id' not in indexes:
        op.create_index(
            'ix_chat_hermes_session_id',
            'chat',
            ['hermes_session_id'],
            unique=False,
        )
    if 'hermes_session_id_user_id_idx' not in indexes:
        op.create_index(
            'hermes_session_id_user_id_idx',
            'chat',
            ['hermes_session_id', 'user_id'],
            unique=False,
        )


def downgrade() -> None:
    existing = get_existing_tables()
    if 'chat' not in existing:
        return
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    columns = [c['name'] for c in inspector.get_columns('chat')]
    indexes = {idx['name'] for idx in inspector.get_indexes('chat')}
    if 'hermes_session_id_user_id_idx' in indexes:
        op.drop_index('hermes_session_id_user_id_idx', table_name='chat')
    if 'ix_chat_hermes_session_id' in indexes:
        op.drop_index('ix_chat_hermes_session_id', table_name='chat')
    if 'hermes_session_id' in columns:
        op.drop_column('chat', 'hermes_session_id')
