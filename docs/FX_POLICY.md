# FX policy

PyTender separates three concepts that are commonly conflated:

1. **Quote retrieval** — an `ExchangeRateProvider` obtains a quote.
2. **Caching/resilience** — infrastructure decorators optimize or protect retrieval.
3. **Business validity** — a `RatePolicy` decides whether a valid quote is acceptable for a particular use case.

## RatePolicy

```python
from datetime import timedelta
from pytender import MissingTimestampPolicy, RateKind, RatePolicy

checkout = RatePolicy(
    max_age=timedelta(seconds=30),
    allowed_sources=frozenset({"treasury"}),
    allowed_kinds=frozenset({RateKind.EXECUTABLE}),
    missing_timestamp=MissingTimestampPolicy.REJECT,
    allow_inverse=False,
    allow_triangulation=False,
)
```

`max_age` uses `provenance.as_of` by default. If an application explicitly chooses `USE_FETCHED_AT`, PyTender may use the retrieval timestamp when the provider did not publish an effective-time timestamp. That is a weaker semantic and should be a deliberate choice.

## Derived quotes

Inverse and triangulated rates are tagged `RateKind.DERIVED` and carry a typed `DerivationKind`. Provenance metadata may repeat the method for audit readability, but policy decisions use the typed field, not a string convention. To accept a triangulated rate, a policy must explicitly allow the derived kind and triangulation:

```python
reporting = RatePolicy(
    max_age=timedelta(hours=24),
    allowed_kinds=frozenset({RateKind.REFERENCE, RateKind.DERIVED}),
    allow_triangulation=True,
)
```

This two-part opt-in is intentional. It makes accidental use of a mathematical cross-rate in an executable checkout harder.

Custom provider authors must keep `RateKind` and `DerivationKind` consistent. A derived rate must declare `INVERSE`, `TRIANGULATION`, or `CUSTOM`; a non-derived rate must use `NONE`. PyTender rejects inconsistent objects at construction time.

## Cache TTL versus freshness

A cache expiry is an infrastructure optimization. A quote's `as_of` timestamp is business data. Always use `RatePolicy` when quote age matters commercially or legally.

## Historical replay

For deterministic replay, persist the actual `ExchangeRate` used for the original transaction or an equivalent immutable quote record. Querying a live provider later is not historical replay.

## Policy presets

Most applications should start with a named policy rather than constructing every field manually:

```python
from pytender.infrastructure import checkout_policy, display_policy, reporting_policy, treasury_policy

checkout = checkout_policy(allowed_sources={"treasury"})
reporting = reporting_policy(allow_derived=True)
display = display_policy()
treasury = treasury_policy(allowed_sources={"bank-a", "bank-b"})
```

Presets are functions rather than mutable global policy objects.

## Custom source trust and governance

`allowed_sources` handles the common allow-list case. Larger organizations can attach a validator for rules that belong to their own governance model, such as environment, region, market, source trust, deviation limits, or approval state:

```python
from pytender import RatePolicy, RatePolicyError

TRUSTED = {"treasury": 100, "bank-a": 80}


def require_high_trust(rate):
    if TRUSTED.get(rate.source, 0) < 90:
        raise RatePolicyError(f"source {rate.source!r} is below the required trust level")


policy = RatePolicy(validator=require_high_trust)
```

PyTender intentionally does not define what "trusted" means for your organization.

## Daily reference dates are not live quote timestamps

Some reference providers expose a date only. Representing `2026-08-15` as midnight UTC is a precise encoding of that daily observation date, but it does **not** mean the quote was a live executable market quote at midnight. Model those rates as `REFERENCE`, choose `max_age` accordingly, and do not reuse checkout policy intended for live executable quotes.
