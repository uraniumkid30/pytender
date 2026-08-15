# Extending PyTender

## Custom FX provider

Implement `get_rate(base, quote) -> ExchangeRate`. No inheritance is required. Normalize third-party errors into `RateUnavailableError` when the pair is simply unavailable and `ProviderError` for operational failures.

Preserve provenance: provider name, source URI, source publication timestamp (`as_of`), fetch timestamp, request/correlation ID, and useful string metadata.

## Provider composition

Use `ChainedRateProvider(primary, fallback)`, `InverseRateProvider(provider)`, and `CachedRateProvider(provider)` as decorators. Equivalent async decorators are provided.

Do not build retry storms in the core. Put retry/backoff/circuit-breaker behavior at the HTTP/provider boundary where idempotency and provider limits are known.

## Rounding policy

Implement `quantize_minor(Decimal) -> int`. Inject it into `Money.from_major`, `multiply_rate`, converters, or cash rounding. Never put rounding policy into an FX provider.

## Custom registry

Clone `DEFAULT_REGISTRY` or use `CurrencyRegistry.iso4217()`. Register private units. Use `replace=True` only for deliberate metadata overrides.

## Third-party provider plugins

External packages can advertise providers without PyTender importing them eagerly:

```toml
[project.entry-points."pytender.fx_providers"]
acme = "acme_money:build_provider"
```

The external package exposes a factory:

```python
def build_provider(**config):
    return AcmeProvider(**config)
```

Applications can then call `load_provider_plugin("acme", api_key=...)`. Entry-point discovery uses the Python standard library, so the core remains dependency-free. Prefer separate plugin distributions for vendor-specific SDKs with heavy or conflicting dependencies.
