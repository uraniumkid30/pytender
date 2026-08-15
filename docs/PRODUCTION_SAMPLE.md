# Production FX sample: simple first, explicit when needed

MoneyTender has two intentionally different usage levels.

## Level 1: safe money arithmetic

You do **not** need to understand FX infrastructure to use `Money`:

```python
from moneytender import Money

total = Money.from_major("19.99", "USD") + Money.from_major("4.50", "USD")
```

## Level 2: production checkout FX

Use the high-level builder so decorator order is not a prerequisite for safe adoption:

```python
from moneytender.infrastructure import (
    ProductionProviderConfig,
    RateLimitPolicy,
    build_production_converter,
    checkout_policy,
)

converter = build_production_converter(
    treasury_provider,
    backup_provider,
    policy=checkout_policy(allowed_sources={"treasury", "backup-bank"}),
    config=ProductionProviderConfig(
        cache_ttl_seconds=10,
        stale_if_error_seconds=0,  # fail rather than silently use an expired cache item
        rate_limit=RateLimitPolicy(rate_per_second=10, burst=20),
    ),
)

result = converter.convert_with_rate(order_total, "EUR")
```

Persist `result.rate` or the full `ConversionResult` when the exact quote matters for audit/replay.

## Level 3: advanced infrastructure composition

Staff/principal engineers can compose every provider decorator directly when order or behaviour must differ from the safe preset. The builder uses this inner-to-outer order:

```text
each provider
    -> retry
    -> optional local rate limit
    -> circuit breaker
then
    -> ordered provider chain
    -> cache
    -> optional audit
    -> optional observer
```

`RetryPolicy.attempts` is per provider. With three providers and three attempts, the worst-case failure path can make up to nine upstream calls. Inverse and triangulation are never enabled automatically. Derived FX must be an explicit business choice.

## Local vs distributed state

**Important:** built-in cache, token bucket and circuit breaker state are process-local. Ten pods have ten caches, ten token buckets and ten circuit states. Use a centralized rate service or application-owned distributed coordination when cluster-wide consistency/quota enforcement is required.

## Failure decisions belong to the application

MoneyTender gives you typed failures and resilience primitives; it cannot decide whether your checkout should proceed. Decide explicitly what your application does when:

- the provider times out;
- all providers fail;
- the pair is unsupported;
- the quote is stale;
- audit storage is unavailable;
- a quote is derived rather than executable.
