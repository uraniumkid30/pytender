from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import TYPE_CHECKING, Callable, TypeAlias

from .exceptions import RatePolicyError, StaleRateError

if TYPE_CHECKING:
    from .fx import ExchangeRate

RateValidator: TypeAlias = Callable[["ExchangeRate"], None]


class RateKind(str, Enum):
    """Business meaning attached to an FX quote.

    REFERENCE
        A market/reference quote that is useful for valuation or reporting but is
        not necessarily executable.
    INDICATIVE
        A quote intended to guide a user but not guarantee execution.
    EXECUTABLE
        A provider asserts that the quote may be used for an executable/commercial
        transaction subject to that provider's own terms.
    DERIVED
        A quote mathematically derived from one or more other quotes, for example
        by inversion or triangulation.
    """

    REFERENCE = "reference"
    INDICATIVE = "indicative"
    EXECUTABLE = "executable"
    DERIVED = "derived"


class DerivationKind(str, Enum):
    """How a derived FX rate was produced.

    ``NONE`` is required for non-derived rates. ``CUSTOM`` lets provider authors
    represent a domain-specific derivation without relying on untyped metadata keys.
    """

    NONE = "none"
    INVERSE = "inverse"
    TRIANGULATION = "triangulation"
    CUSTOM = "custom"


class MissingTimestampPolicy(str, Enum):
    """How a rate policy handles a quote with no provider ``as_of`` timestamp."""

    REJECT = "reject"
    USE_FETCHED_AT = "use_fetched_at"


@dataclass(frozen=True, slots=True)
class RatePolicy:
    """Validate whether an exchange rate is acceptable for a business context.

    A cache TTL controls *how long PyTender keeps an object in memory*. ``max_age``
    controls *whether the quote is still valid for the caller's business purpose*.
    They deliberately solve different problems.

    ``allowed_sources`` is empty by default, which means any provider is accepted.
    ``allowed_kinds`` defaults to reference, indicative and executable quotes while
    rejecting derived rates unless the application opts into them explicitly.
    """

    max_age: timedelta | None = None
    allowed_sources: frozenset[str] = frozenset()
    allowed_kinds: frozenset[RateKind] = frozenset(
        {RateKind.REFERENCE, RateKind.INDICATIVE, RateKind.EXECUTABLE}
    )
    missing_timestamp: MissingTimestampPolicy = MissingTimestampPolicy.REJECT
    allow_inverse: bool = False
    allow_triangulation: bool = False
    max_future_skew: timedelta = timedelta(seconds=5)
    validator: RateValidator | None = None

    def __post_init__(self) -> None:
        if self.max_age is not None and self.max_age < timedelta(0):
            raise ValueError("max_age cannot be negative")
        if self.max_future_skew < timedelta(0):
            raise ValueError("max_future_skew cannot be negative")
        if not self.allowed_kinds:
            raise ValueError("allowed_kinds must contain at least one RateKind")

    def validate(self, rate: "ExchangeRate", *, now: datetime | None = None) -> None:
        """Raise a policy-specific error when ``rate`` is unsafe for this context."""
        # Local import avoids a runtime import cycle between fx.py and policy.py.
        from .fx import ExchangeRate

        if not isinstance(rate, ExchangeRate):
            raise TypeError("rate must be an ExchangeRate")

        if rate.derivation is DerivationKind.INVERSE and not self.allow_inverse:
            raise RatePolicyError("inverse-derived rates are not allowed by this policy")
        if rate.derivation is DerivationKind.TRIANGULATION and not self.allow_triangulation:
            raise RatePolicyError("triangulated rates are not allowed by this policy")

        if rate.kind not in self.allowed_kinds:
            raise RatePolicyError(
                f"rate kind {rate.kind.value!r} is not allowed by this policy; "
                f"allowed={sorted(kind.value for kind in self.allowed_kinds)}"
            )

        if self.allowed_sources and rate.source not in self.allowed_sources:
            raise RatePolicyError(
                f"rate source {rate.source!r} is not allowed by this policy; "
                f"allowed={sorted(self.allowed_sources)}"
            )

        reference_time = rate.provenance.as_of
        current = now or datetime.now(timezone.utc)
        if current.tzinfo is None:
            raise ValueError("now must be timezone-aware")

        if self.max_age is None:
            if reference_time is not None:
                self._validate_future_timestamp(reference_time, current)
            if self.validator is not None:
                self.validator(rate)
            return

        if reference_time is None:
            if self.missing_timestamp is MissingTimestampPolicy.REJECT:
                raise RatePolicyError(
                    "rate has no as_of timestamp, but this policy requires freshness; "
                    "configure MissingTimestampPolicy.USE_FETCHED_AT only when that "
                    "semantic is acceptable"
                )
            reference_time = rate.provenance.fetched_at

        self._validate_future_timestamp(reference_time, current)
        age = current - reference_time
        if age > self.max_age:
            raise StaleRateError(
                f"rate {rate.base}/{rate.quote} from {rate.source!r} is stale: "
                f"age={age}, maximum={self.max_age}, as_of={reference_time.isoformat()}"
            )

        if self.validator is not None:
            self.validator(rate)

    def _validate_future_timestamp(self, reference_time: datetime, current: datetime) -> None:
        if reference_time - current > self.max_future_skew:
            raise RatePolicyError(
                f"rate timestamp {reference_time.isoformat()} is unexpectedly in the future "
                f"relative to {current.isoformat()}"
            )

