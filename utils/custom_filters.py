from aiogram import types
from aiogram.filters import BaseFilter
from aiogram.types import Message

from enums.staff_role import Permission
from db import get_db_session
from models.user import UserDTO
from repositories.user import UserRepository
from services.user import UserService


class AdminIdFilter(BaseFilter):
    """Passes staff members whose role has the given permission (any staff member if permission is None)."""

    def __init__(self, permission: Permission | None = None):
        self.permission = permission

    async def __call__(self, message: types.message):
        from services.staff import StaffService
        return await StaffService.can(message.from_user.id, self.permission)


class IsUserExistFilter(BaseFilter):
    async def __call__(self, message: Message) -> bool:
        async with get_db_session() as session:
            is_exist = await UserService.get(UserDTO(telegram_id=message.from_user.id), session)
            return is_exist is not None


class IsUserBannedFilter(BaseFilter):
    async def __call__(self, message: Message):
        async with get_db_session() as session:
            user = await UserRepository.get_by_tgid(message.from_user.id, session)
            if user:
                return user.is_banned and user.is_admin is False
            else:
                return False
