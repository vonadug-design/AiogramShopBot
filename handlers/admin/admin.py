from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder
from callbacks import AdminMenuCallback, AnnouncementCallback, InventoryManagementCallback, \
    UserManagementCallback, StatisticsCallback, WalletCallback, MediaManagementCallback, CouponManagementCallback, \
    ShippingManagementCallback, MyProfileCallback, ReviewManagementCallback, TextsCallback, CatalogCallback, \
    LinkButtonsCallback, DataCallback
from enums.bot_entity import BotEntity
from enums.keyboard_button import KeyboardButton as KB
from enums.language import Language
from enums.user_role import UserRole
from handlers.admin.announcement import announcement_router
from handlers.admin.buys_management import buys_management_router
from handlers.admin.coupon_management import coupons_management
from handlers.admin.inventory_management import inventory_management
from handlers.admin.media_management import media_management
from handlers.admin.shipping_management import shipping_management
from handlers.admin.statistics import statistics
from handlers.admin.user_management import user_management
from handlers.admin.wallet import wallet
from handlers.admin.texts import texts_router
from handlers.admin.catalog import catalog_router
from handlers.admin.link_buttons import link_buttons_router
from handlers.admin.data import data_router
from enums.staff_role import Permission, StaffRole
from services.staff import StaffService
from utils.custom_filters import AdminIdFilter
from aiogram.filters import Command, CommandObject
from sqlalchemy.ext.asyncio import AsyncSession
from utils.utils import get_text

admin_router = Router()
admin_router.include_routers(announcement_router,
                             inventory_management,
                             user_management,
                             statistics,
                             wallet,
                             media_management,
                             coupons_management,
                             shipping_management,
                             buys_management_router,
                             texts_router,
                             catalog_router,
                             link_buttons_router,
                             data_router)


@admin_router.message(F.text.in_(KB.get_localized_set(KB.ADMIN_MENU)), AdminIdFilter())
async def admin_command_handler(message: Message, state: FSMContext, language: Language):
    await admin(message=message, state=state, language=language)


async def admin(**kwargs):
    message: Message | CallbackQuery = kwargs.get("message") or kwargs.get("callback")
    state: FSMContext = kwargs.get("state")
    language: Language = kwargs.get("language")
    await state.clear()
    kb_builder = InlineKeyboardBuilder()
    menu = [
        (Permission.ANNOUNCEMENTS, "announcements", AnnouncementCallback.create(level=0)),
        (Permission.INVENTORY, "inventory_management", InventoryManagementCallback.create(level=0)),
        (Permission.INVENTORY, "catalog_management", CatalogCallback.create(level=0)),
        (Permission.USERS, "user_management", UserManagementCallback.create(level=0)),
        (Permission.STATISTICS, "statistics", StatisticsCallback.create(level=0)),
        (Permission.WALLET, "crypto_withdraw", WalletCallback.create(level=0)),
        (Permission.MEDIA, "media_management", MediaManagementCallback.create(level=0)),
        (Permission.COUPONS, "coupons_management", CouponManagementCallback.create(level=0)),
        (Permission.SHIPPING, "shipping_management", ShippingManagementCallback.create(level=0)),
        (Permission.BUYS, "buys_management", MyProfileCallback.create(level=3, user_role=UserRole.ADMIN)),
        (Permission.REVIEWS, "reviews_management", ReviewManagementCallback.create(level=5, user_role=UserRole.ADMIN)),
        (Permission.TEXTS, "texts_management", TextsCallback.create(level=0)),
        (Permission.TEXTS, "links_management", LinkButtonsCallback.create(level=0)),
        (Permission.STAFF, "data_management", DataCallback()),
    ]
    for permission, text_key, callback_data in menu:
        if await StaffService.can(message.from_user.id, permission):
            kb_builder.button(text=get_text(language, BotEntity.ADMIN, text_key), callback_data=callback_data)
    kb_builder.adjust(2)
    msg_text = get_text(language, BotEntity.ADMIN, "menu")
    if isinstance(message, Message):
        await message.answer(msg_text,
                             reply_markup=kb_builder.as_markup())
    elif isinstance(message, CallbackQuery):
        callback = message
        if callback.message.caption:
            await callback.message.delete()
            await callback.message.answer(text=msg_text, reply_markup=kb_builder.as_markup())
        else:
            await callback.message.edit_text(msg_text, reply_markup=kb_builder.as_markup())


@admin_router.callback_query(AdminIdFilter(), AdminMenuCallback.filter())
async def admin_menu_navigation(callback: CallbackQuery,
                                state: FSMContext,
                                callback_data: AdminMenuCallback,
                                language: Language):
    current_level = callback_data.level

    levels = {
        0: admin
    }

    current_level_function = levels[current_level]

    kwargs = {
        "callback": callback,
        "state": state,
        "language": language
    }

    await current_level_function(**kwargs)


_ROLE_WORDS = {
    "admin": StaffRole.ADMIN, "админ": StaffRole.ADMIN, "administrators": StaffRole.ADMIN,
    "moderator": StaffRole.MODERATOR, "mod": StaffRole.MODERATOR, "модератор": StaffRole.MODERATOR,
    "remove": None, "none": None, "удалить": None, "-": None,
}


@admin_router.message(AdminIdFilter(Permission.STAFF), Command("staff"))
async def staff_command(message: Message, command: CommandObject, session: AsyncSession, language: Language):
    """/staff lists staff; /staff <telegram_id> admin|moderator|remove changes a role (owners only)."""
    args = (command.args or "").split()
    if len(args) == 2 and args[0].isdigit() and args[1].lower() in _ROLE_WORDS:
        telegram_id = int(args[0])
        if await StaffService.get_role(telegram_id, session) == StaffRole.OWNER:
            return await message.answer(get_text(language, BotEntity.ADMIN, "staff_owner_fixed"))
        role = _ROLE_WORDS[args[1].lower()]
        await StaffService.set_role(telegram_id, role, session)
        if role is None:
            return await message.answer(get_text(language, BotEntity.ADMIN, "staff_removed").format(
                telegram_id=telegram_id))
        return await message.answer(get_text(language, BotEntity.ADMIN, "staff_updated").format(
            telegram_id=telegram_id, role=role.value))
    if args:
        return await message.answer(get_text(language, BotEntity.ADMIN, "staff_usage"))
    lines = [get_text(language, BotEntity.ADMIN, "staff_header")]
    for telegram_id, role in await StaffService.get_all(session):
        lines.append(f"<code>{telegram_id}</code> · {role.value}")
    lines.append("")
    lines.append(get_text(language, BotEntity.ADMIN, "staff_usage"))
    await message.answer("\n".join(lines))
