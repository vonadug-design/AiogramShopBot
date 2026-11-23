import logging
from decimal import Decimal

from aiogram import Router, F
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy.ext.asyncio import AsyncSession

import config
from callbacks import ApironeCallback, TopUpAmountCallback
from crypto_api.apirone import APIRONE_CURRENCIES, enabled_currencies
from enums.bot_entity import BotEntity
from enums.language import Language
from handlers.user.constants import UserStates
from repositories.user import UserRepository
from services.apirone import ApironeService
from services.payment import PaymentService
from utils.custom_filters import IsUserExistFilter
from utils.utils import get_text

apirone_top_up_router = Router()
CANCEL_WORDS = {"cancel", "/cancel", "отмена", "отменить", "atcelt"}


async def _send_invoice(message: Message, telegram_id: int, currency: str, amount: Decimal,
                        session: AsyncSession, language: Language):
    user = await UserRepository.get_by_tgid(telegram_id, session)
    try:
        pay_url = await ApironeService.create_top_up(user.id, currency, amount, session)
    except Exception as exception:
        logging.error(f"Apirone invoice creation failed: {exception}")
        return await message.answer(get_text(language, BotEntity.USER, "apirone_error"))
    kb_builder = InlineKeyboardBuilder()
    kb_builder.button(text=get_text(language, BotEntity.USER, "apirone_pay_button"), url=pay_url)
    await message.answer(get_text(language, BotEntity.USER, "apirone_invoice_created").format(
        amount=amount, currency_text=config.CURRENCY.get_localized_text(),
        coin=APIRONE_CURRENCIES[currency][0]), reply_markup=kb_builder.as_markup())


@apirone_top_up_router.callback_query(IsUserExistFilter(), TopUpAmountCallback.filter())
async def top_up_by_amount(callback: CallbackQuery, callback_data: TopUpAmountCallback, session: AsyncSession,
                           language: Language):
    amount = PaymentService._parse_fiat_amount(callback_data.amount)
    currencies = enabled_currencies()
    if amount is None or not currencies:
        return await callback.answer()
    await callback.answer()
    if len(currencies) == 1:
        return await _send_invoice(callback.message, callback.from_user.id, currencies[0], amount, session, language)
    kb_builder = InlineKeyboardBuilder()
    for currency in currencies:
        kb_builder.button(text=APIRONE_CURRENCIES[currency][0],
                          callback_data=ApironeCallback(currency=currency, amount=callback_data.amount))
    kb_builder.adjust(1)
    await callback.message.answer(get_text(language, BotEntity.USER, "top_up_pick_coin").format(
        amount=amount, currency_sym=config.CURRENCY.get_localized_symbol()), reply_markup=kb_builder.as_markup())


@apirone_top_up_router.callback_query(IsUserExistFilter(), ApironeCallback.filter())
async def choose_coin(callback: CallbackQuery, callback_data: ApironeCallback, state: FSMContext,
                      session: AsyncSession, language: Language):
    if callback_data.currency not in enabled_currencies():
        return await callback.answer()
    if callback_data.amount:
        amount = PaymentService._parse_fiat_amount(callback_data.amount)
        await callback.answer()
        if amount is not None:
            await _send_invoice(callback.message, callback.from_user.id, callback_data.currency, amount, session,
                                language)
        return
    await state.set_state(UserStates.apirone_amount)
    await state.update_data(apirone_currency=callback_data.currency)
    await callback.message.answer(get_text(language, BotEntity.USER, "apirone_enter_amount").format(
        currency_text=config.CURRENCY.get_localized_text(), coin=APIRONE_CURRENCIES[callback_data.currency][0]))
    await callback.answer()


@apirone_top_up_router.message(IsUserExistFilter(), F.text, StateFilter(UserStates.apirone_amount))
async def receive_amount(message: Message, state: FSMContext, session: AsyncSession, language: Language):
    if (message.text or "").strip().lower() in CANCEL_WORDS:
        await state.set_state()
        return await message.answer(get_text(language, BotEntity.USER, "top_up_cancelled"))
    amount: Decimal | None = PaymentService._parse_fiat_amount(message.text)
    if amount is None:
        return await message.answer(get_text(language, BotEntity.USER, "apirone_invalid_amount"))
    currency = (await state.get_data()).get("apirone_currency")
    await state.set_state()
    await _send_invoice(message, message.from_user.id, currency, amount, session, language)
