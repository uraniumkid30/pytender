# Operational resilience: optional by design

PyTender deliberately separates monetary correctness from operational resilience.

## Core boundary

The top-level `pytender` API focuses on money, currency, rounding, exchange-rate contracts, policy, and conversion. Those concepts are deterministic domain logic and do not require network or resilience infrastructure.

## Opt-in infrastructure

Import operational helpers explicitly:

```python
from pytender.infrastructure import (
    CachedRateProvider,
    CircuitBreakerRateProvider,
    RetryingRateProvider,
)
```

The infrastructure helpers are dependency-free reference implementations. They are useful when an application does not already have standardized resilience middleware, but they are not mandatory.

If your organization already uses a mature retry/circuit-breaker/rate-limit stack, wrap your `ExchangeRateProvider` with that infrastructure instead. PyTender only requires:

```python
class ExchangeRateProvider(Protocol):
    def get_rate(self, base: CurrencyCode, quote: CurrencyCode) -> ExchangeRate: ...
```

and the async equivalent.

## Why the top-level API stays small

A beginner should be able to write:

```python
from pytender import Money
```

without learning circuit breakers, token buckets, cache stampedes, or provider failover.

Senior/staff/principal engineers can opt into `pytender.infrastructure` and choose exact operational semantics.

## Maturity

The infrastructure layer has tests for concurrency, cancellation, stale fallback, retries, circuit state, and sync/async parity. Operational resilience still depends on workload, deployment topology, provider behavior, and failure modes, so validate it with staged rollout, monitoring, and fault injection in your environment.
