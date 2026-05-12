"""Add refresh_token_encrypted column to user_llm_key for OAuth providers.

Revision ID: e3f4a5b6c7d8
Revises: c4d5e6f7a8b9
Create Date: 2026-04-19 12:00:00.000000

Nullable column; only populated for provider='openai-codex' (and future
OAuth providers). Fixes MYAH-AGENT-16 — access tokens expiring silently
after 30-60 minutes because the refresh token was discarded on save.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from open_webui.migrations.util import get_existing_tables

revision: str = 'e3f4a5b6c7d8'
down_revision: Union[str, None] = 'c4d5e6f7a8b9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if 'user_llm_key' not in get_existing_tables():
        # Fresh install — the creating migration already ran for this deploy;
        # nothing to do. Safe idempotent no-op.
        return

    conn = op.get_bind()
    inspector = sa.inspect(conn)
    existing_cols = {c['name'] for c in inspector.get_columns('user_llm_key')}
    if 'refresh_token_encrypted' not in existing_cols:
        op.add_column(
            'user_llm_key',
            sa.Column('refresh_token_encrypted', sa.String(), nullable=True),
        )


def downgrade() -> None:
    if 'user_llm_key' not in get_existing_tables():
        return
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    existing_cols = {c['name'] for c in inspector.get_columns('user_llm_key')}
    if 'refresh_token_encrypted' in existing_cols:
        op.drop_column('user_llm_key', 'refresh_token_encrypted')
