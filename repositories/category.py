import math

from sqlalchemy import select, func, update, or_, and_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

import config
from db import session_execute, session_flush
from enums.item_type import ItemType
from enums.sort_order import SortOrder
from enums.sort_property import SortProperty
from models.category import Category, CategoryDTO
from models.item import Item
from utils.utils import get_bot_photo_id, calculate_max_page


class CategoryRepository:
    PATH_SEPARATOR = "/"

    @staticmethod
    async def _get_visible_ids(item_type: ItemType | None,
                               session: Session | AsyncSession) -> tuple[set[int], dict[int, int | None]]:
        """Categories that have unsold items in themselves or anywhere below them, plus the parent map."""
        conditions = [Item.is_sold == False]
        if item_type:
            conditions.append(Item.item_type == item_type)
        with_items = await session_execute(select(Item.category_id).where(*conditions).distinct(), session)
        with_items = set(with_items.scalars().all())
        parents = await session_execute(select(Category.id, Category.parent_id), session)
        parents = {category_id: parent_id for category_id, parent_id in parents.all()}
        visible = set()
        for category_id in with_items:
            while category_id is not None and category_id not in visible:
                visible.add(category_id)
                category_id = parents.get(category_id)
        return visible, parents

    @staticmethod
    def _level_conditions(visible: set[int], parent_id: int | None, filters: list[str] | None) -> list:
        conditions = [Category.id.in_(visible or {-1})]
        if filters is not None:
            conditions.append(or_(*[Category.name.icontains(name) for name in filters]))
        else:
            conditions.append(Category.parent_id.is_(None) if parent_id is None else Category.parent_id == parent_id)
        return conditions

    @staticmethod
    async def get(sort_pairs: dict[str, int],
                  filters: list[str] | None,
                  item_type: ItemType | None,
                  page: int,
                  session: AsyncSession,
                  parent_id: int | None = None) -> list[CategoryDTO]:
        """One level of the tree (children of parent_id, or roots). A search looks through all levels."""
        sort_methods = []
        for sort_property, sort_order in sort_pairs.items():
            sort_property, sort_order = SortProperty(int(sort_property)), SortOrder(sort_order)
            if sort_order != SortOrder.DISABLE and sort_property == SortProperty.NAME:
                sort_methods.append(getattr(Category.name, sort_order.name.lower())())
        visible, _ = await CategoryRepository._get_visible_ids(item_type, session)
        stmt = (select(Category)
                .where(*CategoryRepository._level_conditions(visible, parent_id, filters))
                .order_by(*sort_methods, Category.name)
                .limit(config.PAGE_ENTRIES)
                .offset(page * config.PAGE_ENTRIES))
        categories = await session_execute(stmt, session)
        return [CategoryDTO.model_validate(category, from_attributes=True) for category in categories.scalars().all()]

    @staticmethod
    async def get_maximum_page(filters: list[str] | None, session: AsyncSession,
                               parent_id: int | None = None, item_type: ItemType | None = None) -> int:
        visible, _ = await CategoryRepository._get_visible_ids(item_type, session)
        stmt = (select(func.count(Category.id))
                .where(*CategoryRepository._level_conditions(visible, parent_id, filters)))
        count = await session_execute(stmt, session)
        return calculate_max_page(count.scalar_one())

    @staticmethod
    async def has_visible_children(category_id: int, item_type: ItemType | None, session: AsyncSession) -> bool:
        visible, parents = await CategoryRepository._get_visible_ids(item_type, session)
        return any(parents.get(child) == category_id for child in visible)

    @staticmethod
    async def has_own_items(category_id: int, item_type: ItemType | None, session: AsyncSession) -> bool:
        conditions = [Item.is_sold == False, Item.category_id == category_id]
        if item_type:
            conditions.append(Item.item_type == item_type)
        result = await session_execute(select(Item.id).where(*conditions).limit(1), session)
        return result.scalar() is not None

    @staticmethod
    async def get_path(category_id: int, session: Session | AsyncSession) -> str:
        """"Games / Steam / Keys" for a category, used in admin lists."""
        parents = await session_execute(select(Category.id, Category.parent_id, Category.name), session)
        rows = {row_id: (parent_id, name) for row_id, parent_id, name in parents.all()}
        names = []
        while category_id is not None and category_id in rows and len(names) < 50:
            parent_id, name = rows[category_id]
            names.append(name)
            category_id = parent_id
        return " / ".join(reversed(names))

    @staticmethod
    async def get_by_id(category_id: int, session: Session | AsyncSession) -> CategoryDTO:
        stmt = select(Category).where(Category.id == category_id)
        category = await session_execute(stmt, session)
        return CategoryDTO.model_validate(category.scalar(), from_attributes=True)

    @staticmethod
    async def get_to_delete(sort_pairs: dict[str, int],
                            filters: list[str],
                            page: int, session: AsyncSession) -> list[CategoryDTO]:
        sort_methods = []
        for sort_property, sort_order in sort_pairs.items():
            sort_property, sort_order = SortProperty(int(sort_property)), SortOrder(sort_order)
            if sort_order != SortOrder.DISABLE:
                sort_column = sort_property.get_column(Category)
                sort_method = (getattr(sort_column, sort_order.name.lower()))
                sort_methods.append(sort_method())
        conditions = [
            Item.is_sold == False
        ]
        if filters is not None:
            filter_conditions = [Category.name.icontains(name) for name in filters]
            conditions.append(or_(*filter_conditions))
        stmt = (select(Category)
                .join(Item, Item.category_id == Category.id)
                .where(*conditions)
                .distinct()
                .limit(config.PAGE_ENTRIES)
                .offset(page * config.PAGE_ENTRIES)
                .order_by(*sort_methods))
        categories = await session_execute(stmt, session)
        result = []
        for category in categories.scalars().all():
            category_dto = CategoryDTO.model_validate(category, from_attributes=True)
            category_dto.name = await CategoryRepository.get_path(category_dto.id, session)
            result.append(category_dto)
        return result

    @staticmethod
    async def get_to_delete_maximum_page(filters: list[str] | None, session: AsyncSession) -> int:
        conditions = [Item.is_sold == False]
        if filters is not None:
            conditions.append(or_(*[Category.name.icontains(name) for name in filters]))
        sub_stmt = (
            select(Category.id)
            .join(Item, Item.category_id == Category.id)
            .where(and_(*conditions))
            .distinct()
        ).alias('unique_categories')
        count = await session_execute(select(func.count()).select_from(sub_stmt), session)
        return calculate_max_page(count.scalar_one())

    @staticmethod
    async def get_or_create(category_name: str, session: Session | AsyncSession) -> CategoryDTO:
        """Accepts a path like "Games/Steam/Keys": every missing level is created, the last one is returned."""
        parts = [part.strip() for part in category_name.split(CategoryRepository.PATH_SEPARATOR) if part.strip()]
        parts = parts or [category_name.strip()]
        parent_id = None
        category = None
        for part in parts:
            parent_condition = Category.parent_id.is_(None) if parent_id is None else Category.parent_id == parent_id
            result = await session_execute(select(Category).where(Category.name == part, parent_condition), session)
            category = result.scalars().first()
            if category is None:
                bot_photo_id = get_bot_photo_id()
                category = Category(name=part, media_id=f"0{bot_photo_id}", parent_id=parent_id)
                session.add(category)
                await session_flush(session)
            parent_id = category.id
        return CategoryDTO.model_validate(category, from_attributes=True)

    @staticmethod
    async def get_by_ids(category_ids: list[int], session: Session | AsyncSession) -> list[CategoryDTO]:
        if not category_ids:
            return []
        stmt = select(Category).where(Category.id.in_(category_ids))
        categories = await session_execute(stmt, session)
        return [CategoryDTO.model_validate(category, from_attributes=True) for category in categories.scalars().all()]

    @staticmethod
    async def update(category_dto: CategoryDTO, session: AsyncSession):
        stmt = (update(Category)
                .where(Category.id == category_dto.id)
                .values(**category_dto.model_dump()))
        await session_execute(stmt, session)
