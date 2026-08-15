from __future__ import annotations

import asyncio
import random
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from enum import StrEnum
from threading import RLock

from .exceptions import CircuitOpenError, ProviderError, RateUnavailableError
from .fx import AsyncExchangeRateProvider, ExchangeRate, ExchangeRateProvider
from .types import CurrencyCode


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    """Retry configuration for transient provider failures.

    ``attempts`` includes the first attempt. ``RateUnavailableError`` is not retried
    by default because it usually means the provider cannot supply that pair rather
    than that the provider is temporarily unhealthy.
    """

    attempts: int = 3
    base_delay_seconds: float = 0.05
    max_delay_seconds: float = 1.0
    backoff_multiplier: float = 2.0
    jitter_ratio: float = 0.1
    retry_rate_unavailable: bool = False

    def __post_init__(self) -> None:
        if self.attempts < 1:
            raise ValueError("attempts must be at least 1")
        if self.base_delay_seconds < 0 or self.max_delay_seconds < 0:
            raise ValueError("retry delays cannot be negative")
        if self.backoff_multiplier < 1:
            raise ValueError("backoff_multiplier must be >= 1")
        if not 0 <= self.jitter_ratio <= 1:
            raise ValueError("jitter_ratio must be between 0 and 1")

    def delay_for_retry(self, retry_index: int) -> float:
        """Return bounded exponential-backoff delay for a zero-based retry index."""
        if retry_index < 0:
            raise ValueError("retry_index cannot be negative")
        raw = min(
            self.max_delay_seconds,
            self.base_delay_seconds * (self.backoff_multiplier**retry_index),
        )
        if raw == 0 or self.jitter_ratio == 0:
            return raw
        spread = raw * self.jitter_ratio
        return max(0.0, raw + random.uniform(-spread, spread))


@dataclass(frozen=True, slots=True)
class RateLimitPolicy:
    """Local token-bucket limit for protecting an upstream provider.

    ``rate_per_second`` controls the refill rate and ``burst`` controls how many
    calls can proceed immediately after an idle period. This limiter is process-local;
    distributed quotas require an application-owned shared coordinator.
    """

    rate_per_second: float
    burst: int = 1

    def __post_init__(self) -> None:
        if self.rate_per_second <= 0:
            raise ValueError("rate_per_second must be positive")
        if self.burst < 1:
            raise ValueError("burst must be at least 1")


@dataclass(frozen=True, slots=True)
class CircuitSnapshot:
    """Point-in-time passive health snapshot of a circuit breaker."""

    state: "CircuitState"
    consecutive_failures: int
    opened_for_seconds: float | None


