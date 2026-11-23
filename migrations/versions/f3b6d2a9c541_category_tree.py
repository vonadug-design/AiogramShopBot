"""category tree: categories.parent_id, names unique per level only

Revision ID: f3b6d2a9c541
Revises: e7a2c9d4b318
Create Date: 2026-11-23 22:40:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'f3b6d2a9c541'
down_revision: Union[str, None] = 'e7a2c9d4b318'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('categories') as batch_op:
        batch_op.add_column(sa.Column('parent_id', sa.Integer(), nullable=True))
        batch_op.create_foreign_key('fk_categories_parent_id', 'categories', ['parent_id'], ['id'],
                                    ondelete='SET NULL')
        batch_op.create_index('ix_categories_parent_id', ['parent_id'])
        batch_op.drop_index('ix_categories_name')
        batch_op.create_index('ix_categories_name', ['name'], unique=False)


def downgrade() -> None:
    with op.batch_alter_table('categories') as batch_op:
        batch_op.drop_index('ix_categories_name')
        batch_op.create_index('ix_categories_name', ['name'], unique=True)
        batch_op.drop_index('ix_categories_parent_id')
        batch_op.drop_constraint('fk_categories_parent_id', type_='foreignkey')
        batch_op.drop_column('parent_id')
