# Production FX architecture

PyTender can safely represent and validate FX quotes, but it cannot decide your commercial policy. A payment checkout, treasury service and end-of-day report usually need different guarantees.

## Recommended boundary

```text
request / job
    ↓
application pricing policy
    ↓
MoneyConverter + RatePolicy
    ↓
optional audit / observation
    ↓
CachedRateProvider              # local optimization only
    ↓
ChainedRateProvider             # ordered failover
    ├── Provider A -> retry -> optional local rate limit -> circuit
    ├── Provider B -> retry -> optional local rate limit -> circuit
    └── Provider C -> retry -> optional local rate limit -> circuit
         ↓
external rate service(s)
```

The order is intentionally application-controlled. For example, placing a cache outside retry avoids retrying when a fresh value is already available. A different system may centralize rates behind its own service and use no local cache at all.

## Cache TTL is not quote validity

`ttl_seconds=60` means "keep this object locally for up to 60 seconds." It does **not** mean the quote is commercially valid for 60 seconds. Enforce business validity separately:

```python
from datetime import timedelta
from pytender import MoneyConverter, RateKind, RatePolicy

checkout_policy = RatePolicy(
    max_age=timedelta(seconds=30),
    allowed_sources=frozenset({"treasury"}),
    allowed_kinds=frozenset({RateKind.EXECUTABLE}),
)
converter = MoneyConverter(provider, policy=checkout_policy)
```

## Reference, indicative, executable and derived

`ExchangeRate.kind` makes quote meaning explicit:

- `REFERENCE`: valuation/reference data; not automatically tradable.
- `INDICATIVE`: guidance only.
- `EXECUTABLE`: provider asserts transaction suitability subject to its terms.
- `DERIVED`: calculated by inversion/triangulation rather than directly quoted.

PyTender cannot verify that a provider is economically correct. It can prevent your application from accidentally accepting a class of quote it did not authorize.

## Inverse and triangulated rates

Inverse and triangulated quotes are marked `DERIVED` and carry a typed `DerivationKind`. `RatePolicy` rejects inverse/triangulated derivations unless explicitly enabled. Metadata is descriptive only and cannot override the typed derivation. A mathematical cross-rate is not necessarily an executable market price because timestamps, spread, liquidity and methodology can differ.

## Retry and circuit breaker

`RetryingRateProvider` retries `ProviderError` with bounded exponential backoff and jitter. `RateUnavailableError` is not retried by default because pair unavailability is usually not a transient health failure.

`CircuitBreakerRateProvider` opens after repeated provider failures and fails fast until a recovery window allows a probe. This protects your request path from repeatedly waiting on a failing dependency.

Neither decorator replaces provider-specific HTTP timeout configuration. Always set a timeout at the network adapter as well.

### Retry scope in the production builder

`build_production_provider()` applies retry **to each provider before failover**, not around the whole chain. If `attempts=3` and three providers are configured, a complete worst-case outage can therefore make up to nine upstream calls (three per provider) before failing. This is intentional and documented so latency and provider quotas are predictable. If your system needs different semantics, compose the low-level providers explicitly instead of using the preset.

## Rate limiting

`RateLimitedRateProvider` and `AsyncRateLimitedRateProvider` provide an optional dependency-free token bucket. They protect a provider from accidental local request bursts and make provider quotas explicit in composition. They are intentionally **process-local**; if a quota is shared across pods/workers, use a centralized limiter or rate service.

```python
from pytender.infrastructure import RateLimitedRateProvider, RateLimitPolicy

provider = RateLimitedRateProvider(
    provider,
    policy=RateLimitPolicy(rate_per_second=10, burst=20),
)
```

## Passive health checking

A circuit breaker exposes `snapshot()` so an application health endpoint can inspect `CLOSED`, `OPEN`, or `HALF_OPEN` state plus the consecutive failure count without causing a provider request. This is passive health information, not a substitute for provider-specific active health endpoints.

