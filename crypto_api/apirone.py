import logging
from decimal import Decimal

import aiohttp

import config

API_BASE = "https://apirone.com/api/v2"

# Stablecoins pegged to USD. Apirone invoices are priced in the coin itself, so a shop in another currency
# (e.g. EUR) converts the amount with Apirone's exchange rate when the invoice is created.
APIRONE_CURRENCIES = {
    "usdt@trx": ("USDT (TRC20)", 6),
    "usdc@trx": ("USDC (TRC20)", 6),
    "usdt@bnb": ("USDT (BEP20)", 18),
    "usdc@bnb": ("USDC (BEP20)", 18),
    "usdt@ton": ("USDT (TON)", 6),
    "usdt@eth": ("USDT (ERC20)", 6),
    "usdc@eth": ("USDC (ERC20)", 6),
}
PAID_STATUSES = {"completed"}


def enabled_currencies() -> list[str]:
    raw = getattr(config, "APIRONE_CURRENCIES", "usdt@trx") or "usdt@trx"
    return [code.strip() for code in raw.split(",") if code.strip() in APIRONE_CURRENCIES]


def coin_amount_for(fiat_amount: Decimal, rate: Decimal) -> Decimal:
    """Coins to ask for, rounded up to a cent of the coin, so the shop never receives less than the price."""
    from decimal import ROUND_UP
    return (fiat_amount / rate).quantize(Decimal("0.01"), rounding=ROUND_UP)


def to_minor_units(currency: str, amount: Decimal) -> str:
    decimals = APIRONE_CURRENCIES[currency][1]
    return str(int((amount * (Decimal(10) ** decimals)).to_integral_value()))


class ApironeClient:
    """Minimal client for Apirone invoices (https://apirone.com/docs/invoices)."""

    @staticmethod
    async def get_rate(currency: str, fiat: str) -> Decimal:
        """How much of the fiat currency one coin is worth now, from https://apirone.com/docs/rate."""
        if fiat.lower() == "usd":
            return Decimal(1)  # USD stablecoins: 1 coin = 1 USD
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{API_BASE}/ticker", params={"currency": currency, "fiat": fiat.lower()}) as response:
                response.raise_for_status()
                data = await response.json()
        rate = Decimal(str(data[fiat.lower()]))
        if not Decimal("0.01") < rate < Decimal("1000"):
            raise ValueError(f"Unexpected {currency}/{fiat} rate: {rate}")
        return rate

    @staticmethod
    async def create_invoice(currency: str, fiat_amount: Decimal, callback_url: str,
                             title: str, lifetime_seconds: int = 3600) -> dict:
        rate = await ApironeClient.get_rate(currency, config.CURRENCY.value)
        body = {
            "currency": currency,
            "amount": to_minor_units(currency, coin_amount_for(fiat_amount, rate)),
            "lifetime": lifetime_seconds,
            "callback-url": callback_url,
            # Shown on the payment page; the amount above is what is actually charged in coins.
            "user-data": {"title": title, "price": f"{fiat_amount} {config.CURRENCY.value}"},
        }
        url = f"{API_BASE}/accounts/{config.APIRONE_ACCOUNT}/invoices"
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=body) as response:
                if response.status == 400:
                    # The docs spell the field both ways; retry with the other spelling
                    logging.warning(f"Apirone rejected invoice: {await response.text()}")
                    body["callback_url"] = body.pop("callback-url")
                    async with session.post(url, json=body) as retry:
                        retry.raise_for_status()
                        return await retry.json()
                response.raise_for_status()
                return await response.json()

    @staticmethod
    async def get_invoice(invoice_id: str) -> dict:
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{API_BASE}/invoices/{invoice_id}") as response:
                response.raise_for_status()
                return await response.json()
