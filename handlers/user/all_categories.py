from aiogram import Router, F
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession
from callbacks import AllCategoriesCallback
from enums.entity_type import EntityType
from enums.keyboard_button import KeyboardButton as KB
from enums.language import Language
from handlers.common.common import enable_search
from handlers.user.constants import UserStates
from services.cart import CartService
from services.category import CategoryService
from services.notification import NotificationService
from services.subcategory import SubcategoryService
from utils.custom_filters import IsUserExistFilter
from utils.redis_client import get_redis

all_categories_router = Router()


@all_categories_router.message(F.text.in_(KB.get_localized_set(KB.ALL_CATEGORIES)), IsUserExistFilter())
async def all_categories_text_message(message: Message, session: AsyncSession, state: FSMContext, language: Language):
    await state.update_data(filter=None)
    await state.set_state()
    media, kb_builder = await CategoryService.get_buttons(AllCategoriesCallback.create(level=1), state, session,
                                                          language, message.from_user.id)
    await NotificationService.answer_media(message, media, kb_builder.as_markup())


async def all_categories(**kwargs):
    callback: CallbackQuery = kwargs.get("callback")
    callback_data: AllCategoriesCallback = kwargs.get("callback_data")
    session: AsyncSession = kwargs.get("session")
    state: FSMContext = kwargs.get("state")
    language: Language = kwargs.get("language")
    state_data = await state.get_data()
    if callback_data.is_filter_enabled and state_data.get('filter') is not None:
        media, kb_builder = await CategoryService.get_buttons(callback_data, state, session, language)
    elif callback_data.is_filter_enabled:
        item_type_value = callback_data.item_type.value if callback_data.item_type else None
        media, kb_builder = await enable_search(callback_data,
                                                EntityType.CATEGORY,
                                                {"item_type": item_type_value},
                                                state,
                                                UserStates.filter_items,
                                                language)
    else:
        await state.update_data(filter=None)
        await state.set_state()
        media, kb_builder = await CategoryService.get_buttons(callback_data, state, session, language,
                                                              callback.from_user.id)
    await callback.message.edit_media(media=media, reply_markup=kb_builder.as_markup())


async def show_subcategories_in_category(**kwargs):
    callback: CallbackQuery = kwargs.get("callback")
    callback_data: AllCategoriesCallback = kwargs.get("callback_data")
    session: AsyncSession = kwargs.get("session")
    state: FSMContext = kwargs.get("state")
    language: Language = kwargs.get("language")
    state_data = await state.get_data()
    if callback_data.is_filter_enabled and state_data.get('filter') is not None:
        media, kb_builder = await SubcategoryService.get_buttons(callback_data, state, session, language)
    elif callback_data.is_filter_enabled:
        item_type_value = callback_data.item_type.value if callback_data.item_type else None
        media, kb_builder = await enable_search(callback_data,
                                                EntityType.SUBCATEGORY,
                                                {"category_id": callback_data.category_id,
                                                 "item_type": item_type_value},
                                                state,
                                                UserStates.filter_items,
                                                language)
    else:
        await state.update_data(filter=None)
        await state.set_state()
        media, kb_builder = await SubcategoryService.get_buttons(callback_data, state, session, language)
    await callback.message.edit_media(media=media, reply_markup=kb_builder.as_markup())


async def select_quantity(**kwargs):
    callback: CallbackQuery = kwargs.get("callback")
    callback_data: AllCategoriesCallback = kwargs.get("callback_data")
    session: AsyncSession = kwargs.get("session")
    language: Language = kwargs.get("language")
    media, kb_builder = await SubcategoryService.get_select_quantity_buttons(callback_data, session, language)
    await callback.message.edit_media(media=media, reply_markup=kb_builder.as_markup())


async def add_to_cart_confirmation(**kwargs):
    callback: CallbackQuery = kwargs.get("callback")
    callback_data: AllCategoriesCallback = kwargs.get("callback_data")
    session: AsyncSession = kwargs.get("session")
    language: Language = kwargs.get("language")
    msg, kb_builder = await SubcategoryService.get_add_to_cart_buttons(callback_data, session, language,
                                                                       callback.from_user.id)
    await callback.message.edit_caption(caption=msg, reply_markup=kb_builder.as_markup())


async def buy_now(**kwargs):
    callback: CallbackQuery = kwargs.get("callback")
    callback_data: AllCategoriesCallback = kwargs.get("callback_data")
    session: AsyncSession = kwargs.get("session")
    language: Language = kwargs.get("language")
    if not callback_data.confirmation:
        return await callback.answer()
    # One purchase per confirmation screen: a double tap must not buy twice.
    guard_key = f"buy_now:{callback.message.chat.id}:{callback.message.message_id}"
    if not await get_redis().set(guard_key, 1, nx=True, ex=24 * 3600):
        return await callback.answer()
    await callback.message.edit_reply_markup(reply_markup=None)
    msg, kb_builder = await CartService.buy_now(callback, callback_data, session, language)
    await callback.message.edit_caption(caption=msg, reply_markup=kb_builder.as_markup())


async def add_to_cart(**kwargs):
    callback: CallbackQuery = kwargs.get("callback")
    callback_data: AllCategoriesCallback = kwargs.get("callback_data")
    session: AsyncSession = kwargs.get("session")
    language: Language = kwargs.get("language")
    media, kb_builder = await CartService.add_to_cart(callback, callback_data, session, language)
    await callback.message.edit_media(media=media, reply_markup=kb_builder.as_markup())


@all_categories_router.message(IsUserExistFilter(), F.text, StateFilter(UserStates.filter_items))
async def receive_filter_message(message: Message, state: FSMContext, session: AsyncSession, language: Language):
    await state.update_data(filter=message.html_text)
    state_data = await state.get_data()
    entity_type = EntityType(state_data['entity_type'])
    if entity_type == EntityType.CATEGORY:
        media, kb_builder = await CategoryService.get_buttons(None, state, session, language)
    else:
        media, kb_builder = await SubcategoryService.get_buttons(None, state, session, language)
    await NotificationService.answer_media(message, media, kb_builder.as_markup())


@all_categories_router.callback_query(AllCategoriesCallback.filter(), IsUserExistFilter())
async def navigate_categories(callback: CallbackQuery,
                              callback_data: AllCategoriesCallback,
                              session: AsyncSession,
                              state: FSMContext,
                              language: Language):
    current_level = callback_data.level

    if current_level == 0:
        # The catalog has no "item type" step any more: level 0 is the list of top categories.
        callback_data = callback_data.model_copy(update={"level": 1, "category_id": None, "page": 0})
        current_level = 1
    levels = {
        1: all_categories,
        2: show_subcategories_in_category,
        3: select_quantity,
        4: add_to_cart_confirmation,
        5: add_to_cart,
        6: buy_now
    }

    current_level_function = levels.get(current_level)
    if current_level_function is None:
        return await callback.answer()

    kwargs = {
        "callback": callback,
        "session": session,
        "callback_data": callback_data,
        "state": state,
        "language": language
    }

    await current_level_function(**kwargs)
