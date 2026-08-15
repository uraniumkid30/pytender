"""Safe, high-level FX composition helpers.

The low-level provider decorators remain public for advanced users. This module gives
beginners and application teams a documented default order so they do not need to
learn decorator-order semantics before deploying a sensible FX stack.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import timedelta
from enum import StrEnum
from typing import TYPE_CHECKING

from .fx import (
    CachedRateProvider,
    ChainedRateProvider,
    ExchangeRateProvider,
    MoneyConverter,
)
from .observability import (
    AuditedRateProvider,
    HookFailureMode,
    ObservedRateProvider,
    ProviderObserver,
    RateAuditSink,
)
from .policy import MissingTimestampPolicy, RateKind, RatePolicy
from .registry import DEFAULT_REGISTRY, CurrencyRegistry
from .resilience import (
    CircuitBreakerRateProvider,
    PairCircuitBreakerRateProvider,
    RateLimitedRateProvider,
    RateLimitPolicy,
    RetryingRateProvider,
    RetryPolicy,
)
from .rounding import DEFAULT_ROUNDING, RoundingPolicy

if TYPE_CHECKING:
    from .fx import AsyncExchangeRateProvider, AsyncMoneyConverter
    from .observability import AsyncProviderObserver, AsyncRateAuditSink


class CircuitScope(StrEnum):
    """Choose whether breaker health is shared by a provider or isolated by pair."""

    PROVIDER = "provider"
    PAIR = "pair"


@dataclass(frozen=True, slots=True)
class ProductionProviderConfig:
    """Opinionated but conservative defaults for a production provider stack.

    Nothing here makes distributed guarantees: cache, rate limiting and circuit state
    remain process-local. Set ``rate_limit`` only when a per-process token bucket is
    appropriate for the upstream provider quota.
    """

    cache_ttl_seconds: float = 10.0
    cache_maxsize: int = 256
    stale_if_error_seconds: float = 0.0
    retry: RetryPolicy = field(default_factory=RetryPolicy)
    rate_limit: RateLimitPolicy | None = None
    circuit_failure_threshold: int = 5
    circuit_recovery_seconds: float = 30.0
    circuit_scope: CircuitScope = CircuitScope.PROVIDER


def checkout_policy(
    *,
    max_age: timedelta = timedelta(seconds=30),
    allowed_sources: Iterable[str] = (),
) -> RatePolicy:
    """Return a strict checkout policy: executable, fresh, non-derived quotes only."""
    return RatePolicy(
        max_age=max_age,
        allowed_sources=frozenset(allowed_sources),
        allowed_kinds=frozenset({RateKind.EXECUTABLE}),
        missing_timestamp=MissingTimestampPolicy.REJECT,
        allow_inverse=False,
        allow_triangulation=False,
    )


def reporting_policy(
    *,
    max_age: timedelta = timedelta(hours=24),
    allowed_sources: Iterable[str] = (),
    allow_derived: bool = True,
) -> RatePolicy:
    """Return a valuation/reporting policy with a wider freshness window."""
    kinds = {RateKind.REFERENCE, RateKind.INDICATIVE, RateKind.EXECUTABLE}
    if allow_derived:
        kinds.add(RateKind.DERIVED)
    return RatePolicy(
        max_age=max_age,
        allowed_sources=frozenset(allowed_sources),
        allowed_kinds=frozenset(kinds),
        missing_timestamp=MissingTimestampPolicy.USE_FETCHED_AT,
        allow_inverse=allow_derived,
        allow_triangulation=allow_derived,
    )


def display_policy(
    *,
    max_age: timedelta = timedelta(minutes=15),
    allowed_sources: Iterable[str] = (),
) -> RatePolicy:
    """Return a user-display policy that allows non-executable but non-derived quotes."""
    return RatePolicy(
        max_age=max_age,
        allowed_sources=frozenset(allowed_sources),
        allowed_kinds=frozenset(
            {RateKind.REFERENCE, RateKind.INDICATIVE, RateKind.EXECUTABLE}
        ),
        missing_timestamp=MissingTimestampPolicy.USE_FETCHED_AT,
    )


def treasury_policy(
    *,
    max_age: timedelta = timedelta(minutes=5),
    allowed_sources: Iterable[str] = (),
) -> RatePolicy:
    """Return a conservative treasury policy for fresh direct executable quotes."""
    return checkout_policy(max_age=max_age, allowed_sources=allowed_sources)


def _wrap_sync_provider(
    provider: ExchangeRateProvider,
    *,
    config: ProductionProviderConfig,
) -> ExchangeRateProvider:
    """Apply provider-local resilience before failover composition."""
    wrapped: ExchangeRateProvider = RetryingRateProvider(provider, policy=config.retry)

    if config.rate_limit is not None:
        wrapped = RateLimitedRateProvider(wrapped, policy=config.rate_limit)

    if config.circuit_scope is CircuitScope.PAIR:
        return PairCircuitBreakerRateProvider(
            wrapped,
            failure_threshold=config.circuit_failure_threshold,
            recovery_timeout_seconds=config.circuit_recovery_seconds,
        )

    return CircuitBreakerRateProvider(
        wrapped,
        failure_threshold=config.circuit_failure_threshold,
        recovery_timeout_seconds=config.circuit_recovery_seconds,
    )


def build_production_provider(
    primary: ExchangeRateProvider,
    *fallbacks: ExchangeRateProvider,
    config: ProductionProviderConfig | None = None,
    audit_sink: RateAuditSink | None = None,
    audit_failure_mode: HookFailureMode = HookFailureMode.FAIL_CLOSED,
    observer: ProviderObserver | None = None,
    observer_failure_mode: HookFailureMode = HookFailureMode.FAIL_OPEN,
) -> ExchangeRateProvider:
    """Build the recommended synchronous production composition.

    Resilience is applied *per provider* before ordered failover::

        primary  -> retry -> optional local rate limit -> circuit
        fallback -> retry -> optional local rate limit -> circuit
                              |
                              v
                            chain
                              |
                             cache
                              |
                     optional audit/observe

    ``RetryPolicy.attempts`` therefore means attempts **for each provider**, not
    attempts around the whole provider chain. With three providers and
    ``attempts=3``, the worst-case failure path can make up to nine upstream calls
    before the chain gives up. This behavior is explicit so incident latency and
    provider quotas can be sized intentionally.

    The helper deliberately does not add inverse or triangulation automatically.
    Derived quotes are a business decision. Advanced users who need different
    ordering or provider-specific policies should compose the low-level decorators
    from :mod:`pytender.infrastructure` directly.
    """
    config = config or ProductionProviderConfig()
    wrapped = [_wrap_sync_provider(provider, config=config) for provider in (primary, *fallbacks)]
    provider: ExchangeRateProvider = (
        wrapped[0] if len(wrapped) == 1 else ChainedRateProvider(*wrapped)
    )

    provider = CachedRateProvider(
        provider,
        ttl_seconds=config.cache_ttl_seconds,
        maxsize=config.cache_maxsize,
        stale_if_error_seconds=config.stale_if_error_seconds,
    )
    if audit_sink is not None:
        provider = AuditedRateProvider(
            provider,
            audit_sink,
            failure_mode=audit_failure_mode,
        )
    if observer is not None:
        provider = ObservedRateProvider(
            provider,
            observer,
            failure_mode=observer_failure_mode,
        )
    return provider


def build_production_converter(
    primary: ExchangeRateProvider,
    *fallbacks: ExchangeRateProvider,
    policy: RatePolicy | None = None,
    config: ProductionProviderConfig | None = None,
    registry: CurrencyRegistry = DEFAULT_REGISTRY,
    rounding: RoundingPolicy = DEFAULT_ROUNDING,
    audit_sink: RateAuditSink | None = None,
    audit_failure_mode: HookFailureMode = HookFailureMode.FAIL_CLOSED,
    observer: ProviderObserver | None = None,
    observer_failure_mode: HookFailureMode = HookFailureMode.FAIL_OPEN,
) -> MoneyConverter:
    """Build a production provider stack and wrap it in :class:`MoneyConverter`.

    ``policy`` defaults to ``None`` for backwards-compatible general use. For checkout
    and other money-moving paths, pass :func:`checkout_policy` explicitly.
    """
    config = config or ProductionProviderConfig()
    provider = build_production_provider(
        primary,
        *fallbacks,
        config=config,
        audit_sink=audit_sink,
        audit_failure_mode=audit_failure_mode,
        observer=observer,
        observer_failure_mode=observer_failure_mode,
    )
    return MoneyConverter(provider, registry=registry, rounding=rounding, policy=policy)


def _wrap_async_provider(
    provider: "AsyncExchangeRateProvider",
    *,
    config: ProductionProviderConfig,
) -> "AsyncExchangeRateProvider":
    """Apply async provider-local resilience before failover composition."""
    from .resilience import (
        AsyncCircuitBreakerRateProvider,
        AsyncPairCircuitBreakerRateProvider,
        AsyncRateLimitedRateProvider,
        AsyncRetryingRateProvider,
    )

    wrapped: AsyncExchangeRateProvider = AsyncRetryingRateProvider(
        provider,
        policy=config.retry,
    )
    if config.rate_limit is not None:
        wrapped = AsyncRateLimitedRateProvider(wrapped, policy=config.rate_limit)

    if config.circuit_scope is CircuitScope.PAIR:
        return AsyncPairCircuitBreakerRateProvider(
            wrapped,
            failure_threshold=config.circuit_failure_threshold,
            recovery_timeout_seconds=config.circuit_recovery_seconds,
        )

    return AsyncCircuitBreakerRateProvider(
        wrapped,
        failure_threshold=config.circuit_failure_threshold,
        recovery_timeout_seconds=config.circuit_recovery_seconds,
    )


def build_async_production_provider(
    primary: "AsyncExchangeRateProvider",
    *fallbacks: "AsyncExchangeRateProvider",
    config: ProductionProviderConfig | None = None,
    audit_sink: "AsyncRateAuditSink | None" = None,
    audit_failure_mode: HookFailureMode = HookFailureMode.FAIL_CLOSED,
    observer: "AsyncProviderObserver | None" = None,
    observer_failure_mode: HookFailureMode = HookFailureMode.FAIL_OPEN,
) -> "AsyncExchangeRateProvider":
    """Build the async equivalent of :func:`build_production_provider`.

    Retry, rate limiting and circuit breaking are applied per provider before
    ordered failover. The same per-provider attempt-count semantics documented by
    :func:`build_production_provider` therefore apply to async stacks.
    """
    from .fx import AsyncCachedRateProvider, AsyncChainedRateProvider
    from .observability import AsyncAuditedRateProvider, AsyncObservedRateProvider

    config = config or ProductionProviderConfig()
    wrapped = [
        _wrap_async_provider(provider, config=config)
        for provider in (primary, *fallbacks)
    ]
    provider: AsyncExchangeRateProvider = (
        wrapped[0] if len(wrapped) == 1 else AsyncChainedRateProvider(*wrapped)
    )

    provider = AsyncCachedRateProvider(
        provider,
        ttl_seconds=config.cache_ttl_seconds,
        maxsize=config.cache_maxsize,
        stale_if_error_seconds=config.stale_if_error_seconds,
    )
    if audit_sink is not None:
        provider = AsyncAuditedRateProvider(
            provider,
            audit_sink,
            failure_mode=audit_failure_mode,
        )
    if observer is not None:
        provider = AsyncObservedRateProvider(
            provider,
            observer,
            failure_mode=observer_failure_mode,
        )
    return provider


def build_async_production_converter(
    primary: "AsyncExchangeRateProvider",
    *fallbacks: "AsyncExchangeRateProvider",
    policy: RatePolicy | None = None,
    config: ProductionProviderConfig | None = None,
    registry: CurrencyRegistry = DEFAULT_REGISTRY,
    rounding: RoundingPolicy = DEFAULT_ROUNDING,
    audit_sink: "AsyncRateAuditSink | None" = None,
    audit_failure_mode: HookFailureMode = HookFailureMode.FAIL_CLOSED,
    observer: "AsyncProviderObserver | None" = None,
    observer_failure_mode: HookFailureMode = HookFailureMode.FAIL_OPEN,
) -> "AsyncMoneyConverter":
    """Build an async production provider stack and converter."""
    from .fx import AsyncMoneyConverter

    config = config or ProductionProviderConfig()
    provider = build_async_production_provider(
        primary,
        *fallbacks,
        config=config,
        audit_sink=audit_sink,
        audit_failure_mode=audit_failure_mode,
        observer=observer,
        observer_failure_mode=observer_failure_mode,
    )
    return AsyncMoneyConverter(
        provider,
        registry=registry,
        rounding=rounding,
        policy=policy,
    )
