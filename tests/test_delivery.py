import pytest

from enums.item_type import ItemType
from enums.language import Language
from models.item import ItemDTO
from services.delivery import DeliveryService
from services.photo_stock import PhotoStockService


class _FakeBot:
    def __init__(self, fail_photo=False):
        self.photos, self.messages, self.fail_photo = [], [], fail_photo

    async def send_photo(self, chat_id, photo, caption=None):
        if self.fail_photo:
            raise RuntimeError("boom")
        self.photos.append((chat_id, photo, caption))

    async def send_message(self, chat_id, text):
        self.messages.append((chat_id, text))


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    async def _sleep(delay):
        return None
    monkeypatch.setattr("services.delivery.asyncio.sleep", _sleep)


@pytest.mark.asyncio
async def test_delivers_photo_with_key_and_text_only_items():
    bot = _FakeBot()
    items = [ItemDTO(id=1, item_type=ItemType.DIGITAL, private_data="KEY-1", photo_id="0photo-file-id"),
             ItemDTO(id=2, item_type=ItemType.DIGITAL, private_data="KEY-2"),
             ItemDTO(id=3, item_type=ItemType.PHYSICAL)]

    delivered = await DeliveryService.deliver(bot, 42, items, Language.EN)

    assert delivered == 2
    assert bot.photos[0][0] == 42 and bot.photos[0][1] == "photo-file-id" and "KEY-1" in bot.photos[0][2]
    assert bot.messages[0][0] == 42 and "KEY-2" in bot.messages[0][1]


@pytest.mark.asyncio
async def test_failed_delivery_does_not_raise():
    bot = _FakeBot(fail_photo=True)
    items = [ItemDTO(id=1, item_type=ItemType.DIGITAL, private_data="KEY-1", photo_id="0photo-file-id")]
    assert await DeliveryService.deliver(bot, 42, items, Language.EN) == 0


def test_done_words():
    assert PhotoStockService.is_done_word(" Готово ")
    assert PhotoStockService.is_done_word("done")
    assert not PhotoStockService.is_done_word("KEY-123")
