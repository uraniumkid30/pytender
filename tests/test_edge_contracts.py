from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest

from moneytender import (
    AllocationError,
    AsyncMoneyConverter,
    CircuitOpenError,
    Currency,
    CurrencyCode,
    CurrencyMismatchError,
    CurrencyRegistry,
    CurrencyStatus,
    DownRounding,
    DuplicateCurrencyError,
    ExchangeRate,
    HalfUpRounding,
    InvalidAmountError,
    InvalidRateError,
    Money,
    MoneyConverter,
    ProviderError,
    RateKind,
    RatePolicy,
    RatePolicyError,
    RateProvenance,
    RateUnavailableError,
    RegistryFrozenError,
    RoundingError,
    StaleRateError,
    StaticRateProvider,
    UnknownCurrencyError,
    UpRounding,
    round_to_increment,
)
from moneytender.adapters.database import from_columns, to_columns
from moneytender.infrastructure import (
    AsyncChainedRateProvider,
    AsyncCircuitBreakerRateProvider,
    AsyncFromSyncProvider,
    AsyncInverseRateProvider,
    AsyncObservedRateProvider,
    AsyncPolicyRateProvider,
    AsyncRetryingRateProvider,
    AsyncTriangulatingRateProvider,
    ChainedRateProvider,
    CircuitBreakerRateProvider,
    InverseRateProvider,
    ObservedRateProvider,
    PolicyRateProvider,
    ProviderEvent,
    RetryingRateProvider,
    RetryPolicy,
    TriangulatingRateProvider,
)
from moneytender.registry import DEFAULT_REGISTRY
from moneytender.serialization import from_dict, to_dict


def test_money_constructor_and_arithmetic_error_paths() -> None:
    with pytest.raises(TypeError):
        Money.from_minor(True, "USD")
    with pytest.raises(TypeError):
        Money("bad", DEFAULT_REGISTRY.get("USD"))  # type: ignore[arg-type]
    with pytest.raises(InvalidAmountError):
        Money.from_major("not-a-number", "USD")
    with pytest.raises(TypeError):
        Money.from_major("1", "USD") * Decimal("2")  # type: ignore[operator]

    usd = Money.from_minor(100, "USD")
    assert -usd == Money.from_minor(-100, "USD")
    assert abs(-usd) == usd
    assert bool(usd)
    assert not bool(Money.from_minor(0, "USD"))
    assert 3 * usd == Money.from_minor(300, "USD")
    assert usd.multiply_rate("1.5") == Money.from_minor(150, "USD")


def test_money_ratio_comparison_and_allocation_contracts() -> None:
    one = Money.from_minor(100, "USD")
    two = Money.from_minor(200, "USD")
    assert one < two
    assert one <= two
    assert two > one
    assert two >= one
    assert one.ratio(two) == Decimal("0.5")

    with pytest.raises(ZeroDivisionError):
        one.ratio(Money.from_minor(0, "USD"))
    with pytest.raises(CurrencyMismatchError):
        one + Money.from_minor(1, "EUR")
    with pytest.raises(AllocationError):
        one.split(0)
    with pytest.raises(AllocationError):
        one.allocate([])
    with pytest.raises(AllocationError):
        one.allocate([1, True])
    with pytest.raises(AllocationError):
        one.allocate([1, -1])

    assert [part.minor for part in Money.from_minor(-5, "USD").split(2)] == [-3, -2]
    assert [part.minor for part in one.allocate([0, 0])] == [0, 0]
    assert sum(part.minor for part in Money.from_minor(-101, "USD").allocate([1, 1])) == -101


