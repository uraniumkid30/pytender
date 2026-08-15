from __future__ import annotations

import asyncio
from collections import OrderedDict
from collections.abc import Mapping
from concurrent.futures import Future
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation, localcontext
from threading import RLock
from time import monotonic
from types import MappingProxyType
from typing import Protocol, runtime_checkable

from ._numeric import integer_decimal_digits
from .exceptions import InvalidRateError, ProviderError, RateUnavailableError
from .money import Money
from .policy import DerivationKind, RateKind, RatePolicy
from .registry import DEFAULT_REGISTRY, CurrencyRegistry
from .rounding import DEFAULT_ROUNDING, RoundingPolicy
from .types import Currency, CurrencyCode, MinorUnits


def _normalize_currency_code(value: str | CurrencyCode) -> CurrencyCode:
    code = str(value).upper()
    if len(code) != 3 or not code.isalpha():
        raise InvalidRateError(f"currency code must be exactly three alphabetic characters, got {value!r}")
    return CurrencyCode(code)


@dataclass(frozen=True, slots=True)
class RateProvenance:
    """Audit metadata describing where and when an FX quote came from."""

    provider: str
    source_uri: str = ""
    as_of: datetime | None = None
    fetched_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    request_id: str = ""
    metadata: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.provider, str) or not self.provider:
            raise ValueError("provenance.provider must be a non-empty string")
        if not isinstance(self.source_uri, str):
            raise TypeError("provenance.source_uri must be a string")
        if not isinstance(self.request_id, str):
            raise TypeError("provenance.request_id must be a string")
        if self.as_of is not None and self.as_of.tzinfo is None:
            raise ValueError("provenance.as_of must be timezone-aware")
        if self.fetched_at.tzinfo is None:
            raise ValueError("provenance.fetched_at must be timezone-aware")
        metadata = dict(self.metadata)
        if any(not isinstance(key, str) or not isinstance(value, str) for key, value in metadata.items()):
            raise TypeError("provenance.metadata keys and values must be strings")
        object.__setattr__(self, "metadata", MappingProxyType(metadata))

    def __hash__(self) -> int:
        metadata_items = tuple(sorted(self.metadata.items()))
        return hash(
            (
                self.provider,
                self.source_uri,
                self.as_of,
                self.fetched_at,
                self.request_id,
                metadata_items,
            )
        )


@dataclass(frozen=True, slots=True)
class ExchangeRate:
    """A positive finite FX quote with explicit business meaning and provenance."""

    base: CurrencyCode
    quote: CurrencyCode
    value: Decimal
    provenance: RateProvenance = field(default_factory=lambda: RateProvenance("unknown"))
    kind: RateKind = RateKind.REFERENCE
    derivation: DerivationKind = DerivationKind.NONE

    def __post_init__(self) -> None:
        object.__setattr__(self, "base", _normalize_currency_code(self.base))
        object.__setattr__(self, "quote", _normalize_currency_code(self.quote))
        if not isinstance(self.value, Decimal):
            raise InvalidRateError(
                "exchange rate value must be Decimal; construct it from a string, not float"
            )
        if not self.value.is_finite() or self.value <= 0:
            raise InvalidRateError("exchange rate must be a positive finite Decimal")
        if not isinstance(self.kind, RateKind):
            raise InvalidRateError("exchange rate kind must be a RateKind")
        if not isinstance(self.derivation, DerivationKind):
            raise InvalidRateError("exchange rate derivation must be a DerivationKind")
        if self.kind is RateKind.DERIVED and self.derivation is DerivationKind.NONE:
            raise InvalidRateError(
                "derived exchange rates must declare how they were derived; "
                "use DerivationKind.INVERSE, TRIANGULATION, or CUSTOM"
            )
        if self.kind is not RateKind.DERIVED and self.derivation is not DerivationKind.NONE:
            raise InvalidRateError("non-derived exchange rates must use DerivationKind.NONE")

        metadata_derivation = self.provenance.metadata.get("derived")
        if metadata_derivation and metadata_derivation != self.derivation.value:
            raise InvalidRateError(
                "provenance.metadata['derived'] conflicts with the typed derivation field; "
                f"metadata={metadata_derivation!r}, derivation={self.derivation.value!r}"
            )

    @property
    def source(self) -> str:
        """Return the logical provider name from provenance."""
        return self.provenance.provider


