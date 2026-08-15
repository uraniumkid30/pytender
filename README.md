# MoneyTender

MoneyTender is a strict, typed money and FX-policy library for Python. It stores monetary values as **integer minor units**, uses `Decimal` for rates and fractional arithmetic, rejects float monetary input, and keeps currency conversion explicit.

The core package has **zero required runtime dependencies**.

> **Operational note:** The money/currency domain is the stable core. Dependency-free operational FX helpers under `moneytender.infrastructure` are opt-in and should be validated under your own load and outage conditions before they become a money-moving availability dependency. You may instead wrap MoneyTender providers with your organization's established resilience libraries.

## Who should start where?

### I only need safe money arithmetic

```python
from moneytender import Money

price = Money.from_major("19.99", "USD")
shipping = Money.from_major("4.50", "USD")
total = price + shipping

assert total.minor == 2449
assert total.major.as_tuple().exponent == -2
```

Read the [5-minute quick start](docs/QUICKSTART.md).

### I need FX in production

For most teams, start with the safe high-level composition helper instead of hand-ordering infrastructure decorators:

```python
from moneytender.infrastructure import build_production_converter, checkout_policy

converter = build_production_converter(
    treasury_provider,
    backup_provider,
    policy=checkout_policy(allowed_sources={"treasury", "backup-bank"}),
)

result = converter.convert_with_rate(order_total, "EUR")
```

This applies provider-local retry/rate-limit/circuit protection, ordered failover, then caching while keeping derived FX disabled. Advanced users can still compose every low-level decorator directly. See the [production sample](docs/PRODUCTION_SAMPLE.md).

> **Distributed systems warning:** MoneyTender's built-in cache, token bucket and circuit breaker are process-local. Multiple pods/workers do not share those states. Use a central rate service or application-owned distributed coordination when cluster-wide consistency or quota enforcement matters.

Persist `result.rate` when deterministic audit/replay matters. Read [Production FX](docs/PRODUCTION_FX.md), [FX policy](docs/FX_POLICY.md), and [audit storage](docs/AUDIT_STORAGE.md).

### I am writing an FX provider

Implement one structural protocol; inheritance is not required:

```python
from moneytender import CurrencyCode, ExchangeRate


class MyRates:
    def get_rate(self, base: CurrencyCode, quote: CurrencyCode) -> ExchangeRate: ...
```

Read [Provider authoring](docs/PROVIDERS.md).

### I use Django, SQLAlchemy, Pydantic, or localized formatting

Framework adapters are optional extras. JSON-backed ORM adapters are convenience integrations, **not** the preferred schema for high-volume financial ledgers. Read [Adapters](docs/ADAPTERS.md) and [Database storage](docs/DATABASE_STORAGE.md).

## Core guarantees

MoneyTender deliberately guarantees:

- integer minor units are the canonical stored representation;
- Python `int` amounts are arbitrary precision;
- major-unit derivation and FX math use explicitly sized local `Decimal` contexts;
- float/bool monetary input is rejected;
- arithmetic requires compatible full currency definitions, not merely matching codes;
- currency conversion is explicit;
- exchange rates must be positive finite `Decimal` values;
- FX provenance is immutable and hashable;
- `DEFAULT_REGISTRY` is immutable; application overrides use a clone;
- cash rounding is opt-in and distinct from ledger/card rounding;
- caches are bounded, process-local, LRU/TTL caches with single-flight protection;
- optional operational FX helpers live under `moneytender.infrastructure`, not the beginner top-level API;
- retry, rate-limit and circuit-breaker helpers are dependency-free reference implementations and can be replaced by established infrastructure libraries;
- cache TTL and business quote freshness are separate concepts;
- inverse/triangulated rates are marked `DERIVED` and can be rejected by policy;
- the core never performs network I/O or imports an optional framework.

## Rate semantics

Every `ExchangeRate` has a `RateKind`:

```text
REFERENCE   market/reference valuation
INDICATIVE  guidance, not guaranteed execution
EXECUTABLE  provider asserts transaction suitability subject to its terms
DERIVED     calculated rather than directly quoted; `DerivationKind` records how
```

MoneyTender validates structure and policy. It cannot determine whether an economically supplied quote is actually fair, legal, liquid, or executable. That responsibility remains with the provider and application.

## Custom currencies and registry overrides

The shared ISO registry is frozen:

```python
from moneytender import DEFAULT_REGISTRY

registry = DEFAULT_REGISTRY.clone()
# registry is now application-owned and mutable
```

This avoids test pollution and plugin/application mutation of process-wide defaults.

## Install

```bash
pip install MoneyTender
pip install 'MoneyTender[http]'
pip install 'MoneyTender[pydantic]'
pip install 'MoneyTender[django]'
pip install 'MoneyTender[sqlalchemy]'
pip install 'MoneyTender[babel]'
```

## Quality gates

MoneyTender enforces **98% branch-aware coverage on the stable monetary domain** (`Money`, currency metadata/registry, rounding, serialization, formatting, policy, and canonical database payloads). The optional FX infrastructure has its own concurrency, cancellation, failover, cache, circuit-breaker, and sync/async parity tests, but is not allowed to dilute or game the core-domain coverage metric. CI also runs Ruff, Ruff formatting, strict mypy, property tests, database integration tests, package builds, and artifact validation.

## Documentation

- [Quick start](docs/QUICKSTART.md)
- [Production FX architecture](docs/PRODUCTION_FX.md)
- [Optional resilience infrastructure](docs/RESILIENCE.md)
- [Production FX sample](docs/PRODUCTION_SAMPLE.md)
- [FX audit persistence](docs/AUDIT_STORAGE.md)
- [FX policy](docs/FX_POLICY.md)
- [Custom/provider integrations](docs/PROVIDERS.md)
- [Architecture](docs/ARCHITECTURE.md)
- [Ledger boundary](docs/LEDGER_BOUNDARY.md)
- [Database storage](docs/DATABASE_STORAGE.md)
- [Currency registry](docs/CURRENCIES.md)
- [Rounding](docs/QUICKSTART.md#cash-rounding)
- [Errors and troubleshooting](docs/ERRORS.md)
- [Framework adapters](docs/ADAPTERS.md)
- [Limitations](docs/LIMITATIONS.md)
- [API stability](docs/API_STABILITY.md)
- [Contributing](CONTRIBUTING.md)
- [Security](SECURITY.md)

## What MoneyTender is not

MoneyTender is not a payment processor, accounting ledger, tax engine, market-data authority, compliance product, distributed cache, or pricing oracle. See [Ledger boundary](docs/LEDGER_BOUNDARY.md).

## License

MIT.
