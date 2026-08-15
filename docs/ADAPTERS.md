# Framework adapters

Adapters are optional and never imported by `pytender` core.

## Pydantic v2

`MoneyModel` uses `{amount: integer_minor_units, currency: "USD"}` and forbids unknown fields. Convert with `.to_money()` / `.from_money()`.

## SQLAlchemy 2

`MoneyType` is a portable JSON `TypeDecorator`. This is ideal for application objects and portability. For analytical ledgers, use two native indexed columns (`BIGINT/NUMERIC` amount + `CHAR(3)` currency) and construct `Money` in your repository/domain mapper.

## Django

`MoneyField` is JSON-backed and portable. For high-volume ledgers or SQL aggregation, prefer two explicit columns for queryability and indexing. The adapter is deliberately ergonomic rather than pretending JSON is the best schema for every financial workload.
