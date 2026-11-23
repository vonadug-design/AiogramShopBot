"""Admin menu -> Buttons: link buttons under the welcome messages (channels, chats) and the support link."""
from aiogram import Router, F
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy.ext.asyncio import AsyncSession

from callbacks import LinkButtonsCallback
from enums.bot_entity import BotEntity
from enums.language import Language
from enums.staff_role import Permission
from handlers.admin.constants import AdminConstants, LinkButtonsStates
from services.custom_buttons import CustomButtonService, MAX_BUTTONS, MAX_TEXT_LENGTH
from utils.custom_filters import AdminIdFilter
from utils.utils import get_text

link_buttons_router = Router()


def _t(language: Language, key: str) -> str:
    return get_text(language, BotEntity.ADMIN, key)


def _back(language: Language) -> InlineKeyboardBuilder:
    kb_builder = InlineKeyboardBuilder()
    kb_builder.button(text=get_text(language, BotEntity.COMMON, "back_button"),
                      callback_data=LinkButtonsCallback.create(0))
    return kb_builder


async def _menu(session: AsyncSession, language: Language) -> tuple[str, InlineKeyboardBuilder]:
    kb_builder = InlineKeyboardBuilder()
    buttons = await CustomButtonService.get_all(session)
    for button in buttons:
        kb_builder.row(InlineKeyboardButton(text=button.text,
                                            callback_data=LinkButtonsCallback.create(1, button.id).pack()))
    if len(buttons) < MAX_BUTTONS:
        kb_builder.row(InlineKeyboardButton(text=_t(language, "links_add_button"),
                                            callback_data=LinkButtonsCallback.create(0, action="add").pack()))
    kb_builder.row(InlineKeyboardButton(text=_t(language, "links_support_button"),
                                        callback_data=LinkButtonsCallback.create(0, action="support").pack()))
    kb_builder.row(AdminConstants.back_to_main_button(language))
    text = _t(language, "links_menu").format(support_link=CustomButtonService.get_support_link() or "—")
    return text, kb_builder


async def _show(callback: CallbackQuery, text: str, kb_builder: InlineKeyboardBuilder):
    try:
        await callback.message.edit_text(text, reply_markup=kb_builder.as_markup(), disable_web_page_preview=True)
    except TelegramBadRequest as exception:
        if "message is not modified" not in str(exception):
            raise


@link_buttons_router.callback_query(AdminIdFilter(Permission.TEXTS), LinkButtonsCallback.filter())
async def link_buttons_navigation(callback: CallbackQuery, callback_data: LinkButtonsCallback, state: FSMContext,
                                  session: AsyncSession, language: Language):
    await state.clear()
    if callback_data.level == 1 and callback_data.button_id is not None:
        if callback_data.action == "remove":
            await CustomButtonService.remove(callback_data.button_id, session)
            await callback.answer(_t(language, "links_removed"))
        else:
            if callback_data.action in ("up", "down"):
                await CustomButtonService.move(callback_data.button_id, -1 if callback_data.action == "up" else 1,
                                               session)
            buttons = await CustomButtonService.get_all(session)
            button = next((item for item in buttons if item.id == callback_data.button_id), None)
            if button is not None:
                kb_builder = InlineKeyboardBuilder()
                kb_builder.button(text=_t(language, "catalog_up_button"),
                                  callback_data=LinkButtonsCallback.create(1, button.id, action="up"))
                kb_builder.button(text=_t(language, "catalog_down_button"),
                                  callback_data=LinkButtonsCallback.create(1, button.id, action="down"))
                kb_builder.button(text=_t(language, "links_remove_button"),
                                  callback_data=LinkButtonsCallback.create(1, button.id, action="remove"))
                kb_builder.adjust(2, 1)
                kb_builder.row(LinkButtonsCallback.create(0).get_back_button(language, 0))
                position = [item.id for item in buttons].index(button.id) + 1
                return await _show(callback, _t(language, "links_button_info").format(
                    text=button.text, url=button.url, position=position, count=len(buttons)), kb_builder)
    if callback_data.level == 0 and callback_data.action == "add":
        await state.set_state(LinkButtonsStates.text)
        return await _show(callback, _t(language, "links_request_text").format(max_length=MAX_TEXT_LENGTH),
                           _back(language))
    if callback_data.level == 0 and callback_data.action == "support":
        await state.set_state(LinkButtonsStates.support_link)
        return await _show(callback, _t(language, "links_request_support"), _back(language))
    text, kb_builder = await _menu(session, language)
    await _show(callback, text, kb_builder)


@link_buttons_router.message(AdminIdFilter(Permission.TEXTS), F.text, StateFilter(LinkButtonsStates.text))
async def receive_button_text(message: Message, state: FSMContext, language: Language):
    text = message.text.strip()
    if not text or len(text) > MAX_TEXT_LENGTH:
        return await message.answer(_t(language, "links_request_text").format(max_length=MAX_TEXT_LENGTH),
                                    reply_markup=_back(language).as_markup())
    await state.update_data(link_text=text)
    await state.set_state(LinkButtonsStates.url)
    await message.answer(_t(language, "links_request_url"), reply_markup=_back(language).as_markup())


@link_buttons_router.message(AdminIdFilter(Permission.TEXTS), F.text, StateFilter(LinkButtonsStates.url))
async def receive_button_url(message: Message, state: FSMContext, session: AsyncSession, language: Language):
    url = CustomButtonService.normalize_url(message.text)
    if url is None:
        return await message.answer(_t(language, "links_bad_url"), reply_markup=_back(language).as_markup())
    await CustomButtonService.add((await state.get_data())["link_text"], url, session)
    await state.clear()
    text, kb_builder = await _menu(session, language)
    await message.answer(_t(language, "links_added") + "\n\n" + text, reply_markup=kb_builder.as_markup(),
                         disable_web_page_preview=True)


@link_buttons_router.message(AdminIdFilter(Permission.TEXTS), F.text, StateFilter(LinkButtonsStates.support_link))
async def receive_support_link(message: Message, state: FSMContext, session: AsyncSession, language: Language):
    url = CustomButtonService.normalize_url(message.text)
    if url is None:
        return await message.answer(_t(language, "links_bad_url"), reply_markup=_back(language).as_markup())
    await CustomButtonService.set_support_link(url, session)
    await state.clear()
    text, kb_builder = await _menu(session, language)
    await message.answer(_t(language, "links_support_saved") + "\n\n" + text, reply_markup=kb_builder.as_markup(),
                         disable_web_page_preview=True)
