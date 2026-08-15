from decimal import Decimal

import pytest

from pytender import (
    Currency,
    CurrencyCode,
    CurrencyMismatchError,
    InvalidAmountError,
    Money,
)


def test_major_minor_exact() -> None:
    money = Money.from_major("10.25", "USD")
    assert money.minor == 1025
    assert money.major == Decimal("10.25")


def test_float_rejected() -> None:
    with pytest.raises(InvalidAmountError):
        Money.from_major(0.1, "USD")


def test_same_currency_arithmetic() -> None:
    result = Money.from_minor(10, "USD") + Money.from_minor(7, "USD")
    assert result.minor == 17


def test_cross_currency_requires_conversion() -> None:
    with pytest.raises(CurrencyMismatchError):
        _ = Money.from_minor(1, "USD") + Money.from_minor(1, "EUR")


def test_split_preserves_positive_and_negative_totals() -> None:
    for amount in (100, -100, 1, -1, 0):
        parts = Money.from_minor(amount, "USD").split(3)
        assert sum(int(part.minor) for part in parts) == amount


def test_allocate_preserves_total() -> None:
    money = Money.from_minor(100, "USD")
    parts = money.allocate([1, 2, 3])
    assert sum(int(part.minor) for part in parts) == 100


def test_cash_rounding_uses_currency_increment() -> None:
    assert Money.from_minor(103, "CHF").cash_round().minor == 105
    assert Money.from_minor(102, "CHF").cash_round().minor == 100


def test_custom_currency() -> None:
    currency = Currency(CurrencyCode("TOK"), 4, "T", "Token", cash_increment=10)
    assert Money.from_major("1.2345", currency).minor == 12345
