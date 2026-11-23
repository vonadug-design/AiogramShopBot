from aiogram.fsm.context import FSMContext
from aiogram.types import InputMediaVideo, InputMediaAnimation, InputMediaPhoto, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

import config
from callbacks import AllCategoriesCallback
from enums.bot_entity import BotEntity
from enums.entity_type import EntityType
from enums.language import Language
from enums.sort_property import SortProperty
from handlers.common.common import add_pagination_buttons, add_sorting_buttons, get_filters_settings, add_search_button
from repositories.category import CategoryRepository
from repositories.item import ItemRepository
from repositories.subcategory import SubcategoryRepository
from services.media import MediaService
from utils.utils import get_text
from utils.utils import get_bot_photo_id


class SubcategoryService:

    @staticmethod
    async def _get_back_button(callback_data: AllCategoriesCallback, session: AsyncSession, language: Language):
        """Back from a product list goes to the level that holds this category."""
        parent_id = None
        if callback_data.category_id is not None:
            category = await CategoryRepository.get_by_id(callback_data.category_id, session)
            parent_id = category.parent_id
            if await CategoryRepository.has_own_items(callback_data.category_id, callback_data.item_type, session) \
                    and await CategoryRepository.has_visible_children(callback_data.category_id,
                                                                      callback_data.item_type, session):
                # We came here from the "products in this category" button.
                parent_id = callback_data.category_id
        return AllCategoriesCallback.create(level=1, item_type=callback_data.item_type,
                                            category_id=parent_id).get_back_button(language, 1)

    @staticmethod
    async def get_buttons(callback_data: AllCategoriesCallback | None,
                          state: FSMContext,
                          session: AsyncSession,
                          language: Language) -> tuple[InputMediaPhoto |
                                                       InputMediaAnimation |
                                                       InputMediaVideo, InlineKeyboardBuilder]:
        state_data = await state.get_data()
        callback_data = callback_data or AllCategoriesCallback.create(2, **state_data.get("entity_id_dict"))
        sort_pairs, filters = await get_filters_settings(state, callback_data)
        kb_builder = InlineKeyboardBuilder()
        items = await SubcategoryRepository.get_paginated_by_category_id(sort_pairs, filters,
                                                                         callback_data.item_type,
                                                                         callback_data.category_id,
                                                                         callback_data.page, session)
        for item in items:
            available_qty = await ItemRepository.get_available_qty(item_type=item.item_type,
                                                                   category_id=item.category_id,
                                                                   subcategory_id=item.subcategory_id,
                                                                   session=session)
            kb_builder.button(text=get_text(language, BotEntity.USER, "subcategory_button").format(
                subcategory_name=item.subcategory_name,
                subcategory_price=item.price,
                available_quantity=available_qty,
                currency_sym=config.CURRENCY.get_localized_symbol()),
                callback_data=AllCategoriesCallback.create(
                    level=callback_data.level + 1,
                    item_type=item.item_type,
                    category_id=item.category_id,
                    subcategory_id=item.subcategory_id
                )
            )
        kb_builder.adjust(1)
        kb_builder = await add_search_button(kb_builder, EntityType.SUBCATEGORY, callback_data, filters, language)
        kb_builder = await add_sorting_buttons(kb_builder, [SortProperty.NAME, SortProperty.PRICE],
                                               callback_data, sort_pairs, language)
        kb_builder = await add_pagination_buttons(kb_builder, callback_data,
                                                  SubcategoryRepository.get_maximum_page(callback_data.category_id,
                                                                                         filters, session),
                                                  await SubcategoryService._get_back_button(callback_data, session,
                                                                                            language),
                                                  language)
        prompt = get_text(language, BotEntity.USER, "pick_subcategory")
        if callback_data.category_id:
            from services.category import CategoryService
            category_dto = await CategoryRepository.get_by_id(callback_data.category_id, session)
            caption = CategoryService.build_card(category_dto, language, prompt)
            media = MediaService.convert_to_media(category_dto.media_id, caption)
        else:
            media = InputMediaPhoto(media=get_bot_photo_id(), caption=prompt)
        return media, kb_builder

    @staticmethod
    async def get_select_quantity_buttons(callback_data: AllCategoriesCallback,
                                          session: AsyncSession,
                                          language: Language) -> tuple[InputMediaPhoto |
                                                                       InputMediaAnimation |
                                                                       InputMediaVideo, InlineKeyboardBuilder]:
        item_dto = await ItemRepository.get_single(callback_data.item_type, callback_data.category_id,
                                                   callback_data.subcategory_id, session)
        subcategory_dto = await SubcategoryRepository.get_by_id(callback_data.subcategory_id, session)
        category_dto = await CategoryRepository.get_by_id(callback_data.category_id, session)
        available_qty = await ItemRepository.get_available_qty(item_type=callback_data.item_type,
                                                               category_id=callback_data.category_id,
                                                               subcategory_id=callback_data.subcategory_id,
                                                               session=session)
        caption = get_text(language, BotEntity.USER, "select_quantity").format(
            category_name=category_dto.name,
            subcategory_name=subcategory_dto.name,
            price=item_dto.price,
            description=item_dto.description,
            quantity=available_qty,
            currency_sym=config.CURRENCY.get_localized_symbol()
        )
        kb_builder = InlineKeyboardBuilder()
        for i in range(1, max(1, min(10, available_qty)) + 1):
            kb_builder.button(text=str(i), callback_data=AllCategoriesCallback.create(
                level=callback_data.level + 1,
                item_type=item_dto.item_type,
                category_id=item_dto.category_id,
                subcategory_id=item_dto.subcategory_id,
                quantity=i
            ))
        kb_builder.adjust(3)
        kb_builder.row(callback_data.get_back_button(language))
        media = MediaService.convert_to_media(subcategory_dto.media_id, caption)
        return media, kb_builder

    @staticmethod
    async def get_add_to_cart_buttons(callback_data: AllCategoriesCallback,
                                      session: AsyncSession | Session,
                                      language: Language,
                                      telegram_id: int | None = None) -> tuple[str, InlineKeyboardBuilder]:
        """After the quantity is picked: buy right away from the balance (main way) or put into the cart."""
        from enums.item_type import ItemType
        from services.user import UserService
        item = await ItemRepository.get_single(callback_data.item_type, callback_data.category_id,
                                               callback_data.subcategory_id, session)
        category = await CategoryRepository.get_by_id(callback_data.category_id, session)
        subcategory = await SubcategoryRepository.get_by_id(callback_data.subcategory_id, session)
        total_price = round(item.price * callback_data.quantity, 2)
        balance = await UserService.get_balance(telegram_id, session) if telegram_id is not None else 0.0
        currency_sym = config.CURRENCY.get_localized_symbol()
        message_text = get_text(language, BotEntity.USER, "buy_confirmation").format(
            item_type=item.item_type.get_localized(language),
            category_name=category.name,
            subcategory_name=subcategory.name,
            price=item.price,
            description=item.description,
            quantity=callback_data.quantity,
            total_price=total_price,
            balance=balance,
            currency_sym=currency_sym)
        kb_builder = InlineKeyboardBuilder()
        product = dict(item_type=item.item_type, category_id=callback_data.category_id,
                       subcategory_id=callback_data.subcategory_id, quantity=callback_data.quantity)
        # Physical goods need a shipping address, which only the cart asks for.
        can_buy_now = item.item_type == ItemType.DIGITAL
        if can_buy_now and balance + 1e-9 >= total_price:
            kb_builder.button(text=get_text(language, BotEntity.USER, "buy_now_button"),
                              callback_data=AllCategoriesCallback.create(level=6, confirmation=True, **product))
        elif can_buy_now:
            missing = SubcategoryService.top_up_amount_for(total_price - balance)
            message_text += "\n\n" + get_text(language, BotEntity.USER, "buy_now_not_enough").format(
                missing=total_price - balance, currency_sym=currency_sym)
            kb_builder.row(SubcategoryService.top_up_button(missing, language))
        kb_builder.row(InlineKeyboardButton(text=get_text(language, BotEntity.USER, "add_to_cart_button"),
                                            callback_data=AllCategoriesCallback.create(
                                                level=5, confirmation=True, **product).pack()))
        kb_builder.row(AllCategoriesCallback.create(level=3, item_type=item.item_type,
                                                    category_id=callback_data.category_id,
                                                    subcategory_id=callback_data.subcategory_id)
                       .get_back_button(language, 3))
        return message_text, kb_builder

    @staticmethod
    def top_up_amount_for(missing: float) -> str:
        """The shortfall rounded up to whole cents and to the smallest top-up (5)."""
        import math
        cents = max(500, math.ceil(round(missing * 100, 6)))
        return f"{cents // 100}.{cents % 100:02d}"

    @staticmethod
    def top_up_button(amount: str, language: Language) -> InlineKeyboardButton:
        from callbacks import TopUpAmountCallback, MyProfileCallback
        if getattr(config, "PAYMENT_PROVIDER", "kryptoexpress") == "apirone":
            callback_data = TopUpAmountCallback(amount=amount).pack()
        else:
            callback_data = MyProfileCallback.create(level=1).pack()
        return InlineKeyboardButton(text=get_text(language, BotEntity.USER, "top_up_exact_button").format(
            amount=amount, currency_sym=config.CURRENCY.get_localized_symbol()), callback_data=callback_data)
