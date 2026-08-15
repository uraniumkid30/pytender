# Limitations and guarantees

MoneyTender is a money/FX domain library, not an accounting ledger, tax engine, legal-tender authority, locale database, pricing oracle, market-data authority or compliance product.

## FX correctness

A structurally valid rate can still be economically wrong. MoneyTender can enforce source, timestamp, rate kind and derivation policy; it cannot verify liquidity, spread, market fairness, provider methodology, legal validity or whether an `EXECUTABLE` classification will actually be honored by an upstream venue.

## Provider availability

Retries, circuit breakers, chains and local caching are available as composition primitives. Applications still own SLA targets, HTTP timeouts, dependency budgets, distributed coordination, alert routing and incident response.

## Process-local cache

The built-in cache is not distributed. Different workers/pods can temporarily hold different quotes. Use a centralized rate service/shared cache when cluster-wide pricing consistency is a business requirement.

## Stale fallback

Stale-on-provider-error is disabled by default and must be explicitly configured. Cache expiry is not quote validity. Use `RatePolicy(max_age=...)` to enforce business freshness even when stale fallback is enabled.

## Derived FX

Inverse and triangulated rates are mathematical derivations, not automatically executable market quotes. They are classified as `DERIVED` and rejected by the default policy unless explicitly authorized.

## Currency metadata

Currency minor units, legal status and cash rounding practices can change. Refresh the bundled ISO snapshot deliberately. Historical ledger records should persist the currency/rate semantics required to replay them.

## Cash rounding

Cash rounding varies by jurisdiction and payment channel. Built-in currency metadata is a default, not universal legal advice.

## Database limits

Python integers are arbitrary precision; database integer types are not. Applications must choose and test a relational numeric type suitable for their maximum values. JSON ORM adapters are conveniences, not optimal ledger schemas.

## Formatting

Core formatting is deterministic, not fully locale-aware. Rich localization belongs in the optional Babel/CLDR adapter.

## Plugins

Entry-point plugins execute third-party code in your process. Review, pin and control installed plugin distributions like any other production dependency.