@dataclass(frozen=True, slots=True)
class ConversionResult:
    """Auditable conversion result that retains the exact rate used."""

    source: Money
    target: Money
    rate: ExchangeRate


@runtime_checkable
class ExchangeRateProvider(Protocol):
    """Structural contract for synchronous FX providers."""

    def get_rate(self, base: CurrencyCode, quote: CurrencyCode) -> ExchangeRate: ...


@runtime_checkable
class AsyncExchangeRateProvider(Protocol):
    """Structural contract for asynchronous FX providers."""

    async def get_rate(self, base: CurrencyCode, quote: CurrencyCode) -> ExchangeRate: ...


class StaticRateProvider:
    """Deterministic in-memory provider useful for testing, replay and fixed pricing."""

    __slots__ = (
        "_rates",
        "kind",
        "name",
    )

    def __init__(
        self,
        rates: Mapping[tuple[str, str], str | Decimal | int],
        *,
        name: str = "static",
        kind: RateKind = RateKind.REFERENCE,
    ) -> None:
        self.name = name
        self.kind = kind
        self._rates: dict[tuple[CurrencyCode, CurrencyCode], Decimal] = {}
        for (base, quote), value in rates.items():
            if isinstance(value, (bool, float)):
                raise InvalidRateError("bool/float rates are forbidden; use str, int, or Decimal")
            try:
                rate = value if isinstance(value, Decimal) else Decimal(value)
            except (InvalidOperation, ValueError) as exc:
                raise InvalidRateError(f"invalid rate for {base}/{quote}: {value!r}") from exc
            if not rate.is_finite() or rate <= 0:
                raise InvalidRateError(f"invalid rate for {base}/{quote}: {value!r}")
            key = (_normalize_currency_code(base), _normalize_currency_code(quote))
            self._rates[key] = rate

    def get_rate(self, base: CurrencyCode, quote: CurrencyCode) -> ExchangeRate:
        """Return the configured quote or raise RateUnavailableError when absent."""
        if base == quote:
            return ExchangeRate(
                base,
                quote,
                Decimal("1"),
                RateProvenance(self.name),
                self.kind,
            )
        try:
            value = self._rates[(base, quote)]
        except KeyError as exc:
            raise RateUnavailableError(f"no exchange rate available for {base}/{quote}") from exc
        return ExchangeRate(base, quote, value, RateProvenance(self.name), self.kind)


class AsyncFromSyncProvider:
    """Adapt only cheap non-blocking sync providers to the async protocol."""

    __slots__ = ("_inner",)

    def __init__(self, inner: ExchangeRateProvider) -> None:
        self._inner = inner

    async def get_rate(self, base: CurrencyCode, quote: CurrencyCode) -> ExchangeRate:
        """Return a quote from a cheap non-blocking synchronous provider."""
        return self._inner.get_rate(base, quote)


class PolicyRateProvider:
    """Enforce a business :class:`RatePolicy` on every synchronous quote."""

    __slots__ = (
        "_inner",
        "_policy",
    )

    def __init__(self, inner: ExchangeRateProvider, policy: RatePolicy) -> None:
        self._inner = inner
        self._policy = policy

    def get_rate(self, base: CurrencyCode, quote: CurrencyCode) -> ExchangeRate:
        """Return a quote only after it satisfies the configured RatePolicy."""
        rate = self._inner.get_rate(base, quote)
        self._policy.validate(rate)
        return rate


class AsyncPolicyRateProvider:
    """Async rate-policy decorator."""

    __slots__ = (
        "_inner",
        "_policy",
    )

    def __init__(self, inner: AsyncExchangeRateProvider, policy: RatePolicy) -> None:
        self._inner = inner
        self._policy = policy

    async def get_rate(self, base: CurrencyCode, quote: CurrencyCode) -> ExchangeRate:
        """Return an async quote only after it satisfies the configured RatePolicy."""
        rate = await self._inner.get_rate(base, quote)
        self._policy.validate(rate)
        return rate


