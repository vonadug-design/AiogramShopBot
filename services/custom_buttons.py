"""Link buttons (channels, chats, sites) under the welcome messages, and the support link. Both are set in the bot."""
import re

from aiogram.types import InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy import select, delete, update, func
from sqlalchemy.ext.asyncio import AsyncSession

import config
from db import session_execute, session_commit
from enums.bot_entity import BotEntity
from models.custom_button import CustomButton
from models.text_override import TextOverride
from utils.localizator import Localizator

MAX_BUTTONS = 10
MAX_TEXT_LENGTH = 64
SUPPORT_LINK_KEY = "support_link"
# Settings that are the same for every language are kept with the texts, under this "language".
ALL_LANGUAGES = "*"
_USERNAME = re.compile(r"^@?([A-Za-z0-9_]{4,32})$")


class CustomButtonService:

    @staticmethod
    def normalize_url(raw: str | None) -> str | None:
        """Accepts https://..., t.me/name or @name. Returns a link Telegram accepts, or None."""
        value = (raw or "").strip()
        if not value or len(value) > 512 or any(char.isspace() for char in value):
            return None
        username = _USERNAME.match(value)
        if username and not value.lower().startswith(("http", "t.me")):
            return f"https://t.me/{username.group(1)}"
        if value.lower().startswith("t.me/"):
            value = "https://" + value
        if re.match(r"^https?://[^/\s]+\.[^/\s]+", value, re.IGNORECASE) or value.lower().startswith("tg://"):
            return value
        return None

    @staticmethod
    async def get_all(session: AsyncSession) -> list[CustomButton]:
        result = await session_execute(select(CustomButton).order_by(CustomButton.position, CustomButton.id), session)
        return list(result.scalars().all())

    @staticmethod
    async def add(text: str, url: str, session: AsyncSession) -> None:
        position = (await session_execute(select(func.coalesce(func.max(CustomButton.position), -1)),
                                          session)).scalar() + 1
        session.add(CustomButton(text=text, url=url, position=position))
        await session_commit(session)

    @staticmethod
    async def remove(button_id: int, session: AsyncSession) -> None:
        await session_execute(delete(CustomButton).where(CustomButton.id == button_id), session)
        await session_commit(session)

    @staticmethod
    async def move(button_id: int, step: int, session: AsyncSession) -> None:
        ids = [button.id for button in await CustomButtonService.get_all(session)]
        if button_id not in ids:
            return
        index = ids.index(button_id)
        target = index + step
        if 0 <= target < len(ids):
            ids[index], ids[target] = ids[target], ids[index]
        for position, current_id in enumerate(ids):
            await session_execute(update(CustomButton).where(CustomButton.id == current_id)
                                  .values(position=position), session)
        await session_commit(session)

    @staticmethod
    async def add_rows(kb_builder: InlineKeyboardBuilder, session: AsyncSession) -> InlineKeyboardBuilder:
        for button in await CustomButtonService.get_all(session):
            kb_builder.row(InlineKeyboardButton(text=button.text, url=button.url))
        return kb_builder

    @staticmethod
    def get_support_link() -> str | None:
        return Localizator._overrides.get((ALL_LANGUAGES, BotEntity.USER.name, SUPPORT_LINK_KEY)) \
            or config.SUPPORT_LINK or None

    @staticmethod
    async def set_support_link(url: str | None, session: AsyncSession) -> None:
        await session_execute(delete(TextOverride).where(TextOverride.language == ALL_LANGUAGES,
                                                         TextOverride.entity == BotEntity.USER.name,
                                                         TextOverride.key == SUPPORT_LINK_KEY), session)
        if url:
            session.add(TextOverride(language=ALL_LANGUAGES, entity=BotEntity.USER.name, key=SUPPORT_LINK_KEY,
                                     value=url))
        await session_commit(session)
        if url:
            Localizator._overrides[(ALL_LANGUAGES, BotEntity.USER.name, SUPPORT_LINK_KEY)] = url
        else:
            Localizator._overrides.pop((ALL_LANGUAGES, BotEntity.USER.name, SUPPORT_LINK_KEY), None)
