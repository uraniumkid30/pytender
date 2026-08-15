from __future__ import annotations

import os
from decimal import Decimal

import pytest

pytest.importorskip("sqlalchemy")

from sqlalchemy import (
    Column,
    Integer,
    String,
    create_engine,
)
from sqlalchemy.orm import DeclarativeBase, Session

from moneytender import Money
from moneytender.adapters.sqlalchemy import MinorUnitsType, MoneyType

DATABASE_URL = os.getenv("PYTENDER_DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not DATABASE_URL,
    reason="set PYTENDER_DATABASE_URL to run external database integration tests",
)


class Base(DeclarativeBase):
    pass


class JsonMoneyRecord(Base):
    __tablename__ = "moneytender_money_json_integration"

    id = Column(Integer, primary_key=True)
    amount = Column(MoneyType, nullable=False)


class NativeMoneyRecord(Base):
    __tablename__ = "moneytender_money_native_integration"
    id = Column(Integer, primary_key=True)
    amount_minor = Column(MinorUnitsType(38), nullable=False, index=True)
    currency_code = Column(String(3), nullable=False, index=True)


def _roundtrip_json(values: list[Money]) -> list[Money]:
    assert DATABASE_URL is not None
    engine = create_engine(DATABASE_URL)
    try:
        Base.metadata.drop_all(engine)
        Base.metadata.create_all(engine, tables=[JsonMoneyRecord.__table__])
        with Session(engine) as session:
            session.add_all(JsonMoneyRecord(amount=value) for value in values)
            session.commit()
            return [row.amount for row in session.query(JsonMoneyRecord).order_by(JsonMoneyRecord.id)]
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()


def test_json_money_adapter_roundtrips_negative_zero_and_large_values() -> None:
    values = [
        Money.from_minor(-12345, "USD"),
        Money.from_minor(0, "JPY"),
        Money.from_minor(9_223_372_036_854_775_000, "EUR"),
    ]
    assert _roundtrip_json(values) == values


def test_recommended_native_columns_roundtrip_large_exact_values() -> None:
    assert DATABASE_URL is not None
    engine = create_engine(DATABASE_URL)
    try:
        Base.metadata.drop_all(engine)
        Base.metadata.create_all(engine, tables=[NativeMoneyRecord.__table__])
        values = [
            (-12345, "USD"),
            (0, "JPY"),
            (10**30 + 123456789, "EUR"),
        ]
        with Session(engine) as session:
            session.add_all(
                NativeMoneyRecord(amount_minor=amount, currency_code=currency) for amount, currency in values
            )
            session.commit()
            restored = [
                (int(row.amount_minor), row.currency_code)
                for row in session.query(NativeMoneyRecord).order_by(NativeMoneyRecord.id)
            ]
        assert restored == values
        assert all(isinstance(row[0], int) for row in restored)
        assert Decimal(restored[-1][0]) == Decimal(values[-1][0])
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()