class RateLimitedRateProvider:
    """Protect a synchronous provider with a local token-bucket rate limit."""

    __slots__ = (
        "_clock",
        "_inner",
        "_lock",
        "_policy",
        "_sleep",
        "_tokens",
        "_updated_at",
    )

    def __init__(
        self,
        inner: ExchangeRateProvider,
        *,
        policy: RateLimitPolicy,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._inner = inner
        self._policy = policy
        self._clock = clock
        self._sleep = sleep
        self._lock = RLock()
        self._tokens = float(policy.burst)
        self._updated_at = clock()

    def get_rate(self, base: CurrencyCode, quote: CurrencyCode) -> ExchangeRate:
        """Acquire one local token, then call the wrapped provider."""
        self._acquire()
        return self._inner.get_rate(base, quote)

    def _acquire(self) -> None:
        while True:
            with self._lock:
                now = self._clock()
                elapsed = max(0.0, now - self._updated_at)
                self._tokens = min(
                    float(self._policy.burst),
                    self._tokens + elapsed * self._policy.rate_per_second,
                )
                self._updated_at = now
                if self._tokens >= 1.0:
                    self._tokens -= 1.0
                    return
                delay = (1.0 - self._tokens) / self._policy.rate_per_second
            self._sleep(delay)


class AsyncRateLimitedRateProvider:
    """Async token-bucket counterpart to :class:`RateLimitedRateProvider`."""

    __slots__ = (
        "_clock",
        "_inner",
        "_lock",
        "_policy",
        "_sleep",
        "_tokens",
        "_updated_at",
    )

    def __init__(
        self,
        inner: AsyncExchangeRateProvider,
        *,
        policy: RateLimitPolicy,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._inner = inner
        self._policy = policy
        self._clock = clock
        self._sleep = sleep
        self._lock = asyncio.Lock()
        self._tokens = float(policy.burst)
        self._updated_at = clock()

    async def get_rate(self, base: CurrencyCode, quote: CurrencyCode) -> ExchangeRate:
        """Await one local token, then call the wrapped async provider."""
        await self._acquire()
        return await self._inner.get_rate(base, quote)

    async def _acquire(self) -> None:
        while True:
            async with self._lock:
                now = self._clock()
                elapsed = max(0.0, now - self._updated_at)
                self._tokens = min(
                    float(self._policy.burst),
                    self._tokens + elapsed * self._policy.rate_per_second,
                )
                self._updated_at = now
                if self._tokens >= 1.0:
                    self._tokens -= 1.0
                    return
                delay = (1.0 - self._tokens) / self._policy.rate_per_second
            await self._sleep(delay)


class RetryingRateProvider:
    """Retry transient failures from a synchronous provider with bounded backoff."""

    __slots__ = (
        "_inner",
        "_policy",
        "_sleep",
    )

    def __init__(
        self,
        inner: ExchangeRateProvider,
        *,
        policy: RetryPolicy | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._inner = inner
        self._policy = policy or RetryPolicy()
        self._sleep = sleep

    def get_rate(self, base: CurrencyCode, quote: CurrencyCode) -> ExchangeRate:
        """Return a quote, retrying configured transient failures with bounded backoff."""
        last_error: ProviderError | RateUnavailableError | None = None
        for attempt in range(self._policy.attempts):
            try:
                return self._inner.get_rate(base, quote)
            except RateUnavailableError as exc:
                if not self._policy.retry_rate_unavailable:
                    raise
                last_error = exc
            except ProviderError as exc:
                last_error = exc

            if attempt + 1 < self._policy.attempts:
                self._sleep(self._policy.delay_for_retry(attempt))

        assert last_error is not None
        if isinstance(last_error, RateUnavailableError):
            raise RateUnavailableError(
                f"rate remained unavailable after {self._policy.attempts} attempts for "
                f"{base}/{quote}: {last_error}"
            ) from last_error
        raise ProviderError(
            f"provider failed after {self._policy.attempts} attempts for {base}/{quote}: "
            f"{last_error}"
        ) from last_error


class AsyncRetryingRateProvider:
    """Async counterpart to :class:`RetryingRateProvider`."""

    __slots__ = (
        "_inner",
        "_policy",
    )

    def __init__(
        self,
        inner: AsyncExchangeRateProvider,
        *,
        policy: RetryPolicy | None = None,
    ) -> None:
        self._inner = inner
        self._policy = policy or RetryPolicy()

    async def get_rate(self, base: CurrencyCode, quote: CurrencyCode) -> ExchangeRate:
        """Return an async quote with cancellation-safe bounded retries."""
        last_error: ProviderError | RateUnavailableError | None = None
        for attempt in range(self._policy.attempts):
            try:
                return await self._inner.get_rate(base, quote)
            except RateUnavailableError as exc:
                if not self._policy.retry_rate_unavailable:
                    raise
                last_error = exc
            except ProviderError as exc:
                last_error = exc

            if attempt + 1 < self._policy.attempts:
                await asyncio.sleep(self._policy.delay_for_retry(attempt))

        assert last_error is not None
        if isinstance(last_error, RateUnavailableError):
            raise RateUnavailableError(
                f"rate remained unavailable after {self._policy.attempts} attempts for "
                f"{base}/{quote}: {last_error}"
            ) from last_error
        raise ProviderError(
            f"async provider failed after {self._policy.attempts} attempts for "
            f"{base}/{quote}: {last_error}"
        ) from last_error


class CircuitState(StrEnum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitBreakerRateProvider:
    """Fail fast after repeated provider failures and probe after a recovery window."""

    __slots__ = (
        "_failure_threshold",
        "_failures",
        "_half_open_probe",
        "_inner",
        "_lock",
        "_opened_at",
        "_recovery_timeout",
    )

    def __init__(
        self,
        inner: ExchangeRateProvider,
        *,
        failure_threshold: int = 5,
        recovery_timeout_seconds: float = 30.0,
    ) -> None:
        if failure_threshold < 1:
            raise ValueError("failure_threshold must be at least 1")
        if recovery_timeout_seconds <= 0:
            raise ValueError("recovery_timeout_seconds must be positive")
        self._inner = inner
        self._failure_threshold = failure_threshold
        self._recovery_timeout = recovery_timeout_seconds
        self._lock = RLock()
        self._failures = 0
        self._opened_at: float | None = None
        self._half_open_probe = False

    @property
    def state(self) -> CircuitState:
        """Return the current provider-wide circuit state."""
        return self.snapshot().state

    def snapshot(self) -> CircuitSnapshot:
        """Return passive circuit health without calling the upstream provider."""
        with self._lock:
            if self._opened_at is None:
                return CircuitSnapshot(CircuitState.CLOSED, self._failures, None)
            opened_for = max(0.0, time.monotonic() - self._opened_at)
            state = (
                CircuitState.HALF_OPEN
                if opened_for >= self._recovery_timeout
                else CircuitState.OPEN
            )
            return CircuitSnapshot(state, self._failures, opened_for)

    def get_rate(self, base: CurrencyCode, quote: CurrencyCode) -> ExchangeRate:
        """Return a quote or fail fast while the provider-wide circuit is open."""
        with self._lock:
            if self._opened_at is not None:
                elapsed = time.monotonic() - self._opened_at
                if elapsed < self._recovery_timeout:
                    raise CircuitOpenError(
                        f"FX provider circuit is open for {base}/{quote}; retry after "
                        f"{self._recovery_timeout - elapsed:.3f}s"
                    )
                if self._half_open_probe:
                    raise CircuitOpenError("FX provider circuit is half-open and a probe is already running")
                self._half_open_probe = True

        try:
            rate = self._inner.get_rate(base, quote)
        except RateUnavailableError:
            # Pair availability should not count as provider health failure.
            self._finish_successful_probe_if_needed()
            raise
        except ProviderError:
            self._record_failure()
            raise
        else:
            with self._lock:
                self._failures = 0
                self._opened_at = None
                self._half_open_probe = False
            return rate

    def _finish_successful_probe_if_needed(self) -> None:
        with self._lock:
            if self._half_open_probe:
                self._half_open_probe = False
                self._failures = 0
                self._opened_at = None

    def _record_failure(self) -> None:
        with self._lock:
            self._half_open_probe = False
            self._failures += 1
            if self._failures >= self._failure_threshold:
                self._opened_at = time.monotonic()


class AsyncCircuitBreakerRateProvider:
    """Async circuit breaker with the same semantics as the synchronous variant."""

    __slots__ = (
        "_failure_threshold",
        "_failures",
        "_half_open_probe",
        "_inner",
        "_lock",
        "_opened_at",
        "_recovery_timeout",
    )

    def __init__(
        self,
        inner: AsyncExchangeRateProvider,
        *,
        failure_threshold: int = 5,
        recovery_timeout_seconds: float = 30.0,
    ) -> None:
        if failure_threshold < 1:
            raise ValueError("failure_threshold must be at least 1")
        if recovery_timeout_seconds <= 0:
            raise ValueError("recovery_timeout_seconds must be positive")
        self._inner = inner
        self._failure_threshold = failure_threshold
        self._recovery_timeout = recovery_timeout_seconds
        self._lock = asyncio.Lock()
        self._failures = 0
        self._opened_at: float | None = None
        self._half_open_probe = False

    async def snapshot(self) -> CircuitSnapshot:
        """Return passive async circuit health without touching the provider."""
        async with self._lock:
            if self._opened_at is None:
                return CircuitSnapshot(CircuitState.CLOSED, self._failures, None)
            opened_for = max(0.0, time.monotonic() - self._opened_at)
            state = (
                CircuitState.HALF_OPEN
                if opened_for >= self._recovery_timeout
                else CircuitState.OPEN
            )
            return CircuitSnapshot(state, self._failures, opened_for)

    async def get_rate(self, base: CurrencyCode, quote: CurrencyCode) -> ExchangeRate:
        """Return an async quote or fail fast while the provider-wide circuit is open."""
        async with self._lock:
            if self._opened_at is not None:
                elapsed = time.monotonic() - self._opened_at
                if elapsed < self._recovery_timeout:
                    raise CircuitOpenError(
                        f"FX provider circuit is open for {base}/{quote}; retry after "
                        f"{self._recovery_timeout - elapsed:.3f}s"
                    )
                if self._half_open_probe:
                    raise CircuitOpenError("FX provider circuit is half-open and a probe is already running")
                self._half_open_probe = True

        try:
            rate = await self._inner.get_rate(base, quote)
        except RateUnavailableError:
            async with self._lock:
                if self._half_open_probe:
                    self._half_open_probe = False
                    self._failures = 0
                    self._opened_at = None
            raise
        except ProviderError:
            async with self._lock:
                self._half_open_probe = False
                self._failures += 1
                if self._failures >= self._failure_threshold:
                    self._opened_at = time.monotonic()
            raise
        else:
            async with self._lock:
                self._failures = 0
                self._opened_at = None
                self._half_open_probe = False
            return rate


@dataclass(slots=True)
class _PairCircuitEntry:
    failures: int = 0
    opened_at: float | None = None
    half_open_probe: bool = False


class PairCircuitBreakerRateProvider:
    """Circuit breaker scoped independently to each currency pair.

    Use this when a provider may have partial pair-specific outages and one failing
    pair should not block healthy pairs. For provider-wide outages, the simpler
    :class:`CircuitBreakerRateProvider` is usually the safer default.
    """

    __slots__ = (
        "_entries",
        "_failure_threshold",
        "_inner",
        "_lock",
        "_recovery_timeout",
    )

    def __init__(
        self,
        inner: ExchangeRateProvider,
        *,
        failure_threshold: int = 5,
        recovery_timeout_seconds: float = 30.0,
    ) -> None:
        if failure_threshold < 1:
            raise ValueError("failure_threshold must be at least 1")
        if recovery_timeout_seconds <= 0:
            raise ValueError("recovery_timeout_seconds must be positive")
        self._inner = inner
        self._failure_threshold = failure_threshold
        self._recovery_timeout = recovery_timeout_seconds
        self._lock = RLock()
        self._entries: dict[tuple[CurrencyCode, CurrencyCode], _PairCircuitEntry] = {}

    def snapshot(self, base: CurrencyCode, quote: CurrencyCode) -> CircuitSnapshot:
        """Return passive circuit health for one currency pair."""
        key = (base, quote)
        with self._lock:
            entry = self._entries.get(key)
            if entry is None or entry.opened_at is None:
                failures = 0 if entry is None else entry.failures
                return CircuitSnapshot(CircuitState.CLOSED, failures, None)
            opened_for = max(0.0, time.monotonic() - entry.opened_at)
            state = (
                CircuitState.HALF_OPEN
                if opened_for >= self._recovery_timeout
                else CircuitState.OPEN
            )
            return CircuitSnapshot(state, entry.failures, opened_for)

    def get_rate(self, base: CurrencyCode, quote: CurrencyCode) -> ExchangeRate:
        """Fetch a rate while isolating circuit state to ``base/quote``."""
        key = (base, quote)
        with self._lock:
            entry = self._entries.setdefault(key, _PairCircuitEntry())
            if entry.opened_at is not None:
                elapsed = time.monotonic() - entry.opened_at
                if elapsed < self._recovery_timeout:
                    raise CircuitOpenError(
                        f"FX pair circuit is open for {base}/{quote}; retry after "
                        f"{self._recovery_timeout - elapsed:.3f}s"
                    )
                if entry.half_open_probe:
                    raise CircuitOpenError(
                        f"FX pair circuit for {base}/{quote} is half-open and a probe "
                        "is already running"
                    )
                entry.half_open_probe = True

        try:
            rate = self._inner.get_rate(base, quote)
        except RateUnavailableError:
            self._record_pair_success(key)
            raise
        except ProviderError:
            self._record_pair_failure(key)
            raise
        else:
            self._record_pair_success(key)
            return rate

    def _record_pair_success(self, key: tuple[CurrencyCode, CurrencyCode]) -> None:
        with self._lock:
            entry = self._entries.setdefault(key, _PairCircuitEntry())
            entry.failures = 0
            entry.opened_at = None
            entry.half_open_probe = False

    def _record_pair_failure(self, key: tuple[CurrencyCode, CurrencyCode]) -> None:
        with self._lock:
            entry = self._entries.setdefault(key, _PairCircuitEntry())
            entry.half_open_probe = False
            entry.failures += 1
            if entry.failures >= self._failure_threshold:
                entry.opened_at = time.monotonic()


class AsyncPairCircuitBreakerRateProvider:
    """Async pair-scoped circuit breaker."""

    __slots__ = (
        "_entries",
        "_failure_threshold",
        "_inner",
        "_lock",
        "_recovery_timeout",
    )

    def __init__(
        self,
        inner: AsyncExchangeRateProvider,
        *,
        failure_threshold: int = 5,
        recovery_timeout_seconds: float = 30.0,
    ) -> None:
        if failure_threshold < 1:
            raise ValueError("failure_threshold must be at least 1")
        if recovery_timeout_seconds <= 0:
            raise ValueError("recovery_timeout_seconds must be positive")
        self._inner = inner
        self._failure_threshold = failure_threshold
        self._recovery_timeout = recovery_timeout_seconds
        self._lock = asyncio.Lock()
        self._entries: dict[tuple[CurrencyCode, CurrencyCode], _PairCircuitEntry] = {}

    async def snapshot(self, base: CurrencyCode, quote: CurrencyCode) -> CircuitSnapshot:
        """Return passive async circuit health for one currency pair."""
        key = (base, quote)
        async with self._lock:
            entry = self._entries.get(key)
            if entry is None or entry.opened_at is None:
                failures = 0 if entry is None else entry.failures
                return CircuitSnapshot(CircuitState.CLOSED, failures, None)
            opened_for = max(0.0, time.monotonic() - entry.opened_at)
            state = (
                CircuitState.HALF_OPEN
                if opened_for >= self._recovery_timeout
                else CircuitState.OPEN
            )
            return CircuitSnapshot(state, entry.failures, opened_for)

    async def get_rate(self, base: CurrencyCode, quote: CurrencyCode) -> ExchangeRate:
        """Fetch a rate while isolating async circuit state to one pair."""
        key = (base, quote)
        async with self._lock:
            entry = self._entries.setdefault(key, _PairCircuitEntry())
            if entry.opened_at is not None:
                elapsed = time.monotonic() - entry.opened_at
                if elapsed < self._recovery_timeout:
                    raise CircuitOpenError(
                        f"FX pair circuit is open for {base}/{quote}; retry after "
                        f"{self._recovery_timeout - elapsed:.3f}s"
                    )
                if entry.half_open_probe:
                    raise CircuitOpenError(
                        f"FX pair circuit for {base}/{quote} is half-open and a probe "
                        "is already running"
                    )
                entry.half_open_probe = True

        try:
            rate = await self._inner.get_rate(base, quote)
        except RateUnavailableError:
            await self._record_pair_success(key)
            raise
        except ProviderError:
            await self._record_pair_failure(key)
            raise
        else:
            await self._record_pair_success(key)
            return rate

    async def _record_pair_success(
        self,
        key: tuple[CurrencyCode, CurrencyCode],
    ) -> None:
        async with self._lock:
            entry = self._entries.setdefault(key, _PairCircuitEntry())
            entry.failures = 0
            entry.opened_at = None
            entry.half_open_probe = False

    async def _record_pair_failure(
        self,
        key: tuple[CurrencyCode, CurrencyCode],
    ) -> None:
        async with self._lock:
            entry = self._entries.setdefault(key, _PairCircuitEntry())
            entry.half_open_probe = False
            entry.failures += 1
            if entry.failures >= self._failure_threshold:
                entry.opened_at = time.monotonic()
