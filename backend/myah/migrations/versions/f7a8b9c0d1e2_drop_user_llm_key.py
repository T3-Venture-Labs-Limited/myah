"""Drop legacy user_llm_key table (pre-MVP cleanup).

Revision ID: f7a8b9c0d1e2
Revises: e6f7a8b9c0d1
Create Date: 2026-04-20 00:00:00.000000

The user_llm_key table was the V1 provider credential store. As of PR 2,
all credentials live in the Hermes agent container (sourced from
/myah/api/providers) and per-user connection state is tracked in
user_provider_status. The legacy table is no longer read or written by
any application code — this migration removes it.

Idempotent: runs safely on databases where the table was already dropped
by a manual migration or a fresh install that never had the table.
"""
from typing import Sequence, Union

from alembic import op
from myah.migrations.util import get_existing_tables

revision: str = 'f7a8b9c0d1e2'
down_revision: Union[str, None] = 'e6f7a8b9c0d1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    existing_tables = get_existing_tables()
    if 'user_llm_key' in existing_tables:
        op.drop_table('user_llm_key')


def downgrade() -> None:
    # The table shape from c4d5e6f7a8b9 + e3f4a5b6c7d8 (refresh_token_encrypted):
    import sqlalchemy as sa

    existing_tables = get_existing_tables()
    if 'user_llm_key' not in existing_tables:
        op.create_table(
            'user_llm_key',
            sa.Column('user_id', sa.String(), nullable=False),
            sa.Column('provider', sa.String(), nullable=False, server_default='openrouter'),
            sa.Column('encrypted_key', sa.String(), nullable=False, server_default=''),
            sa.Column('key_last_four', sa.String(), nullable=False, server_default='****'),
            sa.Column('openai_base_url', sa.String(), nullable=True),
            sa.Column('is_valid', sa.Boolean(), nullable=False, server_default='true'),
            sa.Column('validated_at', sa.BigInteger(), nullable=True),
            sa.Column('created_at', sa.BigInteger(), nullable=False, server_default='0'),
            sa.Column('updated_at', sa.BigInteger(), nullable=False, server_default='0'),
            sa.Column('refresh_token_encrypted', sa.String(), nullable=True),
            sa.Column('migrated_at', sa.BigInteger(), nullable=True),
            sa.PrimaryKeyConstraint('user_id', 'provider', name='pk_user_llm_key'),
        )
