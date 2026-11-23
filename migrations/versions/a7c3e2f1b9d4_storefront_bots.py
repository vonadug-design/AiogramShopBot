"""storefront bot pool: encrypted tokens and customer pinning

Revision ID: a7c3e2f1b9d4
Revises: 91c3856a8aa0
Create Date: 2026-11-23 20:40:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a7c3e2f1b9d4'
down_revision: Union[str, None] = '91c3856a8aa0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

storefront_status = sa.Enum('ACTIVE', 'BANNED', 'DISABLED', name='storefrontstatus')


def upgrade() -> None:
    op.create_table(
        'storefront_bots',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('telegram_bot_id', sa.BigInteger(), nullable=False),
        sa.Column('username', sa.String(), nullable=False),
        sa.Column('token_encrypted', sa.String(), nullable=False),
        sa.Column('token_hash', sa.String(length=64), nullable=False),
        sa.Column('status', storefront_status, nullable=False),
        sa.Column('max_users', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('banned_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index('ix_storefront_bots_telegram_bot_id', 'storefront_bots', ['telegram_bot_id'], unique=True)
    op.create_index('ix_storefront_bots_token_hash', 'storefront_bots', ['token_hash'], unique=True)
    op.add_column('users', sa.Column('storefront_bot_id', sa.Integer(), nullable=True))
    op.create_foreign_key('fk_users_storefront_bot_id', 'users', 'storefront_bots',
                          ['storefront_bot_id'], ['id'], ondelete='SET NULL')
    op.create_index('ix_users_storefront_bot_id', 'users', ['storefront_bot_id'])


def downgrade() -> None:
    op.drop_index('ix_users_storefront_bot_id', table_name='users')
    op.drop_constraint('fk_users_storefront_bot_id', 'users', type_='foreignkey')
    op.drop_column('users', 'storefront_bot_id')
    op.drop_index('ix_storefront_bots_token_hash', table_name='storefront_bots')
    op.drop_index('ix_storefront_bots_telegram_bot_id', table_name='storefront_bots')
    op.drop_table('storefront_bots')
    storefront_status.drop(op.get_bind(), checkfirst=True)
