"""label source

Revision ID: 83083cb708ae
Revises: 8c561a25a69a
Create Date: 2026-11-14 23:56:39.252838

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '83083cb708ae'
down_revision: Union[str, Sequence[str], None] = '8c561a25a69a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """file_labels gets `source` as part of its primary key: rebuilt, existing rows kept with source ''."""
    op.execute("CREATE TABLE file_labels_old AS SELECT file_id, kind, value FROM file_labels")  # a copy: renaming would keep the old primary key's name
    op.drop_index('file_labels_kv', table_name='file_labels')
    op.drop_table('file_labels')
    op.create_table('file_labels',
    sa.Column('file_id', sa.Integer(), nullable=False),
    sa.Column('source', sa.String(), nullable=False),
    sa.Column('kind', sa.String(), nullable=False),
    sa.Column('value', sa.String(), nullable=False),
    sa.PrimaryKeyConstraint('file_id', 'source', 'kind', 'value', name=op.f('pk_file_labels'))
    )
    op.execute("INSERT INTO file_labels(file_id, source, kind, value) SELECT file_id, '', kind, value FROM file_labels_old")
    op.drop_table('file_labels_old')
    with op.batch_alter_table('file_labels', schema=None) as batch_op:
        batch_op.create_index('file_labels_kv', ['kind', 'value'], unique=False)


def downgrade() -> None:
    """Back to (file_id, kind, value): the source is dropped, rows that differ only by it collapse."""
    op.execute("CREATE TABLE file_labels_new AS SELECT file_id, kind, value FROM file_labels")
    op.drop_index('file_labels_kv', table_name='file_labels')
    op.drop_table('file_labels')
    op.create_table('file_labels',
    sa.Column('file_id', sa.Integer(), nullable=False),
    sa.Column('kind', sa.String(), nullable=False),
    sa.Column('value', sa.String(), nullable=False),
    sa.PrimaryKeyConstraint('file_id', 'kind', 'value', name=op.f('pk_file_labels'))
    )
    op.execute("INSERT INTO file_labels(file_id, kind, value) SELECT DISTINCT file_id, kind, value FROM file_labels_new")
    op.drop_table('file_labels_new')
    with op.batch_alter_table('file_labels', schema=None) as batch_op:
        batch_op.create_index('file_labels_kv', ['kind', 'value'], unique=False)
