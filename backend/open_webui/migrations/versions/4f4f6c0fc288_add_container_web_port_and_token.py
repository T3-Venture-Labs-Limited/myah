"""Add web_port and web_session_token columns to container table

Revision ID: 4f4f6c0fc288
Revises: a1b2c3d4e5f7
Create Date: 2026-04-25 00:00:00.000000

Workstream A Phase 0 — Hermes-Native Admin pivot.

Each per-user agent container now runs a `hermes dashboard` server on
loopback inside the container, exposed on a dedicated host port. The
platform backend authenticates against it with a per-container session
token shared via the HERMES_WEB_SESSION_TOKEN env var.

This migration adds two nullable columns to the `container` table:

* ``web_port`` — host port mapped to container port 9119
  (`hermes dashboard --port 9119`). Allocated on container spawn alongside
  ``host_port``/``vite_port``/``vnc_port``.

* ``web_session_token`` — opaque bearer token (32 bytes of url-safe random)
  the platform sends in the ``Authorization: Bearer <token>`` header to
  authenticate plugin API calls. Lives in the DB so the platform can read
  it without `docker exec`-ing into the container.

Both columns are nullable to allow rolling deploy: existing containers
created before this migration will have NULL values until they're
recreated by the next ``restart_container`` cycle.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from open_webui.migrations.util import get_existing_tables

revision: str = '4f4f6c0fc288'
down_revision: Union[str, None] = 'a1b2c3d4e5f7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    existing = get_existing_tables()
    if 'container' in existing:
        conn = op.get_bind()
        inspector = sa.inspect(conn)
        columns = [c['name'] for c in inspector.get_columns('container')]
        if 'web_port' not in columns:
            op.add_column('container', sa.Column('web_port', sa.Integer(), nullable=True))
        if 'web_session_token' not in columns:
            op.add_column('container', sa.Column('web_session_token', sa.String(length=255), nullable=True))


def downgrade() -> None:
    existing = get_existing_tables()
    if 'container' in existing:
        conn = op.get_bind()
        inspector = sa.inspect(conn)
        columns = [c['name'] for c in inspector.get_columns('container')]
        if 'web_session_token' in columns:
            op.drop_column('container', 'web_session_token')
        if 'web_port' in columns:
            op.drop_column('container', 'web_port')
