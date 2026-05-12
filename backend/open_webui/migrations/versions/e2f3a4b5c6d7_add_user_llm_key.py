"""Add user_llm_key table

Revision ID: e2f3a4b5c6d7
Revises: 53bce1ae0c21
Create Date: 2026-03-31 00:00:00.000000

Adds per-user LLM API key storage with encryption at rest.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from open_webui.migrations.util import get_existing_tables

# revision identifiers, used by Alembic.
revision: str = 'e2f3a4b5c6d7'
down_revision: Union[str, Sequence[str], None] = 'd1e2f3a4b5c6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    existing = get_existing_tables()
    if 'user_llm_key' not in existing:
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


def downgrade() -> None:
    op.drop_table('user_llm_key')
