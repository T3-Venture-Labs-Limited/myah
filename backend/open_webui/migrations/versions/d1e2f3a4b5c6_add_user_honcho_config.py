"""Add user_honcho_config table

Revision ID: d1e2f3a4b5c6
Revises: 53bce1ae0c21, a1b2c3d4e5f6
Create Date: 2026-03-30 00:00:00.000000

Merges the agent-capabilities+vite-port branch (53bce1ae0c21) with the
skill-table branch (a1b2c3d4e5f6) and adds the user_honcho_config table
for per-user Honcho workspace isolation.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from open_webui.migrations.util import get_existing_tables

# revision identifiers, used by Alembic.
revision: str = 'd1e2f3a4b5c6'
down_revision: Union[str, Sequence[str], None] = ('53bce1ae0c21', 'a1b2c3d4e5f6')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    existing = get_existing_tables()
    if 'user_honcho_config' not in existing:
        op.create_table(
            'user_honcho_config',
            sa.Column('user_id', sa.String(), nullable=False, primary_key=True),
            sa.Column('workspace_id', sa.String(), nullable=False, server_default=''),
            sa.Column('api_key', sa.String(), nullable=False, server_default=''),
            sa.Column('peer_name', sa.String(), nullable=False, server_default=''),
            sa.Column('ai_peer_name', sa.String(), nullable=False, server_default='myah'),
            sa.Column('provisioned', sa.Boolean(), nullable=False, server_default=sa.text('false')),
            sa.Column('created_at', sa.BigInteger(), nullable=False, server_default='0'),
            sa.Column('updated_at', sa.BigInteger(), nullable=False, server_default='0'),
        )


def downgrade() -> None:
    op.drop_table('user_honcho_config')
