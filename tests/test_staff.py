import asyncio
from types import SimpleNamespace

import pytest

import config
from enums.staff_role import StaffRole, Permission, ROLE_PERMISSIONS
from services.staff import StaffService


@pytest.fixture(autouse=True)
def staff_cache(monkeypatch):
    async def fake_load(cls, session=None):
        cls._cache = {10: StaffRole.ADMIN, 20: StaffRole.MODERATOR}
        cls._loaded_at = 10 ** 12

    monkeypatch.setattr(StaffService, "_load", classmethod(fake_load))
    StaffService.invalidate()
    yield
    StaffService.invalidate()


def run(coro):
    return asyncio.run(coro)


def test_owner_comes_from_admin_id_list():
    owner = config.ADMIN_ID_LIST[0]
    assert run(StaffService.get_role(owner)) == StaffRole.OWNER
    assert all(run(StaffService.can(owner, p)) for p in Permission)


def test_admin_cannot_withdraw_or_manage_staff():
    assert run(StaffService.can(10, Permission.USERS))
    assert run(StaffService.can(10, Permission.STOREFRONTS))
    assert not run(StaffService.can(10, Permission.WALLET))
    assert not run(StaffService.can(10, Permission.STAFF))


def test_moderator_only_goods_orders_reviews():
    assert ROLE_PERMISSIONS[StaffRole.MODERATOR] == {Permission.INVENTORY, Permission.MEDIA,
                                                     Permission.BUYS, Permission.REVIEWS}
    assert run(StaffService.can(20, Permission.INVENTORY))
    assert not run(StaffService.can(20, Permission.USERS))
    assert not run(StaffService.can(20, Permission.ANNOUNCEMENTS))


def test_customer_has_no_access():
    assert run(StaffService.get_role(999)) is None
    assert not run(StaffService.can(999))


def test_admin_filter_uses_permission():
    from utils.custom_filters import AdminIdFilter
    message = SimpleNamespace(from_user=SimpleNamespace(id=20))
    assert run(AdminIdFilter()(message))
    assert run(AdminIdFilter(Permission.INVENTORY)(message))
    assert not run(AdminIdFilter(Permission.WALLET)(message))


def test_notifications_go_to_owners_and_admins():
    ids = run(StaffService.get_notification_ids())
    assert ids == list(config.ADMIN_ID_LIST) + [10]
