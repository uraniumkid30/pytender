from __future__ import annotations

import asyncio
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from time import perf_counter
from typing import Protocol, runtime_checkable

from .fx import AsyncExchangeRateProvider, ExchangeRate, ExchangeRateProvider
from .types import CurrencyCode


class HookFailureMode(StrEnum):
    """Control whether audit/observability hook failures affect FX operations.

    ``FAIL_OPEN`` protects the pricing path: hook failures are ignored.
    ``FAIL_CLOSED`` protects the hook guarantee: hook failures are propagated.
    Metrics/telemetry normally use ``FAIL_OPEN``; compliance-grade audit storage may
    deliberately use ``FAIL_CLOSED``.
    """

    FAIL_OPEN = "fail_open"
    FAIL_CLOSED = "fail_closed"


@dataclass(frozen=True, slots=True)
class RateAuditRecord:
    """One successful FX lookup suitable for application audit storage."""

    rate: ExchangeRate
    observed_at: datetime


@dataclass(frozen=True, slots=True)
class ProviderEvent:
    """Operational event emitted for an observed provider call."""

    provider_type: str
    base: CurrencyCode
    quote: CurrencyCode
    duration_seconds: float
    succeeded: bool
    error_type: str = ""


@runtime_checkable
class RateAuditSink(Protocol):
    """Application-owned sink for successful quote audit records."""

    def record(self, record: RateAuditRecord) -> None: ...


@runtime_checkable
class AsyncRateAuditSink(Protocol):
    """Async application-owned sink for successful quote audit records."""

    async def record(self, record: RateAuditRecord) -> None: ...


@runtime_checkable
class ProviderObserver(Protocol):
    """Application-owned metrics/monitoring sink for provider call outcomes."""

    def observe(self, event: ProviderEvent) -> None: ...


@runtime_checkable
class AsyncProviderObserver(Protocol):
    """Async application-owned metrics/monitoring sink."""

    async def observe(self, event: ProviderEvent) -> None: ...


def _record_audit(
    sink: RateAuditSink,
    record: RateAuditRecord,
    mode: HookFailureMode,
) -> None:
    try:
        sink.record(record)
    except Exception:
        if mode is HookFailureMode.FAIL_CLOSED:
            raise


async def _record_audit_async(
    sink: AsyncRateAuditSink,
    record: RateAuditRecord,
    mode: HookFailureMode,
) -> None:
    try:
        await sink.record(record)
    except asyncio.CancelledError:
        raise
    except Exception:
        if mode is HookFailureMode.FAIL_CLOSED:
            raise


def _observe(
    observer: ProviderObserver,
    event: ProviderEvent,
    mode: HookFailureMode,
) -> None:
    try:
        observer.observe(event)
    except Exception:
        if mode is HookFailureMode.FAIL_CLOSED:
            raise


async def _observe_async(
    observer: AsyncProviderObserver,
    event: ProviderEvent,
    mode: HookFailureMode,
    *,
    preserve_cancellation: bool = False,
) -> None:
    try:
        await observer.observe(event)
    except asyncio.CancelledError:
        if preserve_cancellation or mode is HookFailureMode.FAIL_CLOSED:
            raise
    except Exception:
        if mode is HookFailureMode.FAIL_CLOSED:
            raise


class AuditedRateProvider:
    """Record successful rates, with explicit fail-open/fail-closed semantics.

    Audit defaults to ``FAIL_CLOSED`` to preserve the 1.x behaviour and because an
    application choosing synchronous audit often intends audit persistence to be a
    correctness requirement. Use ``FAIL_OPEN`` only when losing an audit record is an
    accepted business decision.
    """

    __slots__ = (
        "_inner",
        "_mode",
        "_sink",
    )

    def __init__(
        self,
        inner: ExchangeRateProvider,
        sink: RateAuditSink,
        *,
        failure_mode: HookFailureMode = HookFailureMode.FAIL_CLOSED,
    ) -> None:
        self._inner = inner
        self._sink = sink
        self._mode = failure_mode

    def get_rate(self, base: CurrencyCode, quote: CurrencyCode) -> ExchangeRate:
        """Return a rate and write its audit record according to ``failure_mode``."""
        rate = self._inner.get_rate(base, quote)
        record = RateAuditRecord(rate=rate, observed_at=datetime.now(UTC))
        _record_audit(self._sink, record, self._mode)
        return rate


