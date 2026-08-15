from __future__ import annotations

import asyncio
import inspect
import time
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from pytender import (
    CircuitOpenError,
    CurrencyCode,
    ExchangeRate,
    Money,
    MoneyConverter,
    ProviderError,
    RateKind,
    RateProvenance,
    StaticRateProvider,
)
from pytender.infrastructure import (
    AsyncCachedRateProvider,
    AsyncFromSyncProvider,
    AsyncObservedRateProvider,
    AsyncPairCircuitBreakerRateProvider,
    AsyncRateLimitedRateProvider,
    AsyncRetryingRateProvider,
    AuditedRateProvider,
    CachedRateProvider,
    CircuitScope,
    HookFailureMode,
    ObservedRateProvider,
    PairCircuitBreakerRateProvider,
    ProductionProviderConfig,
    ProviderEvent,
    RateLimitPolicy,
    RetryPolicy,
    build_production_converter,
    checkout_policy,
    display_policy,
    reporting_policy,
    treasury_policy,
)

USD = CurrencyCode("USD")
EUR = CurrencyCode("EUR")
GBP = CurrencyCode("GBP")


def _rate(
    base: CurrencyCode = USD,
    quote: CurrencyCode = EUR,
    value: str = "0.9",
) -> ExchangeRate:
    return ExchangeRate(
        base,
        quote,
        Decimal(value),
        RateProvenance("test", as_of=datetime.now(timezone.utc)),
        RateKind.EXECUTABLE,
    )


def test_stale_fallback_window_is_checked_after_slow_provider_failure() -> None:
    class SlowFailure:
        calls = 0

        def get_rate(self, base: CurrencyCode, quote: CurrencyCode) -> ExchangeRate:
            self.calls += 1
            if self.calls == 1:
                return _rate(base, quote)
            time.sleep(0.05)
            raise ProviderError("slow outage")

    cache = CachedRateProvider(
        SlowFailure(),
        ttl_seconds=0.005,
        stale_if_error_seconds=0.03,
    )
    cache.get_rate(USD, EUR)
    time.sleep(0.01)

    with pytest.raises(ProviderError, match="slow outage"):
        cache.get_rate(USD, EUR)


@pytest.mark.asyncio
async def test_async_stale_fallback_window_is_checked_after_slow_failure() -> None:
    class SlowFailure:
        calls = 0

        async def get_rate(self, base: CurrencyCode, quote: CurrencyCode) -> ExchangeRate:
            self.calls += 1
            if self.calls == 1:
                return _rate(base, quote)
            await asyncio.sleep(0.05)
            raise ProviderError("slow outage")

    cache = AsyncCachedRateProvider(
        SlowFailure(),
        ttl_seconds=0.005,
        stale_if_error_seconds=0.03,
    )
    await cache.get_rate(USD, EUR)
    await asyncio.sleep(0.01)

    with pytest.raises(ProviderError, match="slow outage"):
        await cache.get_rate(USD, EUR)


def test_money_format_public_parameter_is_typed() -> None:
    parameter = inspect.signature(Money.format).parameters["formatter"]
    assert parameter.annotation is not inspect.Parameter.empty


def test_observer_is_fail_open_by_default() -> None:
    class BrokenObserver:
        def observe(self, event: ProviderEvent) -> None:
            raise RuntimeError("metrics unavailable")

    provider = ObservedRateProvider(
        StaticRateProvider({("USD", "EUR"): "0.9"}),
        BrokenObserver(),
    )
    assert provider.get_rate(USD, EUR).value == Decimal("0.9")


def test_observer_can_be_explicitly_fail_closed() -> None:
    class BrokenObserver:
        def observe(self, event: ProviderEvent) -> None:
            raise RuntimeError("metrics unavailable")

    provider = ObservedRateProvider(
        StaticRateProvider({("USD", "EUR"): "0.9"}),
        BrokenObserver(),
        failure_mode=HookFailureMode.FAIL_CLOSED,
    )
    with pytest.raises(RuntimeError, match="metrics unavailable"):
        provider.get_rate(USD, EUR)


