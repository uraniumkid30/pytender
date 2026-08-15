from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal, getcontext

import pytest

from moneytender import (
    DEFAULT_REGISTRY,
    AsyncMoneyConverter,
    CircuitOpenError,
    Currency,
    CurrencyCode,
    ExchangeRate,
    InvalidAmountError,
    MissingTimestampPolicy,
    Money,
    MoneyConverter,
    ProviderError,
    RateKind,
    RatePolicy,
    RatePolicyError,
    RateProvenance,
    RateUnavailableError,
    RegistryFrozenError,
    StaleRateError,
    StaticRateProvider,
)
from moneytender.infrastructure import (
    AsyncCachedRateProvider,
    AsyncFromSyncProvider,
    AsyncRetryingRateProvider,
    AuditedRateProvider,
    CachedRateProvider,
    ChainedRateProvider,
    CircuitBreakerRateProvider,
    RateAuditRecord,
    RetryingRateProvider,
    RetryPolicy,
    TriangulatingRateProvider,
)


def _rate(
    value: str = "1.25",
    *,
    as_of: datetime | None = None,
    kind: RateKind = RateKind.REFERENCE,
    provider: str = "test",
) -> ExchangeRate:
    return ExchangeRate(
        CurrencyCode("USD"),
        CurrencyCode("EUR"),
        Decimal(value),
        RateProvenance(provider, as_of=as_of),
        kind,
    )


def test_rate_policy_rejects_stale_rate() -> None:
    now = datetime(2026, 8, 15, tzinfo=UTC)
    rate = _rate(as_of=now - timedelta(seconds=31))
    policy = RatePolicy(max_age=timedelta(seconds=30))

    with pytest.raises(StaleRateError):
        policy.validate(rate, now=now)


def test_rate_policy_can_use_fetched_at_when_as_of_missing() -> None:
    rate = _rate()
    policy = RatePolicy(
        max_age=timedelta(minutes=1),
        missing_timestamp=MissingTimestampPolicy.USE_FETCHED_AT,
    )
    policy.validate(rate, now=rate.provenance.fetched_at + timedelta(seconds=10))


def test_rate_policy_rejects_unapproved_provider_and_kind() -> None:
    policy = RatePolicy(allowed_sources=frozenset({"treasury"}))
    with pytest.raises(RatePolicyError):
        policy.validate(_rate(provider="public-reference"))

    executable_only = RatePolicy(allowed_kinds=frozenset({RateKind.EXECUTABLE}))
    with pytest.raises(RatePolicyError):
        executable_only.validate(_rate(kind=RateKind.REFERENCE))


def test_triangulated_rate_is_explicitly_derived_and_policy_rejects_by_default() -> None:
    provider = TriangulatingRateProvider(
        StaticRateProvider(
            {
                ("NGN", "USD"): "0.00065",
                ("USD", "EUR"): "0.92",
            }
        ),
        pivots=("USD",),
    )
    rate = provider.get_rate(CurrencyCode("NGN"), CurrencyCode("EUR"))

    assert rate.kind is RateKind.DERIVED
    assert rate.provenance.metadata["derived"] == "triangulation"
    with pytest.raises(RatePolicyError):
        RatePolicy().validate(rate)

    RatePolicy(
        allowed_kinds=frozenset({RateKind.DERIVED}),
        allow_triangulation=True,
    ).validate(rate)


def test_converter_can_return_exact_rate_for_audit_or_replay() -> None:
    provider = StaticRateProvider({("USD", "EUR"): "0.92"}, kind=RateKind.EXECUTABLE)
    result = MoneyConverter(provider).convert_with_rate(
        Money.from_major("10.00", "USD"),
        "EUR",
    )

    assert result.target == Money.from_major("9.20", "EUR")
    assert result.rate.value == Decimal("0.92")
    assert result.rate.kind is RateKind.EXECUTABLE


def test_converter_enforces_policy_before_money_is_returned() -> None:
    old = datetime.now(UTC) - timedelta(hours=1)

    class OldProvider:
        def get_rate(self, base: CurrencyCode, quote: CurrencyCode) -> ExchangeRate:
            return ExchangeRate(
                base,
                quote,
                Decimal("1"),
                RateProvenance("treasury", as_of=old),
                RateKind.EXECUTABLE,
            )

    converter = MoneyConverter(
        OldProvider(),
        policy=RatePolicy(
            max_age=timedelta(seconds=30),
            allowed_kinds=frozenset({RateKind.EXECUTABLE}),
        ),
    )
    with pytest.raises(StaleRateError):
        converter.convert(Money.from_major("1", "USD"), "EUR")


