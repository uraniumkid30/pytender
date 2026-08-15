from __future__ import annotations

from decimal import Decimal

import pytest

import pytender
from pytender import (
    CurrencyCode,
    DerivationKind,
    ExchangeRate,
    InvalidRateError,
    RateKind,
    RatePolicy,
    RateProvenance,
)
from pytender.infrastructure import (
    AsyncFromSyncProvider,
    build_async_production_provider,
    build_production_provider,
    ProductionProviderConfig,
    RetryPolicy,
)

USD = CurrencyCode("USD")
EUR = CurrencyCode("EUR")


def _rate(value: str = "0.9") -> ExchangeRate:
    return ExchangeRate(
        USD,
        EUR,
        Decimal(value),
        RateProvenance("fallback"),
        RateKind.REFERENCE,
    )


def test_public_version_and_small_top_level_surface() -> None:
    assert pytender.__version__ == "1.0.0"
    assert not hasattr(pytender, "RetryingRateProvider")
    assert not hasattr(pytender, "build_production_provider")


def test_derived_rate_requires_typed_derivation() -> None:
    with pytest.raises(InvalidRateError, match="must declare how"):
        ExchangeRate(
            USD,
            EUR,
            Decimal("0.9"),
            RateProvenance("custom"),
            RateKind.DERIVED,
        )


def test_non_derived_rate_rejects_derived_typed_state() -> None:
    with pytest.raises(InvalidRateError, match="non-derived"):
        ExchangeRate(
            USD,
            EUR,
            Decimal("0.9"),
            RateProvenance("custom"),
            RateKind.REFERENCE,
            DerivationKind.CUSTOM,
        )


def test_metadata_cannot_contradict_typed_derivation() -> None:
    with pytest.raises(InvalidRateError, match="conflicts"):
        ExchangeRate(
            USD,
            EUR,
            Decimal("0.9"),
            RateProvenance("custom", metadata={"derived": "inverse"}),
            RateKind.DERIVED,
            DerivationKind.TRIANGULATION,
        )


def test_rate_policy_uses_typed_derivation_not_free_form_metadata() -> None:
    rate = ExchangeRate(
        USD,
        EUR,
        Decimal("0.9"),
        RateProvenance("custom", metadata={"note": "inverse-like source naming"}),
        RateKind.REFERENCE,
    )
    RatePolicy().validate(rate)


def test_custom_derivation_has_an_explicit_typed_escape_hatch() -> None:
    rate = ExchangeRate(
        USD,
        EUR,
        Decimal("0.9"),
        RateProvenance("custom"),
        RateKind.DERIVED,
        DerivationKind.CUSTOM,
    )
    RatePolicy(allowed_kinds=frozenset({RateKind.DERIVED})).validate(rate)


def test_production_builder_retries_each_provider_before_failover() -> None:
    class Primary:
        def __init__(self) -> None:
            self.calls = 0

        def get_rate(self, base: CurrencyCode, quote: CurrencyCode) -> ExchangeRate:
            from pytender import ProviderError

            self.calls += 1
            raise ProviderError("primary down")

    class Fallback:
        def __init__(self) -> None:
            self.calls = 0

        def get_rate(self, base: CurrencyCode, quote: CurrencyCode) -> ExchangeRate:
            self.calls += 1
            return _rate()

    primary = Primary()
    fallback = Fallback()
    provider = build_production_provider(
        primary,
        fallback,
        config=ProductionProviderConfig(
            retry=RetryPolicy(
                attempts=3,
                base_delay_seconds=0,
                max_delay_seconds=0,
                jitter_ratio=0,
            )
        ),
    )

    assert provider.get_rate(USD, EUR).value == Decimal("0.9")
    assert primary.calls == 3
    assert fallback.calls == 1


@pytest.mark.asyncio
async def test_async_production_builder_matches_sync_retry_failover_semantics() -> None:
    class Primary:
        def __init__(self) -> None:
            self.calls = 0

        async def get_rate(self, base: CurrencyCode, quote: CurrencyCode) -> ExchangeRate:
            from pytender import ProviderError

            self.calls += 1
            raise ProviderError("primary down")

    class Fallback:
        def __init__(self) -> None:
            self.calls = 0

        async def get_rate(self, base: CurrencyCode, quote: CurrencyCode) -> ExchangeRate:
            self.calls += 1
            return _rate()

    primary = Primary()
    fallback = Fallback()
    provider = build_async_production_provider(
        primary,
        fallback,
        config=ProductionProviderConfig(
            retry=RetryPolicy(
                attempts=3,
                base_delay_seconds=0,
                max_delay_seconds=0,
                jitter_ratio=0,
            )
        ),
    )

    assert (await provider.get_rate(USD, EUR)).value == Decimal("0.9")
    assert primary.calls == 3
    assert fallback.calls == 1


@pytest.mark.asyncio
async def test_sync_async_simple_provider_contracts_remain_equivalent() -> None:
    from pytender import StaticRateProvider

    sync = StaticRateProvider({("USD", "EUR"): "0.9"})
    async_provider = AsyncFromSyncProvider(sync)

    sync_rate = sync.get_rate(USD, EUR)
    async_rate = await async_provider.get_rate(USD, EUR)

    assert async_rate.base == sync_rate.base
    assert async_rate.quote == sync_rate.quote
    assert async_rate.value == sync_rate.value
    assert async_rate.kind == sync_rate.kind
    assert async_rate.derivation == sync_rate.derivation
    assert async_rate.source == sync_rate.source
