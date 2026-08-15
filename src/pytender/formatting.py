from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from .money import Money


@runtime_checkable
class MoneyFormatter(Protocol):
    """Structural contract for monetary display formatting."""

    def format(self, money: Money) -> str: ...


@dataclass(frozen=True, slots=True)
class SimpleMoneyFormatter:
    """Dependency-free deterministic formatter.

    This formatter does not consult locale state. For CLDR-backed localization,
    install ``PyTender[babel]`` and use
    :class:`pytender.adapters.babel.BabelMoneyFormatter`.
    """

    decimal_separator: str = "."
    thousands_separator: str = ","
    symbol_first: bool = True
    symbol_space: bool = False
    code_when_symbol_missing: bool = True
    group_thousands: bool = True

    def format(self, money: Money) -> str:
        """Render ``money`` without changing its value or using ambient Decimal precision."""
        negative = money.minor < 0
        absolute = money.major.copy_abs()
        quantized = f"{absolute:.{money.currency.exponent}f}"
        integer, dot, fraction = quantized.partition(".")
        if self.group_thousands:
            integer = _group_digits(integer, self.thousands_separator)

        number = integer
        if dot:
            number += self.decimal_separator + fraction

        symbol = money.currency.symbol
        if symbol:
            space = " " if self.symbol_space else ""
            rendered = (
                f"{symbol}{space}{number}"
                if self.symbol_first
                else f"{number}{space}{symbol}"
            )
        elif self.code_when_symbol_missing:
            rendered = f"{number} {money.currency.code}"
        else:
            rendered = number
        return f"-{rendered}" if negative else rendered


def _group_digits(value: str, separator: str) -> str:
    if not value:
        return value
    first_group = len(value) % 3 or 3
    groups = [value[:first_group]]
    groups.extend(value[index : index + 3] for index in range(first_group, len(value), 3))
    return separator.join(groups)


DEFAULT_FORMATTER = SimpleMoneyFormatter()
