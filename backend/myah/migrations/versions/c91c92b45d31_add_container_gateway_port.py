"""Add gateway_port column to container table.

Revision ID: c91c92b45d31
Revises: ed7ec1eb4934
Create Date: 2026-05-07 00:00:00.000000

Tier 2A port-coordination follow-up.

After Tier 2A's standalone-runner refactor, the agent's Myah adapter
mounts `/myah/v1/*` and `/myah/health` on a separate aiohttp app bound
to MYAH_GATEWAY_PORT (default 8643), instead of sharing the API
server's 8642. The platform's per-user container spawner needs to
publish that port too — this migration adds the column to track which
host port is mapped to 8643.

Nullable: existing rows from before this migration keep gateway_port=NULL,
and readers (`_resolve_gateway_port`, `aux_call`) fall back to
`host_port` so containers running pre-Tier-2A agent code keep working
until they're respawned.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from myah.migrations.util import get_existing_tables

revision: str = 'c91c92b45d31'
down_revision: Union[str, None] = 'ed7ec1eb4934'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    existing = get_existing_tables()
    if 'container' in existing:
        conn = op.get_bind()
        inspector = sa.inspect(conn)
        columns = [c['name'] for c in inspector.get_columns('container')]
        if 'gateway_port' not in columns:
            op.add_column('container', sa.Column('gateway_port', sa.Integer(), nullable=True))


def downgrade() -> None:
    existing = get_existing_tables()
    if 'container' in existing:
        conn = op.get_bind()
        inspector = sa.inspect(conn)
        columns = [c['name'] for c in inspector.get_columns('container')]
        if 'gateway_port' in columns:
            op.drop_column('container', 'gateway_port')
