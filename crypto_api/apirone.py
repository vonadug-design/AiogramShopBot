import logging
from decimal import Decimal

import aiohttp

import config

API_BASE = "https://apirone.com/api/v2"

# Stablecoins pegged 1:1 to USD. Apirone does not convert fiat, so the shop price is charged 1:1.
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


def to_minor_units(currency: str, amount: Decimal) -> str:
    decimals = APIRONE_CURRENCIES[currency][1]
    return str(int((amount * (Decimal(10) ** decimals)).to_integral_value()))


class ApironeClient:
    """Minimal client for Apirone invoices (https://apirone.com/docs/invoices)."""

    @staticmethod
    async def create_invoice(currency: str, fiat_amount: Decimal, callback_url: str,
                             title: str, lifetime_seconds: int = 3600) -> dict:
        body = {
            "currency": currency,
            "amount": to_minor_units(currency, fiat_amount),
            "lifetime": lifetime_seconds,
            "callback-url": callback_url,
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
