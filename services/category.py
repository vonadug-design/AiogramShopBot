from aiogram.fsm.context import FSMContext
from aiogram.types import InputMediaPhoto, InputMediaVideo, InputMediaAnimation, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy.ext.asyncio import AsyncSession

from callbacks import AllCategoriesCallback
from enums.bot_entity import BotEntity
from enums.entity_type import EntityType
from enums.keyboard_button import KeyboardButton
from enums.language import Language
from enums.sort_property import SortProperty
from handlers.common.common import add_pagination_buttons, add_sorting_buttons, add_search_button, get_filters_settings
from repositories.button_media import ButtonMediaRepository
from models.category import CategoryDTO
from repositories.category import CategoryRepository
from services.media import MediaService
from utils.utils import get_text


class CategoryService:

    @staticmethod
    def get_description(category: CategoryDTO, language: Language) -> str:
        descriptions = category.descriptions or {}
        return descriptions.get(language.value) or descriptions.get(Language.EN.value) or ""

    @staticmethod
    def build_card(category: CategoryDTO, language: Language, prompt: str) -> str:
        """Caption of a category screen: its name, its description (if set), then what to do next."""
        parts = [get_text(language, BotEntity.USER, "category_card").format(category_name=category.name)]
        description = CategoryService.get_description(category, language)
        if description:
            parts.append(description)
        parts.append(prompt)
        return "\n\n".join(parts)

    @staticmethod
    async def get_buttons(
            callback_data: AllCategoriesCallback | None,
            state: FSMContext,
            session: AsyncSession,
            language: Language,
            telegram_id: int | None = None
    ) -> tuple[InputMediaPhoto |
               InputMediaAnimation |
               InputMediaVideo, InlineKeyboardBuilder]:
        state_data = await state.get_data()
        callback_data = callback_data or AllCategoriesCallback.create(1, **state_data.get("entity_id_dict"))
        parent_id = callback_data.category_id
        if parent_id is not None and not await CategoryRepository.has_visible_children(
                parent_id, callback_data.item_type, session):
            # A leaf category: show its products.
            from services.subcategory import SubcategoryService
            return await SubcategoryService.get_buttons(callback_data.model_copy(update={"level": 2, "page": 0}),
                                                        state, session, language)
        sort_pairs, filters = await get_filters_settings(state, callback_data)
        categories = await CategoryRepository.get(
            sort_pairs, filters, callback_data.item_type, callback_data.page, session, parent_id
        )
        kb_builder = InlineKeyboardBuilder()
        for category in categories:
            kb_builder.button(
                text=category.name,
                callback_data=AllCategoriesCallback.create(level=1,
                                                           item_type=callback_data.item_type,
                                                           category_id=category.id)
            )
        has_categories = len(categories) > 0
        if not has_categories:
            prompt = get_text(language, BotEntity.USER, "no_categories")
        else:
            kb_builder.adjust(2)
            prompt = get_text(language, BotEntity.USER, "pick_category")
            if parent_id is not None and await CategoryRepository.has_own_items(
                    parent_id, callback_data.item_type, session):
                # Products that sit directly in this category, next to its subcategories.
                kb_builder.row(InlineKeyboardButton(
                    text=get_text(language, BotEntity.USER, "category_own_items"),
                    callback_data=AllCategoriesCallback.create(level=2,
                                                               item_type=callback_data.item_type,
                                                               category_id=parent_id).pack()))
        if parent_id is None:
            # The catalog starts here, so there is nothing to go back to.
            back_button = None
        else:
            parent = await CategoryRepository.get_by_id(parent_id, session)
            back_button = AllCategoriesCallback.create(
                level=1, item_type=callback_data.item_type, category_id=parent.parent_id
            ).get_back_button(language, 1)
        kb_builder = await add_search_button(kb_builder, EntityType.CATEGORY, callback_data, filters, language)
        kb_builder = await add_sorting_buttons(
            kb_builder, [SortProperty.NAME], callback_data, sort_pairs, language
        )
        kb_builder = await add_pagination_buttons(
            kb_builder, callback_data,
            CategoryRepository.get_maximum_page(filters, session, parent_id, callback_data.item_type),
            back_button, language
        )
        if parent_id is None:
            caption = prompt
            if telegram_id is not None:
                from services.user import UserService
                caption += "\n\n" + await UserService.get_balance_line(telegram_id, session, language)
            button_media = await ButtonMediaRepository.get_by_button(
                KeyboardButton.ALL_CATEGORIES, session
            )
            media = MediaService.convert_to_media(button_media.media_id, caption=caption)
        else:
            caption = CategoryService.build_card(parent, language, prompt)
            media = MediaService.convert_to_media(parent.media_id, caption=caption)
        return media, kb_builder
