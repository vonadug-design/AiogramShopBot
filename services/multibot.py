import asyncio
import logging
from dataclasses import dataclass
from typing import Awaitable, Callable

from aiogram import Bot
from aiogram.exceptions import TelegramForbiddenError, TelegramUnauthorizedError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

import config
from db import get_db_session, session_commit
from enums.storefront_status import StorefrontStatus
from models.storefront_bot import StorefrontBot
from repositories.storefront_bot import StorefrontBotRepository
from utils.telegram import create_bot
from utils.token_crypto import encrypt_token, decrypt_token, token_hash, webhook_secret


class AddBotResult:
    ADDED = "added"
    INVALID = "invalid"
    MAIN_TOKEN = "main_token"
    DUPLICATE = "duplicate"


@dataclass
class Relocation:
    telegram_id: int
    storefront: StorefrontBot | None


class StorefrontBotCache:
    """Bot objects for storefronts, built from the encrypted tokens on first use."""

    def __init__(self):
        self.bots: dict[int, Bot] = {}
        self.session = None

    def configure(self, session) -> None:
        self.session = session

    def forget(self, storefront_id: int) -> None:
        self.bots.pop(storefront_id, None)

    async def get(self, storefront_id: int) -> Bot | None:
        if storefront_id not in self.bots:
            async with get_db_session() as session:
                token = await MultibotService.get_token(storefront_id, session)
            if token is None:
                return None
            self.bots[storefront_id] = create_bot(token, session=self.session)
        return self.bots[storefront_id]


storefront_bot_cache = StorefrontBotCache()


