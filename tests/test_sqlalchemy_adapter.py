import pytest

pytest.importorskip("sqlalchemy")

from sqlalchemy import (
    Column,
    Integer,
    create_engine,
)
from sqlalchemy.orm import DeclarativeBase, Session

from moneytender import Money
from moneytender.adapters.sqlalchemy import MoneyType


class Base(DeclarativeBase):
    pass


class Item(Base):
    __tablename__ = "item"

    id = Column(Integer, primary_key=True)
    price = Column(MoneyType, nullable=False)


def test_sqlalchemy_roundtrip() -> None:
    engine = create_engine("sqlite:///:memory:")
    try:
        Base.metadata.create_all(engine)
        with Session(engine) as session:
            session.add(Item(price=Money.from_minor(1234, "USD")))
            session.commit()
            item = session.query(Item).one()
            assert item.price.minor == 1234
    finally:
        engine.dispose()
