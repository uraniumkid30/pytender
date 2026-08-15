import pytest

from pytender import Money

django_adapter = pytest.importorskip("pytender.adapters.django", exc_type=ImportError)
MoneyField = django_adapter.MoneyField


def test_django_field_prep_value_uses_canonical_wire_payload():
    field = MoneyField()
    assert field.get_prep_value(Money.from_major("12.34", "USD")) == {
        "amount": 1234,
        "currency": "USD",
    }


def test_django_field_to_python_roundtrips_canonical_wire_payload():
    field = MoneyField()
    money = field.to_python({"amount": 1234, "currency": "USD"})

    assert money == Money.from_minor(1234, "USD")
