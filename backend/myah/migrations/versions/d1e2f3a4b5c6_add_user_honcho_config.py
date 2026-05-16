"""Add user_honcho_config table

Revision ID: d1e2f3a4b5c6
Revises: 53bce1ae0c21, a1b2c3d4e5f6
Create Date: 2026-03-30 00:00:00.000000

Merges the agent-capabilities+vite-port branch (53bce1ae0c21) with the
skill-table branch (a1b2c3d4e5f6) and adds the user_honcho_config table
for per-user Honcho workspace isolation.

The Honcho integration is **hosted-only** (Phase D anti-SaaS surgical
removal). OSS users never read or write this table — Honcho memory is
gated by ``utils/hermes_web.is_oss_mode()`` in
``models/user_honcho_config.py`` and ``services/honcho.py`` only
exists in hosted's overlay. Creating the table in OSS DBs ships a dead
structure that confuses self-host operators who poke their SQLite file
and ask "why is there a honcho table I never enabled?". Guard the
``upgrade()`` body so OSS installs skip it.
"""

import os
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from myah.migrations.util import get_existing_tables

# revision identifiers, used by Alembic.
revision: str = 'd1e2f3a4b5c6'
down_revision: Union[str, Sequence[str], None] = ('53bce1ae0c21', 'a1b2c3d4e5f6')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _is_oss_mode() -> bool:
    """Direct-env check — mirrors ``utils/hermes_web.is_oss_mode`` but
    doesn't import myah modules at migration time (alembic runs in a
    context where some imports may not yet be available)."""
    return os.environ.get('MYAH_DEPLOYMENT_MODE', '').strip().lower() == 'oss'


def upgrade() -> None:
    if _is_oss_mode():
        # OSS doesn't ship the honcho service module; the table would be
        # write-never. Skip cleanly so self-host SQLite stays minimal.
        return
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
    if _is_oss_mode():
        # Symmetrical with upgrade() — OSS never created the table.
        return
    op.drop_table('user_honcho_config')
