"""Database copies made by the "backup" container (scripts/backup.sh): asks for a copy, and sends each new copy
to the owners in Telegram, so a copy survives even if the server is lost."""
import asyncio
import logging
import os
from pathlib import Path

from aiogram.types import FSInputFile

import config
from enums.bot_entity import BotEntity
from utils.telegram import create_bot
from utils.utils import get_text

BACKUP_DIR = Path(os.environ.get("BACKUP_DIR", "/backups"))
CHECK_EVERY_SECONDS = 120
TELEGRAM_FILE_LIMIT = 49 * 1024 * 1024


class BackupService:

    @staticmethod
    def is_available() -> bool:
        return BACKUP_DIR.is_dir()

    @staticmethod
    def list_copies() -> list[Path]:
        if not BackupService.is_available():
            return []
        return sorted(BACKUP_DIR.glob("db-*.sql.gz"))

    @staticmethod
    def request_now() -> bool:
        if not BackupService.is_available():
            return False
        (BACKUP_DIR / ".request").write_text("1")
        return True

    @staticmethod
    def _last_sent() -> str:
        marker = BACKUP_DIR / ".sent"
        return marker.read_text().strip() if marker.exists() else ""

    @staticmethod
    async def send_new_copies(send_document=None, send_message=None) -> int:
        """Sends the newest copy not sent yet to every owner. Returns the number of files sent."""
        copies = BackupService.list_copies()
        from services.notification import NotificationService, _admin_language
        admin_language = _admin_language()
        failed_marker = BACKUP_DIR / ".failed"
        bot = None
        try:
            if failed_marker.exists():
                failed_marker.unlink()
                await (send_message or NotificationService.send_to_admins)(
                    get_text(admin_language, BotEntity.ADMIN, "backup_failed"), None)
            if not copies or copies[-1].name <= BackupService._last_sent():
                return 0
            newest = copies[-1]
            (BACKUP_DIR / ".sent").write_text(newest.name)
            caption = get_text(admin_language, BotEntity.ADMIN, "backup_caption").format(name=newest.name)
            if newest.stat().st_size > TELEGRAM_FILE_LIMIT:
                await (send_message or NotificationService.send_to_admins)(
                    get_text(admin_language, BotEntity.ADMIN, "backup_too_big").format(name=newest.name), None)
                return 0
            sent = 0
            if send_document is None:
                bot = create_bot(config.TOKEN)

                async def send_document(chat_id, path, text):
                    await bot.send_document(chat_id, FSInputFile(path), caption=text)
            for owner_id in config.ADMIN_ID_LIST:
                try:
                    await send_document(owner_id, str(newest), caption)
                    sent += 1
                except Exception as exception:
                    logging.warning(f"Backup was not sent to {owner_id}: {exception}")
            return sent
        finally:
            if bot is not None:
                await bot.session.close()

    @staticmethod
    async def run_forever():
        while True:
            try:
                if BackupService.is_available():
                    await BackupService.send_new_copies()
            except Exception as exception:
                logging.error(f"Backup sending failed: {exception}")
            await asyncio.sleep(CHECK_EVERY_SECONDS)