class InverseRateProvider:
    """Try direct lookup, then derive the reciprocal from the reverse pair."""

    __slots__ = ("_inner",)

    def __init__(self, inner: ExchangeRateProvider) -> None:
        self._inner = inner

    def get_rate(self, base: CurrencyCode, quote: CurrencyCode) -> ExchangeRate:
        """Return a direct quote or an explicitly derived reciprocal quote."""
        try:
            return self._inner.get_rate(base, quote)
        except RateUnavailableError as direct_error:
            try:
                reverse = self._inner.get_rate(quote, base)
            except RateUnavailableError:
                raise direct_error from None

        provenance = reverse.provenance
        value = _reciprocal(reverse.value)
        return ExchangeRate(
            base,
            quote,
            value,
            RateProvenance(
                provider=f"inverse:{provenance.provider}",
                source_uri=provenance.source_uri,
                as_of=provenance.as_of,
                fetched_at=provenance.fetched_at,
                request_id=provenance.request_id,
                metadata={
                    **provenance.metadata,
                    "derived": "inverse",
                    "source_pair": f"{quote}/{base}",
                },
            ),
            RateKind.DERIVED,
            DerivationKind.INVERSE,
        )


class AsyncInverseRateProvider:
    """Async reciprocal-rate decorator."""

    __slots__ = ("_inner",)

    def __init__(self, inner: AsyncExchangeRateProvider) -> None:
        self._inner = inner

    async def get_rate(self, base: CurrencyCode, quote: CurrencyCode) -> ExchangeRate:
        """Return a direct async quote or an explicitly derived reciprocal quote."""
        try:
            return await self._inner.get_rate(base, quote)
        except RateUnavailableError as direct_error:
            try:
                reverse = await self._inner.get_rate(quote, base)
            except RateUnavailableError:
                raise direct_error from None

        provenance = reverse.provenance
        value = _reciprocal(reverse.value)
        return ExchangeRate(
            base,
            quote,
            value,
            RateProvenance(
                provider=f"inverse:{provenance.provider}",
                source_uri=provenance.source_uri,
                as_of=provenance.as_of,
                fetched_at=provenance.fetched_at,
                request_id=provenance.request_id,
                metadata={
                    **provenance.metadata,
                    "derived": "inverse",
                    "source_pair": f"{quote}/{base}",
                },
            ),
            RateKind.DERIVED,
            DerivationKind.INVERSE,
        )


class TriangulatingRateProvider:
    """Try a direct pair, then derive it through explicit pivot currencies."""

    __slots__ = (
        "_inner",
        "_max_leg_skew",
        "_pivots",
    )

    def __init__(
        self,
        inner: ExchangeRateProvider,
        pivots: tuple[str, ...] = ("USD", "EUR"),
        *,
        max_leg_skew: timedelta | None = None,
    ) -> None:
        if max_leg_skew is not None and max_leg_skew < timedelta(0):
            raise ValueError("max_leg_skew cannot be negative")
        self._inner = inner
        self._pivots = tuple(CurrencyCode(pivot.upper()) for pivot in pivots)
        self._max_leg_skew = max_leg_skew
        if not self._pivots:
            raise ValueError("at least one triangulation pivot is required")

    def get_rate(self, base: CurrencyCode, quote: CurrencyCode) -> ExchangeRate:
        """Return a direct quote or derive one through an approved pivot."""
        try:
            return self._inner.get_rate(base, quote)
        except RateUnavailableError as direct_error:
            direct_message = str(direct_error)
            direct_cause = direct_error
            failures: list[str] = []
            for pivot in self._pivots:
                if pivot in (base, quote):
                    continue
                try:
                    left = self._inner.get_rate(base, pivot)
                    right = self._inner.get_rate(pivot, quote)
                except RateUnavailableError as exc:
                    failures.append(str(exc))
                    continue
                try:
                    return _triangulate(
                        base,
                        quote,
                        pivot,
                        left,
                        right,
                        max_leg_skew=self._max_leg_skew,
                    )
                except RateUnavailableError as exc:
                    failures.append(str(exc))
                    continue

        raise RateUnavailableError(
            f"no direct or triangulated rate available for {base}/{quote}; "
            f"direct={direct_message}; pivots={','.join(self._pivots)}; "
            f"failures={'; '.join(failures)}"
        ) from direct_cause


