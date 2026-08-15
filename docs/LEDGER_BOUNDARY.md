# Ledger boundary

MoneyTender is a monetary value and FX-policy library. It is **not** a double-entry ledger, accounting engine, settlement system, tax engine or payment processor.

A typical system boundary is:

```text
Order / Invoice
      ↓
Money values
      ↓
Pricing / fees / tax policy
      ↓
FX quote + RatePolicy
      ↓
ConversionResult (retain the exact quote)
      ↓
Ledger posting
      ↓
Relational database / accounting platform
```

MoneyTender owns exact money representation, explicit rounding, currency compatibility, quote metadata and optional quote-policy enforcement. Your ledger owns accounts, debit/credit balancing, idempotency, posting dates, reversals, settlement state, reconciliation, legal books and retention.

For historical conversions, persist the `ExchangeRate` or sufficient immutable quote data alongside the ledger event. Re-querying today's provider later is not deterministic historical replay.
