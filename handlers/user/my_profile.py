from services.ownership import OwnershipService
from aiogram import Router, F
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession
from callbacks import MyProfileCallback
from enums.bot_entity import BotEntity
from enums.entity_type import EntityType
from enums.keyboard_button import KeyboardButton as KB
from enums.language import Language
from handlers.common.common import enable_search
from handlers.user.constants import UserStates
from repositories.button_media import ButtonMediaRepository
from services.buy import BuyService
from services.media import MediaService
from services.notification import NotificationService
from services.payment import PaymentService
from services.referral import ReferralService
from services.user import UserService
from utils.custom_filters import IsUserExistFilter
from utils.utils import get_text

my_profile_router = Router()


@my_profile_router.message(F.text.in_(KB.get_localized_set(KB.MY_PROFILE)), IsUserExistFilter())
async def my_profile_text_message(message: Message, session: AsyncSession, state: FSMContext, language: Language):
    await my_profile(message=message, session=session, state=state, language=language)


@my_profile_router.message(F.text.in_(KB.get_localized_set(KB.MY_PURCHASES)), IsUserExistFilter())
async def my_purchases_text_message(message: Message, session: AsyncSession, state: FSMContext, language: Language):
    await state.clear()
    caption, kb_builder = await UserService.get_purchase_history_buttons(message.from_user.id, None, state,
                                                                         session, language)
    button_media = await ButtonMediaRepository.get_by_button(KB.MY_PURCHASES, session)
    media = MediaService.convert_to_media(button_media.media_id, caption=caption)
    await NotificationService.answer_media(message, media, kb_builder.as_markup())


async def resend_purchase(**kwargs):
    """Sends the keys of one purchased product again, each with its photo."""
    callback: CallbackQuery = kwargs.get("callback")
    callback_data: MyProfileCallback = kwargs.get("callback_data")
    session: AsyncSession = kwargs.get("session")
    language: Language = kwargs.get("language")
    from repositories.buyItem import BuyItemRepository
    from repositories.item import ItemRepository
    from services.delivery import DeliveryService
    if callback_data.buyItem_id is None:
        return await callback.answer()
    buy_item = await BuyItemRepository.get_by_id(callback_data.buyItem_id, session)
    items = await ItemRepository.get_by_id_list(buy_item.item_ids, session)
    await callback.answer(get_text(language, BotEntity.USER, "purchase_resent"))
    await DeliveryService.deliver(callback.bot, callback.from_user.id, items, language)


async def my_profile(**kwargs):
    message: Message | CallbackQuery = kwargs.get("message") or kwargs.get("callback")
    session: AsyncSession = kwargs.get("session")
    state: FSMContext = kwargs.get("state")
    language: Language = kwargs.get("language")
    await state.clear()
    media, kb_builder = await UserService.get_my_profile_buttons(message.from_user.id, session, language)
    if isinstance(message, Message):
        await NotificationService.answer_media(message, media, kb_builder.as_markup())
    elif isinstance(message, CallbackQuery):
        callback = message
        await callback.message.edit_media(media=media,
                                          reply_markup=kb_builder.as_markup())


async def top_up_balance(**kwargs):
    callback: CallbackQuery = kwargs.get("callback")
    callback_data: MyProfileCallback = kwargs.get("callback_data")
    state: FSMContext = kwargs.get("state")
    language: Language = kwargs.get("language")
    await state.set_state()
    msg_text, kb_builder = await UserService.get_top_up_buttons(callback_data, language)
    await callback.message.edit_caption(caption=msg_text, reply_markup=kb_builder.as_markup())


async def purchase_history(**kwargs):
    callback: CallbackQuery = kwargs.get("callback")
    callback_data: MyProfileCallback = kwargs.get("callback_data")
    session: AsyncSession = kwargs.get("session")
    state: FSMContext = kwargs.get("state")
    language: Language = kwargs.get("language")
    msg_text, kb_builder = await UserService.get_purchase_history_buttons(callback.from_user.id, callback_data,
                                                                          state, session, language)
    if callback.message.caption:
        await callback.message.edit_caption(caption=msg_text, reply_markup=kb_builder.as_markup())
    else:
        await callback.message.edit_text(text=msg_text, reply_markup=kb_builder.as_markup())


async def get_purchase(**kwargs):
    callback: CallbackQuery = kwargs.get("callback")
    callback_data: MyProfileCallback = kwargs.get("callback_data")
    session: AsyncSession = kwargs.get("session")
    language: Language = kwargs.get("language")
    msg, kb_builder = await BuyService.get_purchase(callback_data, session, language)
    methods_map = {
        (True, True): ("edit_caption", "caption"),
        (True, False): ("edit_media", "media"),
        (False, True): ("edit_text", "text"),
        (False, False): ("edit_media", "media"),
    }

    has_caption = bool(callback.message.caption)
    is_string = isinstance(msg, str)
    method_name, param_name = methods_map[(has_caption, is_string)]

    method = getattr(callback.message, method_name)
    await method(**{param_name: msg}, reply_markup=kb_builder.as_markup())


