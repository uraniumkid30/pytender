# Currency data

PyTender ships a generated ISO 4217-oriented snapshot so the core has no Babel/pycountry/runtime-network dependency. ISO states that SIX Financial Information is the official maintenance agency. The repository records a snapshot date and provides `scripts/update_iso4217.py` to fetch SIX List One when maintainers refresh the catalog.

The 2026 snapshot includes the SIX change that moved BGN to historical status from 1 January 2026 and includes newer XCG/ZWG codes missing from older local metadata sources.

ISO minor-unit exponents describe accounting representation; they do **not** fully define cash handling. `cash_increment` is therefore separate, opt-in and overrideable. Built-in cash increments are conservative convenience defaults, not legal/tax advice.

When a currency changes, update the generated snapshot in a dedicated PR, cite the SIX amendment, add regression tests, and document the source/amendment in the pull request.

## Currency equality and compatibility

PyTender intentionally treats the full `Currency` definition as part of monetary semantics. Two objects both labelled `USD` are **not compatible** if their metadata differs (for example exponent `2` versus exponent `0`). Arithmetic and ordering reject that mismatch rather than silently choosing one definition.

This strictness matters when applications use custom registries or historical overrides. Resolve both values through the same application-owned registry before combining them.

## The default registry is immutable

`DEFAULT_REGISTRY` cannot be mutated. This prevents test pollution, plugin interference and process-wide metadata changes:

```python
from pytender import DEFAULT_REGISTRY

registry = DEFAULT_REGISTRY.clone()
# register/replace custom definitions on registry
```

`CurrencyRegistry.iso4217()` also returns an independent mutable registry by default. Pass `frozen=True` when you want a read-only instance.
