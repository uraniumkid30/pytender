from __future__ import annotations

try:
    from pydantic import BaseModel, ConfigDict, field_validator
except ImportError as exc:  # pragma: no cover
    raise ImportError("Pydantic adapter requires PyTender[pydantic]") from exc

from ..money import Money
from ..registry import DEFAULT_REGISTRY, CurrencyRegistry
from ..serialization import from_dict, to_dict


class MoneyModel(BaseModel):
    """Wire-friendly Pydantic v2 model using canonical integer minor units."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    amount: int
    currency: str

    @field_validator("amount")
    @classmethod
    def reject_bool(cls, value: int) -> int:
        if isinstance(value, bool):
            raise ValueError("amount must be integer minor units, not bool")
        return value

    @field_validator("currency")
    @classmethod
    def normalize_currency(cls, value: str) -> str:
        code = value.upper()
        if len(code) != 3 or not code.isalpha():
            raise ValueError("currency must be a three-letter code")
        return code

    def to_money(self, *, registry: CurrencyRegistry = DEFAULT_REGISTRY) -> Money:
        """Convert this transport model to a domain Money value."""
        return from_dict(
            {"amount": self.amount, "currency": self.currency},
            registry=registry,
        )

    @classmethod
    def from_money(cls, money: Money) -> MoneyModel:
        """Create a transport model from a domain Money value."""
        return cls(**to_dict(money))
