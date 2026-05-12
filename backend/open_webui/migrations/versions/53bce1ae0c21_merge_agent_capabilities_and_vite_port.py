"""merge_agent_capabilities_and_vite_port

Revision ID: 53bce1ae0c21
Revises: b3c4d5e6f7a8, 4e032f658791
Create Date: 2026-03-29 22:20:41.332744

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import open_webui.internal.db


# revision identifiers, used by Alembic.
revision: str = '53bce1ae0c21'
down_revision: Union[str, None] = ('b3c4d5e6f7a8', '4e032f658791')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
