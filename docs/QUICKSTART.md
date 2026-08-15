# Quick start

## Create money

```python
from pytender import Money

price = Money.from_major("19.99", "USD")
raw = Money.from_minor(1999, "USD")
assert price == raw
```

Use strings, integers, or `Decimal` for major-unit inputs. Floats and booleans are intentionally rejected.

## Arithmetic

```python
total = Money.from_major("10", "USD") + Money.from_major("2.50", "USD")
tripled = total * 3
fee = total.multiply_rate("0.025")
```

Different currencies cannot be added, subtracted, ordered, or ratio-compared without explicit conversion.

## Split and allocate

```python
Money.from_minor(100, "USD").split(3)
# (USD 0.34, USD 0.33, USD 0.33)

Money.from_minor(100, "USD").allocate([50, 30, 20])
```

The sum of all returned parts always equals the original amount.

## Convert currency

```python
from pytender import MoneyConverter, StaticRateProvider

provider = StaticRateProvider({("USD", "EUR"): "0.92"})
converter = MoneyConverter(provider)
euros = converter.convert(Money.from_major("100", "USD"), "EUR")
```

For live/custom rates, see [PROVIDERS.md](PROVIDERS.md).

## Custom currency metadata

```python
from pytender import Currency, CurrencyCode, CurrencyRegistry, Money

registry = CurrencyRegistry.iso4217()
registry.register(Currency(CurrencyCode("TOK"), 4, "T", "Internal Token"))
amount = Money.from_major("1.2345", "TOK", registry=registry)
```

Clone `DEFAULT_REGISTRY` before application-specific overrides; do not mutate shared assumptions implicitly.

## Serialize

```python
from pytender import to_dict, from_dict

payload = to_dict(amount)
restored = from_dict(payload, registry=registry)
```

The stable payload shape is integer minor units plus a currency code.
