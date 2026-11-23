from types import SimpleNamespace

import pytest

from enums.bot_entity import BotEntity
from enums.keyboard_button import KeyboardButton
from enums.language import Language
from services.multibot import MultibotService
from services.texts import EDITABLE_TEXTS, TextService
from utils.localizator import Localizator


@pytest.fixture(autouse=True)
def clean_overrides():
    Localizator.set_overrides({})
    yield
    Localizator.set_overrides({})


def _item(key):
    return next(item for item in EDITABLE_TEXTS if item.key == key)


def test_override_wins_and_reset_restores_default():
    default = Localizator.get_text(Language.RU, BotEntity.USER, "faq_string")
    Localizator.set_override(Language.RU, BotEntity.USER, "faq_string", "Новые правила")
    assert Localizator.get_text(Language.RU, BotEntity.USER, "faq_string") == "Новые правила"
    assert Localizator.get_text(Language.EN, BotEntity.USER, "faq_string") != "Новые правила"
    Localizator.set_override(Language.RU, BotEntity.USER, "faq_string", None)
    assert Localizator.get_text(Language.RU, BotEntity.USER, "faq_string") == default


def test_renamed_button_is_recognised_immediately():
    names = KeyboardButton.get_localized_set(KeyboardButton.CART)
    assert "🛒 Магазин-корзина" not in names
    Localizator.set_override(Language.RU, BotEntity.USER, "cart", "🛒 Магазин-корзина")
    assert "🛒 Магазин-корзина" in names
    assert Localizator.get_default_text(Language.RU, BotEntity.USER, "cart") in names


def test_validation_keeps_placeholders_and_limits():
    welcome = _item("storefront_your_link")
    assert TextService.validate(welcome, Language.RU, "Привет! Твой магазин: @{bot_username}") is None
    assert TextService.validate(welcome, Language.RU, "Привет без ссылки") == ["{bot_username}"]
    assert TextService.validate(welcome, Language.RU, "@{bot_username} {oops}") is not None
    assert TextService.validate(welcome, Language.RU, "@{bot_username} {") is not None
    assert TextService.validate(welcome, Language.RU, "@{bot_username}" + "x" * 1100) is not None
    rules = _item("faq_string")
    assert TextService.validate(rules, Language.EN, "No braces here") is None


def test_every_editable_item_has_labels_and_defaults():
    for item in EDITABLE_TEXTS:
        for language in Language:
            assert Localizator.get_text(language, BotEntity.ADMIN, item.label_key)
            if not item.is_photo:
                assert Localizator.get_default_text(language, item.entity, item.key)


def test_broadcast_content_is_sent_as_content_not_copied():
    photo = SimpleNamespace(photo=[SimpleNamespace(file_id="small"), SimpleNamespace(file_id="big")],
                            caption="hi", html_text="<b>hi</b>")
    assert MultibotService.extract_content(photo) == {"kind": "photo", "file_id": "big", "text": "<b>hi</b>"}
    text = SimpleNamespace(photo=None, video=None, animation=None, document=None, caption=None,
                           html_text="<i>news</i>")
    assert MultibotService.extract_content(text) == {"kind": "text", "text": "<i>news</i>"}