class AsyncAuditedRateProvider:
    """Async audit decorator with explicit hook-failure semantics."""

    __slots__ = (
        "_inner",
        "_mode",
        "_sink",
    )

    def __init__(
        self,
        inner: AsyncExchangeRateProvider,
        sink: AsyncRateAuditSink,
        *,
        failure_mode: HookFailureMode = HookFailureMode.FAIL_CLOSED,
    ) -> None:
        self._inner = inner
        self._sink = sink
        self._mode = failure_mode

    async def get_rate(self, base: CurrencyCode, quote: CurrencyCode) -> ExchangeRate:
        """Return a rate and asynchronously persist its audit record."""
        rate = await self._inner.get_rate(base, quote)
        record = RateAuditRecord(rate=rate, observed_at=datetime.now(UTC))
        await _record_audit_async(self._sink, record, self._mode)
        return rate


class ObservedRateProvider:
    """Emit provider events without making telemetry a hidden pricing dependency.

    Observation defaults to ``FAIL_OPEN``. Set ``FAIL_CLOSED`` only when the
    application deliberately wants telemetry failure to fail the FX operation.
    """

    __slots__ = (
        "_inner",
        "_mode",
        "_observer",
    )

    def __init__(
        self,
        inner: ExchangeRateProvider,
        observer: ProviderObserver,
        *,
        failure_mode: HookFailureMode = HookFailureMode.FAIL_OPEN,
    ) -> None:
        self._inner = inner
        self._observer = observer
        self._mode = failure_mode

    def get_rate(self, base: CurrencyCode, quote: CurrencyCode) -> ExchangeRate:
        """Return the underlying quote and emit a success or failure event."""
        started = perf_counter()
        try:
            rate = self._inner.get_rate(base, quote)
        except Exception as exc:
            event = ProviderEvent(
                provider_type=type(self._inner).__name__,
                base=base,
                quote=quote,
                duration_seconds=perf_counter() - started,
                succeeded=False,
                error_type=type(exc).__name__,
            )
            _observe(self._observer, event, self._mode)
            raise

        event = ProviderEvent(
            provider_type=type(self._inner).__name__,
            base=base,
            quote=quote,
            duration_seconds=perf_counter() - started,
            succeeded=True,
        )
        _observe(self._observer, event, self._mode)
        return rate


class AsyncObservedRateProvider:
    """Async operational-observability decorator with cancellation-safe semantics."""

    __slots__ = (
        "_inner",
        "_mode",
        "_observer",
    )

    def __init__(
        self,
        inner: AsyncExchangeRateProvider,
        observer: AsyncProviderObserver,
        *,
        failure_mode: HookFailureMode = HookFailureMode.FAIL_OPEN,
    ) -> None:
        self._inner = inner
        self._observer = observer
        self._mode = failure_mode

    async def get_rate(self, base: CurrencyCode, quote: CurrencyCode) -> ExchangeRate:
        """Return a quote and emit an event without masking task cancellation."""
        started = perf_counter()
        try:
            rate = await self._inner.get_rate(base, quote)
        except asyncio.CancelledError:
            # Cancellation always wins. Observability is best-effort on this path so a
            # slow or broken hook cannot convert cancellation into another failure.
            event = ProviderEvent(
                provider_type=type(self._inner).__name__,
                base=base,
                quote=quote,
                duration_seconds=perf_counter() - started,
                succeeded=False,
                error_type="CancelledError",
            )
            with suppress(asyncio.CancelledError):
                await asyncio.shield(
                    _observe_async(
                        self._observer,
                        event,
                        HookFailureMode.FAIL_OPEN,
                        preserve_cancellation=False,
                    )
                )
            raise
        except Exception as exc:
            event = ProviderEvent(
                provider_type=type(self._inner).__name__,
                base=base,
                quote=quote,
                duration_seconds=perf_counter() - started,
                succeeded=False,
                error_type=type(exc).__name__,
            )
            await _observe_async(self._observer, event, self._mode)
            raise

        event = ProviderEvent(
            provider_type=type(self._inner).__name__,
            base=base,
            quote=quote,
            duration_seconds=perf_counter() - started,
            succeeded=True,
        )
        await _observe_async(self._observer, event, self._mode)
        return rate
