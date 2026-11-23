import logging
import secrets
import sys
from typing import Any, Dict

from aiohttp import web
from aiogram import Bot, Dispatcher, Router
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.utils.token import TokenValidationError, validate_token
from aiogram.webhook.aiohttp_server import BaseRequestHandler, SimpleRequestHandler, setup_application
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

import config
from db import create_db_and_tables, get_db_session
from enums.bot_entity import BotEntity
from enums.language import Language
from enums.storefront_status import StorefrontStatus
from middleware.database import DBSessionMiddleware
from middleware.language import I18nMiddleware
from models.storefront_bot import StorefrontBot
from models.user import UserDTO
from repositories.storefront_bot import StorefrontBotRepository
from services.multibot import MultibotService, AddBotResult, Relocation
from services.user import UserService
from utils.custom_filters import AdminIdFilter
from utils.media_relay import MediaRelayMiddleware
from utils.telegram import create_bot, create_telegram_session
from utils.token_crypto import webhook_secret
from utils.utils import get_text

main_router_multibot = Router()

BASE_URL = config.WEBHOOK_HOST
MAIN_BOT_TOKEN = config.TOKEN

WEB_SERVER_HOST = config.WEBAPP_HOST
WEB_SERVER_PORT = config.WEBAPP_PORT
MAIN_BOT_PATH = "/webhook/main"
OTHER_BOTS_PATH = "/webhook/bot/{bot_id}"

OTHER_BOTS_URL = f"{BASE_URL}{OTHER_BOTS_PATH}"


class StorefrontRequestHandler(BaseRequestHandler):
    """Routes /webhook/bot/{bot_id} to the storefront bot; the token never appears in the URL."""

    def __init__(self, dispatcher: Dispatcher, bot_settings: Dict[str, Any] | None = None,
                 handle_in_background: bool = True, **data: Any) -> None:
        super().__init__(dispatcher=dispatcher, handle_in_background=handle_in_background, **data)
        self.bot_settings = bot_settings or {}
        self.bots: Dict[int, Bot] = {}

    def forget(self, storefront_id: int) -> None:
        self.bots.pop(storefront_id, None)

    def verify_secret(self, telegram_secret_token: str, bot: Bot) -> bool:
        return True  # checked in handle(), where the storefront id is known

    async def close(self) -> None:
        self.bots.clear()

    async def resolve_bot(self, request: web.Request) -> Bot:
        try:
            storefront_id = int(request.match_info["bot_id"])
        except ValueError:
            raise web.HTTPNotFound()
        if storefront_id not in self.bots:
            async with get_db_session() as session:
                token = await MultibotService.get_token(storefront_id, session)
            if token is None:
                raise web.HTTPNotFound()
            self.bots[storefront_id] = create_bot(token, **self.bot_settings)
        return self.bots[storefront_id]

    async def handle(self, request: web.Request) -> web.Response:
        try:
            storefront_id = int(request.match_info["bot_id"])
        except ValueError:
            return web.Response(status=404)
        received = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
        if not secrets.compare_digest(received, webhook_secret(storefront_id)):
            return web.Response(body="Unauthorized", status=401)
        return await super().handle(request)


storefront_handler: StorefrontRequestHandler | None = None


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


@main_router_multibot.message(CommandStart())
async def main_bot_start(message: Message, command: CommandObject, session: AsyncSession, language: Language):
    """Main bot: registers the customer and gives them the link to their personal storefront."""
    await UserService.create_if_not_exist(UserDTO(
        telegram_username=message.from_user.username,
        telegram_id=message.from_user.id,
        language=language
    ), command.args, session)
    storefront = await MultibotService.assign_storefront(message.from_user.id, session)
    if storefront is None:
        return await message.answer(get_text(language, BotEntity.USER, "storefront_none_available"))
    return await message.answer(
        get_text(language, BotEntity.USER, "storefront_your_link").format(bot_username=storefront.username),
        reply_markup=_open_shop_markup(storefront, language)
    )


@main_router_multibot.message(AdminIdFilter(), Command("add"))
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
    if storefront_handler is not None:
        storefront_handler.forget(storefront.id)
    return await message.answer(
        get_text(Language.EN, BotEntity.ADMIN, "multibot_bot_added").format(bot_username=storefront.username)
    )


@main_router_multibot.message(AdminIdFilter(), Command("bots"))
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


@main_router_multibot.message(AdminIdFilter(), Command("ban"))
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
    if storefront_handler is not None:
        storefront_handler.forget(storefront_id)
    moved = sum(1 for relocation in relocations if relocation.storefront is not None)
    await message.answer(get_text(Language.EN, BotEntity.ADMIN, "multibot_ban_started").format(
        bot_username=banned_username, total=len(relocations), moved=moved
    ))

    def build_message(relocation: Relocation):
        language = Language.EN
        return (get_text(language, BotEntity.USER, "storefront_moved").format(
            bot_username=relocation.storefront.username),
                _open_shop_markup(relocation.storefront, language))

    notified = await MultibotService.notify_relocations(bot, relocations, build_message)
    return await message.answer(get_text(Language.EN, BotEntity.ADMIN, "multibot_ban_finished").format(
        notified=notified, moved=moved, unplaced=len(relocations) - moved
    ))


async def on_startup(dispatcher: Dispatcher, bot: Bot):
    await bot.set_webhook(f"{BASE_URL}{MAIN_BOT_PATH}", secret_token=config.WEBHOOK_SECRET_TOKEN or None)
    await create_db_and_tables()
    await MultibotService.restore_child_bot_webhooks(OTHER_BOTS_URL)
    for admin in config.ADMIN_ID_LIST:
        try:
            await bot.send_message(admin, 'Bot is working')
        except Exception as e:
            logging.warning(e)


def main(main_router):
    global storefront_handler
    logging.basicConfig(level=logging.INFO, stream=sys.stdout)
    from aiogram.fsm.storage.redis import RedisStorage
    redis = Redis(host=config.REDIS_HOST, password=config.REDIS_PASSWORD)
    session = create_telegram_session()
    # Photos uploaded through one bot become usable in every storefront bot
    session.middleware(MediaRelayMiddleware(redis, config.MEDIA_CACHE_DIR, MultibotService.get_all_tokens))
    bot = create_bot(MAIN_BOT_TOKEN, session=session)
    storage = RedisStorage(redis)

    main_router_multibot.message.middleware(DBSessionMiddleware())
    main_router_multibot.message.middleware(I18nMiddleware())
    main_dispatcher = Dispatcher(storage=storage)
    main_dispatcher.include_router(main_router_multibot)
    main_dispatcher.startup.register(on_startup)

    multibot_dispatcher = Dispatcher(storage=storage)
    multibot_dispatcher.include_router(main_router)

    app = web.Application()
    SimpleRequestHandler(dispatcher=main_dispatcher, bot=bot,
                         secret_token=config.WEBHOOK_SECRET_TOKEN or None).register(app, path=MAIN_BOT_PATH)
    storefront_handler = StorefrontRequestHandler(dispatcher=multibot_dispatcher, bot_settings={"session": session})
    storefront_handler.register(app, path=OTHER_BOTS_PATH)

    setup_application(app, main_dispatcher, bot=bot)
    setup_application(app, multibot_dispatcher)

    web.run_app(app, host=WEB_SERVER_HOST, port=WEB_SERVER_PORT)
