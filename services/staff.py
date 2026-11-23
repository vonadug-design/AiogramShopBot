import time

from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

import config
from db import get_db_session
from enums.staff_role import StaffRole, Permission, ROLE_PERMISSIONS
from models.staff_member import StaffMember


class StaffService:
    """Roles: owner (from ADMIN_ID_LIST), admin and moderator (from the staff_members table)."""
    _cache: dict[int, StaffRole] = {}
    _loaded_at: float | None = None
    CACHE_TTL = 30

    @classmethod
    def invalidate(cls):
        cls._loaded_at = None

    @classmethod
    async def _load(cls, session: AsyncSession | None = None):
        async def _fetch(s: AsyncSession):
            rows = (await s.execute(select(StaffMember))).scalars().all()
            return {row.telegram_id: row.role for row in rows}

        if session is not None:
            cls._cache = await _fetch(session)
        else:
            async with get_db_session() as s:
                cls._cache = await _fetch(s)
        cls._loaded_at = time.monotonic()

    @classmethod
    async def get_role(cls, telegram_id: int, session: AsyncSession | None = None) -> StaffRole | None:
        if telegram_id in config.ADMIN_ID_LIST:
            return StaffRole.OWNER
        if cls._loaded_at is None or time.monotonic() - cls._loaded_at > cls.CACHE_TTL:
            await cls._load(session)
        return cls._cache.get(telegram_id)

    @classmethod
    async def can(cls, telegram_id: int, permission: Permission | None = None,
                  session: AsyncSession | None = None) -> bool:
        role = await cls.get_role(telegram_id, session)
        if role is None:
            return False
        return permission is None or permission in ROLE_PERMISSIONS[role]

    @classmethod
    async def set_role(cls, telegram_id: int, role: StaffRole | None, session: AsyncSession):
        await session.execute(delete(StaffMember).where(StaffMember.telegram_id == telegram_id))
        if role is not None:
            session.add(StaffMember(telegram_id=telegram_id, role=role))
        await session.commit()
        cls.invalidate()

    @classmethod
    async def get_notification_ids(cls) -> list[int]:
        """Owners and admins receive shop notifications (purchases, deposits, errors)."""
        await cls.get_role(0)  # refreshes the cache when it is stale
        admins = [tg_id for tg_id, role in cls._cache.items() if role == StaffRole.ADMIN]
        return list(dict.fromkeys(list(config.ADMIN_ID_LIST) + admins))

    @classmethod
    async def get_all(cls, session: AsyncSession) -> list[tuple[int, StaffRole]]:
        owners = [(tg_id, StaffRole.OWNER) for tg_id in config.ADMIN_ID_LIST]
        rows = (await session.execute(select(StaffMember).order_by(StaffMember.role))).scalars().all()
        return owners + [(row.telegram_id, row.role) for row in rows]
