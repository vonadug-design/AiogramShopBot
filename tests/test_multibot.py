from types import SimpleNamespace

import pytest
from aiogram.exceptions import TelegramUnauthorizedError

import config
from enums.announcement_type import AnnouncementType
from enums.language import Language
from models.user import UserDTO
from services.announcement import AnnouncementService
from enums.storefront_status import StorefrontStatus
from repositories.storefront_bot import StorefrontBotRepository
from services.multibot import MultibotService, AddBotResult
from utils.token_crypto import decrypt_token, encrypt_token, webhook_secret
from services.notification import NotificationService


class _FakeRedis:
    def __init__(self):
        self.values = set()
        self.closed = False

    async def smembers(self, key):
        return set(self.values)

    async def sismember(self, key, value):
        return value in self.values

    async def sadd(self, key, value):
        initial_len = len(self.values)
        self.values.add(value)
        return 1 if len(self.values) != initial_len else 0

    async def srem(self, key, value):
        self.values.discard(value)
        return 1

    async def close(self):
        self.closed = True


class _FakeSession:
    async def close(self):
        return None


class _FakeBot:
    def __init__(self, token, behavior=None):
        self.token = token
        self.behavior = behavior or {}
        self.session = _FakeSession()
        self.sent_messages = []
        self.copied_messages = []
        self.webhooks = []

    async def get_me(self):
        action = self.behavior.get("get_me")
        if isinstance(action, Exception):
            raise action
        username = self.behavior.get("username", "child_bot")
        return SimpleNamespace(id=self.behavior.get("id", 4242), username=username)

    async def set_webhook(self, url, **kwargs):
        action = self.behavior.get("set_webhook")
        if isinstance(action, Exception):
            raise action
        self.webhooks.append((url, kwargs))

    async def delete_webhook(self, **kwargs):
        self.webhooks.append(("delete", kwargs))

    async def send_message(self, chat_id, text, reply_markup=None):
        action = self.behavior.get("send_message")
        if isinstance(action, Exception):
            raise action
        self.sent_messages.append((chat_id, text, reply_markup))

    async def copy_message(self, chat_id, from_chat_id, message_id):
        action = self.behavior.get("copy_message")
        if isinstance(action, Exception):
            raise action
        self.copied_messages.append((chat_id, from_chat_id, message_id))


class _FakeMessage:
    def __init__(self):
        self.answers = []
        self.chat = SimpleNamespace(id=77)
        self.message_id = 501

    async def answer(self, text):
        self.answers.append(text)
        return SimpleNamespace(message_id=900, chat=SimpleNamespace(id=123))

    async def edit_reply_markup(self):
        return None


class _FakeCallback:
    def __init__(self):
        self.message = _FakeMessage()
        self.bot = _FakeBot("main-token")


TEST_FERNET_KEY = "ytaVe5Hyz5mwOug_TCw8lbN_hoEZtogpkN7aBmFSzGI="


@pytest.fixture(autouse=True)
def _multibot_config(monkeypatch):
    monkeypatch.setattr("config.BOT_TOKEN_ENCRYPTION_KEY", TEST_FERNET_KEY, raising=False)
    monkeypatch.setattr("config.STOREFRONT_MAX_USERS", 2, raising=False)
    monkeypatch.setattr("config.WEBHOOK_SECRET_TOKEN", None, raising=False)


def _storefront(storefront_id, username, status=StorefrontStatus.ACTIVE, max_users=None, token="1:child"):
    return SimpleNamespace(id=storefront_id, telegram_bot_id=1000 + storefront_id, username=username,
                           token_encrypted=encrypt_token(token), token_hash=str(storefront_id),
                           status=status, max_users=max_users)


class _NullDbSession:
    async def __aenter__(self):
        return object()

    async def __aexit__(self, *args):
        return False


def test_token_encryption_roundtrip():
    encrypted = encrypt_token("123:secret")
    assert "secret" not in encrypted
    assert decrypt_token(encrypted) == "123:secret"
    assert webhook_secret(1) != webhook_secret(2)


def test_pick_least_loaded_respects_capacity_and_exclusion():
    first, second, third = _storefront(1, "a"), _storefront(2, "b"), _storefront(3, "c", max_users=5)
    counts = {1: 2, 2: 1, 3: 4}
    assert StorefrontBotRepository.pick_least_loaded([first, second, third], counts).id == 2
    assert StorefrontBotRepository.pick_least_loaded([first, second, third], counts, exclude_id=2).id == 3
    assert StorefrontBotRepository.pick_least_loaded([first], counts) is None


