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


def test_eur_amount_is_converted_to_coins_rounded_up():
    from decimal import Decimal
    from crypto_api.apirone import coin_amount_for
    # 1 USDT = 0.86 EUR: 10 EUR needs 11.63 USDT (11.627... rounded up)
    assert coin_amount_for(Decimal("10"), Decimal("0.86")) == Decimal("11.63")
    assert coin_amount_for(Decimal("10"), Decimal("1")) == Decimal("10.00")
    assert to_minor_units("usdt@trx", coin_amount_for(Decimal("10"), Decimal("0.86"))) == "11630000"


def test_invoice_in_eur_asks_for_converted_coin_amount(monkeypatch):
    import asyncio
    from decimal import Decimal
    from types import SimpleNamespace
    import crypto_api.apirone as module
    monkeypatch.setattr(module.config, "CURRENCY", SimpleNamespace(value="EUR"), raising=False)
    monkeypatch.setattr(module.config, "APIRONE_ACCOUNT", "apr-test", raising=False)

    async def fake_rate(currency, fiat):
        assert (currency, fiat) == ("usdt@trx", "EUR")
        return Decimal("0.86")

    sent = {}

    class FakeResponse:
        status = 200
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        def raise_for_status(self): pass
        async def json(self): return {"invoice": "i1", "invoice-url": "https://pay"}

    class FakeSession:
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        def post(self, url, json):
            sent.update(json)
            return FakeResponse()

    monkeypatch.setattr(module.ApironeClient, "get_rate", staticmethod(fake_rate))
    monkeypatch.setattr(module.aiohttp, "ClientSession", FakeSession)
    asyncio.run(module.ApironeClient.create_invoice("usdt@trx", Decimal("10"), "https://cb", "t"))
    assert sent["amount"] == "11630000"
    assert sent["user-data"]["price"] == "10 EUR"
