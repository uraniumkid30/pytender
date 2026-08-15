from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, localcontext
from typing import TYPE_CHECKING, Self

from ._numeric import integer_decimal_digits
from .exceptions import AllocationError, CurrencyMismatchError, InvalidAmountError
from .registry import DEFAULT_REGISTRY, CurrencyRegistry
from .rounding import DEFAULT_ROUNDING, RoundingPolicy, round_to_increment
from .types import Currency, DecimalLike, MinorUnits

if TYPE_CHECKING:
    from .formatting import MoneyFormatter


def to_decimal(value: DecimalLike) -> Decimal:
    """Normalize safe decimal-like input while explicitly rejecting bool/float."""
    if isinstance(value, (bool, float)):
        raise InvalidAmountError(
            "float/bool input is forbidden for money; use str, int, or Decimal"
        )
    try:
        if isinstance(value, Decimal):
            result = value
        elif isinstance(value, int):
            result = Decimal(value)
        else:
            result = Decimal(value)
    except (InvalidOperation, ValueError) as exc:
        raise InvalidAmountError(f"invalid decimal amount: {value!r}") from exc
    if not result.is_finite():
        raise InvalidAmountError("money amounts must be finite")
    return result


@dataclass(frozen=True, slots=True)
class Money:
    """Immutable monetary value stored canonically as integer minor units.

    ``minor`` is always an integer in the currency's smallest configured unit.
    Currency conversion is never implicit; cross-currency operations raise
    :class:`CurrencyMismatchError`.
    """

    minor: MinorUnits
    currency: Currency

    def __post_init__(self) -> None:
        if isinstance(self.minor, bool) or not isinstance(self.minor, int):
            raise TypeError("minor must be an int representing currency minor units")
        object.__setattr__(self, "minor", MinorUnits(int(self.minor)))

    @classmethod
    def from_minor(
        cls,
        amount: int,
        currency: str | Currency,
        *,
        registry: CurrencyRegistry = DEFAULT_REGISTRY,
    ) -> Self:
        """Create money from exact integer minor units.

        No rounding occurs. Negative and zero values are valid. ``bool`` is rejected
        even though it is an ``int`` subclass in Python.

        Raises:
            TypeError: if ``amount`` is not an integer minor-unit value.
            UnknownCurrencyError: if a string currency is absent from ``registry``.
        """
        if isinstance(amount, bool) or not isinstance(amount, int):
            raise TypeError("minor amount must be an int")
        resolved = currency if isinstance(currency, Currency) else registry.get(currency)
        return cls(MinorUnits(amount), resolved)

    @classmethod
    def from_major(
        cls,
        amount: DecimalLike,
        currency: str | Currency,
        *,
        registry: CurrencyRegistry = DEFAULT_REGISTRY,
        rounding: RoundingPolicy = DEFAULT_ROUNDING,
    ) -> Self:
        """Create money from major units using an explicit rounding policy.

        ``str``, ``int`` and ``Decimal`` inputs are accepted; ``float`` and non-finite
        Decimal values are rejected. The amount is multiplied by the currency factor
        and rounded exactly once to integer minor units using ``rounding``.
        """
        resolved = currency if isinstance(currency, Currency) else registry.get(currency)
        decimal_amount = to_decimal(amount)
        amount_digits = len(decimal_amount.as_tuple().digits)
        with localcontext() as context:
            context.prec = max(28, amount_digits + resolved.exponent + 4)
            minor_decimal = decimal_amount * Decimal(resolved.factor)
        return cls(MinorUnits(rounding.quantize_minor(minor_decimal)), resolved)

    @property
    def major(self) -> Decimal:
        """Return the exact major-unit Decimal independent of ambient Decimal context."""
        digits = integer_decimal_digits(self.minor)
        with localcontext() as context:
            context.prec = max(28, digits + self.currency.exponent + 2)
            return Decimal(self.minor) / Decimal(self.currency.factor)

    def _require_same(self, other: "Money") -> None:
        if self.currency != other.currency:
            raise CurrencyMismatchError(
                "cannot operate on incompatible currency definitions: "
                f"{self.currency!r} != {other.currency!r}. Use the same CurrencyRegistry "
                "definition or convert/rebind explicitly."
            )

    def __add__(self, other: "Money") -> "Money":
        if not isinstance(other, Money):
            return NotImplemented
        self._require_same(other)
        return Money(MinorUnits(self.minor + other.minor), self.currency)

    def __sub__(self, other: "Money") -> "Money":
        if not isinstance(other, Money):
            return NotImplemented
        self._require_same(other)
        return Money(MinorUnits(self.minor - other.minor), self.currency)

    def __neg__(self) -> "Money":
        return Money(MinorUnits(-self.minor), self.currency)

    def __abs__(self) -> "Money":
        return Money(MinorUnits(abs(self.minor)), self.currency)

    def __bool__(self) -> bool:
        return self.minor != 0

    def __mul__(self, multiplier: int) -> "Money":
        if isinstance(multiplier, bool) or not isinstance(multiplier, int):
            raise TypeError(
                "Money multiplication accepts integers only; use multiply_rate() "
                "for Decimal rates"
            )
        return Money(MinorUnits(self.minor * multiplier), self.currency)

    def __rmul__(self, multiplier: int) -> "Money":
        return self * multiplier

    def multiply_rate(
        self,
        rate: DecimalLike,
        *,
        rounding: RoundingPolicy = DEFAULT_ROUNDING,
    ) -> "Money":
        """Multiply by a scalar Decimal rate and round once to minor units.

        Negative and zero rates are allowed because this is generic scalar arithmetic,
        not FX. ``float`` and non-finite rates are rejected by ``to_decimal``.
        """
        decimal_rate = to_decimal(rate)
        amount_digits = integer_decimal_digits(self.minor)
        rate_digits = len(decimal_rate.as_tuple().digits)
        with localcontext() as context:
            context.prec = max(28, amount_digits + rate_digits + 4)
            value = Decimal(self.minor) * decimal_rate
        return Money(MinorUnits(rounding.quantize_minor(value)), self.currency)

    def ratio(self, other: "Money") -> Decimal:
        """Return the exact Decimal ratio between compatible monetary values.

        Raises ``ZeroDivisionError`` when ``other`` is zero and
        ``CurrencyMismatchError`` when currency definitions differ.
        """
        self._require_same(other)
        if other.minor == 0:
            raise ZeroDivisionError("cannot compute a money ratio with a zero denominator")

        numerator_digits = integer_decimal_digits(self.minor)
        denominator_digits = integer_decimal_digits(other.minor)
        with localcontext() as context:
            context.prec = max(28, numerator_digits + denominator_digits + 8)
            return Decimal(self.minor) / Decimal(other.minor)

    def cash_round(
        self,
        *,
        increment: int | None = None,
        rounding: RoundingPolicy = DEFAULT_ROUNDING,
    ) -> "Money":
        """Return a new value rounded to a cash denomination increment.

        Cash rounding is opt-in and never changes the original value. The default
        increment comes from ``Currency.cash_increment``; callers may override it for
        payment-channel/jurisdiction-specific rules.
        """
        step = self.currency.cash_increment if increment is None else increment
        rounded = round_to_increment(self.minor, step, rounding=rounding)
        return Money(MinorUnits(rounded), self.currency)

    def split(self, parts: int) -> tuple["Money", ...]:
        """Split into ``parts`` while preserving every minor unit exactly.

        Remainders are assigned deterministically to the earliest parts. Negative
        amounts preserve sign and total. ``parts`` must be a positive integer.
        """
        if isinstance(parts, bool) or not isinstance(parts, int) or parts <= 0:
            raise AllocationError("parts must be a positive integer")

        quotient, remainder = divmod(abs(self.minor), parts)
        sign = -1 if self.minor < 0 else 1
        values = [quotient * sign for _ in range(parts)]
        for index in range(remainder):
            values[index] += sign
        return tuple(Money(MinorUnits(value), self.currency) for value in values)

    def allocate(self, ratios: tuple[int, ...] | list[int]) -> tuple["Money", ...]:
        """Allocate money by non-negative integer ratios without losing minor units.

        A ratio vector of all zeros returns zero for every allocation. Negative ratios,
        booleans and non-integers raise ``AllocationError``. Remainders are distributed
        deterministically from the first allocation onward.
        """
        if not ratios:
            raise AllocationError("at least one ratio is required")
        if any(isinstance(ratio, bool) or not isinstance(ratio, int) for ratio in ratios):
            raise AllocationError("all ratios must be integers")
        if any(ratio < 0 for ratio in ratios):
            raise AllocationError("negative ratios are not allowed")

        total_ratio = sum(ratios)
        if total_ratio == 0:
            return tuple(Money(MinorUnits(0), self.currency) for _ in ratios)

        sign = -1 if self.minor < 0 else 1
        absolute = abs(self.minor)
        shares = [(absolute * ratio) // total_ratio for ratio in ratios]
        leftover = absolute - sum(shares)
        for index in range(leftover):
            shares[index % len(shares)] += 1
        return tuple(Money(MinorUnits(sign * share), self.currency) for share in shares)

    def __lt__(self, other: "Money") -> bool:
        if not isinstance(other, Money):
            return NotImplemented
        self._require_same(other)
        return self.minor < other.minor

    def __le__(self, other: "Money") -> bool:
        if not isinstance(other, Money):
            return NotImplemented
        self._require_same(other)
        return self.minor <= other.minor

    def __gt__(self, other: "Money") -> bool:
        if not isinstance(other, Money):
            return NotImplemented
        self._require_same(other)
        return self.minor > other.minor

    def __ge__(self, other: "Money") -> bool:
        if not isinstance(other, Money):
            return NotImplemented
        self._require_same(other)
        return self.minor >= other.minor

    def format(self, formatter: "MoneyFormatter | None" = None) -> str:
        """Format this value using an explicit formatter or the deterministic default."""
        if formatter is None:
            from .formatting import DEFAULT_FORMATTER

            formatter = DEFAULT_FORMATTER
        return formatter.format(self)

    def __str__(self) -> str:
        return self.format()
