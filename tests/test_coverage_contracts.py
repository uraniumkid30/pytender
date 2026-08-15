from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest

import pytender.plugins as plugins
from pytender import (
    Currency,
    CurrencyCode,
    InvalidAmountError,
    InvalidRateError,
    Money,
    MoneyConverter,
    RateKind,
    RatePolicy,
    RatePolicyError,
    RateProvenance,
    StaticRateProvider,
)
from pytender.exceptions import CircuitOpenError, ProviderError, RateUnavailableError
from pytender.formatting import SimpleMoneyFormatter, _group_digits
from pytender.fx import (
    AsyncCachedRateProvider,
    AsyncChainedRateProvider,
    AsyncFromSyncProvider,
    AsyncInverseRateProvider,
    AsyncPolicyRateProvider,
    AsyncTriangulatingRateProvider,
    CachedRateProvider,
    ChainedRateProvider,
    ExchangeRate,
    InverseRateProvider,
    PolicyRateProvider,
    TriangulatingRateProvider,
)
from pytender.infrastructure import (
    AsyncCircuitBreakerRateProvider,
    AsyncObservedRateProvider,
    AsyncPairCircuitBreakerRateProvider,
    AsyncRateLimitedRateProvider,
    AsyncRetryingRateProvider,
    CircuitBreakerRateProvider,
    HookFailureMode,
    ObservedRateProvider,
    PairCircuitBreakerRateProvider,
    ProviderObserver,
    RateLimitPolicy,
    RateLimitedRateProvider,
    RetryPolicy,
    RetryingRateProvider,
    build_async_production_provider,
    build_production_provider,
    display_policy,
    reporting_policy,
)
from pytender.policy import DerivationKind, MissingTimestampPolicy
from pytender.registry import CurrencyRegistry
from pytender.resilience import CircuitState
from pytender.rounding import DecimalRounding, round_to_increment
from pytender.serialization import from_dict
from pytender.types import CurrencyStatus

USD = CurrencyCode("USD")
EUR = CurrencyCode("EUR")
GBP = CurrencyCode("GBP")


def rate(
    base: CurrencyCode = USD,
    quote: CurrencyCode = EUR,
    value: str = "0.9",
    *,
    provider: str = "test",
    kind: RateKind = RateKind.REFERENCE,
    derivation: DerivationKind = DerivationKind.NONE,
    as_of: datetime | None = None,
) -> ExchangeRate:
    return ExchangeRate(
        base,
        quote,
        Decimal(value),
        RateProvenance(provider, as_of=as_of),
        kind,
        derivation,
    )


class SyncProvider:
    def __init__(self, outcome: ExchangeRate | Exception) -> None:
        self.outcome = outcome
        self.calls = 0

    def get_rate(self, base: CurrencyCode, quote: CurrencyCode) -> ExchangeRate:
        self.calls += 1
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return self.outcome


class AsyncProvider:
    def __init__(self, outcome: ExchangeRate | Exception) -> None:
        self.outcome = outcome
        self.calls = 0

    async def get_rate(self, base: CurrencyCode, quote: CurrencyCode) -> ExchangeRate:
        self.calls += 1
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return self.outcome


def test_money_pythonic_protocols_and_error_edges() -> None:
    zero = Money.from_minor(0, "USD")
    value = Money.from_minor(-125, "USD")
    assert not zero
    assert value
    assert abs(value).minor == 125
    assert (-value).minor == 125
    assert (value * 2).minor == -250
    assert (2 * value).minor == -250
    assert value < zero
    assert value <= zero
    assert zero > value
    assert zero >= value
    assert str(Money.from_major("1234.50", "USD")) == "$1,234.50"
    assert Money.from_major("1", "USD").multiply_rate("1.5").minor == 150
    assert Money.from_minor(3, "USD").ratio(Money.from_minor(2, "USD")) == Decimal("1.5")
    with pytest.raises(ZeroDivisionError):
        Money.from_minor(1, "USD").ratio(zero)
    with pytest.raises(TypeError):
        Money.from_minor(True, "USD")
    with pytest.raises(TypeError):
        _ = value * Decimal("2")  # type: ignore[operator]
    with pytest.raises(InvalidAmountError):
        Money.from_major("NaN", "USD")


