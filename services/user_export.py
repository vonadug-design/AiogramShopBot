"""Everyone who pressed /start (main bot or a storefront): numbers for the admin menu and a CSV file."""
import csv
import datetime
import io

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from db import session_execute
from models.buy import Buy
from models.storefront_bot import StorefrontBot
from models.user import User

CSV_COLUMNS = ["telegram_id", "username", "language", "registered_at", "balance", "purchases", "spent",
               "storefront", "can_receive_messages", "is_banned"]


class UserExportService:

    @staticmethod
    async def get_stats(session: AsyncSession) -> dict:
        now = datetime.datetime.now(tz=datetime.timezone.utc)
        day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

        async def count(*conditions):
            return (await session_execute(select(func.count(User.id)).where(*conditions), session)).scalar() or 0

        buyers = (await session_execute(select(func.count(func.distinct(Buy.buyer_id))), session)).scalar() or 0
        return {
            "total": await count(),
            "today": await count(User.registered_at >= day_start),
            "week": await count(User.registered_at >= now - datetime.timedelta(days=7)),
            "buyers": buyers,
            "blocked": await count(User.can_receive_messages == False),  # noqa: E712
        }

    @staticmethod
    async def build_csv(session: AsyncSession) -> bytes:
        purchases = {buyer_id: (number, spent) for buyer_id, number, spent in (await session_execute(
            select(Buy.buyer_id, func.count(Buy.id), func.sum(Buy.total_price)).group_by(Buy.buyer_id),
            session)).all()}
        storefronts = {storefront_id: username for storefront_id, username in (await session_execute(
            select(StorefrontBot.id, StorefrontBot.username), session)).all()}
        users = (await session_execute(select(User).order_by(User.id), session)).scalars().all()
        output = io.StringIO()
        writer = csv.writer(output, delimiter=";")
        writer.writerow(CSV_COLUMNS)
        for user in users:
            number, spent = purchases.get(user.id, (0, 0.0))
            writer.writerow([
                user.telegram_id,
                f"@{user.telegram_username}" if user.telegram_username else "",
                user.language.value if user.language else "",
                user.registered_at.strftime("%Y-%m-%d %H:%M") if user.registered_at else "",
                f"{(user.top_up_amount or 0) - (user.consume_records or 0):.2f}",
                number,
                f"{spent or 0:.2f}",
                f"@{storefronts[user.storefront_bot_id]}" if user.storefront_bot_id in storefronts else "",
                "yes" if user.can_receive_messages is not False else "no",
                "yes" if user.is_banned else "no",
            ])
        # The BOM makes Excel open the file as UTF-8.
        return ("﻿" + output.getvalue()).encode("utf-8")
