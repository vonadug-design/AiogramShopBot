"""Main bot of the multibot mode: hands out storefront links and manages the storefront pool.

The shop itself runs in the storefront bots. All bots are served by the FastAPI app in bot.py:
the main bot on WEBHOOK_PATH, storefronts on /webhook/bot/{id}.
"""
import logging
from typing import Any

from aiogram import Bot, Router
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import Message
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
from repositories.storefront_bot import StorefrontBotRepository
from services.multibot import MultibotService, AddBotResult, Relocation, storefront_bot_cache
from services.user import UserService
from enums.staff_role import Permission
from utils.custom_filters import AdminIdFilter
from utils.utils import get_text

STOREFRONT_WEBHOOK_PATH = "/webhook/bot/{bot_id}"
OTHER_BOTS_URL = f"{config.WEBHOOK_HOST}{STOREFRONT_WEBHOOK_PATH}"

main_router_multibot = Router()


def is_bot_token(value: str) -> bool:
    try:
        validate_token(value)
    except TokenValidationError:
        return False
    return True


def _open_shop_markup(storefront: StorefrontBot, language: Language):
    kb_builder = InlineKeyboardBuilder()
    kb_builder.button(text=get_text(language, BotEntity.USER, "storefront_open_button"),
                      url=f"https://t.me/{storefront.username}")
    return kb_builder.as_markup()


@main_router_multibot.message(AdminIdFilter(Permission.STOREFRONTS), Command("add"))
async def command_add_bot(message: Message, command: CommandObject, session: AsyncSession) -> Any:
    if not command.args or not is_bot_token(command.args.strip()):
        return await message.answer(get_text(Language.EN, BotEntity.ADMIN, "multibot_invalid_token"))
    token = command.args.strip()
    try:
        await message.delete()  # do not leave the token in the chat history
    except Exception as exception:
        logging.info(exception)
    result, storefront = await MultibotService.add_bot(token, OTHER_BOTS_URL, session)
    match result:
        case AddBotResult.MAIN_TOKEN:
            return await message.answer(get_text(Language.EN, BotEntity.ADMIN, "multibot_main_token_not_allowed"))
        case AddBotResult.DUPLICATE:
            return await message.answer(get_text(Language.EN, BotEntity.ADMIN, "multibot_bot_already_added"))
        case AddBotResult.INVALID:
            return await message.answer(get_text(Language.EN, BotEntity.ADMIN, "multibot_invalid_token"))
    storefront_bot_cache.forget(storefront.id)
    return await message.answer(
        get_text(Language.EN, BotEntity.ADMIN, "multibot_bot_added").format(bot_username=storefront.username)
    )


@main_router_multibot.message(AdminIdFilter(Permission.STOREFRONTS), Command("bots"))
async def command_list_bots(message: Message, session: AsyncSession) -> Any:
    storefronts = await StorefrontBotRepository.get_all(session)
    if not storefronts:
        return await message.answer(get_text(Language.EN, BotEntity.ADMIN, "multibot_no_bots"))
    counts = await StorefrontBotRepository.get_user_counts(session)
    lines = [get_text(Language.EN, BotEntity.ADMIN, "multibot_bots_header")]
    for storefront in storefronts:
        capacity = storefront.max_users or config.STOREFRONT_MAX_USERS
        lines.append(get_text(Language.EN, BotEntity.ADMIN, "multibot_bot_line").format(
            id=storefront.id,
            bot_username=storefront.username,
            status=storefront.status.value,
            users=counts.get(storefront.id, 0),
            capacity=capacity
        ))
    return await message.answer("\n".join(lines))


@main_router_multibot.message(AdminIdFilter(Permission.STOREFRONTS), Command("ban"))
async def command_ban_bot(message: Message, command: CommandObject, session: AsyncSession, bot: Bot) -> Any:
    """/ban <id>: the storefront was banned, move its customers and send them new links via the main bot."""
    if not command.args or not command.args.strip().isdigit():
        return await message.answer(get_text(Language.EN, BotEntity.ADMIN, "multibot_ban_usage"))
    storefront_id = int(command.args.strip())
    storefront = await StorefrontBotRepository.get_by_id(storefront_id, session)
    if storefront is None:
        return await message.answer(get_text(Language.EN, BotEntity.ADMIN, "multibot_bot_not_found"))
    if storefront.status == StorefrontStatus.BANNED:
        return await message.answer(get_text(Language.EN, BotEntity.ADMIN, "multibot_bot_already_banned"))
    banned_username = storefront.username
    relocations = await MultibotService.ban_and_relocate(storefront_id, session)
    storefront_bot_cache.forget(storefront_id)
    moved = sum(1 for relocation in relocations if relocation.storefront is not None)
    await message.answer(get_text(Language.EN, BotEntity.ADMIN, "multibot_ban_started").format(
        bot_username=banned_username, total=len(relocations), moved=moved
    ))
    languages = await MultibotService.get_languages([relocation.telegram_id for relocation in relocations], session)

    def build_message(relocation: Relocation):
        language = languages.get(relocation.telegram_id, Language.EN)
        return (get_text(language, BotEntity.USER, "storefront_moved").format(
            bot_username=relocation.storefront.username),
                _open_shop_markup(relocation.storefront, language))

    notified = await MultibotService.notify_relocations(bot, relocations, build_message)
    return await message.answer(get_text(Language.EN, BotEntity.ADMIN, "multibot_ban_finished").format(
        notified=notified, moved=moved, unplaced=len(relocations) - moved
    ))


@main_router_multibot.message(CommandStart())
@main_router_multibot.message()
async def main_bot_start(message: Message, session: AsyncSession, language: Language,
                         command: CommandObject | None = None):
    """Main bot: registers the customer and gives them the link to their personal storefront."""
    await UserService.create_if_not_exist(UserDTO(
        telegram_username=message.from_user.username,
        telegram_id=message.from_user.id,
        language=language
    ), command.args if command else None, session)
    storefront = await MultibotService.assign_storefront(message.from_user.id, session)
    if storefront is None:
        return await message.answer(get_text(language, BotEntity.USER, "storefront_none_available"))
    return await message.answer(
        get_text(language, BotEntity.USER, "storefront_your_link").format(bot_username=storefront.username),
        reply_markup=_open_shop_markup(storefront, language)
    )


main_router_multibot.message.middleware(DBSessionMiddleware())
main_router_multibot.message.middleware(I18nMiddleware())
