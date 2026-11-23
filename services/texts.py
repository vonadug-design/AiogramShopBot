import re
from dataclasses import dataclass

from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from db import get_db_session, session_execute, session_commit
from enums.bot_entity import BotEntity
from enums.language import Language
from models.text_override import TextOverride
from utils.localizator import Localizator

PLACEHOLDER = re.compile(r"\{[^{}]*\}")
WELCOME_PHOTO_KEY = "welcome_photo"


@dataclass(frozen=True)
class EditableText:
    entity: BotEntity
    key: str
    label_key: str          # admin i18n key with the name shown in the menu
    max_length: int = 4096  # captions under a photo are limited to 1024 characters
    is_photo: bool = False


# What admins can change from the bot ("Texts" in the admin menu). Index = position in callbacks.
EDITABLE_TEXTS: list[EditableText] = [
    EditableText(BotEntity.USER, "storefront_your_link", "texts_item_main_welcome", 1024),
    EditableText(BotEntity.COMMON, WELCOME_PHOTO_KEY, "texts_item_welcome_photo", is_photo=True),
    EditableText(BotEntity.COMMON, "start_message", "texts_item_shop_welcome", 1024),
    EditableText(BotEntity.USER, "faq_string", "texts_item_rules"),
    EditableText(BotEntity.USER, "help_string", "texts_item_support"),
    EditableText(BotEntity.USER, "storefront_moved", "texts_item_moved"),
    EditableText(BotEntity.USER, "all_categories", "texts_item_btn_catalog", 64),
    EditableText(BotEntity.USER, "my_profile", "texts_item_btn_profile", 64),
    EditableText(BotEntity.USER, "cart", "texts_item_btn_cart", 64),
    EditableText(BotEntity.USER, "faq", "texts_item_btn_rules", 64),
    EditableText(BotEntity.USER, "help", "texts_item_btn_support", 64),
    EditableText(BotEntity.USER, "reviews", "texts_item_btn_reviews", 64),
    EditableText(BotEntity.USER, "storefront_open_button", "texts_item_btn_open_shop", 64),
]


class TextService:

    @staticmethod
    async def load() -> None:
        async with get_db_session() as session:
            rows = (await session_execute(select(TextOverride), session)).scalars().all()
            Localizator.set_overrides({(row.language, row.entity, row.key): row.value for row in rows})

    @staticmethod
    def get_welcome_photo(language: Language) -> str | None:
        return (Localizator.get_override(language, BotEntity.COMMON, WELCOME_PHOTO_KEY)
                or Localizator.get_override(Language.EN, BotEntity.COMMON, WELCOME_PHOTO_KEY))

    @staticmethod
    def get_current(item: EditableText, language: Language) -> str | None:
        if item.is_photo:
            return Localizator.get_override(language, item.entity, item.key)
        return Localizator.get_text(language, item.entity, item.key)

    @staticmethod
    def validate(item: EditableText, language: Language, value: str) -> list[str] | None:
        """None if the text can be saved, otherwise the placeholders it must contain."""
        default = Localizator.get_default_text(language, item.entity, item.key)
        required = sorted(set(PLACEHOLDER.findall(default)))
        found = PLACEHOLDER.findall(value)
        braces_ok = value.count("{") == len(found) and value.count("}") == len(found)
        if sorted(set(found)) != required or not braces_ok or len(value) > item.max_length or not value.strip():
            return required
        return None

    @staticmethod
    async def save(item: EditableText, language: Language, value: str | None, session: AsyncSession) -> None:
        """value None restores the default text."""
        await session_execute(delete(TextOverride).where(TextOverride.language == language.value,
                                                         TextOverride.entity == item.entity.name,
                                                         TextOverride.key == item.key), session)
        if value is not None:
            session.add(TextOverride(language=language.value, entity=item.entity.name, key=item.key, value=value))
        await session_commit(session)
        Localizator.set_override(language, item.entity, item.key, value)
