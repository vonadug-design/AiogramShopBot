"""Checks that a button pressed by a customer refers to their own cart items and purchases.

Callback data comes from the user's Telegram client and can be forged, so ids inside it are not trusted.
"""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db import session_execute
from models.buy import Buy
from models.buyItem import BuyItem
from models.cart import Cart
from models.cartItem import CartItem
from models.user import User


class OwnershipService:

    @staticmethod
    async def owns_cart_item(telegram_id: int, cart_item_id: int, session: AsyncSession) -> bool:
        stmt = (select(CartItem.id)
                .join(Cart, Cart.id == CartItem.cart_id)
                .join(User, User.id == Cart.user_id)
                .where(CartItem.id == cart_item_id, User.telegram_id == telegram_id))
        return (await session_execute(stmt, session)).scalar() is not None

    @staticmethod
    async def owns_buy(telegram_id: int, buy_id: int | None, buy_item_id: int | None, session: AsyncSession) -> bool:
        if buy_id is not None:
            stmt = (select(Buy.id).join(User, User.id == Buy.buyer_id)
                    .where(Buy.id == buy_id, User.telegram_id == telegram_id))
            if (await session_execute(stmt, session)).scalar() is None:
                return False
        if buy_item_id is not None:
            stmt = (select(BuyItem.id).join(Buy, Buy.id == BuyItem.buy_id).join(User, User.id == Buy.buyer_id)
                    .where(BuyItem.id == buy_item_id, User.telegram_id == telegram_id))
            if (await session_execute(stmt, session)).scalar() is None:
                return False
        return True
