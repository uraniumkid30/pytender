from __future__ import annotations

from typing import TypedDict

from ..money import Money
from ..registry import DEFAULT_REGISTRY, CurrencyRegistry


class MoneyColumns(TypedDict):
    amount_minor: int
    currency_code: str


def to_columns(money: Money) -> MoneyColumns:
    """Canonical relational-storage representation: exact integer + currency code."""
    return {"amount_minor": int(money.minor), "currency_code": str(money.currency.code)}


def from_columns(
    amount_minor: int,
    currency_code: str,
    *,
    registry: CurrencyRegistry = DEFAULT_REGISTRY,
) -> Money:
    if isinstance(amount_minor, bool) or not isinstance(amount_minor, int):
        raise TypeError("amount_minor must be an integer")
    if not isinstance(currency_code, str):
        raise TypeError("currency_code must be a string")
    return Money.from_minor(amount_minor, currency_code, registry=registry)
