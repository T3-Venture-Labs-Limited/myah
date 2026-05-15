"""Add vnc_port column to container table

Revision ID: a7b8c9d0e1f2
Revises: d5e6f7a8b9c0
Create Date: 2026-04-12 00:00:00.000000

Adds a nullable vnc_port integer column to the container table so the
platform knows which host port maps to the container's VNC server (5900).
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from myah.migrations.util import get_existing_tables

revision: str = 'a7b8c9d0e1f2'
down_revision: Union[str, None] = 'd5e6f7a8b9c0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    existing = get_existing_tables()
    if 'container' in existing:
        conn = op.get_bind()
        inspector = sa.inspect(conn)
        columns = [c['name'] for c in inspector.get_columns('container')]
        if 'vnc_port' not in columns:
            op.add_column('container', sa.Column('vnc_port', sa.Integer(), nullable=True))


def downgrade() -> None:
    existing = get_existing_tables()
    if 'container' in existing:
        op.drop_column('container', 'vnc_port')