def test_audit_failure_mode_is_explicit() -> None:
    class BrokenSink:
        def record(self, record: object) -> None:
            raise RuntimeError("audit unavailable")

    inner = StaticRateProvider({("USD", "EUR"): "0.9"})
    with pytest.raises(RuntimeError, match="audit unavailable"):
        AuditedRateProvider(inner, BrokenSink()).get_rate(USD, EUR)

    provider = AuditedRateProvider(
        inner,
        BrokenSink(),
        failure_mode=HookFailureMode.FAIL_OPEN,
    )
    assert provider.get_rate(USD, EUR).value == Decimal("0.9")


@pytest.mark.asyncio
async def test_async_observer_failure_does_not_mask_cancellation() -> None:
    started = asyncio.Event()

    class BlockingProvider:
        async def get_rate(self, base: CurrencyCode, quote: CurrencyCode) -> ExchangeRate:
            started.set()
            await asyncio.sleep(60)
            return _rate(base, quote)

    class BrokenObserver:
        async def observe(self, event: ProviderEvent) -> None:
            raise RuntimeError("observer broken")

    task = asyncio.create_task(
        AsyncObservedRateProvider(BlockingProvider(), BrokenObserver()).get_rate(USD, EUR)
    )
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


def test_pair_scoped_circuit_does_not_poison_other_pairs() -> None:
    class PartialFailure:
        def get_rate(self, base: CurrencyCode, quote: CurrencyCode) -> ExchangeRate:
            if (base, quote) == (USD, EUR):
                raise ProviderError("USD/EUR down")
            return _rate(base, quote, "1.2")

    breaker = PairCircuitBreakerRateProvider(
        PartialFailure(),
        failure_threshold=1,
        recovery_timeout_seconds=60,
    )
    with pytest.raises(ProviderError):
        breaker.get_rate(USD, EUR)
    with pytest.raises(CircuitOpenError):
        breaker.get_rate(USD, EUR)
    assert breaker.get_rate(GBP, EUR).value == Decimal("1.2")


@pytest.mark.asyncio
async def test_async_pair_scoped_circuit_does_not_poison_other_pairs() -> None:
    class PartialFailure:
        async def get_rate(self, base: CurrencyCode, quote: CurrencyCode) -> ExchangeRate:
            if (base, quote) == (USD, EUR):
                raise ProviderError("USD/EUR down")
            return _rate(base, quote, "1.2")

    breaker = AsyncPairCircuitBreakerRateProvider(
        PartialFailure(),
        failure_threshold=1,
        recovery_timeout_seconds=60,
    )
    with pytest.raises(ProviderError):
        await breaker.get_rate(USD, EUR)
    with pytest.raises(CircuitOpenError):
        await breaker.get_rate(USD, EUR)
    assert (await breaker.get_rate(GBP, EUR)).value == Decimal("1.2")


def test_production_builder_gives_beginner_safe_composition() -> None:
    class LiveExecutable:
        def get_rate(self, base: CurrencyCode, quote: CurrencyCode) -> ExchangeRate:
            return _rate(base, quote, "0.9")

    converter = build_production_converter(
        LiveExecutable(),
        policy=checkout_policy(max_age=__import__("datetime").timedelta(minutes=1)),
        config=ProductionProviderConfig(
            retry=RetryPolicy(attempts=1),
            circuit_scope=CircuitScope.PAIR,
        ),
    )
    result = converter.convert_with_rate(Money.from_major("10", "USD"), "EUR")
    assert result.target == Money.from_major("9", "EUR")


def test_policy_presets_are_intentionally_different() -> None:
    assert checkout_policy().allowed_kinds == frozenset({RateKind.EXECUTABLE})
    assert RateKind.DERIVED in reporting_policy().allowed_kinds
    assert RateKind.DERIVED not in display_policy().allowed_kinds
    assert treasury_policy().allowed_kinds == frozenset({RateKind.EXECUTABLE})


