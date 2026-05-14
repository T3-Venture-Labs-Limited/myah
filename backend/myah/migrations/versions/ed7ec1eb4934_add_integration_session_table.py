"""add integration_session table

Revision ID: ed7ec1eb4934
Revises: c975dfaa2c25
Create Date: 2026-05-06 14:20:15.063472

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'ed7ec1eb4934'
down_revision: Union[str, None] = 'c975dfaa2c25'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'integration_session',
        sa.Column('user_id', sa.String(), sa.ForeignKey('user.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('provider', sa.String(), primary_key=True),
        sa.Column('session_url', sa.Text(), nullable=False),
        sa.Column('session_headers_encrypted', sa.Text(), nullable=False),
        sa.Column('last_minted_at', sa.DateTime(), nullable=False),
        sa.Column('registered_in_agent', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table('integration_session')
