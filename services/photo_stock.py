import json

from utils.redis_client import get_redis

DONE_WORDS = {"done", "готово", "gatavs", "/done"}


class PhotoStockService:
    """Collects "photo + key" units an admin sends before the price is entered.

    Kept in a Redis list, so photos sent as an album (several messages at once) are not lost.
    """

    @staticmethod
    def _key(admin_id: int) -> str:
        return f"pending_photo_items:{admin_id}"

    @staticmethod
    def media_id_from_message(message) -> str | None:
        if message.photo:
            return f"0{message.photo[-1].file_id}"
        return None

    @staticmethod
    async def add(admin_id: int, photo_id: str, private_data: str) -> int:
        redis = get_redis()
        count = await redis.rpush(PhotoStockService._key(admin_id),
                                  json.dumps({"photo_id": photo_id, "private_data": private_data}))
        await redis.expire(PhotoStockService._key(admin_id), 24 * 3600)
        return count

    @staticmethod
    async def count(admin_id: int) -> int:
        return await get_redis().llen(PhotoStockService._key(admin_id))

    @staticmethod
    async def pop_all(admin_id: int) -> list[dict]:
        redis = get_redis()
        raw = await redis.lrange(PhotoStockService._key(admin_id), 0, -1)
        await redis.delete(PhotoStockService._key(admin_id))
        return [json.loads(entry) for entry in raw]

    @staticmethod
    async def clear(admin_id: int) -> None:
        await get_redis().delete(PhotoStockService._key(admin_id))

    @staticmethod
    def is_done_word(text: str | None) -> bool:
        return (text or "").strip().lower() in DONE_WORDS
