from decimal import Decimal

import pytest

from crypto_api.apirone import to_minor_units, enabled_currencies


def test_minor_units_follow_token_decimals():
    assert to_minor_units("usdt@trx", Decimal("50")) == "50000000"
    assert to_minor_units("usdt@trx", Decimal("12.34")) == "12340000"
    assert to_minor_units("usdt@bnb", Decimal("1")) == "1" + "0" * 18


def test_enabled_currencies_ignores_unknown(monkeypatch):
    monkeypatch.setattr("config.APIRONE_CURRENCIES", "usdt@trx, btc ,usdt@ton", raising=False)
    assert enabled_currencies() == ["usdt@trx", "usdt@ton"]