def test_rounding_policies_and_validation() -> None:
    assert HalfUpRounding().quantize_minor(Decimal("1.5")) == 2
    assert DownRounding().quantize_minor(Decimal("1.9")) == 1
    assert UpRounding().quantize_minor(Decimal("1.1")) == 2
    assert round_to_increment(103, 5) == 105
    with pytest.raises(RoundingError):
        round_to_increment(True, 5)
    with pytest.raises(RoundingError):
        round_to_increment(10, 0)
    with pytest.raises(RoundingError):
        HalfUpRounding().quantize_minor(Decimal("NaN"))


def test_currency_validation_and_lifecycle() -> None:
    with pytest.raises(ValueError):
        Currency(CurrencyCode("US"), 2)
    with pytest.raises(ValueError):
        Currency(CurrencyCode("USD"), True)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        Currency(CurrencyCode("USD"), 10)
    with pytest.raises(ValueError):
        Currency(CurrencyCode("USD"), 2, numeric_code="12")
    with pytest.raises(ValueError):
        Currency(CurrencyCode("USD"), 2, cash_increment=0)
    with pytest.raises(ValueError):
        Currency(
            CurrencyCode("USD"),
            2,
            valid_from=date(2026, 2, 1),
            valid_to=date(2026, 1, 1),
        )
    with pytest.raises(ValueError):
        Currency(CurrencyCode("USD"), 2, replacement_code=CurrencyCode("EU"))

    historical = Currency(
        CurrencyCode("ZZZ"),
        2,
        status=CurrencyStatus.HISTORICAL,
        valid_from=date(2020, 1, 1),
        valid_to=date(2021, 12, 31),
    )
    assert not historical.is_valid_on(date(2019, 1, 1))
    assert historical.is_valid_on(date(2021, 1, 1))
    assert not historical.is_valid_on(date(2022, 1, 1))


def test_registry_full_mutation_contract() -> None:
    registry = CurrencyRegistry()
    currency = Currency(CurrencyCode("TOK"), 4, status=CurrencyStatus.CUSTOM)
    registry.register(currency)
    assert registry.contains("tok")
    with pytest.raises(DuplicateCurrencyError):
        registry.register(currency)
    replacement = Currency(CurrencyCode("TOK"), 2, status=CurrencyStatus.CUSTOM)
    registry.register(replacement, replace=True)
    assert registry.get("TOK") == replacement
    assert registry.unregister("TOK") == replacement
    with pytest.raises(UnknownCurrencyError):
        registry.get("TOK")
    with pytest.raises(UnknownCurrencyError):
        registry.unregister("TOK")

    registry.register_many([currency])
    clone = registry.clone(frozen=True)
    assert clone.is_frozen
    with pytest.raises(RegistryFrozenError):
        clone.unregister("TOK")
    assert len(tuple(iter(registry))) == 1


def test_serialization_and_database_validation() -> None:
    money = Money.from_minor(-123, "USD")
    assert from_dict(to_dict(money)) == money
    assert from_columns(**to_columns(money)) == money
    with pytest.raises(TypeError):
        from_dict({"amount": True, "currency": "USD"})  # type: ignore[typeddict-item]
    with pytest.raises(TypeError):
        from_dict({"amount": 1, "currency": 3})  # type: ignore[typeddict-item]
    with pytest.raises(TypeError):
        from_columns(True, "USD")
    with pytest.raises(TypeError):
        from_columns(1, 2)  # type: ignore[arg-type]


def test_rate_validation_and_provenance_contracts() -> None:
    with pytest.raises(ValueError):
        RateProvenance("")
    with pytest.raises(ValueError):
        RateProvenance("x", as_of=datetime(2026, 1, 1))
    with pytest.raises(ValueError):
        RateProvenance("x", fetched_at=datetime(2026, 1, 1))
    with pytest.raises(InvalidRateError):
        ExchangeRate(CurrencyCode("USD"), CurrencyCode("EUR"), 1)  # type: ignore[arg-type]
    with pytest.raises(InvalidRateError):
        ExchangeRate(CurrencyCode("USD"), CurrencyCode("EUR"), Decimal("0"))
    with pytest.raises(InvalidRateError):
        ExchangeRate(CurrencyCode("USD"), CurrencyCode("EUR"), Decimal("NaN"))
    with pytest.raises(InvalidRateError):
        ExchangeRate(
            CurrencyCode("USD"),
            CurrencyCode("EUR"),
            Decimal("1"),
            kind="reference",  # type: ignore[arg-type]
        )


