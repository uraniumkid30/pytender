import pytest

pytest.importorskip("pydantic")

from moneytender import Money
from moneytender.adapters.pydantic import MoneyModel


def test_pydantic_roundtrip() -> None:
    money = Money.from_minor(99, "USD")
    assert MoneyModel.from_money(money).to_money() == money
