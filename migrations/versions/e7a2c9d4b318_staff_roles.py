"""staff roles (admin / moderator)

Revision ID: e7a2c9d4b318
Revises: d5f1a8c3e962
Create Date: 2026-11-23 22:10:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'e7a2c9d4b318'
down_revision: Union[str, None] = 'd5f1a8c3e962'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'staff_members',
        sa.Column('telegram_id', sa.BigInteger(), autoincrement=False, nullable=False),
        sa.Column('role', sa.Enum('OWNER', 'ADMIN', 'MODERATOR', name='staffrole'), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.PrimaryKeyConstraint('telegram_id'),
    )


def downgrade() -> None:
    op.drop_table('staff_members')
    sa.Enum(name='staffrole').drop(op.get_bind(), checkfirst=True)
