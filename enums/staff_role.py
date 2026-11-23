from enum import Enum


class StaffRole(str, Enum):
    OWNER = "owner"
    ADMIN = "admin"
    MODERATOR = "moderator"


class Permission(str, Enum):
    ANNOUNCEMENTS = "announcements"
    INVENTORY = "inventory"
    USERS = "users"
    STATISTICS = "statistics"
    WALLET = "wallet"
    MEDIA = "media"
    COUPONS = "coupons"
    SHIPPING = "shipping"
    BUYS = "buys"
    REVIEWS = "reviews"
    STOREFRONTS = "storefronts"
    TEXTS = "texts"
    STAFF = "staff"


ROLE_PERMISSIONS: dict[StaffRole, frozenset[Permission]] = {
    # Owners (ADMIN_ID_LIST in .env) can do everything.
    StaffRole.OWNER: frozenset(Permission),
    # Admins run the shop but cannot withdraw money or change staff.
    StaffRole.ADMIN: frozenset(Permission) - {Permission.WALLET, Permission.STAFF},
    # Moderators handle goods, orders and reviews only.
    StaffRole.MODERATOR: frozenset({Permission.INVENTORY, Permission.MEDIA, Permission.BUYS, Permission.REVIEWS}),
}
