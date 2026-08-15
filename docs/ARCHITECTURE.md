# Architecture

PyTender uses a dependency-inverted, layered design. The hot monetary domain stays dependency-free; FX infrastructure and framework integrations sit outside it.

```text
pytender.core
    Money
    Currency
    CurrencyRegistry
    RoundingPolicy

pytender.fx
    ExchangeRate
    RateProvenance
    ExchangeRateProvider
    MoneyConverter

pytender.policy
    RateKind
    RatePolicy

pytender.infrastructure
    cache
    retry
    circuit breaker
    audit

pytender.providers
    provider contracts + optional vendor adapters

pytender.adapters
    Pydantic / Django / SQLAlchemy / Babel / relational helpers
```

The top-level `pytender` API covers common use cases; layered namespaces provide focused discoverability for core and infrastructure concerns.

## Domain invariants

- Money is stored canonically as arbitrary-precision integer minor units.
- Major units are derived with explicitly sized local Decimal contexts.
- Float monetary input is rejected.
- Money arithmetic requires compatible full `Currency` definitions.
- Cross-currency conversion is explicit.
- FX rates are positive finite `Decimal` values with provenance.
- Cache lifetime is not business rate validity.
- Derived rates are explicitly classified and can be rejected by policy.

## SOLID boundaries

- `Money` knows nothing about HTTP, caches, databases or FX vendors.
- `MoneyConverter` depends on provider protocols rather than concrete vendors.
- Rounding and formatting are small protocols.
- Resilience helpers are decorators rather than inheritance hierarchies.
- Framework adapters are optional and import-guarded.

## Sync/async design

Python deliberately has separate synchronous and asynchronous call semantics. PyTender keeps explicit sync/async provider variants rather than hiding blocking work behind an async-looking API. Shared mathematical helpers are centralized to reduce behavioral drift.

The async triangulator intentionally fetches two independent pivot legs concurrently. The synchronous implementation performs the same logical operation serially because it has no concurrency contract to assume.

## Registry state

`DEFAULT_REGISTRY` is frozen and safe from application mutation. `DEFAULT_REGISTRY.clone()` creates an independent mutable registry for private currencies or explicit overrides.

## Ledger boundary

See [LEDGER_BOUNDARY.md](LEDGER_BOUNDARY.md). PyTender is not a ledger or settlement system.

## Public API boundary in 1.0

`pytender` intentionally exposes the small monetary/FX domain surface used by most applications. Operational decorators and production builders live under `pytender.infrastructure` so resilience complexity is opt-in.

This is a discoverability and maturity boundary, not a dependency wall: the infrastructure code remains dependency-free and ships in the same distribution so installation stays simple. Teams with established resilience libraries can ignore it entirely and wrap the small provider protocols with their own middleware.

Sync and async implementations remain separate because blocking and awaitable control flow have different cancellation/concurrency semantics. PyTender avoids hiding that difference behind clever abstractions; instead, parity tests assert matching business semantics for provider composition, retry/failover behavior, and derived-rate handling.
