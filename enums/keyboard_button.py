from enum import Enum

from enums.bot_entity import BotEntity
from enums.language import Language
from utils.localizator import Localizator
from utils.utils import get_text


class KeyboardButton(Enum):
    ALL_CATEGORIES = "ALL_CATEGORIES"
    MY_PROFILE = "MY_PROFILE"
    FAQ = "FAQ"
    HELP = "HELP"
    REVIEWS = "REVIEWS"
    CART = "CART"
    MY_PURCHASES = "MY_PURCHASES"
    ADMIN_MENU = "MENU"

    def get_localized(self, language: Language):
        return get_text(language, BotEntity.COMMON, "button")

    @staticmethod
    def get_localized_set(button: 'KeyboardButton') -> 'LocalizedButtonTexts':
        """All names of a reply button. Looked up on every check, so renaming a button in the bot works at once."""
        bot_entity = BotEntity.ADMIN if button == KeyboardButton.ADMIN_MENU else BotEntity.USER
        return LocalizedButtonTexts(bot_entity, button.value.lower())


class LocalizedButtonTexts:
    def __init__(self, entity: BotEntity, key: str):
        self.entity = entity
        self.key = key

    def __contains__(self, text: object) -> bool:
        return text in Localizator.get_all_texts(self.entity, self.key)

    def __iter__(self):
        return iter(Localizator.get_all_texts(self.entity, self.key))
