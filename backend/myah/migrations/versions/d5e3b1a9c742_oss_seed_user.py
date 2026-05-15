"""oss_seed_user — seed the single anonymous admin user for OSS deployments

Revision ID: d5e3b1a9c742
Revises: c91c92b45d31
Create Date: 2026-05-14 14:00:00.000000

In OSS mode (``MYAH_DEPLOYMENT_MODE=oss``) the platform serves a single
user. This migration inserts one row into the ``user`` table on first
boot so the front-end has a session to attach chats / files / settings
to. The user is role=admin so any code path that gates on the admin
role still works (the OSS variant has no other roles).

Idempotency invariants:
1. Runs only when ``MYAH_DEPLOYMENT_MODE`` (case-insensitive,
   whitespace-stripped) equals ``oss``.
2. Inserts NOTHING if the ``user`` table already has any row — single-
   user semantics treats any prior user as "already initialised".
3. Safe to re-run via ``alembic upgrade head`` arbitrary times.

Hosted mode (anything except ``oss``, including unset) is a no-op:
hosted user creation goes through the normal ``signin`` / ``signup``
flow in ``platform-hosted/backend/myah/routers/auths.py``.

Refs spec §6 "DB migration", plan Phase 1B Task B.6.
"""

import os
import time
import uuid
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'd5e3b1a9c742'
down_revision: Union[str, None] = 'c91c92b45d31'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _is_oss_mode() -> bool:
    """Match utils.hermes_web.is_oss_mode() exactly — case+whitespace normalised."""
    return os.environ.get('MYAH_DEPLOYMENT_MODE', '').strip().lower() == 'oss'


# Deterministic seed UUID — same value across every fresh OSS install. Lets
# tests / docs reference "the OSS admin" by a stable id. Generated once;
# not derived from anything secret.
SEED_USER_ID = '00000000-0000-0000-0000-000000000001'


def upgrade() -> None:
    if not _is_oss_mode():
        # Hosted deployment — signup flow handles user creation, skip.
        return

    bind = op.get_bind()

    # Idempotent: if the user table already has any row (re-running the
    # migration, or developer pre-seeded the DB), do nothing.
    existing = bind.execute(sa.text('SELECT id FROM user LIMIT 1')).first()
    if existing is not None:
        return

    now = int(time.time())
    bind.execute(
        sa.text(
            'INSERT INTO user '
            '(id, email, name, role, profile_image_url, created_at, updated_at, last_active_at) '
            'VALUES '
            '(:id, :email, :name, :role, :profile_image_url, :now, :now, :now)'
        ),
        {
            'id': SEED_USER_ID,
            'email': 'user@localhost',
            'name': 'Myah User',
            'role': 'admin',
            'profile_image_url': '/user.png',
            'now': now,
        },
    )


def downgrade() -> None:
    if not _is_oss_mode():
        return

    bind = op.get_bind()
    bind.execute(
        sa.text('DELETE FROM user WHERE id = :id AND email = :email'),
        {'id': SEED_USER_ID, 'email': 'user@localhost'},
    )
