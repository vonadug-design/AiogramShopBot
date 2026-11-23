import logging
from decimal import Decimal

from aiogram import Router, F
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy.ext.asyncio import AsyncSession

import config
from callbacks import ApironeCallback
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


@apirone_top_up_router.callback_query(IsUserExistFilter(), ApironeCallback.filter())
async def choose_coin(callback: CallbackQuery, callback_data: ApironeCallback, state: FSMContext,
                      language: Language):
    if callback_data.currency not in enabled_currencies():
        return await callback.answer()
    await state.set_state(UserStates.apirone_amount)
    await state.update_data(apirone_currency=callback_data.currency)
    await callback.message.answer(get_text(language, BotEntity.USER, "apirone_enter_amount").format(
        currency_text=config.CURRENCY.get_localized_text(), coin=APIRONE_CURRENCIES[callback_data.currency][0]))
    await callback.answer()


@apirone_top_up_router.message(IsUserExistFilter(), F.text, StateFilter(UserStates.apirone_amount))
async def receive_amount(message: Message, state: FSMContext, session: AsyncSession, language: Language):
    amount: Decimal | None = PaymentService._parse_fiat_amount(message.text)
    if amount is None:
        return await message.answer(get_text(language, BotEntity.USER, "apirone_invalid_amount"))
    currency = (await state.get_data()).get("apirone_currency")
    await state.set_state()
    user = await UserRepository.get_by_tgid(message.from_user.id, session)
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
