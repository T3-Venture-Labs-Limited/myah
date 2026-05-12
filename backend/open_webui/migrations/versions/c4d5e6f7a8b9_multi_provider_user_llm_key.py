"""Multi-provider UserLLMKey — composite primary key (user_id, provider)

Revision ID: c4d5e6f7a8b9
Revises: a96c5bff3976
Create Date: 2026-04-16 00:00:00.000000

Replaces the single user_id primary key on user_llm_key with a composite
(user_id, provider) key so each user can hold one key per provider.
Existing rows are preserved as-is; their current provider value becomes
part of the new composite key.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from open_webui.migrations.util import get_existing_tables

revision: str = 'c4d5e6f7a8b9'
down_revision: Union[str, None] = 'e2f3a4b5c6d7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    existing = get_existing_tables()
    if 'user_llm_key' not in existing:
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
            sa.PrimaryKeyConstraint('user_id', 'provider', name='pk_user_llm_key'),
        )
        return

    conn = op.get_bind()

    op.rename_table('user_llm_key', 'user_llm_key_old')

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
        sa.PrimaryKeyConstraint('user_id', 'provider', name='pk_user_llm_key'),
    )

    conn.execute(
        sa.text(
            'INSERT INTO user_llm_key '
            '(user_id, provider, encrypted_key, key_last_four, openai_base_url, '
            'is_valid, validated_at, created_at, updated_at) '
            'SELECT user_id, provider, encrypted_key, key_last_four, openai_base_url, '
            'is_valid, validated_at, created_at, updated_at '
            'FROM user_llm_key_old'
        )
    )

    op.drop_table('user_llm_key_old')


def downgrade() -> None:
    conn = op.get_bind()

    op.rename_table('user_llm_key', 'user_llm_key_v2')

    op.create_table(
        'user_llm_key',
        sa.Column('user_id', sa.String(), nullable=False, primary_key=True),
        sa.Column('provider', sa.String(), nullable=False, server_default='openrouter'),
        sa.Column('encrypted_key', sa.String(), nullable=False, server_default=''),
        sa.Column('key_last_four', sa.String(), nullable=False, server_default='****'),
        sa.Column('openai_base_url', sa.String(), nullable=True),
        sa.Column('is_valid', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('validated_at', sa.BigInteger(), nullable=True),
        sa.Column('created_at', sa.BigInteger(), nullable=False, server_default='0'),
        sa.Column('updated_at', sa.BigInteger(), nullable=False, server_default='0'),
    )

    conn.execute(
        sa.text(
            'INSERT INTO user_llm_key '
            '(user_id, provider, encrypted_key, key_last_four, openai_base_url, '
            'is_valid, validated_at, created_at, updated_at) '
            'SELECT t.user_id, t.provider, t.encrypted_key, t.key_last_four, t.openai_base_url, '
            't.is_valid, t.validated_at, t.created_at, t.updated_at '
            'FROM user_llm_key_v2 t '
            'WHERE t.rowid IN (SELECT MIN(rowid) FROM user_llm_key_v2 GROUP BY user_id)'
        )
    )

    op.drop_table('user_llm_key_v2')
