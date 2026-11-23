"""category cards and order, link buttons, review requests

Revision ID: b8d3f1e6a254
Revises: a1c4e8f2d673
Create Date: 2026-11-24 00:10:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b8d3f1e6a254'
down_revision: Union[str, None] = 'a1c4e8f2d673'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TYPE keyboardbutton ADD VALUE IF NOT EXISTS 'MY_PURCHASES'")
    op.add_column('categories', sa.Column('position', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('categories', sa.Column('descriptions', sa.JSON(), nullable=True))
    # Purchases made before this change are not asked for a review.
    op.add_column('buys', sa.Column('review_requests', sa.Integer(), nullable=False, server_default='2'))
    op.alter_column('buys', 'review_requests', server_default='0')
    op.add_column('buys', sa.Column('review_requested_at', sa.DateTime(timezone=True), nullable=True))
    op.create_table(
        'custom_buttons',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('text', sa.String(length=64), nullable=False),
        sa.Column('url', sa.String(length=512), nullable=False),
        sa.Column('position', sa.Integer(), nullable=False, server_default='0'),
        sa.PrimaryKeyConstraint('id'),
    )


def downgrade() -> None:
    op.drop_table('custom_buttons')
    op.drop_column('buys', 'review_requested_at')
    op.drop_column('buys', 'review_requests')
    op.drop_column('categories', 'descriptions')
    op.drop_column('categories', 'position')
