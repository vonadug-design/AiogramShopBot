import asyncio
import datetime
import importlib
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

for _module in ("item", "cart", "cartItem", "user", "buy", "buyItem", "category", "subcategory", "deposit",
                "button_media", "payment", "coupon", "shipping_option", "review", "referral", "storefront_bot",
                "apirone_invoice", "staff_member", "text_override", "custom_button"):
    importlib.import_module(f"models.{_module}")
from enums.language import Language
from models.base import Base
from models.category import Category, CategoryDTO
from repositories.category import CategoryRepository
from services.category import CategoryService
from services.custom_buttons import CustomButtonService
from services.subcategory import SubcategoryService


def run(coro):
    return asyncio.run(coro)


def test_new_modules_import():
    for name in ("handlers.admin.catalog", "handlers.admin.link_buttons", "handlers.user.all_categories",
                 "handlers.user.apirone", "handlers.user.my_profile", "services.review_request"):
        importlib.import_module(name)


@pytest.mark.parametrize("raw, expected", [
    ("https://t.me/mychannel", "https://t.me/mychannel"),
    ("t.me/mychannel", "https://t.me/mychannel"),
    ("@my_support", "https://t.me/my_support"),
    ("my_support", "https://t.me/my_support"),
    ("http://example.com/page", "http://example.com/page"),
    ("not a link", None),
    ("", None),
    ("javascript:alert(1)", None),
])
def test_link_normalization(raw, expected):
    assert CustomButtonService.normalize_url(raw) == expected


@pytest.mark.parametrize("missing, expected", [(0.01, "5.00"), (7.123, "7.13"), (12, "12.00"), (5.1, "5.10")])
def test_top_up_amount_is_rounded_up_and_at_least_minimum(missing, expected):
    assert SubcategoryService.top_up_amount_for(missing) == expected


def test_description_falls_back_to_english():
    category = CategoryDTO(id=1, name="Games", descriptions={"en": "Hello", "ru": "Привет"})
    assert CategoryService.get_description(category, Language.RU) == "Привет"
    assert CategoryService.get_description(category, Language.LV) == "Hello"
    assert CategoryService.get_description(CategoryDTO(id=2, name="x"), Language.RU) == ""


@pytest.fixture
def session(monkeypatch):
    async def execute(stmt, s):
        return s.execute(stmt)

    async def flush(s):
        s.flush()

    monkeypatch.setattr("repositories.category.get_bot_photo_id", lambda: "photo")
    monkeypatch.setattr("repositories.category.session_execute", execute)
    monkeypatch.setattr("repositories.category.session_flush", flush)
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine, tables=[Base.metadata.tables[name] for name in
                                             ("categories", "subcategories", "items")])
    with Session(engine) as s:
        yield s


def test_manual_category_order(session):
    for name in ("Apples", "Bananas", "Cherries"):
        run(CategoryRepository.get_or_create(name, session))
    names = lambda: [c.name for c in run(CategoryRepository.get_children_all(None, session))]
    assert names() == ["Apples", "Bananas", "Cherries"]
    cherries = session.query(Category).filter_by(name="Cherries").one()
    run(CategoryRepository.move(cherries.id, -1, session))
    run(CategoryRepository.move(cherries.id, -1, session))
    session.expire_all()
    assert names() == ["Cherries", "Apples", "Bananas"]
    run(CategoryRepository.move(cherries.id, -1, session))  # already first: stays
    session.expire_all()
    assert names() == ["Cherries", "Apples", "Bananas"]


def test_category_description_per_language(session):
    category = run(CategoryRepository.get_or_create("Games", session))
    run(CategoryRepository.set_description(category.id, "ru", "Игры", session))
    run(CategoryRepository.set_description(category.id, "en", "Games", session))
    run(CategoryRepository.set_description(category.id, "en", None, session))
    session.expire_all()
    assert run(CategoryRepository.get_by_id(category.id, session)).descriptions == {"ru": "Игры"}


class _FakeSession:
    async def commit(self):
        pass


def _patch_review_requests(monkeypatch, buys, products):
    import services.review_request as module

    @asynccontextmanager
    async def fake_db_session():
        yield _FakeSession()

    async def get_due(session, now):
        return buys

    async def get_unreviewed(buy_id, session):
        return products.get(buy_id, [])

    async def execute(stmt, session):
        return SimpleNamespace(scalar=lambda: SimpleNamespace(telegram_id=42, language=Language.RU,
                                                              can_receive_messages=True))

    async def commit(session):
        pass

    monkeypatch.setattr(module, "get_db_session", fake_db_session)
    monkeypatch.setattr(module.ReviewRequestService, "get_due", staticmethod(get_due))
    monkeypatch.setattr(module.ReviewRequestService, "get_unreviewed_products", staticmethod(get_unreviewed))
    monkeypatch.setattr(module, "session_execute", execute)
    monkeypatch.setattr(module, "session_commit", commit)
    return module


def test_review_request_then_reminder_then_stop(monkeypatch):
    now = datetime.datetime.now(tz=datetime.timezone.utc)
    buy = SimpleNamespace(id=1, buyer_id=1, review_requests=0, review_requested_at=None,
                          buy_datetime=now - datetime.timedelta(hours=2))
    old_buy = SimpleNamespace(id=2, buyer_id=1, review_requests=0, review_requested_at=None,
                              buy_datetime=now - datetime.timedelta(days=10))
    module = _patch_review_requests(monkeypatch, [buy, old_buy], {1: [(7, "Steam key")], 2: [(8, "Old")]})
    sent = []

    async def send(text, telegram_id, markup):
        sent.append((text, telegram_id, markup.inline_keyboard[0][4].callback_data))

    assert run(module.ReviewRequestService.send_due(send)) == 1
    assert sent[0][1] == 42 and "Steam key" in sent[0][0] and sent[0][2] == "rate:7:5"
    assert buy.review_requests == 1 and buy.review_requested_at is not None
    assert old_buy.review_requests == 2  # too old to ask about
    run(module.ReviewRequestService.send_due(send))
    assert buy.review_requests == 2 and len(sent) == 2 and "Напоминаем" in sent[1][0]


def test_review_request_skipped_when_already_reviewed(monkeypatch):
    now = datetime.datetime.now(tz=datetime.timezone.utc)
    buy = SimpleNamespace(id=1, buyer_id=1, review_requests=0, review_requested_at=None,
                          buy_datetime=now - datetime.timedelta(hours=2))
    module = _patch_review_requests(monkeypatch, [buy], {})

    async def send(*args):
        raise AssertionError("nothing should be sent")

    assert run(module.ReviewRequestService.send_due(send)) == 0
    assert buy.review_requests == 2
