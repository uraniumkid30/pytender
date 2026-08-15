from decimal import Decimal

import pytest

httpx = pytest.importorskip("httpx")

from pytender import CurrencyCode
from pytender.providers.frankfurter import FrankfurterProvider


def handler(request):
    return httpx.Response(
        200,
        json={
            "date": "2026-08-14",
            "base": "USD",
            "quote": "EUR",
            "rate": 0.85,
        },
    )


def test_sync_http_provider_parses_decimal_and_provenance() -> None:
    client = httpx.Client(
        transport=httpx.MockTransport(handler),
        base_url="https://example.test",
    )
    try:
        rate = FrankfurterProvider(client=client).get_rate(
            CurrencyCode("USD"), CurrencyCode("EUR")
        )
        assert rate.value == Decimal("0.85")
        assert rate.provenance.as_of is not None
    finally:
        client.close()
