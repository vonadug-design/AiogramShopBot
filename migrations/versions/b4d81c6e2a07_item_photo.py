"""individual photo for each stock unit

Revision ID: b4d81c6e2a07
Revises: a7c3e2f1b9d4
Create Date: 2026-11-23 21:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b4d81c6e2a07'
down_revision: Union[str, None] = 'a7c3e2f1b9d4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('items', sa.Column('photo_id', sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column('items', 'photo_id')
