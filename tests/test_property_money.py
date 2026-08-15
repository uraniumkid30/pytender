import pytest

from pytender import Money

hypothesis = pytest.importorskip("hypothesis")
given = hypothesis.given
st = hypothesis.strategies


@given(
    st.integers(min_value=-(10**60), max_value=10**60),
    st.integers(min_value=1, max_value=1000),
)
def test_split_never_loses_minor_units(amount: int, parts: int) -> None:
    split = Money.from_minor(amount, "USD").split(parts)
    values = [int(item.minor) for item in split]
    assert sum(values) == amount
    assert max(values) - min(values) <= 1


@given(
    st.integers(min_value=-(10**60), max_value=10**60),
    st.lists(st.integers(min_value=0, max_value=10_000), min_size=1, max_size=30),
)
def test_allocate_never_loses_minor_units(amount: int, ratios: list[int]) -> None:
    parts = Money.from_minor(amount, "USD").allocate(ratios)
    expected = 0 if sum(ratios) == 0 else amount
    assert sum(int(item.minor) for item in parts) == expected


@given(st.integers(min_value=-(10**80), max_value=10**80))
def test_major_minor_roundtrip_is_exact_for_huge_integers(amount: int) -> None:
    money = Money.from_minor(amount, "USD")
    restored = Money.from_major(money.major, "USD")
    assert restored == money


@given(
    st.integers(min_value=-(10**30), max_value=10**30),
    st.integers(min_value=-1000, max_value=1000),
)
def test_integer_multiplication_distributes_over_minor_units(amount: int, multiplier: int) -> None:
    money = Money.from_minor(amount, "USD")
    assert int((money * multiplier).minor) == amount * multiplier