def test_static_inverse_and_chain_contracts() -> None:
    with pytest.raises(InvalidRateError):
        StaticRateProvider({("USD", "EUR"): 1.2})
    with pytest.raises(InvalidRateError):
        StaticRateProvider({("USD", "EUR"): "0"})

    static = StaticRateProvider({("EUR", "USD"): "2"}, name="rates")
    identity = static.get_rate(CurrencyCode("USD"), CurrencyCode("USD"))
    assert identity.value == Decimal("1")
    with pytest.raises(RateUnavailableError):
        static.get_rate(CurrencyCode("GBP"), CurrencyCode("EUR"))

    inverse = InverseRateProvider(static).get_rate(CurrencyCode("USD"), CurrencyCode("EUR"))
    assert inverse.value == Decimal("0.5")
    assert inverse.kind is RateKind.DERIVED

    class Missing:
        def get_rate(self, base: CurrencyCode, quote: CurrencyCode) -> ExchangeRate:
            raise RateUnavailableError("missing")

    with pytest.raises(RateUnavailableError):
        InverseRateProvider(Missing()).get_rate(CurrencyCode("USD"), CurrencyCode("EUR"))
    with pytest.raises(ValueError):
        ChainedRateProvider()
    with pytest.raises(RateUnavailableError):
        ChainedRateProvider(Missing()).get_rate(CurrencyCode("USD"), CurrencyCode("EUR"))


def test_policy_provider_and_future_timestamp() -> None:
    now = datetime.now(UTC)

    class FutureProvider:
        def get_rate(self, base: CurrencyCode, quote: CurrencyCode) -> ExchangeRate:
            return ExchangeRate(
                base,
                quote,
                Decimal("1"),
                RateProvenance("future", as_of=now + timedelta(minutes=1)),
            )

    policy = RatePolicy(max_age=timedelta(minutes=1), max_future_skew=timedelta(seconds=1))
    with pytest.raises(RatePolicyError):
        PolicyRateProvider(FutureProvider(), policy).get_rate(CurrencyCode("USD"), CurrencyCode("EUR"))


def test_converter_identity_bad_pair_and_same_code_metadata_mismatch() -> None:
    static = StaticRateProvider({("USD", "EUR"): "1"})
    converter = MoneyConverter(static)
    usd = Money.from_minor(100, "USD")
    assert converter.convert(usd, "USD") is usd

    class WrongPair:
        def get_rate(self, base: CurrencyCode, quote: CurrencyCode) -> ExchangeRate:
            return ExchangeRate(CurrencyCode("GBP"), quote, Decimal("1"))

    with pytest.raises(InvalidRateError):
        MoneyConverter(WrongPair()).convert(usd, "EUR")
    with pytest.raises(TypeError):
        MoneyConverter(object())  # type: ignore[arg-type]

    custom_usd = Currency(CurrencyCode("USD"), 0, "$", "Whole USD")
    with pytest.raises(InvalidRateError):
        converter.convert(usd, custom_usd)


