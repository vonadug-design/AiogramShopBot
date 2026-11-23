import asyncio
import logging

from aiogram import Bot

from enums.bot_entity import BotEntity
from enums.item_type import ItemType
from enums.language import Language
from models.item import ItemDTO
from services.media import MediaService
from utils.utils import get_text


class DeliveryService:
    """Sends each purchased digital unit to the buyer: its own photo with the key as the caption."""
    SEND_DELAY_SECONDS = 0.05

    @staticmethod
    def build_caption(item: ItemDTO, number: int, language: Language) -> str:
        return get_text(language, BotEntity.USER, "delivered_item").format(
            count=number, private_data=item.private_data or "")

    @staticmethod
    async def deliver(bot: Bot, telegram_id: int, items: list[ItemDTO], language: Language) -> int:
        delivered = 0
        digital_items = [item for item in items if item.item_type != ItemType.PHYSICAL]
        for number, item in enumerate(digital_items, start=1):
            caption = DeliveryService.build_caption(item, number, language)
            try:
                if item.photo_id:
                    media = MediaService.convert_to_media(item.photo_id, caption)
                    await bot.send_photo(telegram_id, media.media, caption=caption)
                else:
                    await bot.send_message(telegram_id, caption)
                delivered += 1
            except Exception as exception:
                # The purchase is already saved; the buyer still sees the keys in purchase history
                logging.error(f"Delivery of item {item.id} failed: {exception}")
            await asyncio.sleep(DeliveryService.SEND_DELAY_SECONDS)
        return delivered
