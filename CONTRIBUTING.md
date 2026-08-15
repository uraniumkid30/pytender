# Contributing

Thank you for improving MoneyTender. Financial primitives need conservative changes and excellent tests.

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
pytest
ruff check .
ruff format --check .
mypy src/moneytender
```

## Expectations

Keep core dependency-free. Preserve explicit currency conversion and float rejection. Add unit tests plus property tests for arithmetic invariants. Add adapter tests for optional integrations. Document public API behavior. Prefer small protocols and composition over global hooks or vendor conditionals.

Bug fixes should include a regression test. New FX vendors belong under `moneytender.providers` or a separate plugin package and must not be imported by core.

## Compatibility

Public API changes follow Semantic Versioning. Currency snapshot maintenance and provider additions must preserve documented safety guarantees.
