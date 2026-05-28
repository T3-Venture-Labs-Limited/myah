"""Split default_model into (default_provider, default_model) pair.

Mirrors Hermes upstream's canonical {provider, model} shape at the column
level. The old column held three incompatible string formats (bare, slash,
composite) from different writers; after this migration, default_model
holds the bare model id and default_provider holds the provider id as
separate columns.

See `docs/superpowers/specs/2026-05-24-default-model-canonical-format-design.md`.

Revision ID: 6dd2215cc056
Revises: d5e3b1a9c742
Create Date: 2026-05-24
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

from myah.migrations._default_model_split_helpers import run_split_migration

revision: str = '6dd2215cc056'
down_revision: Union[str, Sequence[str], None] = 'd5e3b1a9c742'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = {c['name'] for c in inspector.get_columns('user')}
    if 'default_provider' not in existing:
        op.add_column('user', sa.Column('default_provider', sa.String(), nullable=True))
    run_split_migration(bind)


def downgrade() -> None:
    """Drop the new column. Existing default_model values remain in bare-id
    post-migration form — old code reads them as 'not found' and the user
    re-picks, which is a graceful failure mode."""
    with op.batch_alter_table('user') as batch:
        batch.drop_column('default_provider')
