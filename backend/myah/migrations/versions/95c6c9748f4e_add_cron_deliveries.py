"""add cron_deliveries

Revision ID: 95c6c9748f4e
Revises: 6dd2215cc056
Create Date: 2026-05-27 17:13:23.231386

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = '95c6c9748f4e'
down_revision: Union[str, None] = '6dd2215cc056'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'cron_deliveries',
        sa.Column('id', sa.Text(), primary_key=True),
        sa.Column('user_id', sa.Text(), nullable=False),
        sa.Column('job_id', sa.Text(), nullable=False),
        sa.Column('chat_id', sa.Text(), nullable=False),
        sa.Column('ran_at_iso', sa.Text(), nullable=False),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('metadata_json', sa.Text(), nullable=True),
        sa.Column(
            'delivery_status',
            sa.Text(),
            nullable=False,
            server_default='pending',
        ),
        sa.Column(
            'retry_count',
            sa.Integer(),
            nullable=False,
            server_default='0',
        ),
        sa.Column('next_retry_at', sa.Integer(), nullable=True),
        sa.Column('last_error', sa.Text(), nullable=True),
        sa.Column('leased_at', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.Integer(), nullable=False),
        sa.Column('delivered_at', sa.Integer(), nullable=True),
        sa.Column('legacy_delivered_at', sa.Integer(), nullable=True),
        sa.UniqueConstraint('job_id', 'ran_at_iso', name='uq_cron_deliveries_job_ran'),
    )
    op.create_index(
        'idx_cron_deliveries_status_retry',
        'cron_deliveries',
        ['delivery_status', 'next_retry_at'],
    )
    op.create_index(
        'idx_cron_deliveries_user_created',
        'cron_deliveries',
        ['user_id', 'created_at'],
    )
    # Partial index for the parity-gap query (ADR-7). Per plan-review H-2:
    # the query is `WHERE created_at IN [range] AND legacy_delivered_at IS NULL`.
    # A partial index on (created_at) WHERE legacy_delivered_at IS NULL is
    # the right shape — smaller (skips delivered rows) and the planner can
    # use it for the range scan. SQLite supports partial indices since 3.8.0.
    op.create_index(
        'idx_cron_deliveries_parity_gap',
        'cron_deliveries',
        ['created_at'],
        sqlite_where=sa.text('legacy_delivered_at IS NULL'),
        postgresql_where=sa.text('legacy_delivered_at IS NULL'),
    )


def downgrade() -> None:
    op.drop_index('idx_cron_deliveries_parity_gap', table_name='cron_deliveries')
    op.drop_index('idx_cron_deliveries_user_created', table_name='cron_deliveries')
    op.drop_index('idx_cron_deliveries_status_retry', table_name='cron_deliveries')
    op.drop_table('cron_deliveries')
