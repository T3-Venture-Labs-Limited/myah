"""merge file-system + integrations heads

Revision ID: 1bd50ef74b58
Revises: d9e0f1a2b3c4, ed7ec1eb4934
Create Date: 2026-05-08 15:12:47.343718

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import myah.internal.db


# revision identifiers, used by Alembic.
revision: str = '1bd50ef74b58'
down_revision: Union[str, None] = ('d9e0f1a2b3c4', 'ed7ec1eb4934')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
