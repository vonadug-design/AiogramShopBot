from types import SimpleNamespace

import pytest
from aiogram.exceptions import TelegramBadRequest
from aiogram.methods import SendPhoto, SendMessage
from aiogram.types import BufferedInputFile, Message, PhotoSize, Chat

from utils.media_relay import MediaRelayMiddleware


class _FakeRedis:
    def __init__(self):
        self.data = {}

    async def hget(self, key, field):
        return self.data.get((key, field))

    async def hset(self, key, field, value):
        self.data[(key, field)] = value


def _message_with_photo(file_id):
    return Message(message_id=1, date=0, chat=Chat(id=1, type="private"),
                   photo=[PhotoSize(file_id=file_id, file_unique_id="u", width=1, height=1)])


def _middleware(tmp_path, redis, downloads):
    async def _tokens():
        return ["main-token"]

    middleware = MediaRelayMiddleware(redis, str(tmp_path), _tokens)

    async def _load(file_id):
        downloads.append(file_id)
        return b"jpeg-bytes"

    middleware._load_content = _load
    return middleware


@pytest.mark.asyncio
async def test_foreign_file_id_is_reuploaded_and_cached(tmp_path):
    redis, downloads, sent = _FakeRedis(), [], []
    middleware = _middleware(tmp_path, redis, downloads)
    bot = SimpleNamespace(id=555)

    async def _make_request(bot, method):
        sent.append(method.photo)
        if isinstance(method.photo, str) and method.photo == "foreign-id":
            raise TelegramBadRequest(method=method, message="Bad Request: wrong file identifier/HTTP URL specified")
        return SimpleNamespace(result=_message_with_photo("own-id"))

    method = SendPhoto(chat_id=1, photo="foreign-id")
    await middleware(_make_request, bot, method)

    assert sent[0] == "foreign-id"
    assert isinstance(sent[1], BufferedInputFile)
    assert redis.data[("media_relay:555", "foreign-id")] == "own-id"
    assert method.photo == "foreign-id"

    sent.clear()
    await middleware(_make_request, bot, SendPhoto(chat_id=1, photo="foreign-id"))
    assert sent == ["own-id"]
    assert downloads == ["foreign-id"]


@pytest.mark.asyncio
async def test_other_errors_and_methods_pass_through(tmp_path):
    redis, downloads = _FakeRedis(), []
    middleware = _middleware(tmp_path, redis, downloads)

    async def _fail(bot, method):
        raise TelegramBadRequest(method=method, message="Bad Request: chat not found")

    with pytest.raises(TelegramBadRequest):
        await middleware(_fail, SimpleNamespace(id=1), SendPhoto(chat_id=1, photo="any-id"))
    assert downloads == []

    async def _ok(bot, method):
        return "ok"

    assert await middleware(_ok, SimpleNamespace(id=1), SendMessage(chat_id=1, text="hi")) == "ok"
