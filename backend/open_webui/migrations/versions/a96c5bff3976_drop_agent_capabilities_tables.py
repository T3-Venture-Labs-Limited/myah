"""drop agent capabilities cache tables

Phase 5: Management data is now fetched fresh from the Myah adapter's
in-process endpoints. The 4 caching tables are no longer needed.

Revision ID: a96c5bff3976
Revises: a7b8c9d0e1f2
Create Date: 2026-04-12 18:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from open_webui.migrations.util import get_existing_tables


# revision identifiers, used by Alembic.
revision: str = 'a96c5bff3976'
down_revision: Union[str, None] = 'a7b8c9d0e1f2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    existing = get_existing_tables()
    for table in ('agent_mcp_server', 'agent_plugin', 'agent_skill', 'agent_toolset'):
        if table in existing:
            op.drop_table(table)


def downgrade() -> None:
    raise NotImplementedError('Downgrade not supported. Restore from backup or recreate tables manually.')
