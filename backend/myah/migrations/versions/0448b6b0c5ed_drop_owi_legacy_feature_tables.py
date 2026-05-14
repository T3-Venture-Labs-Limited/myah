"""drop OWI legacy feature tables

Revision ID: 0448b6b0c5ed
Revises: f7a8b9c0d1e2
Create Date: 2026-04-20 00:00:00.000000

Drops 12 tables that belonged to OWI features removed in the platform
cleanup (T3-993): skill, message, message_reaction, channel, channel_member,
channel_file, channel_webhook, tool, function, memory, document, chatidtag.

Also removes access_grant rows scoped to the deleted 'skill' resource type.

This migration is forward-only — downgrade() raises NotImplementedError.
Before applying to any database that has never run this codebase before,
ensure these tables do not exist (the existence check makes it idempotent).
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = '0448b6b0c5ed'
down_revision: Union[str, None] = 'f7a8b9c0d1e2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Tables to drop — all are orphaned OWI feature tables with no surviving
# model files or router references in the Myah codebase.
TABLES_TO_DROP = [
    'skill',
    'message',
    'message_reaction',
    'channel',
    'channel_member',
    'channel_file',
    'channel_webhook',
    'tool',
    'function',
    'memory',
    'document',
    'chatidtag',
]


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = set(inspector.get_table_names())

    # Row-level cleanup: remove access grants for the deleted skills feature.
    # Do this before dropping the skill table so FK constraints (if any) are
    # satisfied.
    if 'access_grant' in existing:
        op.execute("DELETE FROM access_grant WHERE resource_type = 'skill'")

    for table in TABLES_TO_DROP:
        if table in existing:
            op.drop_table(table)


def downgrade() -> None:
    raise NotImplementedError(
        'Phase 6 schema-collapse is forward-only. '
        'To roll back, restore from a pre-migration database snapshot.'
    )
