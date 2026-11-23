"""texts edited from the bot

Revision ID: a1c4e8f2d673
Revises: f3b6d2a9c541
Create Date: 2026-11-23 23:10:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a1c4e8f2d673'
down_revision: Union[str, None] = 'f3b6d2a9c541'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'text_overrides',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('language', sa.String(length=8), nullable=False),
        sa.Column('entity', sa.String(length=16), nullable=False),
        sa.Column('key', sa.String(length=64), nullable=False),
        sa.Column('value', sa.Text(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('language', 'entity', 'key', name='uq_text_overrides'),
    )


def downgrade() -> None:
    op.drop_table('text_overrides')
