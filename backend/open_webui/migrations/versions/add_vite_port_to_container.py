"""Add vite_port column to container table

Revision ID: 4e032f658791
Revises: f1e2d3c4b5a6
Create Date: 2026-03-29 00:00:00.000000

Adds a nullable vite_port integer column to the container table so the
platform knows which host port maps to the container's Vite dev server (5174).
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from open_webui.migrations.util import get_existing_tables

revision: str = '4e032f658791'
down_revision: Union[str, None] = 'f1e2d3c4b5a6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    existing = get_existing_tables()
    if 'container' in existing:
        conn = op.get_bind()
        inspector = sa.inspect(conn)
        columns = [c['name'] for c in inspector.get_columns('container')]
        if 'vite_port' not in columns:
            op.add_column('container', sa.Column('vite_port', sa.Integer(), nullable=True))


def downgrade() -> None:
    existing = get_existing_tables()
    if 'container' in existing:
        op.drop_column('container', 'vite_port')
