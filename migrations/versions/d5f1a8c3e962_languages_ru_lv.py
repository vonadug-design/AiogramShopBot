"""languages: en, ru, lv

Revision ID: d5f1a8c3e962
Revises: c2e9a4b7d150
Create Date: 2026-11-23 21:50:00.000000

"""
from typing import Sequence, Union

from alembic import op


revision: str = 'd5f1a8c3e962'
down_revision: Union[str, None] = 'c2e9a4b7d150'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == 'postgresql':
        with op.get_context().autocommit_block():
            op.execute("ALTER TYPE language ADD VALUE IF NOT EXISTS 'RU'")
            op.execute("ALTER TYPE language ADD VALUE IF NOT EXISTS 'LV'")
    # Languages that were removed fall back to English.
    op.execute("UPDATE users SET language = 'EN' WHERE language NOT IN ('EN', 'RU', 'LV')")


def downgrade() -> None:
    op.execute("UPDATE users SET language = 'EN' WHERE language IN ('RU', 'LV')")