class AsyncTriangulatingRateProvider:
    """Async triangulation; independent pivot legs are requested concurrently."""

    __slots__ = (
        "_inner",
        "_max_leg_skew",
        "_pivots",
    )

    def __init__(
        self,
        inner: AsyncExchangeRateProvider,
        pivots: tuple[str, ...] = ("USD", "EUR"),
        *,
        max_leg_skew: timedelta | None = None,
    ) -> None:
        if max_leg_skew is not None and max_leg_skew < timedelta(0):
            raise ValueError("max_leg_skew cannot be negative")
        self._inner = inner
        self._pivots = tuple(CurrencyCode(pivot.upper()) for pivot in pivots)
        self._max_leg_skew = max_leg_skew
        if not self._pivots:
            raise ValueError("at least one triangulation pivot is required")

    async def get_rate(self, base: CurrencyCode, quote: CurrencyCode) -> ExchangeRate:
        """Return a direct quote or concurrently derive one through an approved pivot."""
        try:
            return await self._inner.get_rate(base, quote)
        except RateUnavailableError as direct_error:
            direct_message = str(direct_error)
            direct_cause = direct_error
            failures: list[str] = []
            for pivot in self._pivots:
                if pivot in (base, quote):
                    continue
                try:
                    left, right = await asyncio.gather(
                        self._inner.get_rate(base, pivot),
                        self._inner.get_rate(pivot, quote),
                    )
                except RateUnavailableError as exc:
                    failures.append(str(exc))
                    continue
                try:
                    return _triangulate(
                        base,
                        quote,
                        pivot,
                        left,
                        right,
                        max_leg_skew=self._max_leg_skew,
                    )
                except RateUnavailableError as exc:
                    failures.append(str(exc))
                    continue

        raise RateUnavailableError(
            f"no direct or triangulated rate available for {base}/{quote}; "
            f"direct={direct_message}; pivots={','.join(self._pivots)}; "
            f"failures={'; '.join(failures)}"
        ) from direct_cause


class ChainedRateProvider:
    """Try providers in priority order with explicit operational failover.

    If every provider reports pair unavailability, ``RateUnavailableError`` is
    raised. If any provider fails operationally and no provider succeeds, the final
    error is ``ProviderError`` so callers do not mistake infrastructure uncertainty
    for authoritative pair unavailability.
    """

    __slots__ = ("_providers",)

    def __init__(self, *providers: ExchangeRateProvider) -> None:
        if not providers:
            raise ValueError("at least one exchange-rate provider is required")
        self._providers = providers

    def get_rate(self, base: CurrencyCode, quote: CurrencyCode) -> ExchangeRate:
        """Return the first successful quote while preserving failure semantics."""
        failures: list[str] = []
        operational_failure = False
        for provider in self._providers:
            try:
                return provider.get_rate(base, quote)
            except RateUnavailableError as exc:
                failures.append(f"{type(provider).__name__}: unavailable: {exc}")
            except ProviderError as exc:
                operational_failure = True
                failures.append(f"{type(provider).__name__}: failed: {exc}")

        detail = f"failures: {'; '.join(failures)}"
        if operational_failure:
            raise ProviderError(f"no configured provider could safely price {base}/{quote}; {detail}")
        raise RateUnavailableError(f"no configured provider could supply {base}/{quote}; {detail}")


