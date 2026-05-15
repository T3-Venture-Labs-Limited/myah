"""Add container table

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-03-26 00:00:00.000000

Tracks per-user Hermes agent Docker containers managed by the Container Manager.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

from myah.migrations.util import get_existing_tables

revision: str = 'c3d4e5f6a7b8'
down_revision: Union[str, None] = 'b2c3d4e5f6a7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Guard: skip if table already exists (safe to re-run)
    existing_tables = set(get_existing_tables())
    if 'container' in existing_tables:
        return

    op.create_table(
        'container',
        sa.Column('id', sa.String(), primary_key=True, nullable=False),
        sa.Column('user_id', sa.String(), nullable=False),
        sa.Column('container_id', sa.String(), nullable=True),
        sa.Column('container_name', sa.String(), nullable=True),
        sa.Column('host_port', sa.Integer(), nullable=True),
        sa.Column('vite_port', sa.Integer(), nullable=True),
        sa.Column('status', sa.String(), nullable=False, server_default='creating'),
        sa.Column('created_at', sa.BigInteger(), nullable=False),
        sa.Column('last_active', sa.BigInteger(), nullable=False),
        sa.UniqueConstraint('user_id', name='uq_container_user_id'),
    )
    op.create_index('container_status_idx', 'container', ['status'])
    op.create_index('container_last_active_idx', 'container', ['last_active'])


def downgrade() -> None:
    op.drop_index('container_last_active_idx', table_name='container')
    op.drop_index('container_status_idx', table_name='container')
    op.drop_table('container')
