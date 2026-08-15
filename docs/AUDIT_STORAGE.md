# FX audit persistence reference

PyTender deliberately does not ship a database dependency, but production teams often need a durable record of the exact quote used.

A reference relational schema is:

```sql
CREATE TABLE fx_quote_audit (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    provider VARCHAR(128) NOT NULL,
    base_currency CHAR(3) NOT NULL,
    quote_currency CHAR(3) NOT NULL,
    rate NUMERIC(50, 25) NOT NULL CHECK (rate > 0),
    rate_kind VARCHAR(16) NOT NULL,
    as_of TIMESTAMP WITH TIME ZONE NULL,
    fetched_at TIMESTAMP WITH TIME ZONE NOT NULL,
    request_id VARCHAR(255) NOT NULL DEFAULT '',
    source_uri TEXT NOT NULL DEFAULT '',
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX fx_quote_audit_pair_time_idx
    ON fx_quote_audit (base_currency, quote_currency, fetched_at DESC);
```

Adjust identity/JSON syntax for your database. The schema is a reference, not a migration PyTender owns.

## Audit failure policy

`AuditedRateProvider` is explicit:

```python
from pytender.infrastructure import AuditedRateProvider, HookFailureMode

# Compliance-sensitive: pricing fails if the audit write fails.
strict = AuditedRateProvider(provider, sink, failure_mode=HookFailureMode.FAIL_CLOSED)

# Availability-sensitive: rate succeeds even if audit storage is temporarily down.
best_effort = AuditedRateProvider(provider, sink, failure_mode=HookFailureMode.FAIL_OPEN)
```

Choose this as a business/compliance decision; do not accept a hidden default without understanding it. The default remains `FAIL_CLOSED` for audit.
