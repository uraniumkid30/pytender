import pytest

pytest.importorskip("pytest_benchmark")

from pytender import Money, MoneyConverter, StaticRateProvider

MONEY = Money.from_minor(10_000, "USD")
OTHER = Money.from_minor(555, "USD")
CONVERTER = MoneyConverter(StaticRateProvider({("USD", "EUR"): "0.91"}))


def test_benchmark_add(benchmark) -> None:
    benchmark(lambda: MONEY + OTHER)


def test_benchmark_split(benchmark) -> None:
    benchmark(MONEY.split, 7)


def test_benchmark_convert(benchmark) -> None:
    benchmark(CONVERTER.convert, MONEY, "EUR")