class AsyncChainedRateProvider:
    """Async ordered provider failover."""

    __slots__ = ("_providers",)

    def __init__(self, *providers: AsyncExchangeRateProvider) -> None:
        if not providers:
            raise ValueError("at least one exchange-rate provider is required")
        self._providers = providers

    async def get_rate(self, base: CurrencyCode, quote: CurrencyCode) -> ExchangeRate:
        """Return the first successful async quote while preserving failure semantics."""
        failures: list[str] = []
        operational_failure = False
        for provider in self._providers:
            try:
                return await provider.get_rate(base, quote)
            except RateUnavailableError as exc:
                failures.append(f"{type(provider).__name__}: unavailable: {exc}")
            except ProviderError as exc:
                operational_failure = True
                failures.append(f"{type(provider).__name__}: failed: {exc}")

        detail = f"failures: {'; '.join(failures)}"
        if operational_failure:
            raise ProviderError(f"no configured async provider could safely price {base}/{quote}; {detail}")
        raise RateUnavailableError(f"no configured async provider could supply {base}/{quote}; {detail}")


class CachedRateProvider:
    """Bounded process-local LRU/TTL cache with per-key single-flight protection.

    ``stale_if_error_seconds`` is disabled by default. When explicitly enabled, an
    expired cached quote may be returned after a *provider failure* for at most that
    many seconds beyond cache expiry. Business freshness should still be enforced by
    ``RatePolicy`` because cache lifetime and quote validity are different concepts.
    """

    __slots__ = (
        "_cache",
        "_inflight",
        "_inner",
        "_lock",
        "_maxsize",
        "_stale_if_error",
        "_ttl",
    )

    def __init__(
        self,
        inner: ExchangeRateProvider,
        *,
        ttl_seconds: float = 60,
        maxsize: int = 256,
        stale_if_error_seconds: float = 0,
    ) -> None:
        if ttl_seconds <= 0 or maxsize <= 0:
            raise ValueError("ttl_seconds and maxsize must be positive")
        if stale_if_error_seconds < 0:
            raise ValueError("stale_if_error_seconds cannot be negative")
        self._inner = inner
        self._ttl = ttl_seconds
        self._maxsize = maxsize
        self._stale_if_error = stale_if_error_seconds
        self._cache: OrderedDict[tuple[CurrencyCode, CurrencyCode], tuple[float, ExchangeRate]] = (
            OrderedDict()
        )
        self._lock = RLock()
        self._inflight: dict[tuple[CurrencyCode, CurrencyCode], Future[ExchangeRate]] = {}

    @property
    def size(self) -> int:
        """Return the number of quote entries currently held by this process-local cache."""
        with self._lock:
            return len(self._cache)

    def clear(self) -> None:
        """Remove all cached quotes without affecting in-flight provider calls."""
        with self._lock:
            self._cache.clear()

    def get_rate(self, base: CurrencyCode, quote: CurrencyCode) -> ExchangeRate:
        """Return a cached quote or single-flight one provider refresh for this pair."""
        key = (base, quote)
        now = monotonic()
        owner = False
        stale: tuple[float, ExchangeRate] | None = None

        with self._lock:
            cached = self._cache.get(key)
            if cached is not None:
                if cached[0] > now:
                    self._cache.move_to_end(key)
                    return cached[1]
                stale = cached

            future = self._inflight.get(key)
            if future is None:
                future = Future()
                self._inflight[key] = future
                owner = True

        if not owner:
            return future.result()

        try:
            rate = self._inner.get_rate(base, quote)
        except ProviderError as exc:
            failure_now = monotonic()
            if stale is not None and failure_now - stale[0] <= self._stale_if_error:
                stale_rate = _mark_stale_fallback(stale[1])
                future.set_result(stale_rate)
                return stale_rate
            future.set_exception(exc)
            raise
        except BaseException as exc:
            # The owner must publish *every* terminal outcome to synchronous waiters;
            # otherwise KeyboardInterrupt/SystemExit in the owner could strand callers
            # forever on Future.result(). The exception is immediately re-raised.
            future.set_exception(exc)
            raise
        else:
            with self._lock:
                self._cache[key] = (monotonic() + self._ttl, rate)
                self._cache.move_to_end(key)
                while len(self._cache) > self._maxsize:
                    self._cache.popitem(last=False)
            future.set_result(rate)
            return rate
        finally:
            with self._lock:
                self._inflight.pop(key, None)


