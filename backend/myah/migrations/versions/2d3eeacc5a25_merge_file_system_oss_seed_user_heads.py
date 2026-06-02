"""merge file-system + oss seed user heads

Revision ID: 2d3eeacc5a25
Revises: 1bd50ef74b58, d5e3b1a9c742
Create Date: 2026-05-25 11:18:50.550093

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import myah.internal.db


# revision identifiers, used by Alembic.
revision: str = '2d3eeacc5a25'
down_revision: Union[str, None] = ('1bd50ef74b58', 'd5e3b1a9c742')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
