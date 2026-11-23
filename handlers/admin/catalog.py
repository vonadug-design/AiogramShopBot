"""Admin menu -> Catalog: walk the category tree, set a category's photo, description and place in the list,
and add more units to an existing product without typing its category, description and price again."""
from aiogram import Router, F
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy.ext.asyncio import AsyncSession

import config
from callbacks import CatalogCallback, MediaManagementCallback
from db import session_commit
from enums.bot_entity import BotEntity
from enums.entity_type import EntityType
from enums.item_type import ItemType
from enums.language import Language
from enums.staff_role import Permission
from handlers.admin.constants import AdminConstants, CatalogStates, InventoryManagementStates
from repositories.category import CategoryRepository
from repositories.item import ItemRepository
from repositories.subcategory import SubcategoryRepository
from services.media import MediaService
from services.photo_stock import PhotoStockService
from utils.custom_filters import AdminIdFilter
from utils.utils import get_text

catalog_router = Router()
MAX_DESCRIPTION_LENGTH = 700  # the description shares a photo caption (1024 characters) with the buttons' prompt
MAX_LIST_BUTTONS = 90


def _t(language: Language, key: str) -> str:
    return get_text(language, BotEntity.ADMIN, key)


async def _show(callback: CallbackQuery, text: str, kb_builder: InlineKeyboardBuilder) -> Message:
    """Shows a screen in place of the current message and returns the message that holds it."""
    if callback.message.photo or callback.message.caption is not None:
        await callback.message.delete()
        return await callback.message.answer(text, reply_markup=kb_builder.as_markup())
    try:
        await callback.message.edit_text(text, reply_markup=kb_builder.as_markup())
    except TelegramBadRequest as exception:
        if "message is not modified" not in str(exception):
            raise
    return callback.message


async def category_screen(category_id: int | None, session: AsyncSession,
                          language: Language) -> tuple[str, InlineKeyboardBuilder]:
    kb_builder = InlineKeyboardBuilder()
    children = await CategoryRepository.get_children_all(category_id, session)
    for child in children[:MAX_LIST_BUTTONS]:
        kb_builder.row(InlineKeyboardButton(text=f"📁 {child.name}",
                                            callback_data=CatalogCallback.create(0, category_id=child.id).pack()))
    if category_id is None:
        kb_builder.row(AdminConstants.back_to_main_button(language))
        text = _t(language, "catalog_root") if children else _t(language, "catalog_empty")
        return text, kb_builder
    category = await CategoryRepository.get_by_id(category_id, session)
    for subcategory_id, name, in_stock, _total in await ItemRepository.get_products_in_category(category_id, session):
        kb_builder.row(InlineKeyboardButton(
            text=_t(language, "catalog_product_button").format(name=name, in_stock=in_stock),
            callback_data=CatalogCallback.create(1, category_id=category_id, subcategory_id=subcategory_id).pack()))
    kb_builder.row(InlineKeyboardButton(text=_t(language, "catalog_photo_button"),
                                        callback_data=CatalogCallback.create(0, category_id, action="photo").pack()),
                   InlineKeyboardButton(text=_t(language, "catalog_description_button"),
                                        callback_data=CatalogCallback.create(2, category_id).pack()))
    kb_builder.row(InlineKeyboardButton(text=_t(language, "catalog_up_button"),
                                        callback_data=CatalogCallback.create(0, category_id, action="up").pack()),
                   InlineKeyboardButton(text=_t(language, "catalog_down_button"),
                                        callback_data=CatalogCallback.create(0, category_id, action="down").pack()))
    kb_builder.row(CatalogCallback.create(0, category.parent_id).get_back_button(language, 0))
    siblings = await CategoryRepository.get_children_all(category.parent_id, session)
    position = next((index for index, sibling in enumerate(siblings, start=1) if sibling.id == category_id), 1)
    descriptions = category.descriptions or {}
    filled = ", ".join(code.upper() for code in descriptions) or "—"
    text = _t(language, "catalog_category").format(path=await CategoryRepository.get_path(category_id, session),
                                                   position=position, count=len(siblings), descriptions=filled)
    return text, kb_builder


async def product_screen(callback_data: CatalogCallback, session: AsyncSession,
                         language: Language) -> tuple[str, InlineKeyboardBuilder]:
    kb_builder = InlineKeyboardBuilder()
    item = await ItemRepository.get_latest(callback_data.category_id, callback_data.subcategory_id, session)
    subcategory = await SubcategoryRepository.get_by_id(callback_data.subcategory_id, session)
    in_stock = await ItemRepository.get_available_qty(None, callback_data.category_id,
                                                      callback_data.subcategory_id, session)
    if item is not None and item.item_type == ItemType.DIGITAL:
        kb_builder.button(text=_t(language, "catalog_restock_button"),
                          callback_data=CatalogCallback.create(1, callback_data.category_id,
                                                               callback_data.subcategory_id, action="restock"))
    kb_builder.row(CatalogCallback.create(0, callback_data.category_id).get_back_button(language, 0))
    text = _t(language, "catalog_product").format(
        name=subcategory.name, path=await CategoryRepository.get_path(callback_data.category_id, session),
        price=item.price if item else 0, currency_sym=config.CURRENCY.get_localized_symbol(), in_stock=in_stock,
        description=item.description if item else "")
    return text, kb_builder


