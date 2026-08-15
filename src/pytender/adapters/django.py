from __future__ import annotations

from typing import Any

try:
    from django.core import exceptions as django_exceptions
    from django.db import models
except ImportError as exc:  # pragma: no cover
    raise ImportError("Django adapter requires PyTender[django]") from exc

from ..money import Money
from ..serialization import from_dict, to_dict


class MoneyField(models.JSONField):
    """Portable JSON-backed Django convenience field for ``Money``.

    This is intentionally *not* the recommended schema for a query-heavy ledger.
    Production ledger/reporting models should generally use separate indexed
    ``amount_minor`` and ``currency_code`` columns with database constraints; see
    ``docs/DATABASE_STORAGE.md``.
    """

    description = "PyTender monetary amount (integer minor units + ISO/custom currency)"

    def from_db_value(self, value: Any, expression: Any, connection: Any) -> Money | None:
        """Convert a database value into Money for Django model loading."""
        raw = super().from_db_value(value, expression, connection)
        if raw is None or isinstance(raw, Money):
            return raw
        try:
            return from_dict(raw)
        except (TypeError, ValueError) as exc:
            raise django_exceptions.ValidationError(str(exc)) from exc

    def to_python(self, value: Any) -> Money | None:
        """Normalize Python/serialized values into Money."""
        if value is None or isinstance(value, Money):
            return value
        raw = super().to_python(value)
        try:
            return from_dict(raw)
        except (TypeError, ValueError) as exc:
            raise django_exceptions.ValidationError(str(exc)) from exc

    def get_prep_value(self, value: Any) -> Any:
        """Serialize Money into the Django JSON convenience representation."""
        if isinstance(value, Money):
            value = dict(to_dict(value))
        elif value is not None and not isinstance(value, dict):
            raise django_exceptions.ValidationError(
                "MoneyField expects Money, dict, or None"
            )
        return super().get_prep_value(value)
