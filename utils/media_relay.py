import hashlib
import logging
from pathlib import Path
from typing import Awaitable, Callable

from aiogram import Bot
from aiogram.client.session.middlewares.base import BaseRequestMiddleware, NextRequestMiddlewareType
from aiogram.exceptions import TelegramBadRequest
from aiogram.methods import SendPhoto, SendVideo, SendAnimation, SendDocument, EditMessageMedia, TelegramMethod
from aiogram.methods.base import Response, TelegramType
from aiogram.types import BufferedInputFile, Message

from utils.telegram import create_bot

TokenProvider = Callable[[], Awaitable[list[str]]]

_FOREIGN_FILE_ERRORS = ("wrong file identifier", "wrong remote file identifier", "file reference",
                        "wrong type of the web page content", "failed to get http url content")


class MediaRelayMiddleware(BaseRequestMiddleware):
    """Makes media uploaded through one bot usable in every bot.

    Telegram file_ids belong to the bot that received the file. When a storefront bot gets a foreign
    file_id, the file is downloaded once (through whichever bot owns it), kept on disk, re-uploaded,
    and the storefront's own file_id is cached in Redis for next time.
    """

    def __init__(self, redis, media_dir: str, token_provider: TokenProvider):
        self.redis = redis
        self.media_dir = Path(media_dir)
        self.token_provider = token_provider

    @staticmethod
    def _target(method: TelegramMethod) -> tuple[object, str, str] | None:
        match method:
            case SendPhoto():
                return method, "photo", "photo.jpg"
            case SendVideo():
                return method, "video", "video.mp4"
            case SendAnimation():
                return method, "animation", "animation.mp4"
            case SendDocument():
                return method, "document", "document"
            case EditMessageMedia():
                filename = {"photo": "photo.jpg", "video": "video.mp4", "animation": "animation.mp4"}
                return method.media, "media", filename.get(getattr(method.media, "type", ""), "document")
        return None

    @staticmethod
    def _is_foreign_file_error(error: TelegramBadRequest) -> bool:
        message = (error.message or "").lower()
        return any(marker in message for marker in _FOREIGN_FILE_ERRORS)

    @staticmethod
    def _extract_file_id(result: object) -> str | None:
        if not isinstance(result, Message):
            return None
        if result.photo:
            return result.photo[-1].file_id
        for attachment in (result.video, result.animation, result.document):
            if attachment is not None:
                return attachment.file_id
        return None

    def _cache_key(self, bot: Bot) -> str:
        return f"media_relay:{bot.id}"

    def _path(self, file_id: str) -> Path:
        return self.media_dir / hashlib.sha256(file_id.encode()).hexdigest()

    async def _load_content(self, file_id: str) -> bytes | None:
        path = self._path(file_id)
        if path.exists():
            return path.read_bytes()
        for token in await self.token_provider():
            owner = create_bot(token)
            try:
                buffer = await owner.download(file_id)
            except Exception:
                continue
            finally:
                await owner.session.close()
            if buffer is None:
                continue
            content = buffer.read()
            self.media_dir.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
            return content
        logging.error("Media relay: no bot could download the file")
        return None

    async def __call__(self, make_request: NextRequestMiddlewareType[TelegramType], bot: Bot,
                       method: TelegramMethod[TelegramType]) -> Response[TelegramType]:
        target = self._target(method)
        if target is None:
            return await make_request(bot, method)
        holder, attribute, filename = target
        original = getattr(holder, attribute, None)
        if not isinstance(original, str) or original.startswith(("http://", "https://")):
            return await make_request(bot, method)
        cached = await self.redis.hget(self._cache_key(bot), original)
        if cached:
            setattr(holder, attribute, cached.decode() if isinstance(cached, bytes) else cached)
        try:
            return await make_request(bot, method)
        except TelegramBadRequest as error:
            if not self._is_foreign_file_error(error):
                raise
            content = await self._load_content(original)
            if content is None:
                raise
            setattr(holder, attribute, BufferedInputFile(content, filename=filename))
            response = await make_request(bot, method)
            new_file_id = self._extract_file_id(response.result)
            if new_file_id:
                await self.redis.hset(self._cache_key(bot), original, new_file_id)
            return response
        finally:
            setattr(holder, attribute, original)
