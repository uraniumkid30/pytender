# API stability

MoneyTender follows Semantic Versioning. Public objects exported from `moneytender.__all__`, documented provider protocols, serialized wire fields (`amount`, `currency`), and the relational storage contract (`amount_minor`, `currency_code`) are compatibility commitments.

A breaking release includes changes such as:

- removing or renaming a public symbol;
- changing canonical money representation or serialized field meaning;
- changing documented rounding or currency-compatibility semantics;
- making a previously optional runtime dependency mandatory.

Backward-compatible releases may add currencies, optional providers, adapters, policy helpers, diagnostics, and stricter rejection of inputs that violate an already documented safety invariant.

Operational helpers under `moneytender.infrastructure` are optional composition primitives. They do not change `Money` arithmetic and do not introduce mandatory runtime dependencies.
