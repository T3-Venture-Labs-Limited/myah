"""Add default_model column to user table

Revision ID: fbc00b73ec45
Revises: a96c5bff3976
Create Date: 2026-04-17 00:00:00.000000

Adds a nullable `default_model` column on the `user` table to store the
per-user default chat model (T3-932). Falls back to admin DEFAULT_MODELS
or the first available provider model when unset.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'fbc00b73ec45'
down_revision: Union[str, None] = 'a96c5bff3976'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Skip if a prior run already added the column (idempotent for local dev
    # where the DB might be ahead of the migration head)
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {col['name'] for col in inspector.get_columns('user')}
    if 'default_model' not in columns:
        op.add_column('user', sa.Column('default_model', sa.String(), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {col['name'] for col in inspector.get_columns('user')}
    if 'default_model' in columns:
        op.drop_column('user', 'default_model')
