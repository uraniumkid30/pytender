from __future__ import annotations

from typing import TypedDict

from .money import Money
from .registry import CurrencyRegistry, DEFAULT_REGISTRY


class MoneyPayload(TypedDict):
    """Stable JSON-friendly representation using integer minor units."""

    amount: int
    currency: str


def to_dict(money: Money) -> MoneyPayload:
    """Serialize ``Money`` without converting through major units or floats."""
    return {"amount": int(money.minor), "currency": str(money.currency.code)}


def from_dict(
    payload: MoneyPayload,
    *,
    registry: CurrencyRegistry = DEFAULT_REGISTRY,
) -> Money:
    """Deserialize canonical minor-unit data using the supplied registry."""
    amount = payload.get("amount")
    currency = payload.get("currency")
    if isinstance(amount, bool) or not isinstance(amount, int):
        raise TypeError("payload.amount must be an integer minor-unit value")
    if not isinstance(currency, str):
        raise TypeError("payload.currency must be a string currency code")
    return Money.from_minor(amount, currency, registry=registry)
