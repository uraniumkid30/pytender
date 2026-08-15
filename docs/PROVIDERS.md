# FX providers

## The contract

You can add your own provider without inheriting from a PyTender base class. Satisfy one structural protocol:

```python
from pytender import CurrencyCode, ExchangeRate

class ExchangeRateProvider:
    def get_rate(self, base: CurrencyCode, quote: CurrencyCode) -> ExchangeRate:
        ...

class AsyncExchangeRateProvider:
    async def get_rate(self, base: CurrencyCode, quote: CurrencyCode) -> ExchangeRate:
        ...
```

The actual protocols are available from both `pytender` and `pytender.providers`.

## Provider obligations

A provider should:

- return the exact requested base/quote pair;
- return a positive finite `Decimal` rate;
- never convert a `float` into a rate silently;
- identify its source with `RateProvenance`;
- use timezone-aware timestamps;
- classify the quote with `RateKind` when its commercial meaning is known;
- raise `RateUnavailableError` when the provider is healthy but cannot supply the pair;
- raise `ProviderError` for operational failures such as timeout, authentication failure, malformed payload or upstream 5xx;
- preserve original exceptions using exception chaining (`raise ... from exc`).

PyTender validates returned pairs before conversion and can apply an explicit `RatePolicy`.

## Minimal custom provider

```python
from datetime import datetime, timezone
from decimal import Decimal
from pytender import CurrencyCode, ExchangeRate, RateKind, RateProvenance

class TreasuryProvider:
    def get_rate(self, base: CurrencyCode, quote: CurrencyCode) -> ExchangeRate:
        raw = treasury_client.fetch(str(base), str(quote))
        return ExchangeRate(
            base=base,
            quote=quote,
            value=Decimal(raw.rate),
            provenance=RateProvenance(
                provider="treasury",
                as_of=datetime.fromisoformat(raw.as_of).astimezone(timezone.utc),
                request_id=raw.request_id,
            ),
            kind=RateKind.EXECUTABLE,
        )
```

## Production composition

Available dependency-free decorators include:

- `CachedRateProvider` / `AsyncCachedRateProvider`
- `RetryingRateProvider` / `AsyncRetryingRateProvider`
- `CircuitBreakerRateProvider` / `AsyncCircuitBreakerRateProvider`
- `ChainedRateProvider` / `AsyncChainedRateProvider`
- `InverseRateProvider` / `AsyncInverseRateProvider`
- `TriangulatingRateProvider` / `AsyncTriangulatingRateProvider`
- `PolicyRateProvider` / `AsyncPolicyRateProvider`
- `AuditedRateProvider` / `AsyncAuditedRateProvider`

Read [Production FX](PRODUCTION_FX.md) before placing a live external provider on a payment-critical request path.

## Retry semantics

`RetryingRateProvider` retries `ProviderError` with exponential backoff and jitter. It does not retry `RateUnavailableError` unless explicitly configured because "pair not offered" is normally not a transient provider-health problem.

## Circuit breaker semantics

The circuit breaker counts `ProviderError` as health failures. Pair-level `RateUnavailableError` does not open the circuit. Once open, calls fail fast until the recovery interval permits a half-open probe.

## Async caution

`AsyncFromSyncProvider` is only for cheap, non-blocking providers such as an in-memory static provider. Do **not** wrap blocking HTTP/database calls with it; implement a real async provider or offload blocking work at the application boundary.

## Plugins

Third-party distributions may expose factories through the `pytender.fx_providers` entry-point group. Plugin code is executable third-party code: pin dependencies, review it, and control what packages are installed in production.

## Derived-rate contract

A provider that returns a mathematically derived quote must use both a derived rate kind and a typed derivation:

```python
from decimal import Decimal
from pytender import DerivationKind, ExchangeRate, RateKind, RateProvenance

rate = ExchangeRate(
    base,
    quote,
    Decimal("0.91"),
    RateProvenance("my-provider"),
    RateKind.DERIVED,
    DerivationKind.CUSTOM,
)
```

Use `INVERSE` or `TRIANGULATION` when those meanings apply. `RatePolicy` makes decisions from `ExchangeRate.derivation`, not from free-form provenance metadata. If metadata includes a `derived` key, PyTender validates that it does not contradict the typed field.

This keeps third-party providers from accidentally creating a quote that says `RateKind.DERIVED` in one place and something incompatible in another.