class AsyncCachedRateProvider:
    """Async bounded process-local LRU/TTL cache with single-flight coalescing."""

    __slots__ = (
        "_cache",
        "_inflight",
        "_inner",
        "_lock",
        "_maxsize",
        "_stale_if_error",
        "_ttl",
    )

    def __init__(
        self,
        inner: AsyncExchangeRateProvider,
        *,
        ttl_seconds: float = 60,
        maxsize: int = 256,
        stale_if_error_seconds: float = 0,
    ) -> None:
        if ttl_seconds <= 0 or maxsize <= 0:
            raise ValueError("ttl_seconds and maxsize must be positive")
        if stale_if_error_seconds < 0:
            raise ValueError("stale_if_error_seconds cannot be negative")
        self._inner = inner
        self._ttl = ttl_seconds
        self._maxsize = maxsize
        self._stale_if_error = stale_if_error_seconds
        self._cache: OrderedDict[tuple[CurrencyCode, CurrencyCode], tuple[float, ExchangeRate]] = (
            OrderedDict()
        )
        self._lock = asyncio.Lock()
        self._inflight: dict[tuple[CurrencyCode, CurrencyCode], asyncio.Future[ExchangeRate]] = {}

    @property
    def size(self) -> int:
        """Return the current process-local async cache entry count."""
        return len(self._cache)

    async def clear(self) -> None:
        """Remove all cached async quotes without cancelling in-flight calls."""
        async with self._lock:
            self._cache.clear()

    async def get_rate(self, base: CurrencyCode, quote: CurrencyCode) -> ExchangeRate:
        """Return a cached quote or single-flight one asynchronous provider refresh."""
        key = (base, quote)
        owner = False
        stale: tuple[float, ExchangeRate] | None = None
        now = monotonic()

        async with self._lock:
            cached = self._cache.get(key)
            if cached is not None:
                if cached[0] > now:
                    self._cache.move_to_end(key)
                    return cached[1]
                stale = cached

            future = self._inflight.get(key)
            if future is None:
                future = asyncio.get_running_loop().create_future()
                future.add_done_callback(_consume_async_future_result)
                self._inflight[key] = future
                owner = True

        if not owner:
            return await asyncio.shield(future)

        try:
            rate = await self._inner.get_rate(base, quote)
        except asyncio.CancelledError:
            if not future.done():
                future.cancel()
            raise
        except ProviderError as exc:
            failure_now = monotonic()
            if stale is not None and failure_now - stale[0] <= self._stale_if_error:
                stale_rate = _mark_stale_fallback(stale[1])
                if not future.done():
                    future.set_result(stale_rate)
                return stale_rate
            if not future.done():
                future.set_exception(exc)
            raise
        except BaseException as exc:
            # Single-flight waiters must be completed even for process-level terminal
            # exceptions. CancelledError is handled separately above and is never
            # converted into ProviderError.
            if not future.done():
                future.set_exception(exc)
            raise
        else:
            async with self._lock:
                self._cache[key] = (monotonic() + self._ttl, rate)
                self._cache.move_to_end(key)
                while len(self._cache) > self._maxsize:
                    self._cache.popitem(last=False)
            if not future.done():
                future.set_result(rate)
            return rate
        finally:
            async with self._lock:
                self._inflight.pop(key, None)


