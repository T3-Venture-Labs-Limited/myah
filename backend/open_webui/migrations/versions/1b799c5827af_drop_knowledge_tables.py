"""drop knowledge tables

Revision ID: 1b799c5827af
Revises: e2f3a4b5c6d7
Create Date: 2026-04-09 22:59:36.969810

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import open_webui.internal.db


# revision identifiers, used by Alembic.
revision: str = '1b799c5827af'
down_revision: Union[str, None] = 'c4d5e6f7a8b9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_table('knowledge_file')
    op.drop_table('knowledge')


def downgrade() -> None:
    raise NotImplementedError('Downgrade not supported. Restore from backup or recreate tables manually.')
