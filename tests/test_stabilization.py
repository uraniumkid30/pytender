import asyncio
import threading
import time
from datetime import date
from decimal import Decimal

import pytest

from pytender import (
    AsyncExchangeRateProvider,
    Currency,
    CurrencyCode,
    CurrencyRegistry,
    CurrencyStatus,
    ExchangeRate,
    ExchangeRateProvider,
    InvalidRateError,
    Money,
    MoneyConverter,
    SimpleMoneyFormatter,
    StaticRateProvider,
)
from pytender.adapters.database import from_columns, to_columns
from pytender.infrastructure import (
    AsyncCachedRateProvider,
    AsyncFromSyncProvider,
    AsyncTriangulatingRateProvider,
    CachedRateProvider,
    TriangulatingRateProvider,
)


def test_triangulation_and_provenance():
    provider = TriangulatingRateProvider(
        StaticRateProvider({("NGN", "USD"): "0.00065", ("USD", "EUR"): "0.91"}),
        pivots=("USD",),
    )
    rate = provider.get_rate(CurrencyCode("NGN"), CurrencyCode("EUR"))
    assert rate.value == Decimal("0.0005915")
    assert rate.provenance.metadata["path"] == "NGN/USD/EUR"


def test_async_triangulation():
    async def run():
        provider = AsyncTriangulatingRateProvider(
            AsyncFromSyncProvider(StaticRateProvider({("NGN", "USD"): "0.00065", ("USD", "EUR"): "0.91"})),
            pivots=("USD",),
        )
        return await provider.get_rate(CurrencyCode("NGN"), CurrencyCode("EUR"))
    assert asyncio.run(run()).value == Decimal("0.0005915")


def test_converter_rejects_provider_wrong_pair():
    class BrokenProvider:
        def get_rate(self, base, quote):
            return ExchangeRate(CurrencyCode("EUR"), CurrencyCode("GBP"), Decimal("1"))
    with pytest.raises(InvalidRateError, match="provider returned"):
        MoneyConverter(BrokenProvider()).convert(Money.from_minor(100, "USD"), "EUR")


def test_sync_cache_single_flight():
    class CountingProvider:
        def __init__(self):
            self.calls = 0
        def get_rate(self, base, quote):
            self.calls += 1
            time.sleep(0.03)
            return ExchangeRate(base, quote, Decimal("1.2"))
    inner = CountingProvider()
    cached = CachedRateProvider(inner, ttl_seconds=10)
    results = []
    threads = [
        threading.Thread(
            target=lambda: results.append(
                cached.get_rate(CurrencyCode("USD"), CurrencyCode("EUR"))
            )
        )
        for _ in range(12)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert inner.calls == 1
    assert len(results) == 12


def test_async_cache_single_flight():
    class Provider:
        def __init__(self):
            self.calls = 0
        async def get_rate(self, base, quote):
            self.calls += 1
            await asyncio.sleep(0.02)
            return ExchangeRate(base, quote, Decimal("1.2"))
    async def run():
        inner = Provider()
        cached = AsyncCachedRateProvider(inner, ttl_seconds=10)
        await asyncio.gather(
            *(
                cached.get_rate(CurrencyCode("USD"), CurrencyCode("EUR"))
                for _ in range(12)
            )
        )
        return inner.calls
    assert asyncio.run(run()) == 1


def test_historical_currency_metadata_remains_representable():
    bgn = Currency(
        CurrencyCode("BGN"),
        2,
        "лв",
        "Bulgarian Lev",
        "975",
        1,
        CurrencyStatus.HISTORICAL,
        valid_to=date(2025, 12, 31),
        replacement_code=CurrencyCode("EUR"),
    )
    registry = CurrencyRegistry([bgn])
    money = Money.from_major("12.34", "BGN", registry=registry)
    assert money.minor == 1234
    assert registry.historical() == (bgn,)
    assert not bgn.is_valid_on(date(2026, 1, 1))


def test_relational_columns_contract_roundtrip():
    money = Money.from_minor(123456789012345678901234567890, "USD")
    columns = to_columns(money)
    assert columns == {"amount_minor": 123456789012345678901234567890, "currency_code": "USD"}
    assert from_columns(**columns) == money


def test_deterministic_formatter_and_negative_symbol():
    formatter = SimpleMoneyFormatter(thousands_separator=",", decimal_separator=".")
    formatted = formatter.format(Money.from_major("-1234.50", "USD"))
    assert formatted in {"-US$1,234.50", "-$1,234.50"}


def test_provider_protocols_are_discoverable_from_provider_namespace():
    from pytender.providers import AsyncExchangeRateProvider as AsyncP
    from pytender.providers import ExchangeRateProvider as SyncP

    assert SyncP is ExchangeRateProvider
    assert AsyncP is AsyncExchangeRateProvider


def test_converter_rejects_invalid_provider_early():
    with pytest.raises(TypeError, match=r"docs/PROVIDERS\.md"):
        MoneyConverter(object())  # type: ignore[arg-type]
