"""Add marketplace tables after cron deliveries.

Revision ID: a8d4f2c6b9e1
Revises: b8e25ad8a9f1
Create Date: 2026-05-29 10:25:00.000000

This consolidates the old marketplace branch migration chain onto the current
master Alembic head. Keeping the historical marketplace head revision ID lets
local/QA databases already stamped at a8d4f2c6b9e1 remain valid, while fresh
current-master databases can upgrade from 95c6c9748f4e and receive the required
marketplace tables.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision: str = 'a8d4f2c6b9e1'
down_revision: Union[str, None] = 'b8e25ad8a9f1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _existing_tables() -> set[str]:
    return set(inspect(op.get_bind()).get_table_names())


def _existing_indexes(table_name: str) -> set[str]:
    return {idx['name'] for idx in inspect(op.get_bind()).get_indexes(table_name)}


def upgrade() -> None:
    existing_tables = _existing_tables()

    if 'marketplace_installation' not in existing_tables:
        op.create_table(
            'marketplace_installation',
            sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column('user_id', sa.String(), nullable=False),
            sa.Column('skill_slug', sa.String(), nullable=False),
            sa.Column('skill_source', sa.String(), nullable=False),
            sa.Column('skill_identifier', sa.String(), nullable=False),
            sa.Column('catalog_ref', sa.String(), nullable=False),
            sa.Column('status', sa.String(), nullable=False),
            sa.Column('failure_reason', sa.Text(), nullable=True),
            sa.Column('install_log', sa.Text(), nullable=True),
            sa.Column(
                'installed_at',
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.UniqueConstraint(
                'user_id',
                'skill_slug',
                name='uq_marketplace_installation_user_slug',
            ),
        )
        op.create_index(
            'marketplace_installation_user_id_idx',
            'marketplace_installation',
            ['user_id'],
        )

    if 'marketplace_blocklist' not in existing_tables:
        op.create_table(
            'marketplace_blocklist',
            sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column('skill_slug', sa.String(), nullable=False),
            sa.Column('skill_identifier', sa.String(), nullable=False),
            sa.Column('source', sa.String(), nullable=False),
            sa.Column('reason', sa.String(), nullable=False),
            sa.Column('notes', sa.Text(), nullable=True),
            sa.Column(
                'blocked_at',
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.Column('blocked_by', sa.String(), nullable=False, server_default='system'),
            sa.UniqueConstraint(
                'skill_slug',
                'source',
                name='uq_marketplace_blocklist_slug_source',
            ),
        )
        op.create_index(
            'marketplace_blocklist_skill_slug_idx',
            'marketplace_blocklist',
            ['skill_slug'],
        )


def downgrade() -> None:
    existing_tables = _existing_tables()

    if 'marketplace_blocklist' in existing_tables:
        if 'marketplace_blocklist_skill_slug_idx' in _existing_indexes(
            'marketplace_blocklist'
        ):
            op.drop_index(
                'marketplace_blocklist_skill_slug_idx',
                table_name='marketplace_blocklist',
            )
        op.drop_table('marketplace_blocklist')

    if 'marketplace_installation' in existing_tables:
        if 'marketplace_installation_user_id_idx' in _existing_indexes(
            'marketplace_installation'
        ):
            op.drop_index(
                'marketplace_installation_user_id_idx',
                table_name='marketplace_installation',
            )
        op.drop_table('marketplace_installation')