@pytest.mark.asyncio
async def test_add_bot_rejects_main_token_and_duplicates(monkeypatch):
    result, _ = await MultibotService.add_bot(config.TOKEN, "https://example.com/webhook/bot/{bot_id}", object())
    assert result == AddBotResult.MAIN_TOKEN

    async def _fake_get_by_token_hash(hashed, session):
        return _storefront(1, "a")

    monkeypatch.setattr("services.multibot.StorefrontBotRepository.get_by_token_hash", _fake_get_by_token_hash)
    result, _ = await MultibotService.add_bot("1:child", "https://example.com/webhook/bot/{bot_id}", object())
    assert result == AddBotResult.DUPLICATE


@pytest.mark.asyncio
async def test_add_bot_stores_encrypted_token_and_sets_secret_webhook(monkeypatch):
    created_bots = []
    saved = []

    async def _none(*args, **kwargs):
        return None

    async def _fake_create(storefront, session):
        storefront.id = 7
        saved.append(storefront)
        return storefront

    def _fake_build_bot(token):
        bot = _FakeBot(token, {"username": "shop_seven_bot"})
        created_bots.append(bot)
        return bot

    monkeypatch.setattr("services.multibot.StorefrontBotRepository.get_by_token_hash", _none)
    monkeypatch.setattr("services.multibot.StorefrontBotRepository.get_by_telegram_bot_id", _none)
    monkeypatch.setattr("services.multibot.StorefrontBotRepository.create", _fake_create)
    monkeypatch.setattr("services.multibot.StorefrontBot", lambda **kwargs: SimpleNamespace(**kwargs))
    monkeypatch.setattr("services.multibot.session_commit", _none)
    monkeypatch.setattr("services.multibot.MultibotService.build_bot", _fake_build_bot)

    result, storefront = await MultibotService.add_bot("777:child-secret",
                                                       "https://example.com/webhook/bot/{bot_id}", object())

    assert result == AddBotResult.ADDED
    assert storefront.username == "shop_seven_bot"
    assert "child-secret" not in saved[0].token_encrypted
    assert decrypt_token(saved[0].token_encrypted) == "777:child-secret"
    url, kwargs = created_bots[0].webhooks[-1]
    assert url == "https://example.com/webhook/bot/7"
    assert "child-secret" not in url
    assert kwargs["secret_token"] == webhook_secret(7)


@pytest.mark.asyncio
async def test_add_bot_reports_invalid_token(monkeypatch):
    async def _none(*args, **kwargs):
        return None

    monkeypatch.setattr("services.multibot.StorefrontBotRepository.get_by_token_hash", _none)
    monkeypatch.setattr("services.multibot.MultibotService.build_bot",
                        lambda token: _FakeBot(token, {"get_me": TelegramUnauthorizedError(method=None, message="bad")}))

    result, storefront = await MultibotService.add_bot("1:bad", "https://example.com/webhook/bot/{bot_id}", object())

    assert result == AddBotResult.INVALID
    assert storefront is None


@pytest.mark.asyncio
async def test_ban_and_relocate_spreads_customers(monkeypatch):
    banned, second, third = _storefront(1, "a"), _storefront(2, "b"), _storefront(3, "c")
    assignments = {}
    statuses = {}

    async def _fake_set_status(storefront_id, status, session):
        statuses[storefront_id] = status
        banned.status = status

    async def _fake_get_ids(storefront_id, session):
        return [11, 12, 13, 14, 15]

    async def _fake_get_active(session):
        return [s for s in (banned, second, third) if s.status == StorefrontStatus.ACTIVE]

    async def _fake_counts(session):
        return {1: 5, 2: 1, 3: 0}

    async def _fake_assign(telegram_id, storefront_id, session):
        assignments[telegram_id] = storefront_id

    async def _none(*args, **kwargs):
        return None

    monkeypatch.setattr("services.multibot.StorefrontBotRepository.set_status", _fake_set_status)
    monkeypatch.setattr("services.multibot.StorefrontBotRepository.get_user_telegram_ids", _fake_get_ids)
    monkeypatch.setattr("services.multibot.StorefrontBotRepository.get_active", _fake_get_active)
    monkeypatch.setattr("services.multibot.StorefrontBotRepository.get_user_counts", _fake_counts)
    monkeypatch.setattr("services.multibot.StorefrontBotRepository.assign_user", _fake_assign)
    monkeypatch.setattr("services.multibot.session_commit", _none)

    relocations = await MultibotService.ban_and_relocate(1, object())

    assert statuses == {1: StorefrontStatus.BANNED}
    # capacity is 2 per storefront: b has 1 free slot, c has 2, the rest stay unplaced
    assert sorted(assignments.values()) == [2, 3, 3]
    assert [r.storefront is None for r in relocations].count(True) == 2


