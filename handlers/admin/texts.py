"""Admin menu -> Texts: change the welcome messages, rules, support text, button names and the welcome photo."""
from aiogram import Router, F
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy.ext.asyncio import AsyncSession

from callbacks import TextsCallback
from enums.bot_entity import BotEntity
from enums.language import Language
from enums.staff_role import Permission
from handlers.admin.constants import AdminConstants, TextsStates
from services.texts import EDITABLE_TEXTS, TextService
from utils.custom_filters import AdminIdFilter
from utils.utils import get_text

texts_router = Router()


def _items_keyboard(language: Language) -> InlineKeyboardBuilder:
    kb_builder = InlineKeyboardBuilder()
    for index, item in enumerate(EDITABLE_TEXTS):
        kb_builder.button(text=get_text(language, BotEntity.ADMIN, item.label_key),
                          callback_data=TextsCallback.create(level=1, item=index))
    kb_builder.adjust(2)
    kb_builder.row(AdminConstants.back_to_main_button(language))
    return kb_builder


async def _show(callback: CallbackQuery, text: str, kb_builder: InlineKeyboardBuilder):
    if callback.message.caption is not None or callback.message.photo:
        await callback.message.delete()
        await callback.message.answer(text, reply_markup=kb_builder.as_markup())
    else:
        try:
            await callback.message.edit_text(text, reply_markup=kb_builder.as_markup())
        except TelegramBadRequest as exception:
            # "Reset" redraws the same screen; Telegram refuses an edit that changes nothing.
            if "message is not modified" not in str(exception):
                raise


@texts_router.callback_query(AdminIdFilter(Permission.TEXTS), TextsCallback.filter())
async def texts_navigation(callback: CallbackQuery, callback_data: TextsCallback, state: FSMContext,
                           session: AsyncSession, language: Language):
    await state.clear()
    if callback_data.level == 0 or not 0 <= callback_data.item < len(EDITABLE_TEXTS):
        return await _show(callback, get_text(language, BotEntity.ADMIN, "texts_menu"), _items_keyboard(language))
    item = EDITABLE_TEXTS[callback_data.item]
    item_name = get_text(language, BotEntity.ADMIN, item.label_key)
    if callback_data.language is None:
        kb_builder = InlineKeyboardBuilder()
        for target in Language:
            kb_builder.button(text=f"{target.get_flag_emoji()} {target.name}",
                              callback_data=TextsCallback.create(level=2, item=callback_data.item, language=target))
        kb_builder.adjust(3)
        kb_builder.row(TextsCallback.create(level=0).get_back_button(language, 0))
        return await _show(callback, get_text(language, BotEntity.ADMIN, "texts_pick_language").format(
            item=item_name), kb_builder)
    target = callback_data.language
    if callback_data.reset:
        await TextService.save(item, target, None, session)
        await callback.answer(get_text(language, BotEntity.ADMIN, "texts_reset_done"), show_alert=True)
    current = TextService.get_current(item, target)
    request_key = "texts_request_photo" if item.is_photo else "texts_request_text"
    kb_builder = InlineKeyboardBuilder()
    kb_builder.button(text=get_text(language, BotEntity.ADMIN, "texts_reset_button"),
                      callback_data=TextsCallback.create(level=2, item=callback_data.item, language=target,
                                                         reset=True))
    kb_builder.row(TextsCallback.create(level=1, item=callback_data.item).get_back_button(language, 1))
    header = get_text(language, BotEntity.ADMIN, request_key).format(item=item_name, language=target.name)
    await state.set_state(TextsStates.value)
    await state.update_data(texts_item=callback_data.item, texts_language=target.value)
    if item.is_photo:
        if current:
            await callback.message.delete()
            return await callback.message.answer_photo(current, caption=header, reply_markup=kb_builder.as_markup())
        return await _show(callback, header, kb_builder)
    # Show the current text exactly as buyers see it, then the instructions.
    await _show(callback, header, kb_builder)
    await callback.message.answer(current)


@texts_router.message(AdminIdFilter(Permission.TEXTS), StateFilter(TextsStates.value))
async def receive_text(message: Message, state: FSMContext, session: AsyncSession, language: Language):
    data = await state.get_data()
    item = EDITABLE_TEXTS[data["texts_item"]]
    target = Language(data["texts_language"])
    back = InlineKeyboardBuilder()
    back.button(text=get_text(language, BotEntity.ADMIN, "texts_back_to_list"),
                callback_data=TextsCallback.create(level=0))
    if message.text and message.text.strip().lower() in ("cancel", "отмена", "atcelt"):
        await state.clear()
        return await message.answer(get_text(language, BotEntity.COMMON, "cancelled"),
                                    reply_markup=back.as_markup())
    if item.is_photo:
        if not message.photo:
            return await message.answer(get_text(language, BotEntity.ADMIN, "texts_need_photo"))
        value = message.photo[-1].file_id
    else:
        if not message.text:
            return await message.answer(get_text(language, BotEntity.ADMIN, "texts_need_text"))
        value = message.html_text
        required = TextService.validate(item, target, value)
        if required is not None:
            return await message.answer(get_text(language, BotEntity.ADMIN, "texts_invalid").format(
                placeholders=", ".join(required) or "—", max_length=item.max_length))
    await TextService.save(item, target, value, session)
    await state.clear()
    await message.answer(get_text(language, BotEntity.ADMIN, "texts_saved"), reply_markup=back.as_markup())