@pytest.mark.asyncio
async def test_async_provider_variants_and_error_paths() -> None:
    static = StaticRateProvider({("EUR", "USD"): "2"})
    adapted = AsyncFromSyncProvider(static)
    assert (await adapted.get_rate(CurrencyCode("EUR"), CurrencyCode("USD"))).value == Decimal("2")

    inverse = AsyncInverseRateProvider(adapted)
    assert (await inverse.get_rate(CurrencyCode("USD"), CurrencyCode("EUR"))).value == Decimal("0.5")

    class AsyncMissing:
        async def get_rate(self, base: CurrencyCode, quote: CurrencyCode) -> ExchangeRate:
            raise RateUnavailableError("missing")

    with pytest.raises(RateUnavailableError):
        await AsyncInverseRateProvider(AsyncMissing()).get_rate(CurrencyCode("USD"), CurrencyCode("EUR"))
    with pytest.raises(ValueError):
        AsyncChainedRateProvider()
    with pytest.raises(RateUnavailableError):
        await AsyncChainedRateProvider(AsyncMissing()).get_rate(CurrencyCode("USD"), CurrencyCode("EUR"))

    with pytest.raises(TypeError):
        AsyncMoneyConverter(object())  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_async_triangulation_direct_and_derived() -> None:
    direct = AsyncFromSyncProvider(StaticRateProvider({("USD", "EUR"): "0.9"}))
    provider = AsyncTriangulatingRateProvider(direct, pivots=("GBP",))
    assert (await provider.get_rate(CurrencyCode("USD"), CurrencyCode("EUR"))).value == Decimal("0.9")

    derived = AsyncFromSyncProvider(StaticRateProvider({("NGN", "USD"): "0.001", ("USD", "EUR"): "0.9"}))
    cross = await AsyncTriangulatingRateProvider(derived, pivots=("USD",)).get_rate(
        CurrencyCode("NGN"), CurrencyCode("EUR")
    )
    assert cross.kind is RateKind.DERIVED

    with pytest.raises(ValueError):
        AsyncTriangulatingRateProvider(derived, pivots=())


def test_sync_triangulation_validation_and_failure() -> None:
    direct = StaticRateProvider({("USD", "EUR"): "0.9"})
    assert TriangulatingRateProvider(direct).get_rate(
        CurrencyCode("USD"), CurrencyCode("EUR")
    ).value == Decimal("0.9")
    with pytest.raises(ValueError):
        TriangulatingRateProvider(direct, pivots=())
    with pytest.raises(RateUnavailableError):
        TriangulatingRateProvider(direct, pivots=("GBP",)).get_rate(CurrencyCode("NGN"), CurrencyCode("JPY"))


def test_retry_policy_validation_and_exhaustion() -> None:
    for kwargs in (
        {"attempts": 0},
        {"base_delay_seconds": -1},
        {"backoff_multiplier": 0.5},
        {"jitter_ratio": 2},
    ):
        with pytest.raises(ValueError):
            RetryPolicy(**kwargs)  # type: ignore[arg-type]

    class Down:
        def get_rate(self, base: CurrencyCode, quote: CurrencyCode) -> ExchangeRate:
            raise ProviderError("down")

    provider = RetryingRateProvider(
        Down(),
        policy=RetryPolicy(attempts=2, base_delay_seconds=0, jitter_ratio=0),
    )
    with pytest.raises(ProviderError, match="after 2 attempts"):
        provider.get_rate(CurrencyCode("USD"), CurrencyCode("EUR"))


@pytest.mark.asyncio
async def test_async_retry_exhaustion_and_policy_decorator() -> None:
    class Down:
        async def get_rate(self, base: CurrencyCode, quote: CurrencyCode) -> ExchangeRate:
            raise ProviderError("down")

    retrying = AsyncRetryingRateProvider(
        Down(),
        policy=RetryPolicy(attempts=2, base_delay_seconds=0, jitter_ratio=0),
    )
    with pytest.raises(ProviderError, match="after 2 attempts"):
        await retrying.get_rate(CurrencyCode("USD"), CurrencyCode("EUR"))

    old = datetime.now(UTC) - timedelta(days=1)

    class Old:
        async def get_rate(self, base: CurrencyCode, quote: CurrencyCode) -> ExchangeRate:
            return ExchangeRate(base, quote, Decimal("1"), RateProvenance("old", as_of=old))

    with pytest.raises(StaleRateError):
        await AsyncPolicyRateProvider(Old(), RatePolicy(max_age=timedelta(seconds=1))).get_rate(
            CurrencyCode("USD"), CurrencyCode("EUR")
        )


