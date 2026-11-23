import logging
from decimal import Decimal

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

import config
from crypto_api.apirone import ApironeClient, APIRONE_CURRENCIES, PAID_STATUSES
from db import session_execute, session_commit, get_db_session
from enums.bot_entity import BotEntity
from models.apirone_invoice import ApironeInvoice
from models.user import User
from services.notification import NotificationService
from utils.utils import get_text


class ApironeService:
    """Balance top-ups through Apirone invoices. Balance is credited once, after the invoice is completed."""

    @staticmethod
    def callback_url() -> str:
        return f"{config.WEBHOOK_HOST}/apirone/callback/{config.APIRONE_CALLBACK_SECRET}"

    @staticmethod
    async def create_top_up(user_id: int, currency: str, fiat_amount: Decimal,
                            session: AsyncSession) -> str:
        invoice = await ApironeClient.create_invoice(
            currency, fiat_amount, ApironeService.callback_url(),
            title=f"Top up {fiat_amount} {config.CURRENCY.value}")
        session.add(ApironeInvoice(invoice_id=invoice["invoice"], user_id=user_id, currency=currency,
                                   fiat_amount=float(fiat_amount), status=invoice.get("status", "created")))
        await session_commit(session)
        return invoice["invoice-url"]

    @staticmethod
    async def process_callback(invoice_id: str) -> None:
        # Never trust the callback body: ask Apirone for the real status
        remote = await ApironeClient.get_invoice(invoice_id)
        status = remote.get("status", "")
        async with get_db_session() as session:
            result = await session_execute(
                select(ApironeInvoice).where(ApironeInvoice.invoice_id == invoice_id).with_for_update(), session)
            invoice = result.scalar()
            if invoice is None:
                logging.warning(f"Apirone callback for unknown invoice {invoice_id}")
                return
            invoice.status = status
            if status not in PAID_STATUSES or invoice.credited:
                await session_commit(session)
                return
            invoice.credited = True
            await session_execute(update(User).where(User.id == invoice.user_id)
                                  .values(top_up_amount=User.top_up_amount + invoice.fiat_amount), session)
            user = (await session_execute(select(User).where(User.id == invoice.user_id), session)).scalar()
            await session_commit(session)
            telegram_id, language, amount = user.telegram_id, user.language, invoice.fiat_amount
        await NotificationService.send_to_user(
            get_text(language, BotEntity.USER, "apirone_topped_up").format(
                amount=amount, currency_text=config.CURRENCY.get_localized_text()),
            telegram_id)
        await NotificationService.send_to_admins(
            f"💰 Apirone: +{amount} {config.CURRENCY.value} from user {telegram_id} ({APIRONE_CURRENCIES.get(invoice.currency, (invoice.currency,))[0]})",
            None)
