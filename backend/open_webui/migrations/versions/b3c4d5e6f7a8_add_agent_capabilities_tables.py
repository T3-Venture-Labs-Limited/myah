"""Add agent capabilities cache tables

Revision ID: b3c4d5e6f7a8
Revises: f1e2d3c4b5a6
Create Date: 2026-03-29 00:00:00.000000
"""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from open_webui.migrations.util import get_existing_tables

revision: str = 'b3c4d5e6f7a8'
down_revision: Union[str, None] = 'c3d4e5f6a7b8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    existing = set(get_existing_tables())

    if 'agent_toolset' not in existing:
        op.create_table(
            'agent_toolset',
            sa.Column('id', sa.Text(), nullable=False, primary_key=True),
            sa.Column('user_id', sa.Text(), nullable=False),
            sa.Column('name', sa.Text(), nullable=False),
            sa.Column('label', sa.Text(), nullable=False),
            sa.Column('emoji', sa.Text(), nullable=True),
            sa.Column('enabled', sa.Boolean(), nullable=False, server_default='1'),
            sa.Column('tools_json', sa.Text(), nullable=False, server_default='[]'),
            sa.Column('last_synced_at', sa.BigInteger(), nullable=False, server_default='0'),
            sa.UniqueConstraint('user_id', 'name', name='uq_agent_toolset_user_name'),
        )
        op.create_index('agent_toolset_user_idx', 'agent_toolset', ['user_id'])

    if 'agent_skill' not in existing:
        op.create_table(
            'agent_skill',
            sa.Column('id', sa.Text(), nullable=False, primary_key=True),
            sa.Column('user_id', sa.Text(), nullable=False),
            sa.Column('name', sa.Text(), nullable=False),
            sa.Column('category', sa.Text(), nullable=False, server_default='general'),
            sa.Column('description', sa.Text(), nullable=False, server_default=''),
            sa.Column('source', sa.Text(), nullable=False, server_default='local'),
            sa.Column('trust', sa.Text(), nullable=False, server_default='local'),
            sa.Column('content', sa.Text(), nullable=False, server_default=''),
            sa.Column('last_synced_at', sa.BigInteger(), nullable=False, server_default='0'),
            sa.UniqueConstraint('user_id', 'name', name='uq_agent_skill_user_name'),
        )
        op.create_index('agent_skill_user_idx', 'agent_skill', ['user_id'])

    if 'agent_plugin' not in existing:
        op.create_table(
            'agent_plugin',
            sa.Column('id', sa.Text(), nullable=False, primary_key=True),
            sa.Column('user_id', sa.Text(), nullable=False),
            sa.Column('filename', sa.Text(), nullable=False),
            sa.Column('name', sa.Text(), nullable=False, server_default=''),
            sa.Column('description', sa.Text(), nullable=False, server_default=''),
            sa.Column('content', sa.Text(), nullable=False, server_default=''),
            sa.Column('last_synced_at', sa.BigInteger(), nullable=False, server_default='0'),
            sa.UniqueConstraint('user_id', 'filename', name='uq_agent_plugin_user_filename'),
        )
        op.create_index('agent_plugin_user_idx', 'agent_plugin', ['user_id'])

    if 'agent_mcp_server' not in existing:
        op.create_table(
            'agent_mcp_server',
            sa.Column('id', sa.Text(), nullable=False, primary_key=True),
            sa.Column('user_id', sa.Text(), nullable=False),
            sa.Column('name', sa.Text(), nullable=False),
            sa.Column('url', sa.Text(), nullable=True),
            sa.Column('command', sa.Text(), nullable=True),
            sa.Column('args_json', sa.Text(), nullable=False, server_default='[]'),
            sa.Column('status', sa.Text(), nullable=False, server_default='unknown'),
            sa.Column('last_synced_at', sa.BigInteger(), nullable=False, server_default='0'),
            sa.UniqueConstraint('user_id', 'name', name='uq_agent_mcp_user_name'),
        )
        op.create_index('agent_mcp_user_idx', 'agent_mcp_server', ['user_id'])


def downgrade() -> None:
    op.drop_table('agent_mcp_server')
    op.drop_table('agent_plugin')
    op.drop_table('agent_skill')
    op.drop_table('agent_toolset')
