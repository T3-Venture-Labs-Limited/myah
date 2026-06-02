"""merge file-system and cron-outbox heads after master refresh

Revision ID: b8e25ad8a9f1
Revises: 2d3eeacc5a25, 95c6c9748f4e
Create Date: 2026-05-28

"""
from typing import Sequence, Union


# revision identifiers, used by Alembic.
revision: str = 'b8e25ad8a9f1'
down_revision: Union[str, Sequence[str], None] = ('2d3eeacc5a25', '95c6c9748f4e')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
