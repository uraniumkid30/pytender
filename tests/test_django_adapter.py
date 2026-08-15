import pytest

from pytender import Money

django_adapter = pytest.importorskip("pytender.adapters.django", exc_type=ImportError)
MoneyField = django_adapter.MoneyField


def test_django_field_prep_value():
    field = MoneyField()
    assert field.get_prep_value(Money.from_major("12.34", "USD")) == {
        "minor": 1234,
        "currency": "USD",
    }