## Stale-on-error

`CachedRateProvider(..., stale_if_error_seconds=N)` can explicitly return an expired local quote after a provider operational failure. It is **disabled by default**. If enabled, combine it with `RatePolicy(max_age=...)` so your business freshness limit remains authoritative.

## Local versus distributed cache

The built-in cache is intentionally process-local. Multiple workers/pods can therefore hold different snapshots. For high-value or tightly coordinated pricing, put a shared cache/rate service in your architecture and implement it as an `ExchangeRateProvider` rather than assuming the local cache provides cluster consistency.

## Audit/replay

Use `convert_with_rate()` when the exact rate must be retained:

```python
result = converter.convert_with_rate(order_total, "EUR")
ledger.store(
    source=result.source,
    target=result.target,
    rate=result.rate,
)
```

`AuditedRateProvider` can additionally emit each successful quote to an application-owned `RateAuditSink`. PyTender deliberately does not choose your logging database or observability vendor.

## Provider disagreement

`ChainedRateProvider` is a **priority/failover** primitive, not a consensus engine. It returns the first successful provider in configured order. If every provider says the pair is unavailable, it raises `RateUnavailableError`; if any provider failed operationally and nobody succeeds, it raises `ProviderError` so infrastructure uncertainty is not misreported as authoritative pair unavailability.

If your business requires median pricing, quorum, deviation thresholds or human review when providers disagree, implement that as a dedicated provider/policy component. PyTender deliberately does not invent a universal financial consensus rule.

## Failure-to-HTTP mapping

PyTender raises typed domain errors; your API decides transport semantics. A common mapping is:

- `RateUnavailableError` → 422/409 when the requested pair cannot be priced.
- `ProviderError` / `CircuitOpenError` → 503 when pricing infrastructure is unhealthy.
- `StaleRateError` / `RatePolicyError` → 409/503 depending on whether the caller can retry.

Do not blindly copy these mappings; they are application decisions.

## Recommended builder for most teams

If you do not need custom decorator ordering, prefer:

```python
from pytender.infrastructure import build_production_converter, checkout_policy

converter = build_production_converter(
    primary_provider,
    fallback_provider,
    policy=checkout_policy(allowed_sources={"treasury", "fallback-bank"}),
)
```

See [Production sample](PRODUCTION_SAMPLE.md) for the complete beginner-to-advanced path.

## Provider-wide vs pair-scoped circuits

`CircuitBreakerRateProvider` tracks provider health globally. This is appropriate when failures indicate provider-wide health. `PairCircuitBreakerRateProvider` isolates state per `(base, quote)` and is useful when a provider can have partial pair outages.

Do not choose pair-scoped circuits merely because they are more granular: widespread provider failure should often trip one provider-wide circuit quickly.

## Audit and telemetry failure semantics

Audit and monitoring are not interchangeable:

- audit defaults to `HookFailureMode.FAIL_CLOSED`;
- provider observation/metrics defaults to `HookFailureMode.FAIL_OPEN`.

Both are configurable. Async cancellation is always preserved rather than being replaced by an observer error.

## Stale fallback window

The stale fallback age is evaluated at the time the provider **fails**, not when the refresh attempt started. A provider that stalls for longer than the configured stale window cannot extend that window accidentally.

## Operational helper maturity and third-party resilience

The money/currency domain is PyTender's stable core. `pytender.infrastructure` contains opt-in, dependency-free operational helpers. They are useful defaults and thoroughly tested, but they do not replace organization-wide resilience tooling when your architecture already provides it.

If your platform already standardizes retry, circuit breaking, quotas, metrics, or distributed caching, keep using that infrastructure. PyTender's `ExchangeRateProvider` / `AsyncExchangeRateProvider` protocols are intentionally small so external middleware can wrap providers without changing the monetary domain.

For a first production rollout, prefer low-risk traffic, feature flags, dashboards, and failure injection before making local circuit/limiter behavior a critical availability dependency.
