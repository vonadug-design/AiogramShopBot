"""Main bot of the multibot mode: hands out storefront links and manages the storefront pool.

The shop itself runs in the storefront bots. All bots are served by the FastAPI app in bot.py:
the main bot on WEBHOOK_PATH, storefronts on /webhook/bot/{id}.
"""
import logging
from typing import Any

from aiogram import Bot, Router
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import Message, CallbackQuery, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.utils.token import TokenValidationError, validate_token
from sqlalchemy.ext.asyncio import AsyncSession

import config
from enums.bot_entity import BotEntity
from enums.language import Language
from enums.storefront_status import StorefrontStatus
from middleware.database import DBSessionMiddleware
from middleware.language import I18nMiddleware
from models.storefront_bot import StorefrontBot
from models.user import UserDTO
from repositories.user import UserRepository
from callbacks import MainLanguageCallback
from services.texts import TextService
from db import session_commit
from repositories.storefront_bot import StorefrontBotRepository
from services.multibot import MultibotService, AddBotResult, Relocation, storefront_bot_cache
from services.user import UserService
from enums.staff_role import Permission
from utils.custom_filters import AdminIdFilter
from utils.token_crypto import decrypt_token
from utils.utils import get_text, get_bot_photo_id

STOREFRONT_WEBHOOK_PATH = "/webhook/bot/{bot_id}"
OTHER_BOTS_URL = f"{config.WEBHOOK_HOST}{STOREFRONT_WEBHOOK_PATH}"

main_router_multibot = Router()


def is_bot_token(value: str) -> bool:
    try:
        validate_token(value)
    except TokenValidationError:
        return False
    return True


def _open_shop_markup(storefront: StorefrontBot | None, language: Language, with_language_button: bool = False):
    kb_builder = InlineKeyboardBuilder()
    if storefront is not None:
        kb_builder.button(text=get_text(language, BotEntity.USER, "storefront_open_button"),
                          url=f"https://t.me/{storefront.username}")
    if with_language_button:
        kb_builder.button(text=get_text(language, BotEntity.USER, "language"),
                          callback_data=MainLanguageCallback(language=None))
    kb_builder.adjust(1)
    return kb_builder.as_markup()


def _language_picker_markup():
    kb_builder = InlineKeyboardBuilder()
    for language in Language:
        kb_builder.button(text=f"{language.get_flag_emoji()} {language.name}",
                          callback_data=MainLanguageCallback(language=language))
    kb_builder.adjust(3)
    return kb_builder.as_markup()


LANGUAGE_PICKER_TEXT = "🌍 Choose your language · Выберите язык · Izvēlieties valodu"


async def _send_welcome(message: Message, telegram_id: int, language: Language, session: AsyncSession):
    """Welcome photo + text + "Open the shop" button with the customer's personal storefront."""
    storefront = await MultibotService.assign_storefront(telegram_id, session)
    if storefront is None:
        return await message.answer(get_text(language, BotEntity.USER, "storefront_none_available"),
                                    reply_markup=_open_shop_markup(None, language, True))
    caption = get_text(language, BotEntity.USER, "storefront_your_link").format(bot_username=storefront.username)
    from services.custom_buttons import CustomButtonService
    # Link buttons go right under "Open the shop", the language button stays last.
    kb_builder = InlineKeyboardBuilder.from_markup(_open_shop_markup(storefront, language))
    await CustomButtonService.add_rows(kb_builder, session)
    kb_builder.row(InlineKeyboardButton(text=get_text(language, BotEntity.USER, "language"),
                                        callback_data=MainLanguageCallback(language=None).pack()))
    markup = kb_builder.as_markup()
    photo = TextService.get_welcome_photo(language) or get_bot_photo_id()
    try:
        return await message.answer_photo(photo, caption=caption, reply_markup=markup)
    except Exception as exception:
        logging.warning(f"Welcome photo failed, sending text only: {exception}")
        return await message.answer(caption, reply_markup=markup)