class MultibotService:
    """Pool of storefront bots that share one database.

    Every customer is pinned to one storefront bot. When a storefront gets banned, its customers are
    moved to the least loaded active storefront and the main bot sends them the new link.
    Tokens are stored encrypted in PostgreSQL; webhooks use /webhook/bot/{storefront_id}.
    """
    SEND_DELAY_SECONDS = 0.3
    RELOCATION_NOTIFY_DELAY_SECONDS = 0.05

    @staticmethod
    def build_bot(token: str) -> Bot:
        return create_bot(token)

    @staticmethod
    def webhook_url(webhook_url_template: str, storefront_id: int) -> str:
        return webhook_url_template.format(bot_id=storefront_id)

    @staticmethod
    async def _set_webhook(bot: Bot, storefront_id: int, webhook_url_template: str) -> None:
        await bot.set_webhook(MultibotService.webhook_url(webhook_url_template, storefront_id),
                              secret_token=webhook_secret(storefront_id))

    @staticmethod
    async def add_bot(token: str, webhook_url_template: str,
                      session: AsyncSession | Session) -> tuple[str, StorefrontBot | None]:
        if token == config.TOKEN:
            return AddBotResult.MAIN_TOKEN, None
        if await StorefrontBotRepository.get_by_token_hash(token_hash(token), session):
            return AddBotResult.DUPLICATE, None
        bot = MultibotService.build_bot(token)
        try:
            try:
                bot_user = await bot.get_me()
            except TelegramUnauthorizedError:
                return AddBotResult.INVALID, None
            existing = await StorefrontBotRepository.get_by_telegram_bot_id(bot_user.id, session)
            if existing:
                # Same bot with a re-issued token: keep its customers, store the new token.
                existing.token_encrypted = encrypt_token(token)
                existing.token_hash = token_hash(token)
                existing.username = bot_user.username
                existing.status = StorefrontStatus.ACTIVE
                storefront = existing
            else:
                storefront = await StorefrontBotRepository.create(StorefrontBot(
                    telegram_bot_id=bot_user.id,
                    username=bot_user.username,
                    token_encrypted=encrypt_token(token),
                    token_hash=token_hash(token),
                    status=StorefrontStatus.ACTIVE,
                ), session)
            await session_commit(session)
            await bot.delete_webhook(drop_pending_updates=True)
            await MultibotService._set_webhook(bot, storefront.id, webhook_url_template)
            return AddBotResult.ADDED, storefront
        finally:
            await bot.session.close()

    @staticmethod
    async def get_token(storefront_id: int, session: AsyncSession | Session) -> str | None:
        storefront = await StorefrontBotRepository.get_by_id(storefront_id, session)
        if storefront is None or storefront.status != StorefrontStatus.ACTIVE:
            return None
        return decrypt_token(storefront.token_encrypted)

    @staticmethod
    async def get_all_tokens() -> list[str]:
        """Main bot token followed by the tokens of all active storefronts."""
        async with get_db_session() as session:
            storefronts = await StorefrontBotRepository.get_active(session)
            return [config.TOKEN] + [decrypt_token(storefront.token_encrypted) for storefront in storefronts]

    @staticmethod
    async def assign_storefront(telegram_id: int, session: AsyncSession | Session) -> StorefrontBot | None:
        """Returns the customer's storefront, pinning them to the least loaded one if needed."""
        current = await StorefrontBotRepository.get_user_storefront(telegram_id, session)
        if current is not None and current.status == StorefrontStatus.ACTIVE:
            return current
        active = await StorefrontBotRepository.get_active(session)
        counts = await StorefrontBotRepository.get_user_counts(session)
        storefront = StorefrontBotRepository.pick_least_loaded(active, counts)
        if storefront is not None:
            await StorefrontBotRepository.assign_user(telegram_id, storefront.id, session)
            await session_commit(session)
        return storefront

    @staticmethod
    async def ban_and_relocate(storefront_id: int, session: AsyncSession | Session) -> list[Relocation]:
        """Marks a storefront as banned and spreads its customers over the remaining storefronts."""
        await StorefrontBotRepository.set_status(storefront_id, StorefrontStatus.BANNED, session)
        telegram_ids = await StorefrontBotRepository.get_user_telegram_ids(storefront_id, session)
        active = await StorefrontBotRepository.get_active(session)
        counts = await StorefrontBotRepository.get_user_counts(session)
        counts.pop(storefront_id, None)
        relocations = []
        for telegram_id in telegram_ids:
            target = StorefrontBotRepository.pick_least_loaded(active, counts, exclude_id=storefront_id)
            if target is not None:
                await StorefrontBotRepository.assign_user(telegram_id, target.id, session)
                counts[target.id] = counts.get(target.id, 0) + 1
            relocations.append(Relocation(telegram_id=telegram_id, storefront=target))
        await session_commit(session)
        return relocations

    @staticmethod
    async def get_languages(telegram_ids: list[int], session: AsyncSession | Session) -> dict:
        from sqlalchemy import select
        from db import session_execute
        from models.user import User
        if not telegram_ids:
            return {}
        result = await session_execute(
            select(User.telegram_id, User.language).where(User.telegram_id.in_(telegram_ids)), session)
        return {telegram_id: language for telegram_id, language in result.all()}

    @staticmethod
    async def notify_relocations(main_bot: Bot, relocations: list[Relocation],
                                 build_message: Callable[[Relocation], tuple[str, object]]) -> int:
        """Sends each relocated customer their new storefront link through the main bot."""
        sent = 0
        for relocation in relocations:
            if relocation.storefront is None:
                continue
            text, markup = build_message(relocation)
            try:
                await main_bot.send_message(relocation.telegram_id, text, reply_markup=markup)
                sent += 1
            except TelegramForbiddenError:
                logging.info(f"User {relocation.telegram_id} has not started the main bot")
            except Exception as exception:
                logging.error(exception)
            await asyncio.sleep(MultibotService.RELOCATION_NOTIFY_DELAY_SECONDS)
        return sent

    @staticmethod
    async def restore_child_bot_webhooks(webhook_url_template: str) -> None:
        async with get_db_session() as session:
            storefronts = await StorefrontBotRepository.get_active(session)
            for storefront in storefronts:
                bot = MultibotService.build_bot(decrypt_token(storefront.token_encrypted))
                try:
                    await bot.get_me()
                    await MultibotService._set_webhook(bot, storefront.id, webhook_url_template)
                except TelegramUnauthorizedError:
                    logging.warning(f"Storefront @{storefront.username} token was revoked, disabling it")
                    await StorefrontBotRepository.set_status(storefront.id, StorefrontStatus.DISABLED, session)
                    await session_commit(session)
                except Exception as exception:
                    logging.error(exception)
                finally:
                    await bot.session.close()

    @staticmethod
    async def _get_delivery_tokens(telegram_id: int, include_all_storefronts: bool,
                                   main_only: bool = False) -> list[tuple[int | None, str]]:
        """Bots to try for a customer, best first: their own storefront, (other storefronts), main bot."""
        if main_only:
            return [(None, config.TOKEN)]
        async with get_db_session() as session:
            own = await StorefrontBotRepository.get_user_storefront(telegram_id, session)
            tokens = []
            if own is not None and own.status == StorefrontStatus.ACTIVE:
                tokens.append((own.id, decrypt_token(own.token_encrypted)))
            if include_all_storefronts:
                for storefront in await StorefrontBotRepository.get_active(session):
                    if own is None or storefront.id != own.id:
                        tokens.append((storefront.id, decrypt_token(storefront.token_encrypted)))
        tokens.append((None, config.TOKEN))
        return tokens

    @staticmethod
    async def _deliver(telegram_id: int, include_all_storefronts: bool,
                       send: Callable[[Bot], Awaitable[object]], main_only: bool = False) -> tuple[int, bool]:
        """Tries bots one by one until one delivers. Returns (success_count, had_only_forbidden_errors)."""
        had_only_forbidden_errors = True
        tokens = await MultibotService._get_delivery_tokens(telegram_id, include_all_storefronts, main_only)
        for index, (storefront_id, token) in enumerate(tokens):
            bot = MultibotService.build_bot(token)
            try:
                await send(bot)
                return 1, False
            except TelegramForbiddenError as exception:
                logging.error(f"TelegramForbiddenError: {exception.message}")
            except TelegramUnauthorizedError:
                had_only_forbidden_errors = False
                if storefront_id is not None:
                    logging.warning(f"Storefront {storefront_id} token was revoked, disabling it")
                    async with get_db_session() as session:
                        await StorefrontBotRepository.set_status(storefront_id, StorefrontStatus.DISABLED, session)
                        await session_commit(session)
            except Exception as exception:
                logging.error(exception)
                had_only_forbidden_errors = False
            finally:
                await bot.session.close()
            if index < len(tokens) - 1:
                await asyncio.sleep(MultibotService.SEND_DELAY_SECONDS)
        return 0, had_only_forbidden_errors

    @staticmethod
    async def send_message_to_user_verbose(text: str,
                                           telegram_id: int,
                                           reply_markup=None,
                                           main_only: bool = False) -> tuple[int, bool]:
        return await MultibotService._deliver(
            telegram_id, False,
            lambda bot: bot.send_message(telegram_id, text, reply_markup=reply_markup),
            main_only
        )

    @staticmethod
    def extract_content(message) -> dict:
        """What to re-send of an admin's message. Copying by message id only works inside one bot's chat,
        so broadcasts through other bots send the content itself (file ids are relayed between bots)."""
        for kind in ("photo", "video", "animation", "document"):
            media = getattr(message, kind, None)
            if media:
                file_id = media[-1].file_id if kind == "photo" else media.file_id
                return {"kind": kind, "file_id": file_id, "text": message.html_text if message.caption else None}
        return {"kind": "text", "text": message.html_text}

    @staticmethod
    async def send_content_to_user(content: dict, telegram_id: int, main_only: bool = False) -> tuple[int, bool]:
        async def send(bot: Bot):
            match content["kind"]:
                case "photo":
                    return await bot.send_photo(telegram_id, content["file_id"], caption=content["text"])
                case "video":
                    return await bot.send_video(telegram_id, content["file_id"], caption=content["text"])
                case "animation":
                    return await bot.send_animation(telegram_id, content["file_id"], caption=content["text"])
                case "document":
                    return await bot.send_document(telegram_id, content["file_id"], caption=content["text"])
                case _:
                    return await bot.send_message(telegram_id, content["text"])
        return await MultibotService._deliver(telegram_id, False, send, main_only)

    @staticmethod
    async def send_message_to_user(text: str,
                                   telegram_id: int,
                                   reply_markup=None) -> int:
        success_count, _ = await MultibotService.send_message_to_user_verbose(
            text=text, telegram_id=telegram_id, reply_markup=reply_markup
        )
        return success_count

    @staticmethod
    async def copy_message_to_user(from_chat_id: int,
                                   message_id: int,
                                   telegram_id: int) -> tuple[int, bool]:
        return await MultibotService._deliver(
            telegram_id, True,
            lambda bot: bot.copy_message(chat_id=telegram_id, from_chat_id=from_chat_id, message_id=message_id)
        )