def test_default_registry_is_frozen_but_clone_is_mutable() -> None:
    custom = Currency(CurrencyCode("TOK"), 4, "T", "Token")
    with pytest.raises(RegistryFrozenError):
        DEFAULT_REGISTRY.register(custom)

    registry = DEFAULT_REGISTRY.clone()
    registry.register(custom)
    assert registry.get("TOK") == custom
    assert not DEFAULT_REGISTRY.contains("TOK")


def test_cache_is_lru_bounded() -> None:
    provider = StaticRateProvider(
        {
            ("USD", "EUR"): "0.9",
            ("USD", "GBP"): "0.8",
            ("USD", "JPY"): "150",
        }
    )
    cache = CachedRateProvider(provider, maxsize=2, ttl_seconds=60)
    cache.get_rate(CurrencyCode("USD"), CurrencyCode("EUR"))
    cache.get_rate(CurrencyCode("USD"), CurrencyCode("GBP"))
    cache.get_rate(CurrencyCode("USD"), CurrencyCode("EUR"))
    cache.get_rate(CurrencyCode("USD"), CurrencyCode("JPY"))
    assert cache.size == 2


def test_stale_cache_fallback_is_opt_in_and_only_for_provider_failure() -> None:
    class FlakyProvider:
        calls = 0

        def get_rate(self, base: CurrencyCode, quote: CurrencyCode) -> ExchangeRate:
            self.calls += 1
            if self.calls == 1:
                return ExchangeRate(base, quote, Decimal("1.1"), RateProvenance("flaky"))
            raise ProviderError("temporary outage")

    provider = FlakyProvider()
    cache = CachedRateProvider(
        provider,
        ttl_seconds=0.001,
        stale_if_error_seconds=1,
    )
    first = cache.get_rate(CurrencyCode("USD"), CurrencyCode("EUR"))
    import time

    time.sleep(0.005)
    second = cache.get_rate(CurrencyCode("USD"), CurrencyCode("EUR"))
    assert second.value == first.value
    assert second.provenance.metadata["cache_status"] == "stale_fallback"


def test_retry_provider_retries_provider_errors_but_not_unavailable_by_default() -> None:
    class Flaky:
        calls = 0

        def get_rate(self, base: CurrencyCode, quote: CurrencyCode) -> ExchangeRate:
            self.calls += 1
            if self.calls < 3:
                raise ProviderError("transient")
            return ExchangeRate(base, quote, Decimal("1"), RateProvenance("flaky"))

    inner = Flaky()
    provider = RetryingRateProvider(
        inner,
        policy=RetryPolicy(attempts=3, base_delay_seconds=0, jitter_ratio=0),
    )
    provider.get_rate(CurrencyCode("USD"), CurrencyCode("EUR"))
    assert inner.calls == 3


def test_circuit_breaker_opens_after_threshold() -> None:
    class Down:
        def get_rate(self, base: CurrencyCode, quote: CurrencyCode) -> ExchangeRate:
            raise ProviderError("down")

    provider = CircuitBreakerRateProvider(
        Down(),
        failure_threshold=2,
        recovery_timeout_seconds=60,
    )
    with pytest.raises(ProviderError):
        provider.get_rate(CurrencyCode("USD"), CurrencyCode("EUR"))
    with pytest.raises(ProviderError):
        provider.get_rate(CurrencyCode("USD"), CurrencyCode("EUR"))
    with pytest.raises(CircuitOpenError):
        provider.get_rate(CurrencyCode("USD"), CurrencyCode("EUR"))


def test_chain_fails_over_after_provider_operational_failure() -> None:
    class Down:
        def get_rate(self, base: CurrencyCode, quote: CurrencyCode) -> ExchangeRate:
            raise ProviderError("down")

    fallback = StaticRateProvider({("USD", "EUR"): "0.9"})
    chain = ChainedRateProvider(Down(), fallback)
    assert chain.get_rate(CurrencyCode("USD"), CurrencyCode("EUR")).value == Decimal("0.9")


