from __future__ import annotations

from typing import Any, cast

try:
    from sqlalchemy import Numeric, String
    from sqlalchemy.engine.interfaces import Dialect
    from sqlalchemy.types import JSON, TypeDecorator, TypeEngine
except ImportError as exc:  # pragma: no cover
    raise ImportError("SQLAlchemy adapter requires PyTender[sqlalchemy]") from exc

from ..money import Money
from ..serialization import MoneyPayload, from_dict, to_dict


class MoneyType(TypeDecorator[Money]):
    """Portable JSON-backed SQLAlchemy convenience type.

    For ledgers, analytics, range queries and database aggregation, prefer separate
    ``amount_minor`` and ``currency_code`` columns. This adapter optimizes
    application ergonomics rather than relational queryability.
    """

    impl = JSON
    cache_ok = True

    def process_bind_param(self, value: Money | None, dialect: Any) -> dict[str, object] | None:
        """Serialize Money into the SQLAlchemy JSON convenience representation."""
        if value is None:
            return None
        if not isinstance(value, Money):
            raise TypeError("MoneyType only accepts Money or None")
        return dict(to_dict(value))

    def process_result_value(self, value: Any, dialect: Any) -> Money | None:
        """Deserialize the SQLAlchemy JSON convenience representation into Money."""
        if value is None:
            return None
        if not isinstance(value, dict):
            raise TypeError("MoneyType expected a JSON object from the database")
        return from_dict(cast(MoneyPayload, value))


class MinorUnitsType(TypeDecorator[int]):
    """Exact SQLAlchemy storage type for arbitrary-size integer minor units.

    PostgreSQL and MySQL use ``NUMERIC(precision, 0)`` so values remain numeric and
    queryable. SQLite cannot guarantee arbitrary-precision integer semantics for its
    ``NUMERIC`` affinity once values exceed signed 64-bit range; it may convert such
    values through IEEE-754 ``REAL`` and silently lose digits. On SQLite this type
    therefore stores the integer's canonical decimal representation as ``TEXT`` and
    converts it back to ``int`` on read.

    This is intended for a two-column money schema alongside a three-character
    ``currency_code`` column. The default precision of 38 is suitable for common
    relational databases while remaining far above signed 64-bit range.
    """

    impl = Numeric
    cache_ok = True

    def __init__(self, precision: int = 38) -> None:
        if isinstance(precision, bool) or not isinstance(precision, int) or precision < 1:
            raise ValueError("precision must be a positive integer")
        self.precision = precision
        super().__init__()

    def load_dialect_impl(self, dialect: Dialect) -> TypeEngine[Any]:
        """Choose an exact physical representation for the active SQL dialect."""
        if dialect.name == "sqlite":
            return dialect.type_descriptor(String(self.precision + 1))
        return dialect.type_descriptor(Numeric(self.precision, 0, asdecimal=True))

    def process_bind_param(self, value: int | None, dialect: Dialect) -> int | str | None:
        """Validate and encode an integer minor-unit value without precision loss."""
        if value is None:
            return None
        if isinstance(value, bool) or not isinstance(value, int):
            raise TypeError("MinorUnitsType only accepts int or None")

        digits = len(str(abs(value))) if value else 1
        if digits > self.precision:
            raise OverflowError(
                f"minor-unit value has {digits} digits but column precision is {self.precision}"
            )

        if dialect.name == "sqlite":
            return str(value)
        return value

    def process_result_value(self, value: Any, dialect: Dialect) -> int | None:
        """Return the database representation as an exact Python integer."""
        if value is None:
            return None
        try:
            return int(value)
        except (TypeError, ValueError) as exc:
            raise TypeError(f"database returned an invalid minor-unit value: {value!r}") from exc
