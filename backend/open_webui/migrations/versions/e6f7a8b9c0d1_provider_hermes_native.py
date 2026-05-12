"""Add user_provider_status table for Hermes-native provider catalog.

Revision ID: e6f7a8b9c0d1
Revises: f4a5b6c7d8e9
Create Date: 2026-04-19 18:00:00.000000

Creates user_provider_status (composite PK), backfills from user_llm_key,
and idempotently ensures users.default_model column exists.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from open_webui.migrations.util import get_existing_tables

revision: str = 'e6f7a8b9c0d1'
down_revision: Union[str, None] = 'f4a5b6c7d8e9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    existing_tables = get_existing_tables()

    # 1. Create user_provider_status if not already there
    if 'user_provider_status' not in existing_tables:
        op.create_table(
            'user_provider_status',
            sa.Column('user_id', sa.String(), nullable=False),
            sa.Column('provider_id', sa.String(), nullable=False),
            sa.Column('entry_id', sa.String(), nullable=True),
            sa.Column('connected_at', sa.BigInteger(), nullable=False, server_default='0'),
            sa.Column('last_validated_at', sa.BigInteger(), nullable=True),
            sa.Column('is_valid', sa.Boolean(), nullable=False, server_default='false'),
            sa.Column('key_last_four', sa.String(), nullable=False, server_default=''),
            sa.Column('reconnect_needed', sa.Boolean(), nullable=False, server_default='false'),
            sa.Column('reconnect_reason', sa.String(), nullable=True),
            sa.Column('sync_watermark', sa.BigInteger(), nullable=True),
            sa.PrimaryKeyConstraint('user_id', 'provider_id', name='pk_user_provider_status'),
        )
        op.create_index(
            'ix_user_provider_status_user_id',
            'user_provider_status',
            ['user_id'],
        )

    # 2. Idempotently ensure users.default_model column exists
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    if 'user' in existing_tables:
        user_cols = {c['name'] for c in inspector.get_columns('user')}
        if 'default_model' not in user_cols:
            op.add_column('user', sa.Column('default_model', sa.String(), nullable=True))

    # 3. Backfill user_provider_status from user_llm_key (if that table exists)
    if 'user_llm_key' in existing_tables:
        # Only backfill rows not already present (idempotent)
        conn.execute(sa.text("""
            INSERT OR IGNORE INTO user_provider_status
              (user_id, provider_id, connected_at, last_validated_at, is_valid, key_last_four)
            SELECT
                user_id,
                CASE
                    WHEN provider = 'openai' THEN 'openai-legacy'
                    WHEN provider = 'google' THEN 'gemini'
                    ELSE provider
                END,
                COALESCE(created_at, 0),
                validated_at,
                0,
                COALESCE(key_last_four, '')
            FROM user_llm_key
        """))

        # 4. Mark user_llm_key rows as migration-aware (non-breaking column add)
        llm_key_cols = {c['name'] for c in inspector.get_columns('user_llm_key')}
        if 'migrated_at' not in llm_key_cols:
            op.add_column('user_llm_key', sa.Column('migrated_at', sa.BigInteger(), nullable=True))


def downgrade() -> None:
    existing_tables = get_existing_tables()
    if 'user_llm_key' in existing_tables:
        conn = op.get_bind()
        inspector = sa.inspect(conn)
        llm_key_cols = {c['name'] for c in inspector.get_columns('user_llm_key')}
        if 'migrated_at' in llm_key_cols:
            op.drop_column('user_llm_key', 'migrated_at')
    if 'user_provider_status' in existing_tables:
        op.drop_index('ix_user_provider_status_user_id', 'user_provider_status')
        op.drop_table('user_provider_status')
