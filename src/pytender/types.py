from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import StrEnum
from typing import NewType, TypeAlias

CurrencyCode = NewType("CurrencyCode", str)
MinorUnits = NewType("MinorUnits", int)
DecimalLike: TypeAlias = Decimal | int | str


class CurrencyStatus(StrEnum):
    """Lifecycle state of a currency definition."""

    CURRENT = "current"
    HISTORICAL = "historical"
    CUSTOM = "custom"


@dataclass(frozen=True, slots=True)
class Currency:
    """Metadata required to interpret integer minor units.

    ``cash_increment`` is expressed in minor units and is only applied when callers
    explicitly request cash rounding. ``valid_from``/``valid_to`` are metadata only;
    PyTender never silently rejects a historical amount because historical ledgers must
    remain readable forever.
    """

    code: CurrencyCode
    exponent: int
    symbol: str = ""
    name: str = ""
    numeric_code: str = ""
    cash_increment: int = 1
    status: CurrencyStatus = CurrencyStatus.CURRENT
    valid_from: date | None = None
    valid_to: date | None = None
    replacement_code: CurrencyCode | None = None

    def __post_init__(self) -> None:
        code = str(self.code).upper()
        if len(code) != 3 or not code.isalpha():
            raise ValueError("currency code must be exactly three alphabetic characters")
        if (
            isinstance(self.exponent, bool)
            or not isinstance(self.exponent, int)
            or not 0 <= self.exponent <= 9
        ):
            raise ValueError("currency exponent must be an integer between 0 and 9")
        if self.numeric_code and (len(self.numeric_code) != 3 or not self.numeric_code.isdigit()):
            raise ValueError("numeric_code must be an empty string or a three-digit ISO code")
        if (
            isinstance(self.cash_increment, bool)
            or not isinstance(self.cash_increment, int)
            or self.cash_increment <= 0
        ):
            raise ValueError("cash_increment must be a positive number of minor units")
        if self.valid_from is not None and self.valid_to is not None and self.valid_from > self.valid_to:
            raise ValueError("valid_from cannot be later than valid_to")
        replacement = self.replacement_code
        if replacement is not None:
            normalized_replacement = str(replacement).upper()
            if len(normalized_replacement) != 3 or not normalized_replacement.isalpha():
                raise ValueError("replacement_code must be a three-letter currency code")
            object.__setattr__(self, "replacement_code", CurrencyCode(normalized_replacement))
        object.__setattr__(self, "code", CurrencyCode(code))

    @property
    def factor(self) -> int:
        """Return the number of minor units in one major currency unit."""
        return int(10**self.exponent)

    def is_valid_on(self, when: date) -> bool:
        """Return whether metadata says the currency was valid on ``when``."""
        if self.valid_from is not None and when < self.valid_from:
            return False
        return self.valid_to is None or when <= self.valid_to