def test_allocation_and_formatting_edge_branches() -> None:
    assert [part.minor for part in Money.from_minor(5, "USD").split(3)] == [2, 2, 1]
    assert [part.minor for part in Money.from_minor(-5, "USD").split(3)] == [-2, -2, -1]
    assert [part.minor for part in Money.from_minor(2, "USD").allocate([1, 1, 1])] == [1, 1, 0]
    assert [part.minor for part in Money.from_minor(0, "USD").allocate([0, 0])] == [0, 0]
    with pytest.raises(Exception):
        Money.from_minor(1, "USD").allocate([])
    formatter = SimpleMoneyFormatter(symbol_first=False, symbol_space=True, group_thousands=False)
    assert Money.from_major("12.34", "USD").format(formatter) == "12.34 $"
    no_symbol = Currency(CurrencyCode("TOK"), 2)
    assert Money.from_major("1.20", no_symbol).format() == "1.20 TOK"
    formatter = SimpleMoneyFormatter(code_when_symbol_missing=False)
    assert Money.from_major("1.20", no_symbol).format(formatter) == "1.20"
    assert _group_digits("", ",") == ""


def test_registry_currency_and_serialization_edge_branches() -> None:
    historical = Currency(
        CurrencyCode("OLD"),
        2,
        status=CurrencyStatus.HISTORICAL,
        valid_from=datetime(2020, 1, 1).date(),
        valid_to=datetime(2020, 12, 31).date(),
    )
    custom = Currency(CurrencyCode("TOK"), 3, status=CurrencyStatus.CUSTOM)
    registry = CurrencyRegistry([historical, custom])
    assert historical.is_valid_on(datetime(2020, 6, 1).date())
    assert not historical.is_valid_on(datetime(2019, 1, 1).date())
    assert not historical.is_valid_on(datetime(2021, 1, 1).date())
    assert registry.contains("tok")
    assert len(tuple(registry)) == 2
    assert registry.historical() == (historical,)
    removed = registry.unregister("TOK")
    assert removed == custom
    with pytest.raises(Exception):
        registry.unregister("TOK")
    with pytest.raises(TypeError):
        from_dict({"amount": True, "currency": "USD"})  # type: ignore[typeddict-item]
    with pytest.raises(TypeError):
        from_dict({"amount": 1, "currency": 123})  # type: ignore[typeddict-item]


def test_rounding_validation_edges() -> None:
    with pytest.raises(Exception):
        DecimalRounding().quantize_minor(Decimal("NaN"))
    with pytest.raises(Exception):
        DecimalRounding().quantize_minor(1)  # type: ignore[arg-type]
    with pytest.raises(Exception):
        round_to_increment(True, 5)
    with pytest.raises(Exception):
        round_to_increment(10, 0)


def test_exchange_rate_validation_and_policy_edges() -> None:
    with pytest.raises(InvalidRateError):
        ExchangeRate(USD, EUR, Decimal("0"))
    with pytest.raises(InvalidRateError):
        ExchangeRate(USD, EUR, Decimal("1"), kind="reference")  # type: ignore[arg-type]
    with pytest.raises(InvalidRateError):
        ExchangeRate(USD, EUR, Decimal("1"), derivation="none")  # type: ignore[arg-type]
    with pytest.raises(InvalidRateError):
        ExchangeRate(USD, EUR, Decimal("1"), kind=RateKind.DERIVED)
    with pytest.raises(InvalidRateError):
        ExchangeRate(USD, EUR, Decimal("1"), derivation=DerivationKind.CUSTOM)
    with pytest.raises(InvalidRateError):
        ExchangeRate(
            USD,
            EUR,
            Decimal("1"),
            RateProvenance("x", metadata={"derived": "inverse"}),
            RateKind.DERIVED,
            DerivationKind.TRIANGULATION,
        )
    with pytest.raises(TypeError):
        RateProvenance("x", source_uri=1)  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        RateProvenance("x", request_id=1)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        RateProvenance("x", as_of=datetime.now())
    with pytest.raises(ValueError):
        RateProvenance("x", fetched_at=datetime.now())
    with pytest.raises(TypeError):
        RateProvenance("x", metadata={"x": 1})  # type: ignore[dict-item]

    now = datetime.now(timezone.utc)
    direct = rate(as_of=now)
    with pytest.raises(RatePolicyError):
        RatePolicy(allowed_sources=frozenset({"other"})).validate(direct)
    with pytest.raises(RatePolicyError):
        RatePolicy(allowed_kinds=frozenset({RateKind.EXECUTABLE})).validate(direct)
    with pytest.raises(RatePolicyError):
        RatePolicy(max_age=timedelta(seconds=1)).validate(rate(as_of=None))
    RatePolicy(
        max_age=timedelta(seconds=1),
        missing_timestamp=MissingTimestampPolicy.USE_FETCHED_AT,
    ).validate(direct)
    with pytest.raises(RatePolicyError):
        RatePolicy().validate(rate(as_of=now + timedelta(seconds=10)), now=now)
    with pytest.raises(ValueError):
        RatePolicy().validate(direct, now=datetime.now())


