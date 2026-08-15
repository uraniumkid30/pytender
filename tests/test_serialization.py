from pytender import (
    from_dict,
    Money,
    to_dict,
)


def test_serialization_roundtrip() -> None:
    money = Money.from_minor(123, "USD")
    assert from_dict(to_dict(money)) == money
