# Errors and troubleshooting

All PyTender exceptions inherit from `MoneyError`.

| Exception | Meaning | Typical action |
|---|---|---|
| `InvalidAmountError` | Unsafe/non-finite amount or float/bool input | Use `str`, `int`, or `Decimal` |
| `UnknownCurrencyError` | Code is absent from the selected registry | Use/register it in the correct application registry |
| `DuplicateCurrencyError` | Registration would overwrite metadata | Use `replace=True` only deliberately |
| `RegistryFrozenError` | Code attempted to mutate a frozen registry | Clone the registry before application overrides |
| `CurrencyMismatchError` | Arithmetic mixed incompatible currency definitions | Resolve/rebind through one registry or convert explicitly |
| `AllocationError` | Invalid split/ratio input | Use a positive part count/non-negative integer ratios |
| `RoundingError` | Invalid rounding value/policy/increment | Supply a finite Decimal and valid policy |
| `InvalidRateError` | FX quote is malformed, non-positive, non-finite, wrong-pair or internally inconsistent | Fix provider output |
| `RateUnavailableError` | A healthy provider cannot supply the requested pair | Use explicit fallback/inverse/triangulation/another provider |
| `RatePolicyError` | Quote violates source/kind/timestamp/derivation policy | Obtain a policy-compliant quote or change business policy deliberately |
| `StaleRateError` | Quote is older than `RatePolicy.max_age` | Refresh pricing or fail according to business semantics |
| `ProviderError` | FX infrastructure failed operationally | Retry/fail over/return service-unavailable as appropriate |
| `CircuitOpenError` | Circuit breaker is rejecting calls while a dependency is unhealthy | Fail fast or use another provider until recovery |
| `AdapterError` | Optional adapter cannot encode/decode a value | Check adapter payload/schema |

## Float input

`Money.from_major(0.1, "USD")` is rejected because binary floating-point is not an acceptable monetary input. Use `"0.1"` or `Decimal("0.1")`.

## Currency mismatch despite the same code

Two currency definitions can both say `USD` but differ in exponent or other metadata. PyTender treats those definitions as incompatible. This prevents a value interpreted as cents from being combined with a whole-dollar override merely because both carry the same code.

## Provider failure versus unavailable pair

Provider authors should use:

- `RateUnavailableError`: provider is healthy but does not have the pair;
- `ProviderError`: timeout, 5xx, authentication failure, malformed response or other operational failure.

This distinction controls retry, circuit-breaker and failover behavior.

## Cache expired versus rate stale

An expired cache entry concerns local storage lifetime. A stale quote concerns business validity. Use `RatePolicy(max_age=...)` for the latter.

## Custom providers

A provider structurally implements `get_rate(base, quote) -> ExchangeRate` or the async equivalent. Inheritance is not required. See [PROVIDERS.md](PROVIDERS.md).
