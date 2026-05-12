"""drop prompt and prompt_history tables

Revision ID: d5e6f7a8b9c0
Revises: 1b799c5827af
Create Date: 2026-04-10 12:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import open_webui.internal.db


# revision identifiers, used by Alembic.
revision: str = 'd5e6f7a8b9c0'
down_revision: Union[str, None] = '1b799c5827af'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_table('prompt_history')
    op.drop_table('prompt')


def downgrade() -> None:
    raise NotImplementedError('Downgrade not supported. Restore from backup or recreate tables manually.')
