from __future__ import annotations

from typing import Any

try:
    from sqlalchemy.types import JSON, TypeDecorator
except ImportError as exc:  # pragma: no cover
    raise ImportError("SQLAlchemy adapter requires PyTender[sqlalchemy]") from exc

from ..money import Money
from ..serialization import from_dict, to_dict


class MoneyType(TypeDecorator[Money]):
    """Portable JSON-backed SQLAlchemy convenience type.

    For ledgers, analytics, range queries and database aggregation, prefer separate
    native ``amount_minor`` and ``currency_code`` columns. This adapter optimizes
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
        return from_dict(value)