def test_static_policy_inverse_chain_and_triangulation_sync() -> None:
    static = StaticRateProvider({("USD", "EUR"): "0.8"})
    assert static.get_rate(USD, USD).value == Decimal("1")
    with pytest.raises(RateUnavailableError):
        static.get_rate(EUR, USD)

    policy_provider = PolicyRateProvider(static, RatePolicy())
    assert policy_provider.get_rate(USD, EUR).value == Decimal("0.8")

    inverse = InverseRateProvider(static).get_rate(EUR, USD)
    assert inverse.kind is RateKind.DERIVED
    assert inverse.derivation is DerivationKind.INVERSE

    first = SyncProvider(RateUnavailableError("missing"))
    second = SyncProvider(rate())
    assert ChainedRateProvider(first, second).get_rate(USD, EUR).value == Decimal("0.9")
    with pytest.raises(ProviderError):
        ChainedRateProvider(
            SyncProvider(ProviderError("down")),
            SyncProvider(RateUnavailableError("missing")),
        ).get_rate(USD, EUR)

    legs = StaticRateProvider({("GBP", "USD"): "1.25", ("USD", "EUR"): "0.8"})
    derived = TriangulatingRateProvider(legs, pivots=("USD",)).get_rate(GBP, EUR)
    assert derived.value == Decimal("1.000")
    assert derived.derivation is DerivationKind.TRIANGULATION
    with pytest.raises(ValueError):
        TriangulatingRateProvider(legs, pivots=())


@pytest.mark.asyncio
async def test_async_provider_parity_edges() -> None:
    static = StaticRateProvider({("USD", "EUR"): "0.8"})
    adapted = AsyncFromSyncProvider(static)
    assert (await adapted.get_rate(USD, EUR)).value == Decimal("0.8")
    policy = AsyncPolicyRateProvider(adapted, RatePolicy())
    assert (await policy.get_rate(USD, EUR)).value == Decimal("0.8")
    inverse = AsyncInverseRateProvider(adapted)
    assert (await inverse.get_rate(EUR, USD)).derivation is DerivationKind.INVERSE

    chain = AsyncChainedRateProvider(
        AsyncProvider(RateUnavailableError("missing")),
        AsyncProvider(rate()),
    )
    assert (await chain.get_rate(USD, EUR)).value == Decimal("0.9")

    legs = AsyncFromSyncProvider(
        StaticRateProvider({("GBP", "USD"): "1.25", ("USD", "EUR"): "0.8"})
    )
    triangulated = await AsyncTriangulatingRateProvider(legs, pivots=("USD",)).get_rate(GBP, EUR)
    assert triangulated.derivation is DerivationKind.TRIANGULATION
    with pytest.raises(ValueError):
        AsyncTriangulatingRateProvider(legs, pivots=())


def test_cache_clear_eviction_and_stale_failure_edges() -> None:
    provider = SyncProvider(rate())
    cache = CachedRateProvider(provider, ttl_seconds=10, maxsize=1)
    assert cache.get_rate(USD, EUR).value == Decimal("0.9")
    cache.get_rate(GBP, EUR)
    assert cache.size == 1
    cache.clear()
    assert cache.size == 0

    failing = CachedRateProvider(
        SyncProvider(ProviderError("down")),
        ttl_seconds=1,
        stale_if_error_seconds=0,
    )
    with pytest.raises(ProviderError):
        failing.get_rate(USD, EUR)


@pytest.mark.asyncio
async def test_async_cache_clear_and_failure_edges() -> None:
    provider = AsyncProvider(rate())
    cache = AsyncCachedRateProvider(provider, ttl_seconds=10, maxsize=1)
    assert (await cache.get_rate(USD, EUR)).value == Decimal("0.9")
    await cache.clear()
    assert cache.size == 0
    with pytest.raises(ProviderError):
        await AsyncCachedRateProvider(AsyncProvider(ProviderError("down"))).get_rate(USD, EUR)


def test_converter_identity_replay_and_invalid_provider() -> None:
    converter = MoneyConverter(StaticRateProvider({("USD", "EUR"): "0.8"}))
    money = Money.from_major("10", "USD")
    result = converter.convert_with_rate(money, "USD")
    assert result.target is money
    quote = rate(value="0.8")
    assert converter.replay(money, quote).target.minor == 800
    with pytest.raises(InvalidRateError):
        converter.replay(money, rate(EUR, USD))
    with pytest.raises(TypeError):
        MoneyConverter(object())  # type: ignore[arg-type]