def test_replay_uses_stored_rate_without_provider_call() -> None:
    class MustNotRun:
        def get_rate(self, base: CurrencyCode, quote: CurrencyCode) -> ExchangeRate:
            raise AssertionError("live provider must not be called during replay")

    rate = _rate(value="0.91")
    result = MoneyConverter(MustNotRun()).replay(Money.from_major("100", "USD"), rate)
    assert result.target == Money.from_major("91", "EUR")
    assert result.rate is rate


@pytest.mark.asyncio
async def test_cancellation_during_retry_sleep_is_not_swallowed() -> None:
    called = asyncio.Event()

    class Down:
        async def get_rate(self, base: CurrencyCode, quote: CurrencyCode) -> ExchangeRate:
            called.set()
            raise ProviderError("down")

    provider = AsyncRetryingRateProvider(
        Down(),
        policy=RetryPolicy(
            attempts=100,
            base_delay_seconds=10,
            max_delay_seconds=10,
            jitter_ratio=0,
        ),
    )
    task = asyncio.create_task(provider.get_rate(USD, EUR))
    await called.wait()
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


@pytest.mark.asyncio
async def test_cancellation_while_waiting_for_rate_limit_is_not_swallowed() -> None:
    provider = AsyncRateLimitedRateProvider(
        AsyncFromSyncProvider(
            StaticRateProvider({("USD", "EUR"): "1"})
        ),
        policy=RateLimitPolicy(rate_per_second=0.01, burst=1),
    )
    await provider.get_rate(USD, EUR)
    task = asyncio.create_task(provider.get_rate(USD, EUR))
    await asyncio.sleep(0.01)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


def test_rate_policy_custom_validator_supports_application_trust_rules() -> None:
    from pytender import RatePolicy, RatePolicyError

    def require_treasury(rate: ExchangeRate) -> None:
        if rate.source != "treasury":
            raise RatePolicyError("untrusted source")

    with pytest.raises(RatePolicyError, match="untrusted"):
        RatePolicy(validator=require_treasury).validate(_rate())


def test_retry_policy_rejects_negative_retry_index() -> None:
    with pytest.raises(ValueError, match="retry_index"):
        RetryPolicy().delay_for_retry(-1)


def test_pair_circuit_validation_and_snapshots() -> None:
    with pytest.raises(ValueError):
        PairCircuitBreakerRateProvider(StaticRateProvider({}), failure_threshold=0)
    with pytest.raises(ValueError):
        PairCircuitBreakerRateProvider(
            StaticRateProvider({}), recovery_timeout_seconds=0
        )

    class Down:
        def get_rate(self, base: CurrencyCode, quote: CurrencyCode) -> ExchangeRate:
            raise ProviderError("down")

    breaker = PairCircuitBreakerRateProvider(
        Down(), failure_threshold=1, recovery_timeout_seconds=0.001
    )
    assert breaker.snapshot(USD, EUR).state.value == "closed"
    with pytest.raises(ProviderError):
        breaker.get_rate(USD, EUR)
    assert breaker.snapshot(USD, EUR).state.value == "open"
    time.sleep(0.002)
    assert breaker.snapshot(USD, EUR).state.value == "half_open"


@pytest.mark.asyncio
async def test_async_pair_circuit_validation_and_snapshots() -> None:
    class Good:
        async def get_rate(self, base: CurrencyCode, quote: CurrencyCode) -> ExchangeRate:
            return _rate(base, quote)

    with pytest.raises(ValueError):
        AsyncPairCircuitBreakerRateProvider(Good(), failure_threshold=0)
    with pytest.raises(ValueError):
        AsyncPairCircuitBreakerRateProvider(Good(), recovery_timeout_seconds=0)

    class Down:
        async def get_rate(self, base: CurrencyCode, quote: CurrencyCode) -> ExchangeRate:
            raise ProviderError("down")

    breaker = AsyncPairCircuitBreakerRateProvider(
        Down(), failure_threshold=1, recovery_timeout_seconds=0.001
    )
    assert (await breaker.snapshot(USD, EUR)).state.value == "closed"
    with pytest.raises(ProviderError):
        await breaker.get_rate(USD, EUR)
    assert (await breaker.snapshot(USD, EUR)).state.value == "open"
    await asyncio.sleep(0.002)
    assert (await breaker.snapshot(USD, EUR)).state.value == "half_open"