@pytest.mark.asyncio
async def test_notify_relocations_skips_unplaced_and_forbidden(monkeypatch):
    from aiogram.exceptions import TelegramForbiddenError
    from services.multibot import Relocation

    async def _no_sleep(delay):
        return None

    monkeypatch.setattr("services.multibot.asyncio.sleep", _no_sleep)
    main_bot = _FakeBot("main")
    target = _storefront(2, "b")
    relocations = [Relocation(11, target), Relocation(12, None)]

    sent = await MultibotService.notify_relocations(main_bot, relocations, lambda r: ("moved", None))

    assert sent == 1
    assert main_bot.sent_messages == [(11, "moved", None)]

    blocked_bot = _FakeBot("main", {"send_message": TelegramForbiddenError(method=None, message="blocked")})
    assert await MultibotService.notify_relocations(blocked_bot, relocations, lambda r: ("moved", None)) == 0


@pytest.mark.asyncio
async def test_send_to_user_prefers_own_storefront_then_main(monkeypatch):
    from aiogram.exceptions import TelegramForbiddenError
    built = []

    async def _fake_tokens(telegram_id, include_all_storefronts):
        return [(2, "storefront-token"), (None, "main-token")]

    async def _no_sleep(delay):
        return None

    def _fake_build_bot(token):
        behavior = {"send_message": TelegramForbiddenError(method=None, message="blocked")} \
            if token == "storefront-token" else {}
        bot = _FakeBot(token, behavior)
        built.append(bot)
        return bot

    monkeypatch.setattr("services.multibot.MultibotService._get_delivery_tokens", _fake_tokens)
    monkeypatch.setattr("services.multibot.MultibotService.build_bot", _fake_build_bot)
    monkeypatch.setattr("services.multibot.asyncio.sleep", _no_sleep)

    sent, only_forbidden = await MultibotService.send_message_to_user_verbose("hello", 100500)

    assert (sent, only_forbidden) == (1, False)
    assert [bot.token for bot in built] == ["storefront-token", "main-token"]
    assert built[1].sent_messages == [(100500, "hello", None)]


@pytest.mark.asyncio
async def test_send_to_user_reports_only_forbidden(monkeypatch):
    from aiogram.exceptions import TelegramForbiddenError

    async def _fake_tokens(telegram_id, include_all_storefronts):
        return [(None, "main-token")]

    monkeypatch.setattr("services.multibot.MultibotService._get_delivery_tokens", _fake_tokens)
    monkeypatch.setattr("services.multibot.MultibotService.build_bot",
                        lambda token: _FakeBot(token, {"send_message": TelegramForbiddenError(method=None, message="x")}))

    assert await MultibotService.send_message_to_user_verbose("hello", 1) == (0, True)


@pytest.mark.asyncio
async def test_storefront_cache_builds_bot_once_and_forgets(monkeypatch):
    from services.multibot import StorefrontBotCache
    built = []

    async def _fake_get_token(storefront_id, session):
        return None if storefront_id == 9 else "5:token"

    monkeypatch.setattr("services.multibot.MultibotService.get_token", _fake_get_token)
    monkeypatch.setattr("services.multibot.get_db_session", lambda: _NullDbSession())
    monkeypatch.setattr("services.multibot.create_bot", lambda token, session=None: built.append(token) or token)
    cache = StorefrontBotCache()

    assert await cache.get(1) == "5:token"
    assert await cache.get(1) == "5:token"
    assert built == ["5:token"]
    assert await cache.get(9) is None
    cache.forget(1)
    await cache.get(1)
    assert len(built) == 2


@pytest.mark.asyncio
async def test_notification_service_send_to_user_uses_multibot_service(monkeypatch):
    called = []
    monkeypatch.setattr("config.MULTIBOT", True)

    async def _fake_send_message_to_user(message, telegram_id, reply_markup=None):
        called.append((message, telegram_id, reply_markup))
        return 2

    monkeypatch.setattr("services.notification.MultibotService.send_message_to_user", _fake_send_message_to_user)

    await NotificationService.send_to_user("hello", 42)

    assert called == [("hello", 42, None)]


