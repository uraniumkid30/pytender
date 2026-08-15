import pytest
pytest.importorskip("django")
from pytender import Money
from pytender.adapters.django import MoneyField

def test_django_field_prep_value():
    field = MoneyField()
    prepared = field.get_prep_value(Money.from_minor(123, "USD"))
    assert prepared == {"amount": 123, "currency": "USD"}