def test_retry_rate_limit_and_circuit_validation_edges() -> None:
    with pytest.raises(ValueError):
        RetryPolicy(attempts=0)
    with pytest.raises(ValueError):
        RetryPolicy(jitter_ratio=2)
    with pytest.raises(ValueError):
        RetryPolicy().delay_for_retry(-1)
    with pytest.raises(ValueError):
        RateLimitPolicy(0)
    with pytest.raises(ValueError):
        RateLimitPolicy(1, burst=0)

    unavailable = RetryingRateProvider(
        SyncProvider(RateUnavailableError("missing")),
        policy=RetryPolicy(attempts=2, retry_rate_unavailable=True, jitter_ratio=0),
        sleep=lambda _: None,
    )
    with pytest.raises(RateUnavailableError):
        unavailable.get_rate(USD, EUR)

    clock_values = iter([0.0, 0.0, 1.0])
    limited = RateLimitedRateProvider(
        SyncProvider(rate()),
        policy=RateLimitPolicy(1, burst=1),
        clock=lambda: next(clock_values),
        sleep=lambda _: None,
    )
    limited.get_rate(USD, EUR)
    limited.get_rate(USD, EUR)

    with pytest.raises(ValueError):
        CircuitBreakerRateProvider(SyncProvider(rate()), failure_threshold=0)
    with pytest.raises(ValueError):
        PairCircuitBreakerRateProvider(SyncProvider(rate()), recovery_timeout_seconds=0)


def test_sync_circuit_open_half_open_and_pair_isolation(monkeypatch: pytest.MonkeyPatch) -> None:
    times = iter([0.0, 0.5, 2.0, 2.0, 2.0])
    monkeypatch.setattr("pytender.resilience.time.monotonic", lambda: next(times))
    provider = SyncProvider(ProviderError("down"))
    breaker = CircuitBreakerRateProvider(provider, failure_threshold=1, recovery_timeout_seconds=1)
    with pytest.raises(ProviderError):
        breaker.get_rate(USD, EUR)
    with pytest.raises(CircuitOpenError):
        breaker.get_rate(USD, EUR)
    assert breaker.snapshot().state is CircuitState.HALF_OPEN

    pair = PairCircuitBreakerRateProvider(
        SyncProvider(ProviderError("down")),
        failure_threshold=1,
        recovery_timeout_seconds=10,
    )
    with pytest.raises(ProviderError):
        pair.get_rate(USD, EUR)
    assert pair.snapshot(USD, EUR).state is CircuitState.OPEN
    assert pair.snapshot(GBP, EUR).state is CircuitState.CLOSED


@pytest.mark.asyncio
async def test_async_resilience_validation_and_open_circuits() -> None:
    retry = AsyncRetryingRateProvider(
        AsyncProvider(ProviderError("down")),
        policy=RetryPolicy(attempts=2, base_delay_seconds=0, jitter_ratio=0),
    )
    with pytest.raises(ProviderError):
        await retry.get_rate(USD, EUR)

    limiter = AsyncRateLimitedRateProvider(
        AsyncProvider(rate()),
        policy=RateLimitPolicy(1000, burst=1),
    )
    assert (await limiter.get_rate(USD, EUR)).value == Decimal("0.9")

    breaker = AsyncCircuitBreakerRateProvider(
        AsyncProvider(ProviderError("down")),
        failure_threshold=1,
        recovery_timeout_seconds=60,
    )
    with pytest.raises(ProviderError):
        await breaker.get_rate(USD, EUR)
    with pytest.raises(CircuitOpenError):
        await breaker.get_rate(USD, EUR)

    pair = AsyncPairCircuitBreakerRateProvider(
        AsyncProvider(ProviderError("down")),
        failure_threshold=1,
        recovery_timeout_seconds=60,
    )
    with pytest.raises(ProviderError):
        await pair.get_rate(USD, EUR)
    assert (await pair.snapshot(USD, EUR)).state is CircuitState.OPEN


class BrokenObserver:
    def observe(self, event: object) -> None:
        raise RuntimeError("telemetry down")


class AsyncBrokenObserver:
    async def observe(self, event: object) -> None:
        raise RuntimeError("telemetry down")


def test_observation_fail_open_and_closed() -> None:
    provider = SyncProvider(rate())
    assert ObservedRateProvider(provider, BrokenObserver()).get_rate(USD, EUR).value == Decimal("0.9")
    with pytest.raises(RuntimeError):
        ObservedRateProvider(
            provider,
            BrokenObserver(),
            failure_mode=HookFailureMode.FAIL_CLOSED,
        ).get_rate(USD, EUR)