def test_observer_records_success_and_failure() -> None:
    events: list[ProviderEvent] = []

    class Observer:
        def observe(self, event: ProviderEvent) -> None:
            events.append(event)

    good = ObservedRateProvider(
        StaticRateProvider({("USD", "EUR"): "1"}),
        Observer(),
    )
    good.get_rate(CurrencyCode("USD"), CurrencyCode("EUR"))
    assert events[-1].succeeded

    class Bad:
        def get_rate(self, base: CurrencyCode, quote: CurrencyCode) -> ExchangeRate:
            raise ProviderError("boom")

    with pytest.raises(ProviderError):
        ObservedRateProvider(Bad(), Observer()).get_rate(CurrencyCode("USD"), CurrencyCode("EUR"))
    assert not events[-1].succeeded
    assert events[-1].error_type == "ProviderError"


@pytest.mark.asyncio
async def test_async_observer_records_success_and_failure() -> None:
    events: list[ProviderEvent] = []

    class Observer:
        async def observe(self, event: ProviderEvent) -> None:
            events.append(event)

    class Good:
        async def get_rate(self, base: CurrencyCode, quote: CurrencyCode) -> ExchangeRate:
            return ExchangeRate(base, quote, Decimal("1"), RateProvenance("good"))

    await AsyncObservedRateProvider(Good(), Observer()).get_rate(CurrencyCode("USD"), CurrencyCode("EUR"))
    assert events[-1].succeeded

    class Bad:
        async def get_rate(self, base: CurrencyCode, quote: CurrencyCode) -> ExchangeRate:
            raise ProviderError("boom")

    with pytest.raises(ProviderError):
        await AsyncObservedRateProvider(Bad(), Observer()).get_rate(CurrencyCode("USD"), CurrencyCode("EUR"))
    assert not events[-1].succeeded


@pytest.mark.asyncio
async def test_async_circuit_breaker_opens() -> None:
    class Down:
        async def get_rate(self, base: CurrencyCode, quote: CurrencyCode) -> ExchangeRate:
            raise ProviderError("down")

    breaker = AsyncCircuitBreakerRateProvider(Down(), failure_threshold=1, recovery_timeout_seconds=60)
    with pytest.raises(ProviderError):
        await breaker.get_rate(CurrencyCode("USD"), CurrencyCode("EUR"))
    with pytest.raises(CircuitOpenError):
        await breaker.get_rate(CurrencyCode("USD"), CurrencyCode("EUR"))


def test_cache_validation_clear_and_error_without_stale_fallback() -> None:
    with pytest.raises(ValueError):
        from moneytender.infrastructure import CachedRateProvider

        CachedRateProvider(StaticRateProvider({}), ttl_seconds=0)
    with pytest.raises(ValueError):
        from moneytender.infrastructure import CachedRateProvider

        CachedRateProvider(StaticRateProvider({}), stale_if_error_seconds=-1)

    class Down:
        def get_rate(self, base: CurrencyCode, quote: CurrencyCode) -> ExchangeRate:
            raise ProviderError("down")

    from moneytender.infrastructure import CachedRateProvider

    cache = CachedRateProvider(Down())
    with pytest.raises(ProviderError):
        cache.get_rate(CurrencyCode("USD"), CurrencyCode("EUR"))
    cache.clear()
    assert cache.size == 0


