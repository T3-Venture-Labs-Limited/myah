"""Merge default_model and refresh_token_encrypted branches

Revision ID: f4a5b6c7d8e9
Revises: fbc00b73ec45, e3f4a5b6c7d8
Create Date: 2026-04-19 12:01:00.000000

Merges the fbc00b73ec45 (add_user_default_model) branch with the
e3f4a5b6c7d8 (add_refresh_token_encrypted) branch into a single head.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'f4a5b6c7d8e9'
down_revision: Union[str, Sequence[str], None] = ('fbc00b73ec45', 'e3f4a5b6c7d8')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
