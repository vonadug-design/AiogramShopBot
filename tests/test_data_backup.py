import asyncio
import datetime
import importlib

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

for _module in ("item", "cart", "cartItem", "user", "buy", "buyItem", "category", "subcategory", "deposit",
                "button_media", "payment", "coupon", "shipping_option", "review", "referral", "storefront_bot",
                "apirone_invoice", "staff_member", "text_override", "custom_button"):
    importlib.import_module(f"models.{_module}")
from enums.buy_status import BuyStatus
from enums.language import Language
from models.base import Base
from models.buy import Buy
from models.user import User


def run(coro):
    return asyncio.run(coro)


def test_backup_sends_only_new_copies(tmp_path, monkeypatch):
    import services.backup as backup
    monkeypatch.setattr(backup, "BACKUP_DIR", tmp_path)
    monkeypatch.setattr(backup.config, "ADMIN_ID_LIST", [1, 2], raising=False)
    sent, messages = [], []

    async def send_document(chat_id, path, text):
        sent.append((chat_id, path))

    async def send_message(text, markup):
        messages.append(text)

    assert run(backup.BackupService.send_new_copies(send_document, send_message)) == 0
    (tmp_path / "db-20261124-0400.sql.gz").write_bytes(b"x")
    assert run(backup.BackupService.send_new_copies(send_document, send_message)) == 2
    assert run(backup.BackupService.send_new_copies(send_document, send_message)) == 0  # already sent
    (tmp_path / "db-20261125-0400.sql.gz").write_bytes(b"y")
    (tmp_path / ".failed").write_text("1")
    assert run(backup.BackupService.send_new_copies(send_document, send_message)) == 2
    assert sent[-1][1].endswith("db-20261125-0400.sql.gz") and len(messages) == 1
    assert backup.BackupService.request_now() and (tmp_path / ".request").exists()


def test_support_link_gets_order_text(monkeypatch):
    from services.custom_buttons import CustomButtonService
    monkeypatch.setattr(CustomButtonService, "get_support_link", staticmethod(lambda: "https://t.me/help_desk"))
    assert CustomButtonService.get_support_link_with_text("Проблема #5") == \
        "https://t.me/help_desk?text=%D0%9F%D1%80%D0%BE%D0%B1%D0%BB%D0%B5%D0%BC%D0%B0%20%235"
    monkeypatch.setattr(CustomButtonService, "get_support_link", staticmethod(lambda: "https://example.com/help"))
    assert CustomButtonService.get_support_link_with_text("x") == "https://example.com/help"


@pytest.fixture
def session(monkeypatch):
    async def execute(stmt, s):
        return s.execute(stmt)

    monkeypatch.setattr("services.user_export.session_execute", execute)
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine, tables=[Base.metadata.tables[name] for name in
                                             ("storefront_bots", "users", "coupons", "shipping_options", "buys")])
    with Session(engine) as s:
        yield s


def test_user_stats_and_csv(session):
    from services.user_export import UserExportService
    now = datetime.datetime.now(tz=datetime.timezone.utc)
    session.add_all([
        User(id=1, telegram_id=111, telegram_username="buyer", language=Language.RU, top_up_amount=20,
             consume_records=5, registered_at=now, can_receive_messages=True),
        User(id=2, telegram_id=222, language=Language.EN, top_up_amount=0, consume_records=0,
             registered_at=now - datetime.timedelta(days=30), can_receive_messages=False),
    ])
    session.add(Buy(id=1, buyer_id=1, total_price=5, status=BuyStatus.COMPLETED, buy_datetime=now))
    session.flush()
    stats = run(UserExportService.get_stats(session))
    assert stats == {"total": 2, "today": 1, "week": 1, "buyers": 1, "blocked": 1}
    text = run(UserExportService.build_csv(session)).decode("utf-8-sig")
    lines = text.strip().splitlines()
    assert lines[0].startswith("telegram_id;username")
    assert lines[1].startswith("111;@buyer;ru;") and ";15.00;1;5.00;" in lines[1]
    assert lines[2].startswith("222;;en;") and lines[2].endswith(";no;no")