@pytest.mark.asyncio
async def test_async_observation_fail_open_and_closed() -> None:
    provider = AsyncProvider(rate())
    observed = AsyncObservedRateProvider(provider, AsyncBrokenObserver())
    assert (await observed.get_rate(USD, EUR)).value == Decimal("0.9")
    with pytest.raises(RuntimeError):
        await AsyncObservedRateProvider(
            provider,
            AsyncBrokenObserver(),
            failure_mode=HookFailureMode.FAIL_CLOSED,
        ).get_rate(USD, EUR)


def test_plugin_loader_success_failure_and_contract(monkeypatch: pytest.MonkeyPatch) -> None:
    class EP:
        name = "good"

        def load(self):
            return lambda **_: StaticRateProvider({("USD", "EUR"): "0.8"})

    monkeypatch.setattr(plugins, "entry_points", lambda **_: [EP()])
    assert "good" in plugins.discover_provider_plugins()
    assert plugins.load_provider_plugin("good").get_rate(USD, EUR).value == Decimal("0.8")

    class BadEP:
        name = "bad"

        def load(self):
            return lambda **_: object()

    monkeypatch.setattr(plugins, "entry_points", lambda **_: [BadEP()])
    with pytest.raises(ProviderError, match="does not satisfy"):
        plugins.load_provider_plugin("bad")

    class ExplodingEP:
        name = "explode"

        def load(self):
            raise RuntimeError("boom")

    monkeypatch.setattr(plugins, "entry_points", lambda **_: [ExplodingEP()])
    with pytest.raises(ProviderError, match="failed to initialize"):
        plugins.load_provider_plugin("explode")


def test_presets_and_production_builder_branches() -> None:
    assert RateKind.DERIVED in reporting_policy().allowed_kinds
    assert RateKind.DERIVED not in reporting_policy(allow_derived=False).allowed_kinds
    assert RateKind.INDICATIVE in display_policy().allowed_kinds
    provider = build_production_provider(
        StaticRateProvider({("USD", "EUR"): "0.8"}),
    )
    assert provider.get_rate(USD, EUR).value == Decimal("0.8")


@pytest.mark.asyncio
async def test_async_production_builder_branch() -> None:
    provider = awaitable = AsyncFromSyncProvider(
        StaticRateProvider({("USD", "EUR"): "0.8"})
    )
    built = build_async_production_provider(provider)
    assert (await built.get_rate(USD, EUR)).value == Decimal("0.8")


def test_money_remaining_validation_and_notimplemented_edges() -> None:
    with pytest.raises(InvalidAmountError):
        Money.from_major(object(), "USD")  # type: ignore[arg-type]
    with pytest.raises(InvalidAmountError):
        Money.from_minor(1, "USD").multiply_rate(True)
    assert Money.__add__(Money.from_minor(1, "USD"), object()) is NotImplemented
    assert Money.__sub__(Money.from_minor(1, "USD"), object()) is NotImplemented
    assert Money.__lt__(Money.from_minor(1, "USD"), object()) is NotImplemented
    with pytest.raises(Exception):
        Money.from_minor(1, "USD").split(0)
    with pytest.raises(Exception):
        Money.from_minor(1, "USD").allocate([1, -1])
    with pytest.raises(Exception):
        Money.from_minor(1, "USD").allocate([1, True])


def test_formatting_symbol_and_grouping_remaining_branch() -> None:
    formatter = SimpleMoneyFormatter(symbol_first=True, symbol_space=True)
    assert Money.from_major("1234", "USD").format(formatter) == "$ 1,234.00"


def test_policy_remaining_validation_and_custom_validator() -> None:
    with pytest.raises(ValueError):
        RatePolicy(max_age=timedelta(seconds=-1))
    with pytest.raises(ValueError):
        RatePolicy(max_future_skew=timedelta(seconds=-1))
    with pytest.raises(ValueError):
        RatePolicy(allowed_kinds=frozenset())
    called: list[ExchangeRate] = []
    policy = RatePolicy(validator=called.append)
    quote = rate()
    policy.validate(quote)
    assert called == [quote]


def test_registry_register_many_atomic_duplicate_branch() -> None:
    registry = CurrencyRegistry()
    usd = Currency(CurrencyCode("USD"), 2)
    with pytest.raises(Exception):
        registry.register_many([usd, usd])
    assert len(registry) == 0