@pytest.mark.asyncio
async def test_async_cache_validation_clear_and_provider_failure() -> None:
    from moneytender.infrastructure import AsyncCachedRateProvider

    with pytest.raises(ValueError):
        AsyncCachedRateProvider(AsyncFromSyncProvider(StaticRateProvider({})), maxsize=0)
    with pytest.raises(ValueError):
        AsyncCachedRateProvider(AsyncFromSyncProvider(StaticRateProvider({})), stale_if_error_seconds=-1)

    class Down:
        async def get_rate(self, base: CurrencyCode, quote: CurrencyCode) -> ExchangeRate:
            raise ProviderError("down")

    cache = AsyncCachedRateProvider(Down())
    with pytest.raises(ProviderError):
        await cache.get_rate(CurrencyCode("USD"), CurrencyCode("EUR"))
    await cache.clear()
    assert cache.size == 0


def test_retry_unavailable_is_not_retried_by_default() -> None:
    calls = 0

    class Missing:
        def get_rate(self, base: CurrencyCode, quote: CurrencyCode) -> ExchangeRate:
            nonlocal calls
            calls += 1
            raise RateUnavailableError("missing")

    provider = RetryingRateProvider(
        Missing(), policy=RetryPolicy(attempts=3, base_delay_seconds=0, jitter_ratio=0)
    )
    with pytest.raises(RateUnavailableError):
        provider.get_rate(CurrencyCode("USD"), CurrencyCode("EUR"))
    assert calls == 1


@pytest.mark.asyncio
async def test_async_retry_unavailable_can_be_explicitly_retried() -> None:
    calls = 0

    class Missing:
        async def get_rate(self, base: CurrencyCode, quote: CurrencyCode) -> ExchangeRate:
            nonlocal calls
            calls += 1
            raise RateUnavailableError("missing")

    provider = AsyncRetryingRateProvider(
        Missing(),
        policy=RetryPolicy(
            attempts=2,
            base_delay_seconds=0,
            jitter_ratio=0,
            retry_rate_unavailable=True,
        ),
    )
    with pytest.raises(RateUnavailableError):
        await provider.get_rate(CurrencyCode("USD"), CurrencyCode("EUR"))
    assert calls == 2


def test_circuit_breaker_validation_state_and_success_reset() -> None:
    with pytest.raises(ValueError):
        CircuitBreakerRateProvider(StaticRateProvider({}), failure_threshold=0)
    with pytest.raises(ValueError):
        CircuitBreakerRateProvider(StaticRateProvider({}), recovery_timeout_seconds=0)

    good = CircuitBreakerRateProvider(
        StaticRateProvider({("USD", "EUR"): "1"}),
        failure_threshold=1,
        recovery_timeout_seconds=1,
    )
    from moneytender.infrastructure import CircuitState

    assert good.state is CircuitState.CLOSED
    good.get_rate(CurrencyCode("USD"), CurrencyCode("EUR"))
    assert good.state is CircuitState.CLOSED


@pytest.mark.asyncio
async def test_async_circuit_breaker_validation_and_success() -> None:
    with pytest.raises(ValueError):
        AsyncCircuitBreakerRateProvider(AsyncFromSyncProvider(StaticRateProvider({})), failure_threshold=0)
    with pytest.raises(ValueError):
        AsyncCircuitBreakerRateProvider(
            AsyncFromSyncProvider(StaticRateProvider({})), recovery_timeout_seconds=0
        )

    good = AsyncCircuitBreakerRateProvider(
        AsyncFromSyncProvider(StaticRateProvider({("USD", "EUR"): "1"})),
        failure_threshold=1,
        recovery_timeout_seconds=1,
    )
    assert (await good.get_rate(CurrencyCode("USD"), CurrencyCode("EUR"))).value == Decimal("1")


