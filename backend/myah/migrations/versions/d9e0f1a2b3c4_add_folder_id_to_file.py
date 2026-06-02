"""Add folder_id to file

Revision ID: d9e0f1a2b3c4
Revises: c975dfaa2c25
Create Date: 2026-05-05 00:00:00.000000

Every file may belong to a folder. A folder may contain any number
of files; when a folder is deleted its files remain, orphaned but
accessible, until moved to another folder or the root.

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'd9e0f1a2b3c4'
down_revision: Union[str, None] = 'c975dfaa2c25'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('file', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                'folder_id',
                sa.Text(),
                sa.ForeignKey('folder.id', name='fk_file_folder_id', ondelete='SET NULL'),
                nullable=True,
            )
        )
        batch_op.create_index('ix_file_folder_id', ['folder_id'], unique=False)


def downgrade() -> None:
    with op.batch_alter_table('file', schema=None) as batch_op:
        batch_op.drop_index('ix_file_folder_id')
        batch_op.drop_constraint('fk_file_folder_id', type_='foreignkey')
        batch_op.drop_column('folder_id')