class MoneyConverter:
    """Convert Money explicitly through a synchronous provider."""

    __slots__ = (
        "_policy",
        "_provider",
        "_registry",
        "_rounding",
    )

    def __init__(
        self,
        provider: ExchangeRateProvider,
        *,
        registry: CurrencyRegistry = DEFAULT_REGISTRY,
        rounding: RoundingPolicy = DEFAULT_ROUNDING,
        policy: RatePolicy | None = None,
    ) -> None:
        if not isinstance(provider, ExchangeRateProvider):
            raise TypeError(
                "provider must implement get_rate(base: CurrencyCode, quote: CurrencyCode) "
                "-> ExchangeRate; see docs/PROVIDERS.md"
            )
        self._provider = provider
        self._registry = registry
        self._rounding = rounding
        self._policy = policy

    def convert(self, money: Money, to_currency: str | Currency) -> Money:
        """Convert and return only the target Money value."""
        return self.convert_with_rate(money, to_currency).target

    def convert_with_rate(
        self,
        money: Money,
        to_currency: str | Currency,
    ) -> ConversionResult:
        """Convert while retaining the exact quote used for audit/replay purposes."""
        target = to_currency if isinstance(to_currency, Currency) else self._registry.get(to_currency)
        if money.currency == target:
            identity = ExchangeRate(
                money.currency.code,
                target.code,
                Decimal("1"),
                RateProvenance("identity"),
                RateKind.EXECUTABLE,
            )
            return ConversionResult(money, money, identity)
        if money.currency.code == target.code and money.currency != target:
            raise InvalidRateError(
                "source and target use the same currency code with incompatible metadata; "
                "rebind to one Currency definition explicitly before conversion"
            )

        rate = self._provider.get_rate(money.currency.code, target.code)
        _validate_pair(rate, money.currency.code, target.code)
        if self._policy is not None:
            self._policy.validate(rate)
        converted = _apply_rate(money, target, rate, self._rounding)
        return ConversionResult(money, converted, rate)

    def replay(self, money: Money, rate: ExchangeRate) -> ConversionResult:
        """Replay a conversion with a previously stored quote and no provider I/O.

        The quote's base must match ``money.currency.code``. Any configured
        ``RatePolicy`` is re-applied, which lets applications intentionally choose
        whether an old stored quote is acceptable in the current context.
        """
        if rate.base != money.currency.code:
            raise InvalidRateError(
                f"stored rate base {rate.base} does not match money currency {money.currency.code}"
            )
        target = self._registry.get(rate.quote)
        _validate_pair(rate, money.currency.code, target.code)
        if self._policy is not None:
            self._policy.validate(rate)
        converted = _apply_rate(money, target, rate, self._rounding)
        return ConversionResult(money, converted, rate)


class AsyncMoneyConverter:
    """Async Money converter with the same semantics as :class:`MoneyConverter`."""

    __slots__ = (
        "_policy",
        "_provider",
        "_registry",
        "_rounding",
    )

    def __init__(
        self,
        provider: AsyncExchangeRateProvider,
        *,
        registry: CurrencyRegistry = DEFAULT_REGISTRY,
        rounding: RoundingPolicy = DEFAULT_ROUNDING,
        policy: RatePolicy | None = None,
    ) -> None:
        if not isinstance(provider, AsyncExchangeRateProvider):
            raise TypeError(
                "provider must implement async get_rate(base: CurrencyCode, quote: CurrencyCode) "
                "-> ExchangeRate; see docs/PROVIDERS.md"
            )
        self._provider = provider
        self._registry = registry
        self._rounding = rounding
        self._policy = policy

    async def convert(self, money: Money, to_currency: str | Currency) -> Money:
        """Convert and return only the target Money value."""
        return (await self.convert_with_rate(money, to_currency)).target

    async def convert_with_rate(
        self,
        money: Money,
        to_currency: str | Currency,
    ) -> ConversionResult:
        """Convert asynchronously while retaining the exact quote used."""
        target = to_currency if isinstance(to_currency, Currency) else self._registry.get(to_currency)
        if money.currency == target:
            identity = ExchangeRate(
                money.currency.code,
                target.code,
                Decimal("1"),
                RateProvenance("identity"),
                RateKind.EXECUTABLE,
            )
            return ConversionResult(money, money, identity)
        if money.currency.code == target.code and money.currency != target:
            raise InvalidRateError(
                "source and target use the same currency code with incompatible metadata; "
                "rebind to one Currency definition explicitly before conversion"
            )

        rate = await self._provider.get_rate(money.currency.code, target.code)
        _validate_pair(rate, money.currency.code, target.code)
        if self._policy is not None:
            self._policy.validate(rate)
        converted = _apply_rate(money, target, rate, self._rounding)
        return ConversionResult(money, converted, rate)

    def replay(self, money: Money, rate: ExchangeRate) -> ConversionResult:
        """Replay a stored quote without performing asynchronous provider I/O."""
        if rate.base != money.currency.code:
            raise InvalidRateError(
                f"stored rate base {rate.base} does not match money currency {money.currency.code}"
            )
        target = self._registry.get(rate.quote)
        _validate_pair(rate, money.currency.code, target.code)
        if self._policy is not None:
            self._policy.validate(rate)
        converted = _apply_rate(money, target, rate, self._rounding)
        return ConversionResult(money, converted, rate)