async def start_restock(callback: CallbackQuery, callback_data: CatalogCallback, state: FSMContext,
                        session: AsyncSession, language: Language):
    item = await ItemRepository.get_latest(callback_data.category_id, callback_data.subcategory_id, session)
    if item is None:
        return await callback.answer()
    subcategory = await SubcategoryRepository.get_by_id(callback_data.subcategory_id, session)
    await state.clear()
    await PhotoStockService.clear(callback.from_user.id)
    # The same flow as "Add items -> menu", already past the category, name, description and price steps.
    await state.update_data(item_type=item.item_type.value, restock=True,
                            restock_category_id=callback_data.category_id,
                            restock_subcategory_id=callback_data.subcategory_id,
                            subcategory_name=subcategory.name, description=item.description, price=item.price)
    await state.set_state(InventoryManagementStates.private_data)
    kb_builder = InlineKeyboardBuilder()
    kb_builder.row(CatalogCallback.create(1, callback_data.category_id, callback_data.subcategory_id)
                   .get_back_button(language, 1))
    text = _t(language, "catalog_restock_request").format(name=subcategory.name) + "\n\n" + \
        _t(language, "add_items_private_data")
    shown = await _show(callback, text, kb_builder)
    await state.update_data(msg_id=shown.message_id, chat_id=shown.chat.id)


async def description_screen(callback: CallbackQuery, callback_data: CatalogCallback, state: FSMContext,
                             session: AsyncSession, language: Language):
    category = await CategoryRepository.get_by_id(callback_data.category_id, session)
    kb_builder = InlineKeyboardBuilder()
    if callback_data.language is None:
        await state.clear()
        for target in Language:
            kb_builder.button(text=f"{target.get_flag_emoji()} {target.name}",
                              callback_data=CatalogCallback.create(2, category.id, language=target))
        kb_builder.adjust(3)
        kb_builder.row(CatalogCallback.create(0, category.id).get_back_button(language, 0))
        return await _show(callback, _t(language, "catalog_description_pick_language").format(name=category.name),
                           kb_builder)
    target = callback_data.language
    if callback_data.action == "clear":
        await CategoryRepository.set_description(category.id, target.value, None, session)
        await session_commit(session)
        await callback.answer(_t(language, "catalog_description_cleared"), show_alert=True)
        category = await CategoryRepository.get_by_id(category.id, session)
    current = (category.descriptions or {}).get(target.value)
    kb_builder.button(text=_t(language, "catalog_description_clear_button"),
                      callback_data=CatalogCallback.create(2, category.id, language=target, action="clear"))
    kb_builder.row(CatalogCallback.create(2, category.id).get_back_button(language, 2))
    text = _t(language, "catalog_description_request").format(name=category.name, language=target.name,
                                                               max_length=MAX_DESCRIPTION_LENGTH)
    if current:
        text += "\n\n" + _t(language, "catalog_description_current") + "\n" + current
    await state.set_state(CatalogStates.description)
    await state.update_data(catalog_category_id=category.id, catalog_language=target.value)
    await _show(callback, text, kb_builder)


@catalog_router.message(AdminIdFilter(Permission.INVENTORY), F.text, StateFilter(CatalogStates.description))
async def receive_description(message: Message, state: FSMContext, session: AsyncSession, language: Language):
    state_data = await state.get_data()
    category_id = state_data.get("catalog_category_id")
    target = state_data.get("catalog_language")
    text = message.html_text.strip()
    if len(text) > MAX_DESCRIPTION_LENGTH:
        return await message.answer(_t(language, "catalog_description_too_long").format(
            max_length=MAX_DESCRIPTION_LENGTH))
    await CategoryRepository.set_description(category_id, target, text, session)
    await session_commit(session)
    await state.clear()
    kb_builder = InlineKeyboardBuilder()
    kb_builder.button(text=get_text(language, BotEntity.COMMON, "back_button"),
                      callback_data=CatalogCallback.create(0, category_id))
    await message.answer(_t(language, "catalog_description_saved"), reply_markup=kb_builder.as_markup())


@catalog_router.callback_query(AdminIdFilter(Permission.INVENTORY), CatalogCallback.filter())
async def catalog_navigation(callback: CallbackQuery, callback_data: CatalogCallback, state: FSMContext,
                             session: AsyncSession, language: Language):
    if callback_data.level == 2:
        return await description_screen(callback, callback_data, state, session, language)
    if callback_data.level == 1:
        if callback_data.action == "restock":
            return await start_restock(callback, callback_data, state, session, language)
        await state.clear()
        text, kb_builder = await product_screen(callback_data, session, language)
        return await _show(callback, text, kb_builder)
    await state.clear()
    if callback_data.category_id is not None and callback_data.action in ("up", "down"):
        await CategoryRepository.move(callback_data.category_id, -1 if callback_data.action == "up" else 1, session)
        await session_commit(session)
    if callback_data.category_id is not None and callback_data.action == "photo":
        msg, kb_builder = await MediaService.set_entity_media_edit(
            MediaManagementCallback.create(level=2, entity_type=EntityType.CATEGORY,
                                           entity_id=callback_data.category_id), state, session, language)
        kb_builder = InlineKeyboardBuilder()
        kb_builder.button(text=get_text(language, BotEntity.COMMON, "cancel"),
                          callback_data=CatalogCallback.create(0, callback_data.category_id))
        shown = await _show(callback, msg, kb_builder)
        return await state.update_data(msg_id=shown.message_id, chat_id=shown.chat.id)
    text, kb_builder = await category_screen(callback_data.category_id, session, language)
    await _show(callback, text, kb_builder)