@pytest.mark.asyncio
async def test_async_converter_identity_policy_and_bad_pair() -> None:
    provider = AsyncFromSyncProvider(StaticRateProvider({("USD", "EUR"): "1"}, kind=RateKind.EXECUTABLE))
    converter = AsyncMoneyConverter(
        provider,
        policy=RatePolicy(allowed_kinds=frozenset({RateKind.EXECUTABLE})),
    )
    usd = Money.from_minor(100, "USD")
    assert await converter.convert(usd, "USD") is usd
    result = await converter.convert_with_rate(usd, "EUR")
    assert result.target.minor == 100

    class Wrong:
        async def get_rate(self, base: CurrencyCode, quote: CurrencyCode) -> ExchangeRate:
            return ExchangeRate(CurrencyCode("GBP"), quote, Decimal("1"))

    with pytest.raises(InvalidRateError):
        await AsyncMoneyConverter(Wrong()).convert(usd, "EUR")


def test_money_format_cash_round_and_notimplemented_paths() -> None:
    money = Money.from_minor(103, "CHF")
    assert money.cash_round().minor == 105
    assert isinstance(str(money), str)
    assert money.__add__(object()) is NotImplemented
    assert money.__sub__(object()) is NotImplemented


def test_policy_validation_constructor_and_missing_timestamp_paths() -> None:
    with pytest.raises(ValueError):
        RatePolicy(max_age=timedelta(seconds=-1))
    with pytest.raises(ValueError):
        RatePolicy(allowed_kinds=frozenset())
    with pytest.raises(ValueError):
        RatePolicy(max_future_skew=timedelta(seconds=-1))
    with pytest.raises(TypeError):
        RatePolicy().validate(object())  # type: ignore[arg-type]

    policy = RatePolicy(max_age=timedelta(seconds=1))
    with pytest.raises(RatePolicyError):
        policy.validate(
            ExchangeRate(
                CurrencyCode("USD"),
                CurrencyCode("EUR"),
                Decimal("1"),
                RateProvenance("untimed"),
            )
        )


def test_registry_current_historical_and_freeze() -> None:
    registry = CurrencyRegistry(
        [
            Currency(CurrencyCode("AAA"), 2),
            Currency(
                CurrencyCode("BBB"),
                2,
                status=CurrencyStatus.HISTORICAL,
            ),
        ]
    )
    assert [currency.code for currency in registry.current()] == ["AAA"]
    assert [currency.code for currency in registry.historical()] == ["BBB"]
    assert registry.freeze() is registry
    with pytest.raises(RegistryFrozenError):
        registry.register(Currency(CurrencyCode("CCC"), 2))


def test_provenance_metadata_must_be_hashable_string_metadata() -> None:
    with pytest.raises(TypeError):
        RateProvenance("provider", metadata={"bad": ["value"]})  # type: ignore[dict-item]
    provenance = RateProvenance("provider", metadata={"environment": "prod"})
    assert isinstance(hash(provenance), int)


def test_exchange_rate_and_static_provider_validate_currency_codes_and_inputs() -> None:
    with pytest.raises(InvalidRateError):
        ExchangeRate(CurrencyCode("USDX"), CurrencyCode("EUR"), Decimal("1"))
    with pytest.raises(InvalidRateError):
        StaticRateProvider({("USD", "EUR"): True})
    with pytest.raises(InvalidRateError):
        StaticRateProvider({("USD", "EUR"): "not-a-rate"})
    with pytest.raises(InvalidRateError):
        StaticRateProvider({("BAD!", "EUR"): "1"})


def test_money_ordering_returns_notimplemented_for_other_types() -> None:
    money = Money.from_minor(1, "USD")
    assert money.__lt__(object()) is NotImplemented
    assert money.__le__(object()) is NotImplemented
    assert money.__gt__(object()) is NotImplemented
    assert money.__ge__(object()) is NotImplemented


def test_register_many_is_all_or_nothing_on_duplicate() -> None:
    registry = CurrencyRegistry()
    first = Currency(CurrencyCode("AAA"), 2)
    duplicate = Currency(CurrencyCode("AAA"), 3)
    second = Currency(CurrencyCode("BBB"), 2)

    with pytest.raises(DuplicateCurrencyError):
        registry.register_many([first, duplicate, second])

    assert len(registry) == 0
