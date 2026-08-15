from __future__ import annotations

from decimal import (
    ROUND_DOWN,
    ROUND_HALF_EVEN,
    ROUND_HALF_UP,
    ROUND_UP,
    Decimal,
    localcontext,
)
from typing import Protocol, runtime_checkable

from ._numeric import integer_decimal_digits
from .exceptions import RoundingError


@runtime_checkable
class RoundingPolicy(Protocol):
    """Strategy for reducing Decimal minor-unit values to integer minor units."""

    def quantize_minor(self, value: Decimal) -> int:
        """Round ``value`` to an integer number of minor units."""


class DecimalRounding:
    """Decimal-based rounding using one of Python's explicit Decimal rounding modes."""

    __slots__ = ("mode",)

    def __init__(self, mode: str = ROUND_HALF_EVEN) -> None:
        self.mode = mode

    def quantize_minor(self, value: Decimal) -> int:
        if not isinstance(value, Decimal):
            raise RoundingError("rounding policies require a Decimal value")
        if not value.is_finite():
            raise RoundingError("cannot round a non-finite Decimal")

        digits = len(value.as_tuple().digits)
        with localcontext() as context:
            context.prec = max(28, digits + abs(value.as_tuple().exponent) + 2)
            return int(value.quantize(Decimal("1"), rounding=self.mode))


class HalfEvenRounding(DecimalRounding):
    """Banker's rounding (ties to even), the default PyTender policy."""

    __slots__ = ()

    def __init__(self) -> None:
        super().__init__(ROUND_HALF_EVEN)


class HalfUpRounding(DecimalRounding):
    """Round ties away from zero in the common financial half-up style."""

    __slots__ = ()

    def __init__(self) -> None:
        super().__init__(ROUND_HALF_UP)


class DownRounding(DecimalRounding):
    """Round toward zero."""

    __slots__ = ()

    def __init__(self) -> None:
        super().__init__(ROUND_DOWN)


class UpRounding(DecimalRounding):
    """Round away from zero."""

    __slots__ = ()

    def __init__(self) -> None:
        super().__init__(ROUND_UP)


DEFAULT_ROUNDING = HalfEvenRounding()


def round_to_increment(
    value_minor: int,
    increment: int,
    *,
    rounding: RoundingPolicy = DEFAULT_ROUNDING,
) -> int:
    """Round integer minor units to a positive cash increment without floats."""
    if isinstance(value_minor, bool) or not isinstance(value_minor, int):
        raise RoundingError("value_minor must be an integer")
    if isinstance(increment, bool) or not isinstance(increment, int) or increment <= 0:
        raise RoundingError("cash rounding increment must be a positive integer")

    value_digits = integer_decimal_digits(value_minor)
    increment_digits = integer_decimal_digits(increment)
    with localcontext() as context:
        context.prec = max(28, value_digits + increment_digits + 4)
        units = Decimal(value_minor) / Decimal(increment)
    return rounding.quantize_minor(units) * increment
