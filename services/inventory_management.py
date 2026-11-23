from aiogram.fsm.context import FSMContext
from services.photo_stock import PhotoStockService
from aiogram.types import Message, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy.ext.asyncio import AsyncSession

import config
from callbacks import InventoryManagementCallback, CatalogCallback
from db import session_commit
from enums.add_type import AddType
from enums.bot_entity import BotEntity
from enums.entity_type import EntityType
from enums.item_type import ItemType
from enums.language import Language
from handlers.admin.constants import AdminConstants, InventoryManagementStates
from models.item import ItemDTO
from repositories.category import CategoryRepository
from repositories.item import ItemRepository
from repositories.subcategory import SubcategoryRepository
from services.notification import NotificationService
from utils.utils import get_text


class InventoryManagementService:

    @staticmethod
    async def get_inventory_management_menu(language: Language) -> tuple[str, InlineKeyboardBuilder]:
        kb_builder = InlineKeyboardBuilder()
        kb_builder.button(text=get_text(language, BotEntity.ADMIN, "add_items"),
                          callback_data=InventoryManagementCallback.create(level=1, entity_type=EntityType.ITEM))
        kb_builder.button(text=get_text(language, BotEntity.ADMIN, "delete_entity").format(
            entity=EntityType.CATEGORY.get_localized(language)
        ),
            callback_data=InventoryManagementCallback.create(level=2,
                                                             entity_type=EntityType.CATEGORY))
        kb_builder.button(text=get_text(language, BotEntity.ADMIN, "delete_entity").format(
            entity=EntityType.SUBCATEGORY.get_localized(language)
        ),
            callback_data=InventoryManagementCallback.create(level=2,
                                                             entity_type=EntityType.SUBCATEGORY))
        kb_builder.adjust(1)
        kb_builder.row(AdminConstants.back_to_main_button(language))
        return get_text(language, BotEntity.ADMIN, "inventory_management"), kb_builder

    @staticmethod
    async def get_add_items_type(callback_data: InventoryManagementCallback,
                                 language: Language) -> tuple[str, InlineKeyboardBuilder]:
        kb_builder = InlineKeyboardBuilder()
        kb_builder.button(text=get_text(language, BotEntity.ADMIN, "add_items_json"),
                          callback_data=InventoryManagementCallback.create(1, AddType.JSON, EntityType.ITEM))
        kb_builder.button(text=get_text(language, BotEntity.ADMIN, "add_items_txt"),
                          callback_data=InventoryManagementCallback.create(1, AddType.TXT, EntityType.ITEM))
        kb_builder.button(text=get_text(language, BotEntity.ADMIN, "add_items_menu"),
                          callback_data=InventoryManagementCallback.create(1, AddType.MENU, EntityType.ITEM))
        kb_builder.adjust(1)
        kb_builder.row(callback_data.get_back_button(language))
        return get_text(language, BotEntity.ADMIN, "add_items_msg"), kb_builder

    @staticmethod
    async def get_add_item_msg(callback_data: InventoryManagementCallback, state: FSMContext, language: Language):
        kb_markup = InlineKeyboardBuilder()
        kb_markup.button(text=get_text(language, BotEntity.COMMON, 'cancel'),
                         callback_data=InventoryManagementCallback.create(1))
        await state.update_data(add_type=callback_data.add_type.value)
        await state.set_state(InventoryManagementStates.document)
        match callback_data.add_type:
            case AddType.JSON:
                return get_text(language, BotEntity.ADMIN, "add_items_json_msg"), kb_markup
            case AddType.TXT:
                return get_text(language, BotEntity.ADMIN, "add_items_txt_msg"), kb_markup
            case AddType.MENU:
                await PhotoStockService.clear(state.key.user_id)
                # The shop sells digital goods, so the "item type" question is skipped.
                await state.update_data(item_type=ItemType.DIGITAL.value)
                await state.set_state(InventoryManagementStates.category)
                return get_text(language, BotEntity.ADMIN, "add_items_category"), kb_markup

    @staticmethod
    async def delete_confirmation(callback_data: InventoryManagementCallback,
                                  session: AsyncSession, language: Language) -> tuple[str, InlineKeyboardBuilder]:
        callback_data.confirmation = True
        kb_builder = InlineKeyboardBuilder()
        kb_builder.button(text=get_text(language, BotEntity.COMMON, "confirm"),
                          callback_data=callback_data)
        kb_builder.button(text=get_text(language, BotEntity.COMMON, "cancel"),
                          callback_data=InventoryManagementCallback.create(0))
        match callback_data.entity_type:
            case EntityType.CATEGORY:
                category = await CategoryRepository.get_by_id(callback_data.entity_id, session)
                return get_text(language, BotEntity.ADMIN, "delete_entity_confirmation").format(
                    entity=callback_data.entity_type.name.capitalize(),
                    entity_name=category.name
                ), kb_builder
            case EntityType.SUBCATEGORY:
                subcategory = await SubcategoryRepository.get_by_id(callback_data.entity_id, session)
                return get_text(language, BotEntity.ADMIN, "delete_entity_confirmation").format(
                    entity=callback_data.entity_type.name.capitalize(),
                    entity_name=subcategory.name
                ), kb_builder

    @staticmethod
    async def delete_entity(callback_data: InventoryManagementCallback,
                            session: AsyncSession,
                            language: Language) -> tuple[str, InlineKeyboardBuilder]:
        kb_builder = InlineKeyboardBuilder()
        kb_builder.row(AdminConstants.back_to_main_button(language))
        match callback_data.entity_type:
            case EntityType.CATEGORY:
                category = await CategoryRepository.get_by_id(callback_data.entity_id, session)
                await ItemRepository.delete_unsold_by_category_id(callback_data.entity_id, session)
                await session_commit(session)
                return get_text(language, BotEntity.ADMIN, "successfully_deleted").format(
                    entity_name=category.name,
                    entity_to_delete=callback_data.entity_type.name.capitalize()), kb_builder
            case EntityType.SUBCATEGORY:
                subcategory = await SubcategoryRepository.get_by_id(callback_data.entity_id, session)
                await ItemRepository.delete_unsold_by_subcategory_id(callback_data.entity_id, session)
                await session_commit(session)
                return get_text(language, BotEntity.ADMIN, "successfully_deleted").format(
                    entity_name=subcategory.name,
                    entity_to_delete=callback_data.entity_type.name.capitalize()), kb_builder

    @staticmethod
    async def add_item_menu(message: Message,
                            state: FSMContext,
                            session: AsyncSession,
                            language: Language) -> tuple[str, InlineKeyboardBuilder]:
        current_state = await state.get_state()
        state_data = await state.get_data()
        await NotificationService.edit_reply_markup(message.bot,
                                                    state_data['chat_id'],
                                                    state_data['msg_id'])
        kb_builder = InlineKeyboardBuilder()
        cancel_button = InlineKeyboardButton(text=get_text(language, BotEntity.COMMON, "cancel"),
                                             callback_data=InventoryManagementCallback.create(1).pack())
        if current_state == InventoryManagementStates.item_type:
            await state.update_data(item_type=message.html_text)
            await state.set_state(InventoryManagementStates.category)
            msg = get_text(language, BotEntity.ADMIN, "add_items_category")
        elif current_state == InventoryManagementStates.category:
            await state.update_data(category_name=message.html_text)
            await state.set_state(InventoryManagementStates.subcategory)
            msg = get_text(language, BotEntity.ADMIN, "add_items_subcategory")
        elif current_state == InventoryManagementStates.subcategory:
            await state.update_data(subcategory_name=message.html_text)
            await state.set_state(InventoryManagementStates.description)
            msg = get_text(language, BotEntity.ADMIN, "add_items_description")
        elif current_state == InventoryManagementStates.description:
            await state.update_data(description=message.html_text)
            await state.set_state(InventoryManagementStates.private_data)
            if ItemType(state_data['item_type'].upper()) == ItemType.PHYSICAL:
                msg = get_text(language, BotEntity.ADMIN, "add_items_private_data_physical")
            else:
                msg = get_text(language, BotEntity.ADMIN, "add_items_private_data")
        elif current_state == InventoryManagementStates.private_data:
            success_msg = get_text(language, BotEntity.ADMIN, "add_items_price").format(
                    currency_text=config.CURRENCY.get_localized_text())
            ready = False
            if ItemType(state_data['item_type'].upper()) == ItemType.PHYSICAL:
                if message.html_text.isdecimal():
                    await state.update_data(items_qty=int(message.html_text))
                    ready = True
                else:
                    msg = get_text(language, BotEntity.ADMIN, "add_items_private_data_physical")
            elif PhotoStockService.is_done_word(message.text):
                if await PhotoStockService.count(message.from_user.id) > 0:
                    await state.update_data(private_data="")
                    ready = True
                else:
                    msg = get_text(language, BotEntity.ADMIN, "add_items_private_data")
            else:
                await state.update_data(private_data=message.html_text)
                ready = True
            if ready and state_data.get("restock"):
                # "Add more" on an existing product: its price is already known.
                count = await InventoryManagementService._create_items(await state.get_data(),
                                                                       message.from_user.id, session)
                await state.clear()
                msg = get_text(language, BotEntity.ADMIN, "add_items_success").format(adding_result=count)
                cancel_button = InlineKeyboardButton(
                    text=get_text(language, BotEntity.COMMON, "back_button"),
                    callback_data=CatalogCallback.create(1, state_data['restock_category_id'],
                                                         state_data['restock_subcategory_id']).pack())
            elif ready:
                await state.set_state(InventoryManagementStates.price)
                msg = success_msg
        else:
            try:
                price = float(message.html_text)
                assert (price > 0)
                await state.update_data(price=message.html_text)
                count = await InventoryManagementService._create_items(await state.get_data(),
                                                                       message.from_user.id, session)
                await state.clear()
                msg = get_text(language, BotEntity.ADMIN, "add_items_success").format(adding_result=count)
                cancel_button.text = get_text(language, BotEntity.COMMON, "back_button")
            except Exception as _:
                msg = get_text(language, BotEntity.ADMIN, "add_items_price").format(
                    currency_text=config.CURRENCY.get_localized_text())
        kb_builder.row(cancel_button)
        return msg, kb_builder

    @staticmethod
    async def _create_items(state_data: dict, admin_id: int, session: AsyncSession) -> int:
        item_type = ItemType(state_data['item_type'].upper())
        if state_data.get("restock"):
            category_id = state_data['restock_category_id']
            subcategory_id = state_data['restock_subcategory_id']
        else:
            category_id = (await CategoryRepository.get_or_create(state_data['category_name'], session)).id
            subcategory_id = (await SubcategoryRepository.get_or_create(state_data['subcategory_name'], session)).id
        common = dict(item_type=item_type, category_id=category_id, subcategory_id=subcategory_id,
                      description=state_data['description'], price=float(state_data['price']))
        if item_type == ItemType.PHYSICAL:
            items_list = [ItemDTO(**common, private_data=None) for _ in range(state_data['items_qty'])]
        else:
            items_list = [ItemDTO(**common, private_data=private_data)
                          for private_data in state_data.get('private_data', '').split('\n') if private_data.strip()]
            items_list += [ItemDTO(**common, private_data=photo_item['private_data'], photo_id=photo_item['photo_id'])
                           for photo_item in await PhotoStockService.pop_all(admin_id)]
        await ItemRepository.add_many(items_list, session)
        await session_commit(session)
        return len(items_list)