async def get_purchased_item(**kwargs):
    callback: CallbackQuery = kwargs.get("callback")
    callback_data: MyProfileCallback = kwargs.get("callback_data")
    state: FSMContext = kwargs.get("state")
    session: AsyncSession = kwargs.get("session")
    language: Language = kwargs.get("language")
    state_data = await state.get_data()
    if callback_data.is_filter_enabled and state_data.get("filter") is not None:
        media, kb_builder = await BuyService.get_purchased_item(callback_data, state, session, language)
    elif callback_data.is_filter_enabled:
        media, kb_builder = await enable_search(callback_data, EntityType.SUBCATEGORY, callback_data.buy_id, state,
                                                UserStates.filter_purchase_history, language)
    else:
        await state.update_data(filter=None)
        await state.set_state()
        media, kb_builder = await BuyService.get_purchased_item(callback_data, state, session, language)
    if callback.message.caption:
        await callback.message.edit_media(media=media, reply_markup=kb_builder.as_markup())
    else:
        await callback.message.edit_text(text=media.caption, reply_markup=kb_builder.as_markup())


async def create_payment(**kwargs):
    callback: CallbackQuery = kwargs.get("callback")
    session: AsyncSession = kwargs.get("session")
    callback_data: MyProfileCallback = kwargs.get("callback_data")
    state: FSMContext = kwargs.get("state")
    language: Language = kwargs.get("language")
    response, kb_builder = await PaymentService.create(callback, callback_data, state, session, language)
    if isinstance(response, str):
        await callback.message.edit_caption(caption=response, reply_markup=kb_builder.as_markup())
    else:
        await callback.message.edit_media(media=response, reply_markup=kb_builder.as_markup())


async def edit_language(**kwargs):
    callback: CallbackQuery = kwargs.get("callback")
    session: AsyncSession = kwargs.get("session")
    callback_data: MyProfileCallback = kwargs.get("callback_data")
    msg, kb_builder = await UserService.edit_language(callback.from_user.id, callback_data, session,
                                                      kwargs.get("language") or Language.EN)
    await callback.message.edit_caption(caption=msg, reply_markup=kb_builder.as_markup())


async def referral_system(**kwargs):
    callback: CallbackQuery = kwargs.get("callback")
    session: AsyncSession = kwargs.get("session")
    callback_data: MyProfileCallback = kwargs.get("callback_data")
    language: Language = kwargs.get("language")
    msg, kb_builder = await ReferralService.view_statistics(callback, callback_data, session, language)
    await callback.message.edit_caption(caption=msg, reply_markup=kb_builder.as_markup())


@my_profile_router.message(IsUserExistFilter(), F.text, StateFilter(UserStates.filter_purchase_history))
async def receive_filter_message(message: Message, state: FSMContext, session: AsyncSession, language: Language):
    await state.update_data(filter=message.html_text)
    media, kb_builder = await BuyService.get_purchased_item(None, state, session, language)
    await NotificationService.answer_media(message, media, kb_builder.as_markup())


@my_profile_router.message(IsUserExistFilter(), F.text, StateFilter(UserStates.top_up_amount))
async def receive_top_up_amount(message: Message,
                                state: FSMContext,
                                session: AsyncSession,
                                language: Language):
    media, kb_builder = await PaymentService.create(message,
                                                    None,
                                                    state,
                                                    session,
                                                    language)
    state_data = await state.get_data()
    if state_data.get("chat_id") and state_data.get("msg_id"):
        await message.bot.edit_message_media(chat_id=state_data.get("chat_id"),
                                             message_id=state_data.get("msg_id"),
                                             media=media,
                                             reply_markup=kb_builder.as_markup())
    else:
        await NotificationService.answer_media(message, media, kb_builder.as_markup())


@my_profile_router.callback_query(MyProfileCallback.filter(), IsUserExistFilter())
async def navigate(callback: CallbackQuery,
                   callback_data: MyProfileCallback,
                   session: AsyncSession,
                   state: FSMContext,
                   language: Language):
    if callback_data.buy_id is not None or callback_data.buyItem_id is not None:
        from enums.user_role import UserRole
        from enums.staff_role import Permission
        from services.staff import StaffService
        if callback_data.user_role == UserRole.ADMIN:
            allowed = await StaffService.can(callback.from_user.id, Permission.BUYS, session)
        else:
            allowed = await OwnershipService.owns_buy(callback.from_user.id, callback_data.buy_id,
                                                      callback_data.buyItem_id, session)
        if not allowed:
            return await callback.answer()
    current_level = callback_data.level

    levels = {
        0: my_profile,
        1: top_up_balance,
        2: create_payment,
        3: purchase_history,
        4: get_purchased_item,
        5: get_purchase,
        6: edit_language,
        7: referral_system,
        8: resend_purchase
    }

    current_level_function = levels[current_level]

    kwargs = {
        "callback": callback,
        "session": session,
        "callback_data": callback_data,
        "state": state,
        "language": language
    }

    await current_level_function(**kwargs)
