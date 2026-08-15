"""Targeted branch coverage for stable public-domain contracts.

These tests deliberately exercise public edge behaviours that are easy to miss in
happy-path examples. They exist to protect semantics, not merely to satisfy a number.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from moneytender import (
    Currency,
    CurrencyCode,
    CurrencyRegistry,
    CurrencyStatus,
    DerivationKind,
    ExchangeRate,
    Money,
    RateKind,
    RatePolicy,
    RatePolicyError,
    RateProvenance,
)
from moneytender.formatting import SimpleMoneyFormatter, _group_digits
from moneytender.rounding import DecimalRounding, RoundingError


def _currency(
    code: str,
    *,
    exponent: int = 2,
    symbol: str = "",
) -> Currency:
    return Currency(
        CurrencyCode(code),
        exponent,
        symbol,
        f"{code} test currency",
        "999",
        1,
        CurrencyStatus.CURRENT,
    )


def _rate(
    *,
    derivation: DerivationKind = DerivationKind.NONE,
    kind: RateKind = RateKind.EXECUTABLE,
    as_of: datetime | None = None,
) -> ExchangeRate:
    return ExchangeRate(
        CurrencyCode("USD"),
        CurrencyCode("EUR"),
        Decimal("0.90"),
        RateProvenance("test", as_of=as_of),
        kind,
        derivation,
    )


def test_formatter_exercises_optional_display_branches() -> None:
    no_symbol = _currency("ZZZ", symbol="")
    amount = Money.from_minor(123456, no_symbol)

    formatter = SimpleMoneyFormatter(
        group_thousands=False,
        code_when_symbol_missing=False,
    )
    assert formatter.format(amount) == "1234.56"

    whole_units = _currency("QQQ", exponent=0, symbol="¤")
    whole = Money.from_minor(1234, whole_units)
    suffix = SimpleMoneyFormatter(symbol_first=False, symbol_space=True)
    assert suffix.format(whole) == "1,234 ¤"

    assert _group_digits("", ",") == ""


def test_money_integer_major_subtraction_and_explicit_formatter_paths() -> None:
    integer_major = Money.from_major(5, "USD")
    assert integer_major.minor == 500

    assert Money.from_major("10", "USD") - Money.from_major(
        "2.50", "USD"
    ) == Money.from_major("7.50", "USD")

    class Formatter:
        def format(self, money: Money) -> str:
            return f"minor={money.minor}"

    assert integer_major.format(Formatter()) == "minor=500"


def test_rate_policy_rejects_inverse_and_naive_now_and_runs_fresh_validator() -> None:
    inverse = _rate(derivation=DerivationKind.INVERSE, kind=RateKind.DERIVED)
    with pytest.raises(RatePolicyError, match="inverse-derived"):
        RatePolicy(allowed_kinds=frozenset({RateKind.DERIVED})).validate(inverse)

    current = datetime(2026, 8, 15, tzinfo=UTC)
    fresh = _rate(as_of=current)
    with pytest.raises(ValueError, match="timezone-aware"):
        RatePolicy(max_age=timedelta(minutes=1)).validate(
            fresh,
            now=datetime(2026, 8, 15),
        )

    seen: list[ExchangeRate] = []
    RatePolicy(
        max_age=timedelta(minutes=1),
        validator=seen.append,
    ).validate(fresh, now=current)
    assert seen == [fresh]


def test_register_many_replace_path_replaces_existing_currency() -> None:
    original = _currency("ZZZ", exponent=2)
    replacement = _currency("ZZZ", exponent=3)
    registry = CurrencyRegistry([original])

    registry.register_many([replacement], replace=True)

    assert registry.get("ZZZ") is replacement


def test_decimal_rounding_rejects_non_decimal_values() -> None:
    with pytest.raises(RoundingError, match="require a Decimal"):
        DecimalRounding().quantize_minor(1)  # type: ignore[arg-type]
