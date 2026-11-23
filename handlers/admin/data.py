"""Admin menu -> Data (owners only): user numbers, the list of everyone who pressed /start, database copies."""
import datetime

from aiogram import Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, BufferedInputFile
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy.ext.asyncio import AsyncSession

from callbacks import DataCallback
from enums.bot_entity import BotEntity
from enums.language import Language
from enums.staff_role import Permission
from handlers.admin.constants import AdminConstants
from services.backup import BackupService
from services.user_export import UserExportService
from utils.custom_filters import AdminIdFilter
from utils.utils import get_text

data_router = Router()


def _t(language: Language, key: str) -> str:
    return get_text(language, BotEntity.ADMIN, key)


@data_router.callback_query(AdminIdFilter(Permission.STAFF), DataCallback.filter())
async def data_menu(callback: CallbackQuery, callback_data: DataCallback, session: AsyncSession,
                    language: Language):
    if callback_data.action == "users_csv":
        content = await UserExportService.build_csv(session)
        name = f"users-{datetime.date.today().isoformat()}.csv"
        await callback.answer()
        return await callback.message.answer_document(BufferedInputFile(content, name),
                                                      caption=_t(language, "data_users_file"))
    if callback_data.action == "backup_now":
        if BackupService.request_now():
            await callback.answer(_t(language, "data_backup_requested"), show_alert=True)
        else:
            return await callback.answer(_t(language, "data_backup_unavailable"), show_alert=True)
    stats = await UserExportService.get_stats(session)
    copies = BackupService.list_copies()
    last_copy = copies[-1].name if copies else "—"
    text = _t(language, "data_menu").format(last_copy=last_copy, copies=len(copies), **stats)
    kb_builder = InlineKeyboardBuilder()
    kb_builder.button(text=_t(language, "data_users_button"), callback_data=DataCallback(action="users_csv"))
    kb_builder.button(text=_t(language, "data_backup_button"), callback_data=DataCallback(action="backup_now"))
    kb_builder.adjust(1)
    kb_builder.row(AdminConstants.back_to_main_button(language))
    try:
        await callback.message.edit_text(text, reply_markup=kb_builder.as_markup())
    except TelegramBadRequest as exception:
        if "message is not modified" not in str(exception):
            raise
