from enum import Enum


class StorefrontStatus(str, Enum):
    ACTIVE = "active"
    BANNED = "banned"
    DISABLED = "disabled"
