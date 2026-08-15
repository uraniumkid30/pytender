# Database storage

## Production recommendation

For query-heavy financial tables and ledgers, prefer native columns:

```text
amount_minor   BIGINT / NUMERIC / DECIMAL(precision, 0) NOT NULL
currency_code CHAR(3)                                  NOT NULL
```

Choose the integer SQL type from your actual maximum amount requirements. Python `int` is arbitrary precision; database `BIGINT` is not.

A PostgreSQL example:

```sql
CREATE TABLE ledger_entry (
    id BIGSERIAL PRIMARY KEY,
    amount_minor NUMERIC(38, 0) NOT NULL,
    currency_code CHAR(3) NOT NULL,
    CHECK (currency_code ~ '^[A-Z]{3}$')
);
CREATE INDEX ledger_entry_currency_idx ON ledger_entry(currency_code);
CREATE INDEX ledger_entry_amount_idx ON ledger_entry(amount_minor);
```

`NUMERIC(38, 0)` is only an example limit. Select a precision appropriate for your domain.

## Canonical adapter helpers

```python
from moneytender.adapters.database import from_columns, to_columns

columns = to_columns(money)
restored = from_columns(columns["amount_minor"], columns["currency_code"])
```

These functions never round-trip through a floating-point or major-unit representation.

## Django and SQLAlchemy JSON adapters

`MoneyField` and `MoneyType` are convenience integrations for ordinary application data. They are not advertised as an optimal ledger schema. JSON is less convenient for SQL aggregation, numeric range queries, indexing, constraints, reporting and accounting workloads.

## Database test matrix

MoneyTender's pure column adapter is database-neutral. Applications must test their chosen SQL types against their actual database engine, including:

- maximum/minimum numeric values;
- negative and zero values;
- NULL policy;
- migration behavior;
- check constraints;
- indexing and query plans;
- ORM serialization;
- PostgreSQL/MySQL/SQLite differences.

MoneyTender cannot promise that an application's chosen column type can store every Python integer.

The repository CI includes SQLAlchemy integration jobs for SQLite, PostgreSQL and MySQL. These verify both the JSON convenience adapter and a native `NUMERIC(38, 0)` + three-character currency-code representation. Engine-specific constraints, migration plans and production query plans remain application responsibilities.
