# Changelog

## 1.0.0 - 2026-08-15

Initial public release of MoneyTender.

### Core monetary domain

- Immutable integer-minor-unit `Money` values with arbitrary-precision Python integers.
- Float monetary input rejected by design.
- Explicitly sized local `Decimal` contexts for major-unit, FX, ratio, and rounding calculations.
- Strict full-currency compatibility for arithmetic and comparison.
- ISO 4217 registry with immutable `DEFAULT_REGISTRY` and clone-based application overrides.
- Exact split/allocation semantics and explicit accounting/cash rounding.
- Typed serialization, formatting, and optional Django/Pydantic/SQLAlchemy/Babel adapters.

### FX domain

- Structural sync/async provider protocols and explicit `MoneyConverter` APIs.
- Immutable rate provenance, `RateKind`, and typed `DerivationKind`.
- Derived-rate invariants enforced at `ExchangeRate` construction time.
- Explicit rate freshness/source/kind policy and deterministic conversion replay.
- Inverse and triangulation helpers with provenance and typed derivation semantics.

### Opt-in operational infrastructure

- Process-local bounded LRU/TTL cache with single-flight and stale-on-error policy.
- Ordered provider failover with distinct unavailable-vs-operational failure semantics.
- Dependency-free retry, local token-bucket rate limiting, provider/pair circuit breakers.
- Explicit audit/observer fail-open/fail-closed modes.
- High-level production builders plus low-level composable primitives under `moneytender.infrastructure`.
- Production builder retries each provider before failover; retry scope and worst-case call counts are documented.
- Sync/async parity and cancellation/fault-injection regression coverage.

### Release posture

This is MoneyTender's first public release. The monetary core is the primary stable surface. Operational helpers are opt-in and should be rolled out with application-specific monitoring, fault injection, and capacity/latency validation. MoneyTender does not replace a ledger, payment processor, market-data authority, distributed cache, or organization-wide resilience platform.