def _consume_async_future_result(future: asyncio.Future[ExchangeRate]) -> None:
    """Prevent unobserved-exception warnings for owner-only single-flight calls."""
    if future.cancelled():
        return
    try:
        future.exception()
    except asyncio.CancelledError:
        return


def _mark_stale_fallback(rate: ExchangeRate) -> ExchangeRate:
    provenance = rate.provenance
    return ExchangeRate(
        rate.base,
        rate.quote,
        rate.value,
        RateProvenance(
            provider=provenance.provider,
            source_uri=provenance.source_uri,
            as_of=provenance.as_of,
            fetched_at=provenance.fetched_at,
            request_id=provenance.request_id,
            metadata={**provenance.metadata, "cache_status": "stale_fallback"},
        ),
        rate.kind,
    )


def _reciprocal(value: Decimal) -> Decimal:
    digits = len(value.as_tuple().digits)
    with localcontext() as context:
        context.prec = max(34, digits * 2 + 8)
        return Decimal("1") / value


def _triangulate(
    base: CurrencyCode,
    quote: CurrencyCode,
    pivot: CurrencyCode,
    left: ExchangeRate,
    right: ExchangeRate,
    *,
    max_leg_skew: timedelta | None = None,
) -> ExchangeRate:
    left_as_of = left.provenance.as_of
    right_as_of = right.provenance.as_of
    if (
        max_leg_skew is not None
        and left_as_of is not None
        and right_as_of is not None
        and abs(left_as_of - right_as_of) > max_leg_skew
    ):
        raise RateUnavailableError(
            f"triangulation via {pivot} rejected because leg timestamp skew "
            f"{abs(left_as_of - right_as_of)} exceeds {max_leg_skew}"
        )
    as_of_values = [value for value in (left_as_of, right_as_of) if value is not None]
    as_of = min(as_of_values) if as_of_values else None
    digits = len(left.value.as_tuple().digits) + len(right.value.as_tuple().digits)
    with localcontext() as context:
        context.prec = max(34, digits + 8)
        value = left.value * right.value
    return ExchangeRate(
        base,
        quote,
        value,
        RateProvenance(
            provider=f"triangulated:{left.source}+{right.source}",
            as_of=as_of,
            fetched_at=max(left.provenance.fetched_at, right.provenance.fetched_at),
            metadata={
                "derived": "triangulation",
                "path": f"{base}/{pivot}/{quote}",
                "left_as_of": left_as_of.isoformat() if left_as_of else "",
                "right_as_of": right_as_of.isoformat() if right_as_of else "",
            },
        ),
        RateKind.DERIVED,
        DerivationKind.TRIANGULATION,
    )


def _validate_pair(
    rate: ExchangeRate,
    expected_base: CurrencyCode,
    expected_quote: CurrencyCode,
) -> None:
    if rate.base != expected_base or rate.quote != expected_quote:
        raise InvalidRateError(
            f"provider returned {rate.base}/{rate.quote} while {expected_base}/{expected_quote} was requested"
        )


def _apply_rate(
    money: Money,
    target: Currency,
    rate: ExchangeRate,
    rounding: RoundingPolicy,
) -> Money:
    try:
        amount_digits = integer_decimal_digits(money.minor)
        rate_digits = len(rate.value.as_tuple().digits)
        precision = max(
            34,
            amount_digits + rate_digits + target.exponent + money.currency.exponent + 8,
        )
        with localcontext() as context:
            context.prec = precision
            target_minor = (
                Decimal(money.minor) * rate.value * Decimal(target.factor) / Decimal(money.currency.factor)
            )
    except (InvalidOperation, ArithmeticError) as exc:
        raise InvalidRateError(f"rate {rate.value!r} could not convert {rate.base}/{rate.quote}") from exc
    return Money(MinorUnits(rounding.quantize_minor(target_minor)), target)
