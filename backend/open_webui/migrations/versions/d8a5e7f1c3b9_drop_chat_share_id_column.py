"""drop chat.share_id column

Revision ID: d8a5e7f1c3b9
Revises: 4f4f6c0fc288
Create Date: 2026-05-01 00:00:00.000000

The share-chats feature is being removed; the supporting ``chat.share_id``
column is dropped along with its UNIQUE INDEX.

Uses Alembic batch mode so SQLite can rebuild the table without the
inline ``UniqueConstraint`` from the original init migration
(``7e5b5dc7342b``). The auto-generated ``sqlite_autoindex_chat_*`` is
removed as part of the table rebuild — no explicit ``drop_index`` is
needed.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from open_webui.migrations.util import get_existing_tables

revision: str = 'd8a5e7f1c3b9'
down_revision: Union[str, None] = '4f4f6c0fc288'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    existing = get_existing_tables()
    if 'chat' not in existing:
        return
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    columns = [c['name'] for c in inspector.get_columns('chat')]
    if 'share_id' not in columns:
        return
    indexes = {idx['name'] for idx in inspector.get_indexes('chat')}
    # Drop the unique index that backs share_id BEFORE dropping the column,
    # otherwise batch_alter_table will try to recreate it during table
    # reconstruction and fail with "no such column: share_id".
    with op.batch_alter_table('chat') as batch_op:
        if 'chat_share_id' in indexes:
            batch_op.drop_index('chat_share_id')
        batch_op.drop_column('share_id')


def downgrade() -> None:
    existing = get_existing_tables()
    if 'chat' not in existing:
        return
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    columns = [c['name'] for c in inspector.get_columns('chat')]
    if 'share_id' in columns:
        return
    with op.batch_alter_table('chat') as batch_op:
        batch_op.add_column(sa.Column('share_id', sa.Text(), nullable=True))
        batch_op.create_index('chat_share_id', ['share_id'], unique=True)