def test_audit_decorator_records_successful_quote() -> None:
    class Sink:
        def __init__(self) -> None:
            self.records: list[RateAuditRecord] = []

        def record(self, record: RateAuditRecord) -> None:
            self.records.append(record)

    sink = Sink()
    provider = AuditedRateProvider(
        StaticRateProvider({("USD", "EUR"): "0.9"}),
        sink,
    )
    returned = provider.get_rate(CurrencyCode("USD"), CurrencyCode("EUR"))
    assert sink.records[0].rate == returned


def test_extreme_decimal_inputs_are_rejected_or_converted_deterministically() -> None:
    for value in (Decimal("NaN"), Decimal("Infinity"), Decimal("-Infinity")):
        with pytest.raises(InvalidAmountError):
            Money.from_major(value, "USD")

    huge_rate = ExchangeRate(
        CurrencyCode("USD"),
        CurrencyCode("JPY"),
        Decimal("9.999999999999999999999999999999E+40"),
        RateProvenance("stress"),
    )

    class HugeProvider:
        def get_rate(self, base: CurrencyCode, quote: CurrencyCode) -> ExchangeRate:
            return huge_rate

    previous = getcontext().prec
    try:
        getcontext().prec = 6
        result = MoneyConverter(HugeProvider()).convert(Money.from_minor(123456789, "USD"), "JPY")
    finally:
        getcontext().prec = previous
    assert isinstance(result.minor, int)
    assert result.minor > 0


@pytest.mark.asyncio
async def test_async_retry_and_cache_waiter_cancellation_do_not_cancel_owner() -> None:
    started = asyncio.Event()
    release = asyncio.Event()
    calls = 0

    class Slow:
        async def get_rate(self, base: CurrencyCode, quote: CurrencyCode) -> ExchangeRate:
            nonlocal calls
            calls += 1
            started.set()
            await release.wait()
            return ExchangeRate(base, quote, Decimal("1"), RateProvenance("slow"))

    cached = AsyncCachedRateProvider(Slow(), ttl_seconds=60)
    owner = asyncio.create_task(cached.get_rate(CurrencyCode("USD"), CurrencyCode("EUR")))
    await started.wait()
    waiter = asyncio.create_task(cached.get_rate(CurrencyCode("USD"), CurrencyCode("EUR")))
    await asyncio.sleep(0)
    waiter.cancel()
    with pytest.raises(asyncio.CancelledError):
        await waiter
    release.set()
    assert (await owner).value == Decimal("1")
    assert calls == 1

    class FlakyAsync:
        calls = 0

        async def get_rate(self, base: CurrencyCode, quote: CurrencyCode) -> ExchangeRate:
            self.calls += 1
            if self.calls == 1:
                raise ProviderError("temporary")
            return ExchangeRate(base, quote, Decimal("1"), RateProvenance("async"))

    retry_inner = FlakyAsync()
    retrying = AsyncRetryingRateProvider(
        retry_inner,
        policy=RetryPolicy(attempts=2, base_delay_seconds=0, jitter_ratio=0),
    )
    converter = AsyncMoneyConverter(retrying)
    assert (await converter.convert(Money.from_major("1", "USD"), "EUR")).minor == 100


def test_triangulation_can_reject_conflicting_leg_timestamps() -> None:
    from datetime import timedelta

    now = datetime.now(UTC)

    class TimedProvider:
        def get_rate(self, base: CurrencyCode, quote: CurrencyCode) -> ExchangeRate:
            if (base, quote) == (CurrencyCode("NGN"), CurrencyCode("USD")):
                as_of = now
                value = Decimal("0.001")
            elif (base, quote) == (CurrencyCode("USD"), CurrencyCode("EUR")):
                as_of = now - timedelta(minutes=10)
                value = Decimal("0.9")
            else:
                raise RateUnavailableError("missing")
            return ExchangeRate(
                base,
                quote,
                value,
                RateProvenance("timed", as_of=as_of),
            )

    provider = TriangulatingRateProvider(
        TimedProvider(),
        pivots=("USD",),
        max_leg_skew=timedelta(seconds=30),
    )
    with pytest.raises(RateUnavailableError, match="timestamp skew"):
        provider.get_rate(CurrencyCode("NGN"), CurrencyCode("EUR"))


