"""Add chat.title_source column for provisional/manual tracking

Revision ID: a1b2c3d4e5f7
Revises: 0448b6b0c5ed
Create Date: 2026-04-22 00:00:00.000000

Adds a nullable title_source column to the chat table to distinguish
between titles set automatically by the AI aux path ('auto') and titles
set explicitly by the user ('manual'). Backfills existing rows to 'auto'
since legacy titles were all generated via the automatic path.

Application code writes this field on every title update — there is no
DB-level default so that the application layer remains the authoritative
source of truth.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from open_webui.migrations.util import get_existing_tables

revision: str = 'a1b2c3d4e5f7'
down_revision: Union[str, None] = '0448b6b0c5ed'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    existing = get_existing_tables()
    if 'chat' in existing:
        conn = op.get_bind()
        inspector = sa.inspect(conn)
        columns = [c['name'] for c in inspector.get_columns('chat')]
        if 'title_source' not in columns:
            op.add_column('chat', sa.Column('title_source', sa.String(), nullable=True))
        # Backfill: all pre-existing titles were generated automatically.
        op.execute("UPDATE chat SET title_source = 'auto' WHERE title_source IS NULL")


def downgrade() -> None:
    existing = get_existing_tables()
    if 'chat' in existing:
        conn = op.get_bind()
        inspector = sa.inspect(conn)
        columns = [c['name'] for c in inspector.get_columns('chat')]
        if 'title_source' in columns:
            op.drop_column('chat', 'title_source')