@main_router_multibot.message(AdminIdFilter(Permission.STOREFRONTS), Command("add"))
async def command_add_bot(message: Message, command: CommandObject, session: AsyncSession,
                          language: Language = Language.EN) -> Any:
    if not command.args or not is_bot_token(command.args.strip()):
        return await message.answer(get_text(language, BotEntity.ADMIN, "multibot_invalid_token"))
    token = command.args.strip()
    try:
        await message.delete()  # do not leave the token in the chat history
    except Exception as exception:
        logging.info(exception)
    result, storefront = await MultibotService.add_bot(token, OTHER_BOTS_URL, session)
    match result:
        case AddBotResult.MAIN_TOKEN:
            return await message.answer(get_text(language, BotEntity.ADMIN, "multibot_main_token_not_allowed"))
        case AddBotResult.DUPLICATE:
            return await message.answer(get_text(language, BotEntity.ADMIN, "multibot_bot_already_added"))
        case AddBotResult.INVALID:
            return await message.answer(get_text(language, BotEntity.ADMIN, "multibot_invalid_token"))
    storefront_bot_cache.forget(storefront.id)
    return await message.answer(
        get_text(language, BotEntity.ADMIN, "multibot_bot_added").format(bot_username=storefront.username)
    )


@main_router_multibot.message(AdminIdFilter(Permission.STOREFRONTS), Command("bots"))
async def command_list_bots(message: Message, session: AsyncSession, language: Language = Language.EN) -> Any:
    storefronts = await StorefrontBotRepository.get_all(session)
    if not storefronts:
        return await message.answer(get_text(language, BotEntity.ADMIN, "multibot_no_bots"))
    counts = await StorefrontBotRepository.get_user_counts(session)
    lines = [get_text(language, BotEntity.ADMIN, "multibot_bots_header")]
    for storefront in storefronts:
        capacity = storefront.max_users or config.STOREFRONT_MAX_USERS
        lines.append(get_text(language, BotEntity.ADMIN, "multibot_bot_line").format(
            id=storefront.id,
            bot_username=storefront.username,
            status=storefront.status.value,
            users=counts.get(storefront.id, 0),
            capacity=capacity
        ))
    return await message.answer("\n".join(lines))


@main_router_multibot.message(AdminIdFilter(Permission.STOREFRONTS), Command("ban"))
async def command_ban_bot(message: Message, command: CommandObject, session: AsyncSession, bot: Bot,
                          language: Language = Language.EN) -> Any:
    """/ban <id>: the storefront was banned, move its customers and send them new links via the main bot."""
    if not command.args or not command.args.strip().isdigit():
        return await message.answer(get_text(language, BotEntity.ADMIN, "multibot_ban_usage"))
    storefront_id = int(command.args.strip())
    storefront = await StorefrontBotRepository.get_by_id(storefront_id, session)
    if storefront is None:
        return await message.answer(get_text(language, BotEntity.ADMIN, "multibot_bot_not_found"))
    if storefront.status == StorefrontStatus.BANNED:
        return await message.answer(get_text(language, BotEntity.ADMIN, "multibot_bot_already_banned"))
    banned_username = storefront.username
    relocations = await MultibotService.ban_and_relocate(storefront_id, session)
    storefront_bot_cache.forget(storefront_id)
    moved = sum(1 for relocation in relocations if relocation.storefront is not None)
    await message.answer(get_text(language, BotEntity.ADMIN, "multibot_ban_started").format(
        bot_username=banned_username, total=len(relocations), moved=moved
    ))
    languages = await MultibotService.get_languages([relocation.telegram_id for relocation in relocations], session)

    def build_message(relocation: Relocation):
        customer_language = languages.get(relocation.telegram_id, Language.EN)
        return (get_text(customer_language, BotEntity.USER, "storefront_moved").format(
            bot_username=relocation.storefront.username),
                _open_shop_markup(relocation.storefront, customer_language))

    notified = await MultibotService.notify_relocations(bot, relocations, build_message)
    return await message.answer(get_text(language, BotEntity.ADMIN, "multibot_ban_finished").format(
        notified=notified, moved=moved, unplaced=len(relocations) - moved
    ))


