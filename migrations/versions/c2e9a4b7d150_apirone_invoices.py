"""apirone invoices

Revision ID: c2e9a4b7d150
Revises: b4d81c6e2a07
Create Date: 2026-11-23 21:20:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c2e9a4b7d150'
down_revision: Union[str, None] = 'b4d81c6e2a07'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'apirone_invoices',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('invoice_id', sa.String(), nullable=False),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('currency', sa.String(), nullable=False),
        sa.Column('fiat_amount', sa.Float(), nullable=False),
        sa.Column('status', sa.String(), nullable=False),
        sa.Column('credited', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index('ix_apirone_invoices_invoice_id', 'apirone_invoices', ['invoice_id'], unique=True)


def downgrade() -> None:
    op.drop_index('ix_apirone_invoices_invoice_id', table_name='apirone_invoices')
    op.drop_table('apirone_invoices')
