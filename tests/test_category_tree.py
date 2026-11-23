import asyncio

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

import importlib

for _module in ("item", "cart", "cartItem", "user", "buy", "buyItem", "category", "subcategory", "deposit",
                "button_media", "payment", "coupon", "shipping_option", "review", "referral", "storefront_bot",
                "apirone_invoice", "staff_member"):
    importlib.import_module(f"models.{_module}")
from enums.item_type import ItemType
from models.base import Base
from models.category import Category
from models.item import Item
from models.subcategory import Subcategory
from repositories.category import CategoryRepository


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


def run(coro):
    return asyncio.run(coro)


def add_item(session, category_id, sold=False):
    subcategory = Subcategory(name=f"product-{category_id}", media_id="0photo")
    session.add(subcategory)
    session.flush()
    session.add(Item(category_id=category_id, subcategory_id=subcategory.id, private_data="key",
                     price=1.0, is_sold=sold, item_type=ItemType.DIGITAL, description="d"))
    session.flush()


def test_path_creates_four_levels_and_reuses_them(session):
    leaf = run(CategoryRepository.get_or_create("Games/Steam/Keys/EU", session))
    again = run(CategoryRepository.get_or_create("Games / Steam / Keys / EU", session))
    assert leaf.id == again.id
    assert session.query(Category).count() == 4
    assert run(CategoryRepository.get_path(leaf.id, session)) == "Games / Steam / Keys / EU"


def test_same_name_allowed_under_different_parents(session):
    a = run(CategoryRepository.get_or_create("Steam/Keys", session))
    b = run(CategoryRepository.get_or_create("Epic/Keys", session))
    assert a.id != b.id


def test_levels_show_only_branches_with_stock(session):
    eu = run(CategoryRepository.get_or_create("Games/Steam/Keys/EU", session))
    empty = run(CategoryRepository.get_or_create("Games/Empty", session))
    sold_out = run(CategoryRepository.get_or_create("Music", session))
    add_item(session, eu.id)
    add_item(session, sold_out.id, sold=True)

    roots = run(CategoryRepository.get({}, None, None, 0, session))
    assert [c.name for c in roots] == ["Games"]
    games = roots[0]
    children = run(CategoryRepository.get({}, None, None, 0, session, parent_id=games.id))
    assert [c.name for c in children] == ["Steam"]
    assert run(CategoryRepository.has_visible_children(games.id, None, session))
    assert not run(CategoryRepository.has_visible_children(eu.id, None, session))
    assert not run(CategoryRepository.has_visible_children(empty.id, None, session))
    assert run(CategoryRepository.get_maximum_page(None, session, games.id)) == 0


def test_items_directly_in_a_parent_category(session):
    keys = run(CategoryRepository.get_or_create("Steam/Keys", session))
    steam_id = keys.parent_id
    add_item(session, keys.id)
    assert not run(CategoryRepository.has_own_items(steam_id, None, session))
    add_item(session, steam_id)
    assert run(CategoryRepository.has_own_items(steam_id, None, session))
    assert run(CategoryRepository.has_visible_children(steam_id, None, session))
