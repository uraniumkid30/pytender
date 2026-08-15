from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal, getcontext, localcontext

import pytest

from moneytender import (
    Currency,
    CurrencyCode,
    CurrencyMismatchError,
    CurrencyRegistry,
    ExchangeRate,
    Money,
    MoneyConverter,
    RateProvenance,
    StaticRateProvider,
)


def test_major_is_exact_independent_of_ambient_decimal_context() -> None:
    currency = Currency(CurrencyCode("TST"), 2)
    money = Money.from_minor(10**30 + 1_234_567, currency)
    old = getcontext().prec
    try:
        getcontext().prec = 6
        assert money.major == Decimal("10000000000000000000000012345.67")
    finally:
        getcontext().prec = old


def test_fx_large_integer_is_independent_of_ambient_context() -> None:
    base = Currency(CurrencyCode("AAA"), 2)
    quote = Currency(CurrencyCode("BBB"), 2)
    registry = CurrencyRegistry((base, quote))
    money = Money.from_minor(10**30 + 1_234_567, base)
    converter = MoneyConverter(StaticRateProvider({("AAA", "BBB"): "1.25"}), registry=registry)
    with localcontext() as context:
        context.prec = 6
        converted = converter.convert(money, quote)
    assert converted.minor == 1_250_000_000_000_000_000_000_001_543_209


def test_same_code_with_incompatible_currency_metadata_is_rejected() -> None:
    two_dp = Currency(CurrencyCode("USD"), 2, "$")
    zero_dp = Currency(CurrencyCode("USD"), 0, "USD")
    with pytest.raises(CurrencyMismatchError):
        _ = Money.from_minor(1000, two_dp) + Money.from_minor(1000, zero_dp)


def test_equality_and_ordering_use_same_currency_compatibility() -> None:
    left = Money.from_minor(500, Currency(CurrencyCode("USD"), 2, "$"))
    right = Money.from_minor(500, Currency(CurrencyCode("USD"), 2, "US$"))
    assert left != right
    with pytest.raises(CurrencyMismatchError):
        _ = left < right


def test_rate_provenance_and_exchange_rate_are_hashable() -> None:
    provenance = RateProvenance("test", metadata={"desk": "treasury"})
    rate = ExchangeRate(CurrencyCode("USD"), CurrencyCode("EUR"), Decimal("0.9"), provenance)
    assert isinstance(hash(provenance), int)
    assert isinstance(hash(rate), int)


def test_registry_iteration_is_snapshot_safe_during_concurrent_mutation() -> None:
    registry = CurrencyRegistry.iso4217()

    def mutate(i: int) -> None:
        code = f"Z{chr(65 + i // 26)}{chr(65 + i % 26)}"
        registry.register(Currency(CurrencyCode(code), 2), replace=True)
        tuple(registry)

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(mutate, range(100)))

    assert len(tuple(registry)) >= 100


def test_large_formatting_is_independent_of_ambient_decimal_context() -> None:
    from decimal import getcontext

    from moneytender import Money

    money = Money.from_minor(10**60 + 12345, "USD")
    previous = getcontext().prec
    try:
        getcontext().prec = 6
        rendered = money.format()
    finally:
        getcontext().prec = previous

    assert rendered.endswith("123.45")


def test_major_construction_multiply_rate_and_cash_round_ignore_ambient_context() -> None:
    from decimal import Decimal, getcontext

    from moneytender import Money, round_to_increment

    previous = getcontext().prec
    try:
        getcontext().prec = 6
        major = Money.from_major(
            Decimal("10000000000000000000000000000000000000000000000000000000123.45"),
            "USD",
        )
        multiplied = Money.from_minor(10**60 + 12345, "USD").multiply_rate(
            Decimal("1.000000000000000000000000000001")
        )
        rounded = round_to_increment(10**60 + 12345, 5)
    finally:
        getcontext().prec = previous

    assert major.minor == 10**60 + 12345
    assert multiplied.minor > 10**60
    assert rounded == 10**60 + 12345