def test_production_builder_exercises_fallback_rate_limit_audit_and_observer() -> None:
    records: list[object] = []
    events: list[ProviderEvent] = []

    class Down:
        def get_rate(self, base: CurrencyCode, quote: CurrencyCode) -> ExchangeRate:
            raise ProviderError("down")

    class Live:
        def get_rate(self, base: CurrencyCode, quote: CurrencyCode) -> ExchangeRate:
            return _rate(base, quote)

    class Sink:
        def record(self, record: object) -> None:
            records.append(record)

    class Observer:
        def observe(self, event: ProviderEvent) -> None:
            events.append(event)

    converter = build_production_converter(
        Down(),
        Live(),
        policy=checkout_policy(),
        config=ProductionProviderConfig(
            retry=RetryPolicy(attempts=1),
            rate_limit=RateLimitPolicy(rate_per_second=1000, burst=2),
        ),
        audit_sink=Sink(),
        observer=Observer(),
    )
    assert converter.convert(Money.from_major("1", "USD"), "EUR") == Money.from_major(
        "0.90", "EUR"
    )
    assert records
    assert events[-1].succeeded


@pytest.mark.asyncio
async def test_async_production_builder_and_converter() -> None:
    from pytender.infrastructure import (
        AsyncFromSyncProvider,
        build_async_production_converter,
    )

    class Live:
        async def get_rate(self, base: CurrencyCode, quote: CurrencyCode) -> ExchangeRate:
            return _rate(base, quote)

    converter = build_async_production_converter(
        Live(),
        policy=checkout_policy(),
        config=ProductionProviderConfig(
            retry=RetryPolicy(attempts=1),
            rate_limit=RateLimitPolicy(rate_per_second=1000, burst=1),
            circuit_scope=CircuitScope.PAIR,
        ),
    )
    target = await converter.convert(Money.from_major("2", "USD"), "EUR")
    assert target == Money.from_major("1.80", "EUR")

    # Keep this adapter visible as the supported non-blocking sync-to-async bridge.
    assert isinstance(
        AsyncFromSyncProvider(StaticRateProvider({("USD", "EUR"): "1"})),
        object,
    )


@pytest.mark.asyncio
async def test_async_audit_and_observer_failure_modes() -> None:
    from pytender.infrastructure import AsyncAuditedRateProvider

    class Live:
        async def get_rate(self, base: CurrencyCode, quote: CurrencyCode) -> ExchangeRate:
            return _rate(base, quote)

    class BrokenSink:
        async def record(self, record: object) -> None:
            raise RuntimeError("audit down")

    class BrokenObserver:
        async def observe(self, event: ProviderEvent) -> None:
            raise RuntimeError("metrics down")

    with pytest.raises(RuntimeError, match="audit down"):
        await AsyncAuditedRateProvider(Live(), BrokenSink()).get_rate(USD, EUR)

    rate = await AsyncAuditedRateProvider(
        Live(), BrokenSink(), failure_mode=HookFailureMode.FAIL_OPEN
    ).get_rate(USD, EUR)
    assert rate.value == Decimal("0.9")

    rate = await AsyncObservedRateProvider(Live(), BrokenObserver()).get_rate(USD, EUR)
    assert rate.value == Decimal("0.9")
    with pytest.raises(RuntimeError, match="metrics down"):
        await AsyncObservedRateProvider(
            Live(),
            BrokenObserver(),
            failure_mode=HookFailureMode.FAIL_CLOSED,
        ).get_rate(USD, EUR)


def test_custom_rate_validator_can_accept_trusted_rate() -> None:
    from pytender import RatePolicy

    seen: list[str] = []

    def validator(rate: ExchangeRate) -> None:
        seen.append(rate.source)

    RatePolicy(validator=validator).validate(_rate())
    assert seen == ["test"]
