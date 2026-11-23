from datetime import datetime

from pydantic import BaseModel
from sqladmin import ModelView
from sqlalchemy import Column, Integer, String, BigInteger, DateTime, Enum, func

from enums.storefront_status import StorefrontStatus
from models.base import Base


class StorefrontBot(Base):
    """A child (storefront) bot. Customers are spread across storefronts so a ban hits only part of them."""
    __tablename__ = 'storefront_bots'

    id = Column(Integer, primary_key=True)
    telegram_bot_id = Column(BigInteger, nullable=False, unique=True, index=True)
    username = Column(String, nullable=False)
    token_encrypted = Column(String, nullable=False)
    token_hash = Column(String(64), nullable=False, unique=True, index=True)
    status = Column(Enum(StorefrontStatus), nullable=False, default=StorefrontStatus.ACTIVE)
    max_users = Column(Integer, nullable=True)
    created_at = Column(DateTime(timezone=True), default=func.now())
    banned_at = Column(DateTime(timezone=True), nullable=True)

    def __repr__(self):
        return f"@{self.username}"


class StorefrontBotDTO(BaseModel):
    id: int | None = None
    telegram_bot_id: int | None = None
    username: str | None = None
    status: StorefrontStatus = StorefrontStatus.ACTIVE
    max_users: int | None = None
    created_at: datetime | None = None
    banned_at: datetime | None = None


class StorefrontBotAdmin(ModelView, model=StorefrontBot):
    column_exclude_list = [StorefrontBot.token_encrypted, StorefrontBot.token_hash]
    form_excluded_columns = [StorefrontBot.token_encrypted, StorefrontBot.token_hash,
                             StorefrontBot.telegram_bot_id, StorefrontBot.created_at]
    column_details_exclude_list = [StorefrontBot.token_encrypted, StorefrontBot.token_hash]
    can_create = False
    can_delete = False
    can_edit = True
    column_sortable_list = [StorefrontBot.id, StorefrontBot.username, StorefrontBot.status,
                            StorefrontBot.created_at]
    name = "Storefront bot"
    name_plural = "Storefront bots"
