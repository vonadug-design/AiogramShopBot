import datetime

from sqlalchemy import select, func, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

import config
from db import session_execute, session_flush
from enums.storefront_status import StorefrontStatus
from models.storefront_bot import StorefrontBot
from models.user import User


class StorefrontBotRepository:

    @staticmethod
    async def get_by_id(storefront_id: int, session: AsyncSession | Session) -> StorefrontBot | None:
        result = await session_execute(select(StorefrontBot).where(StorefrontBot.id == storefront_id), session)
        return result.scalar()

    @staticmethod
    async def get_by_token_hash(hashed: str, session: AsyncSession | Session) -> StorefrontBot | None:
        result = await session_execute(select(StorefrontBot).where(StorefrontBot.token_hash == hashed), session)
        return result.scalar()

    @staticmethod
    async def get_by_telegram_bot_id(telegram_bot_id: int, session: AsyncSession | Session) -> StorefrontBot | None:
        stmt = select(StorefrontBot).where(StorefrontBot.telegram_bot_id == telegram_bot_id)
        result = await session_execute(stmt, session)
        return result.scalar()

    @staticmethod
    async def get_all(session: AsyncSession | Session) -> list[StorefrontBot]:
        result = await session_execute(select(StorefrontBot).order_by(StorefrontBot.id), session)
        return list(result.scalars().all())

    @staticmethod
    async def get_active(session: AsyncSession | Session) -> list[StorefrontBot]:
        stmt = (select(StorefrontBot)
                .where(StorefrontBot.status == StorefrontStatus.ACTIVE)
                .order_by(StorefrontBot.id))
        result = await session_execute(stmt, session)
        return list(result.scalars().all())

    @staticmethod
    async def create(storefront: StorefrontBot, session: AsyncSession | Session) -> StorefrontBot:
        session.add(storefront)
        await session_flush(session)
        return storefront

    @staticmethod
    async def set_status(storefront_id: int, status: StorefrontStatus, session: AsyncSession | Session) -> None:
        values = {"status": status}
        if status == StorefrontStatus.BANNED:
            values["banned_at"] = datetime.datetime.now(tz=datetime.timezone.utc)
        stmt = update(StorefrontBot).where(StorefrontBot.id == storefront_id).values(**values)
        await session_execute(stmt, session)

    @staticmethod
    async def get_user_counts(session: AsyncSession | Session) -> dict[int, int]:
        stmt = (select(User.storefront_bot_id, func.count(User.id))
                .where(User.storefront_bot_id.is_not(None))
                .group_by(User.storefront_bot_id))
        result = await session_execute(stmt, session)
        return {storefront_id: count for storefront_id, count in result.all()}

    @staticmethod
    def pick_least_loaded(active: list[StorefrontBot], counts: dict[int, int],
                          exclude_id: int | None = None) -> StorefrontBot | None:
        """Active storefront with the fewest customers that still has free capacity."""
        candidates = []
        for storefront in active:
            if storefront.id == exclude_id:
                continue
            capacity = storefront.max_users or config.STOREFRONT_MAX_USERS
            load = counts.get(storefront.id, 0)
            if load < capacity:
                candidates.append((load, storefront.id, storefront))
        if not candidates:
            return None
        return min(candidates, key=lambda item: (item[0], item[1]))[2]

    @staticmethod
    async def get_user_telegram_ids(storefront_id: int, session: AsyncSession | Session) -> list[int]:
        stmt = select(User.telegram_id).where(User.storefront_bot_id == storefront_id).order_by(User.id)
        result = await session_execute(stmt, session)
        return list(result.scalars().all())

    @staticmethod
    async def assign_user(telegram_id: int, storefront_id: int, session: AsyncSession | Session) -> None:
        stmt = update(User).where(User.telegram_id == telegram_id).values(storefront_bot_id=storefront_id)
        await session_execute(stmt, session)

    @staticmethod
    async def get_user_storefront(telegram_id: int, session: AsyncSession | Session) -> StorefrontBot | None:
        stmt = (select(StorefrontBot)
                .join(User, User.storefront_bot_id == StorefrontBot.id)
                .where(User.telegram_id == telegram_id))
        result = await session_execute(stmt, session)
        return result.scalar()