@main_router_multibot.message(AdminIdFilter(Permission.STOREFRONTS), Command("unban"))
async def command_unban_bot(message: Message, command: CommandObject, session: AsyncSession,
                            language: Language = Language.EN) -> Any:
    """/unban <id>: a storefront marked as banned by mistake (or unbanned by Telegram) takes customers again."""
    if not command.args or not command.args.strip().isdigit():
        return await message.answer(get_text(language, BotEntity.ADMIN, "multibot_unban_usage"))
    storefront = await StorefrontBotRepository.get_by_id(int(command.args.strip()), session)
    if storefront is None:
        return await message.answer(get_text(language, BotEntity.ADMIN, "multibot_bot_not_found"))
    if storefront.status == StorefrontStatus.ACTIVE:
        return await message.answer(get_text(language, BotEntity.ADMIN, "multibot_bot_already_active"))
    child_bot = MultibotService.build_bot(decrypt_token(storefront.token_encrypted))
    try:
        await child_bot.get_me()
        await MultibotService._set_webhook(child_bot, storefront.id, OTHER_BOTS_URL)
    except Exception as exception:
        logging.warning(exception)
        return await message.answer(get_text(language, BotEntity.ADMIN, "multibot_unban_failed"))
    finally:
        await child_bot.session.close()
    await StorefrontBotRepository.set_status(storefront.id, StorefrontStatus.ACTIVE, session)
    await session_commit(session)
    storefront_bot_cache.forget(storefront.id)
    return await message.answer(get_text(language, BotEntity.ADMIN, "multibot_unbanned").format(
        bot_username=storefront.username))


@main_router_multibot.message(Command("language"))
async def command_language(message: Message):
    return await message.answer(LANGUAGE_PICKER_TEXT, reply_markup=_language_picker_markup())


@main_router_multibot.callback_query(MainLanguageCallback.filter())
async def main_language_chosen(callback: CallbackQuery, callback_data: MainLanguageCallback,
                               session: AsyncSession, language: Language):
    if callback_data.language is None:
        await callback.answer()
        return await callback.message.answer(LANGUAGE_PICKER_TEXT, reply_markup=_language_picker_markup())
    user = await UserRepository.get_by_tgid(callback.from_user.id, session)
    if user is not None:
        user.language = callback_data.language
        await UserRepository.update(user, session)
        await session_commit(session)
    await callback.answer()
    try:
        await callback.message.delete()
    except Exception as exception:
        logging.info(exception)
    await _send_welcome(callback.message, callback.from_user.id, callback_data.language, session)


@main_router_multibot.message(CommandStart())
@main_router_multibot.message()
async def main_bot_start(message: Message, session: AsyncSession, language: Language,
                         command: CommandObject | None = None):
    """Main bot: registers the customer; new customers pick a language first, then get their storefront link."""
    is_new = await UserRepository.get_by_tgid(message.from_user.id, session) is None
    await UserService.create_if_not_exist(UserDTO(
        telegram_username=message.from_user.username,
        telegram_id=message.from_user.id,
        language=language
    ), command.args if command else None, session)
    if is_new:
        return await message.answer(LANGUAGE_PICKER_TEXT, reply_markup=_language_picker_markup())
    return await _send_welcome(message, message.from_user.id, language, session)


main_router_multibot.message.middleware(DBSessionMiddleware())
main_router_multibot.message.middleware(I18nMiddleware())
main_router_multibot.callback_query.middleware(DBSessionMiddleware())
main_router_multibot.callback_query.middleware(I18nMiddleware())


# Review requests can arrive through the main bot when the customer's storefront is unavailable.
from services.review_request import create_review_request_router  # noqa: E402
main_router_multibot.include_router(create_review_request_router())