@pytest.mark.asyncio
async def test_announcement_service_counts_multibot_successes(monkeypatch):
    callback = _FakeCallback()
    updates = []
    user = UserDTO(telegram_id=777, can_receive_messages=True)

    monkeypatch.setattr("config.MULTIBOT", True)
    
    async def _fake_get_active(session):
        return [user]

    async def _fake_get_all_count(session):
        return 1

    async def _fake_create_announcement_message(announcement_type, session, language):
        return ["chunk-1", "chunk-2"]

    async def _fake_send_message_to_user_verbose(text, telegram_id, reply_markup=None, redis_client=None):
        return 2, False

    async def _fake_edit_message(message, source_message_id, chat_id):
        updates.append(message)

    async def _fake_session_commit(session):
        return None

    monkeypatch.setattr("services.announcement.UserRepository.get_active", _fake_get_active)
    monkeypatch.setattr("services.announcement.UserRepository.get_all_count", _fake_get_all_count)
    monkeypatch.setattr("services.announcement.ItemService.create_announcement_message", _fake_create_announcement_message)
    monkeypatch.setattr("services.announcement.MultibotService.send_message_to_user_verbose",
                        _fake_send_message_to_user_verbose)
    monkeypatch.setattr("services.announcement.NotificationService.edit_message", _fake_edit_message)
    monkeypatch.setattr("services.announcement.session_commit", _fake_session_commit)

    await AnnouncementService.send_announcement(
        callback,
        SimpleNamespace(announcement_type=AnnouncementType.CURRENT_STOCK),
        object(),
        Language.EN
    )

    assert any("1" in message for message in updates)


@pytest.mark.asyncio
async def test_announcement_service_marks_user_inactive_when_all_multibot_attempts_forbidden(monkeypatch):
    callback = _FakeCallback()
    updated_users = []
    user = UserDTO(telegram_id=777, can_receive_messages=True)

    monkeypatch.setattr("config.MULTIBOT", True)
    
    async def _fake_get_active(session):
        return [user]

    async def _fake_get_all_count(session):
        return 1

    async def _fake_create_announcement_message(announcement_type, session, language):
        return ["chunk-1", "chunk-2"]

    async def _fake_send_message_to_user_verbose(text, telegram_id, reply_markup=None, redis_client=None):
        return 0, True

    async def _fake_update(user_dto, session):
        updated_users.append(user_dto)

    async def _fake_edit_message(message, source_message_id, chat_id):
        return None

    async def _fake_session_commit(session):
        return None

    monkeypatch.setattr("services.announcement.UserRepository.get_active", _fake_get_active)
    monkeypatch.setattr("services.announcement.UserRepository.get_all_count", _fake_get_all_count)
    monkeypatch.setattr("services.announcement.ItemService.create_announcement_message", _fake_create_announcement_message)
    monkeypatch.setattr("services.announcement.MultibotService.send_message_to_user_verbose",
                        _fake_send_message_to_user_verbose)
    monkeypatch.setattr("services.announcement.UserRepository.update", _fake_update)
    monkeypatch.setattr("services.announcement.NotificationService.edit_message", _fake_edit_message)
    monkeypatch.setattr("services.announcement.session_commit", _fake_session_commit)

    await AnnouncementService.send_announcement(
        callback,
        SimpleNamespace(announcement_type=AnnouncementType.CURRENT_STOCK),
        object(),
        Language.EN
    )

    assert updated_users
    assert updated_users[0].can_receive_messages is False


@pytest.mark.asyncio
async def test_announcement_service_marks_restocking_not_new_once(monkeypatch):
    callback = _FakeCallback()
    set_not_new_calls = []
    user = UserDTO(telegram_id=777, can_receive_messages=True)

    monkeypatch.setattr("config.MULTIBOT", True)

    async def _fake_get_active(session):
        return [user, user]

    async def _fake_get_all_count(session):
        return 2

    async def _fake_create_announcement_message(announcement_type, session, language):
        return ["chunk-1"]

    async def _fake_send_message_to_user_verbose(text, telegram_id, reply_markup=None, redis_client=None):
        return 1, False

    async def _fake_set_not_new(session):
        set_not_new_calls.append(True)

    async def _fake_edit_message(message, source_message_id, chat_id):
        return None

    async def _fake_session_commit(session):
        return None

    monkeypatch.setattr("services.announcement.UserRepository.get_active", _fake_get_active)
    monkeypatch.setattr("services.announcement.UserRepository.get_all_count", _fake_get_all_count)
    monkeypatch.setattr("services.announcement.ItemService.create_announcement_message", _fake_create_announcement_message)
    monkeypatch.setattr("services.announcement.MultibotService.send_message_to_user_verbose",
                        _fake_send_message_to_user_verbose)
    monkeypatch.setattr("services.announcement.ItemRepository.set_not_new", _fake_set_not_new)
    monkeypatch.setattr("services.announcement.NotificationService.edit_message", _fake_edit_message)
    monkeypatch.setattr("services.announcement.session_commit", _fake_session_commit)

    await AnnouncementService.send_announcement(
        callback,
        SimpleNamespace(announcement_type=AnnouncementType.RESTOCKING),
        object(),
        Language.EN
    )

    assert len(set_not_new_calls) == 1
