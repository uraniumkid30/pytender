import asyncio
from decimal import Decimal

import pytest

from pytender import (
    AsyncMoneyConverter,
    CurrencyCode,
    Money,
    MoneyConverter,
    RateUnavailableError,
    StaticRateProvider,
)
from pytender.infrastructure import (
    AsyncCachedRateProvider,
    AsyncFromSyncProvider,
    InverseRateProvider,
)


def test_conversion_exact_rounding() -> None:
    converter = MoneyConverter(StaticRateProvider({("USD", "EUR"): "0.8"}))
    assert converter.convert(Money.from_major("10.00", "USD"), "EUR").minor == 800


def test_inverse_provider() -> None:
    provider = InverseRateProvider(StaticRateProvider({("EUR", "USD"): "2"}))
    rate = provider.get_rate(CurrencyCode("USD"), CurrencyCode("EUR"))
    assert rate.value == Decimal("0.5")


def test_missing_rate_is_clear() -> None:
    with pytest.raises(RateUnavailableError):
        StaticRateProvider({}).get_rate(CurrencyCode("USD"), CurrencyCode("NGN"))


def test_async_conversion_and_cache() -> None:
    async def run() -> None:
        provider = AsyncCachedRateProvider(
            AsyncFromSyncProvider(StaticRateProvider({("USD", "EUR"): "0.75"})),
            ttl_seconds=30,
        )
        converter = AsyncMoneyConverter(provider)
        result = await converter.convert(Money.from_major("4", "USD"), "EUR")
        assert result.major == Decimal("3")

    asyncio.run(run())