def test_rate_policy_checks_future_fetched_at_when_used_as_timestamp() -> None:
    now = datetime.now(UTC)
    rate = ExchangeRate(
        CurrencyCode("USD"),
        CurrencyCode("EUR"),
        Decimal("1"),
        RateProvenance("future-fetch", fetched_at=now + timedelta(minutes=1)),
    )
    policy = RatePolicy(
        max_age=timedelta(minutes=5),
        missing_timestamp=MissingTimestampPolicy.USE_FETCHED_AT,
        max_future_skew=timedelta(seconds=1),
    )
    with pytest.raises(RatePolicyError, match="unexpectedly in the future"):
        policy.validate(rate, now=now)


def test_sync_rate_limiter_enforces_local_token_bucket_without_touching_rate_values() -> None:
    from moneytender.infrastructure import RateLimitedRateProvider, RateLimitPolicy

    now = 0.0
    sleeps: list[float] = []

    def clock() -> float:
        return now

    def sleep(delay: float) -> None:
        nonlocal now
        sleeps.append(delay)
        now += delay

    provider = RateLimitedRateProvider(
        StaticRateProvider({("USD", "EUR"): "0.9"}),
        policy=RateLimitPolicy(rate_per_second=2, burst=1),
        clock=clock,
        sleep=sleep,
    )

    first = provider.get_rate(CurrencyCode("USD"), CurrencyCode("EUR"))
    second = provider.get_rate(CurrencyCode("USD"), CurrencyCode("EUR"))

    assert first.value == second.value == Decimal("0.9")
    assert sleeps == [pytest.approx(0.5)]


@pytest.mark.asyncio
async def test_async_rate_limiter_enforces_local_token_bucket() -> None:
    from moneytender.infrastructure import AsyncRateLimitedRateProvider, RateLimitPolicy

    now = 0.0
    sleeps: list[float] = []

    def clock() -> float:
        return now

    async def sleep(delay: float) -> None:
        nonlocal now
        sleeps.append(delay)
        now += delay

    provider = AsyncRateLimitedRateProvider(
        AsyncFromSyncProvider(StaticRateProvider({("USD", "EUR"): "0.9"})),
        policy=RateLimitPolicy(rate_per_second=4, burst=1),
        clock=clock,
        sleep=sleep,
    )

    await provider.get_rate(CurrencyCode("USD"), CurrencyCode("EUR"))
    await provider.get_rate(CurrencyCode("USD"), CurrencyCode("EUR"))
    assert sleeps == [pytest.approx(0.25)]


def test_retry_preserves_unavailable_semantics_after_explicit_retries() -> None:
    calls = 0

    class Missing:
        def get_rate(self, base: CurrencyCode, quote: CurrencyCode) -> ExchangeRate:
            nonlocal calls
            calls += 1
            raise RateUnavailableError("pair missing")

    provider = RetryingRateProvider(
        Missing(),
        policy=RetryPolicy(
            attempts=2,
            base_delay_seconds=0,
            jitter_ratio=0,
            retry_rate_unavailable=True,
        ),
    )
    with pytest.raises(RateUnavailableError, match="remained unavailable"):
        provider.get_rate(CurrencyCode("USD"), CurrencyCode("EUR"))
    assert calls == 2


def test_chain_does_not_misreport_operational_outage_as_pair_unavailability() -> None:
    class Down:
        def get_rate(self, base: CurrencyCode, quote: CurrencyCode) -> ExchangeRate:
            raise ProviderError("dependency unavailable")

    class Missing:
        def get_rate(self, base: CurrencyCode, quote: CurrencyCode) -> ExchangeRate:
            raise RateUnavailableError("pair missing")

    chain = ChainedRateProvider(Missing(), Down())
    with pytest.raises(ProviderError, match="could safely price"):
        chain.get_rate(CurrencyCode("USD"), CurrencyCode("EUR"))


def test_circuit_breaker_exposes_passive_health_snapshot() -> None:
    from moneytender.infrastructure import CircuitState

    class Down:
        def get_rate(self, base: CurrencyCode, quote: CurrencyCode) -> ExchangeRate:
            raise ProviderError("down")

    breaker = CircuitBreakerRateProvider(
        Down(),
        failure_threshold=1,
        recovery_timeout_seconds=60,
    )
    initial = breaker.snapshot()
    assert initial.state is CircuitState.CLOSED
    assert initial.consecutive_failures == 0

    with pytest.raises(ProviderError):
        breaker.get_rate(CurrencyCode("USD"), CurrencyCode("EUR"))

    opened = breaker.snapshot()
    assert opened.state is CircuitState.OPEN
    assert opened.consecutive_failures == 1
    assert opened.opened_for_seconds is not None
