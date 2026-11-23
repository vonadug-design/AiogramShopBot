"""Asks a buyer to rate the purchase: 1 hour after it, and once more a day later if there is still no review."""
import asyncio
import datetime
import logging

from aiogram import Router
from aiogram.types import CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy import select, or_, and_
from sqlalchemy.ext.asyncio import AsyncSession

from callbacks import ReviewRequestCallback
from db import get_db_session, session_execute, session_commit
from enums.bot_entity import BotEntity
from enums.buy_status import BuyStatus
from enums.language import Language
from models.buy import Buy
from models.buyItem import BuyItem
from models.item import Item
from models.review import Review, ReviewDTO
from models.subcategory import Subcategory
from models.user import User
from repositories.review import ReviewRepository
from services.ownership import OwnershipService
from utils.utils import get_text

FIRST_REQUEST_AFTER = datetime.timedelta(hours=1)
REMINDER_AFTER = datetime.timedelta(hours=24)
# A purchase that is this old when the bot first looks at it is not asked about (e.g. the bot was offline).
TOO_OLD = datetime.timedelta(days=3)
CHECK_EVERY_SECONDS = 300
MAX_PRODUCTS_PER_REQUEST = 3


class ReviewRequestService:

    @staticmethod
    def rating_markup(buy_item_id: int):
        kb_builder = InlineKeyboardBuilder()
        for rating in range(1, 6):
            kb_builder.button(text=f"{rating}⭐", callback_data=ReviewRequestCallback(buy_item_id=buy_item_id,
                                                                                    rating=rating))
        kb_builder.adjust(5)
        return kb_builder.as_markup()

    @staticmethod
    async def get_due(session: AsyncSession, now: datetime.datetime) -> list[Buy]:
        stmt = (select(Buy).where(
            Buy.status == BuyStatus.COMPLETED,
            or_(and_(Buy.review_requests == 0,
                     Buy.buy_datetime <= now - FIRST_REQUEST_AFTER),
                and_(Buy.review_requests == 1,
                     Buy.review_requested_at <= now - REMINDER_AFTER)))
                .order_by(Buy.id).limit(50))
        return list((await session_execute(stmt, session)).scalars().all())

    @staticmethod
    async def get_unreviewed_products(buy_id: int, session: AsyncSession) -> list[tuple[int, str]]:
        """(buy item id, product name) of products in the purchase that have no review yet."""
        buy_items = (await session_execute(select(BuyItem).where(BuyItem.buy_id == buy_id).order_by(BuyItem.id),
                                           session)).scalars().all()
        result = []
        for buy_item in buy_items:
            if not buy_item.item_ids:
                continue
            reviewed = (await session_execute(select(Review.id).where(Review.buyItem_id == buy_item.id),
                                              session)).scalar()
            if reviewed is not None:
                continue
            name = (await session_execute(select(Subcategory.name)
                                          .join(Item, Item.subcategory_id == Subcategory.id)
                                          .where(Item.id == buy_item.item_ids[0]), session)).scalar()
            result.append((buy_item.id, name or ""))
        return result

    @staticmethod
    async def send_due(send=None) -> int:
        """Sends every request that is due. Returns how many messages were sent."""
        from services.notification import NotificationService
        send = send or NotificationService.send_to_user
        now = datetime.datetime.now(tz=datetime.timezone.utc)
        to_send = []
        async with get_db_session() as session:
            for buy in await ReviewRequestService.get_due(session, now):
                is_reminder = buy.review_requests == 1
                # Marked before sending, so a failure never turns into repeated messages.
                too_old = not is_reminder and buy.buy_datetime is not None and \
                    buy.buy_datetime < now - TOO_OLD
                buy.review_requests = 2 if too_old else buy.review_requests + 1
                buy.review_requested_at = now
                if too_old:
                    continue
                user = (await session_execute(select(User).where(User.id == buy.buyer_id), session)).scalar()
                if user is None or user.can_receive_messages is False:
                    continue
                products = await ReviewRequestService.get_unreviewed_products(buy.id, session)
                if not products:
                    buy.review_requests = 2
                    continue
                language = Language(user.language) if user.language else Language.EN
                key = "review_request_reminder" if is_reminder else "review_request"
                for buy_item_id, name in products[:MAX_PRODUCTS_PER_REQUEST]:
                    to_send.append((get_text(language, BotEntity.USER, key).format(subcategory_name=name),
                                    user.telegram_id, ReviewRequestService.rating_markup(buy_item_id)))
            await session_commit(session)
        for text, telegram_id, markup in to_send:
            try:
                await send(text, telegram_id, markup)
            except Exception as exception:
                logging.warning(f"Review request to {telegram_id} failed: {exception}")
        return len(to_send)

    @staticmethod
    async def run_forever():
        while True:
            try:
                await ReviewRequestService.send_due()
            except Exception as exception:
                logging.error(f"Review requests failed: {exception}")
            await asyncio.sleep(CHECK_EVERY_SECONDS)

    @staticmethod
    async def rate(callback: CallbackQuery, callback_data: ReviewRequestCallback, session: AsyncSession,
                   language: Language):
        if not 1 <= callback_data.rating <= 5 or not await OwnershipService.owns_buy(
                callback.from_user.id, None, callback_data.buy_item_id, session):
            return await callback.answer()
        review_dto = await ReviewRepository.get_by_buy_item_id(callback_data.buy_item_id, session)
        if review_dto is None:
            review_dto = await ReviewRepository.create(ReviewDTO(buyItem_id=callback_data.buy_item_id,
                                                                 rating=callback_data.rating), session)
            await session_commit(session)
            try:
                from services.notification import NotificationService
                await NotificationService.new_review_published(review_dto, session)
            except Exception as exception:
                logging.warning(f"Review notification failed: {exception}")
        await callback.answer()
        await callback.message.edit_text(get_text(language, BotEntity.USER, "review_request_thanks").format(
            rating_stars="⭐️" * review_dto.rating))


def create_review_request_router() -> Router:
    """A fresh router each time: the storefronts and the main bot each include their own."""
    router = Router()

    @router.callback_query(ReviewRequestCallback.filter())
    async def review_request_rating(callback: CallbackQuery, callback_data: ReviewRequestCallback,
                                    session: AsyncSession, language: Language):
        await ReviewRequestService.rate(callback, callback_data, session, language)

    return router
