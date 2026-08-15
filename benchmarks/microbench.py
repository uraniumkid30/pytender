from timeit import timeit

from pytender import Money, MoneyConverter, StaticRateProvider

ITERATIONS = 200_000
money = Money.from_minor(10_000, "USD")
other = Money.from_minor(123, "USD")
converter = MoneyConverter(StaticRateProvider({("USD", "EUR"): "0.91"}))

for label, statement in [
    ("add", "money + other"),
    ("split", "money.split(7)"),
    ("convert", "converter.convert(money, 'EUR')"),
]:
    total = timeit(statement, number=ITERATIONS, globals=globals())
    print(f"{label:8} {total / ITERATIONS * 1e6:9.3f} us/op")
