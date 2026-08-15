from __future__ import annotations

import json
from datetime import UTC, datetime, time
from decimal import Decimal
from types import TracebackType
from typing import Any, Self

from .._version import __version__
from ..exceptions import ProviderError, RateUnavailableError
from ..fx import ExchangeRate, RateProvenance
from ..types import CurrencyCode

try:
    import httpx
except ImportError as exc:  # pragma: no cover
    raise ImportError(
        "Frankfurter providers require MoneyTender[http]: pip install 'MoneyTender[http]'"
    ) from exc

_API = "https://api.frankfurter.dev"


def _decode(text: str) -> dict[str, Any]:
    data = json.loads(text, parse_float=Decimal)
    if not isinstance(data, dict):
        raise ProviderError("Frankfurter returned an unexpected JSON shape")
    return data


def _build(data: dict[str, Any], source_uri: str) -> ExchangeRate:
    try:
        base = CurrencyCode(str(data["base"]).upper())
        quote = CurrencyCode(str(data["quote"]).upper())
        raw = data["rate"]
        value = raw if isinstance(raw, Decimal) else Decimal(str(raw))
        as_of = datetime.combine(
            datetime.strptime(str(data["date"]), "%Y-%m-%d").date(),
            time.min,
            tzinfo=UTC,
        )
    except (KeyError, ValueError, TypeError) as exc:
        raise ProviderError("Frankfurter response is missing valid base/quote/rate/date fields") from exc
    return ExchangeRate(base, quote, value, RateProvenance("frankfurter", source_uri, as_of))


class FrankfurterProvider:
    """Synchronous Frankfurter v2 provider. Reuse and close long-lived instances."""

    __slots__ = (
        "_client",
        "_owned",
    )

    def __init__(self, *, client: httpx.Client | None = None, timeout: float = 5.0) -> None:
        self._owned = client is None
        self._client = client or httpx.Client(
            base_url=_API,
            timeout=timeout,
            headers={"User-Agent": f"MoneyTender/{__version__}"},
        )

    def get_rate(self, base: CurrencyCode, quote: CurrencyCode) -> ExchangeRate:
        """Fetch one direct Frankfurter reference quote."""
        if base == quote:
            return ExchangeRate(base, quote, Decimal("1"), RateProvenance("identity"))
        path = f"/v2/rate/{base}/{quote}"
        try:
            response = self._client.get(path)
        except httpx.HTTPError as exc:
            raise ProviderError(f"Frankfurter network failure for {base}/{quote}: {exc}") from exc
        if response.status_code in {404, 422}:
            raise RateUnavailableError(f"Frankfurter has no usable rate for {base}/{quote}")
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise ProviderError(
                f"Frankfurter returned HTTP {response.status_code} for {base}/{quote}"
            ) from exc
        return _build(_decode(response.text), str(response.request.url))

    def close(self) -> None:
        """Close the internally owned HTTP client, if any."""
        if self._owned:
            self._client.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()


class AsyncFrankfurterProvider:
    """Asynchronous Frankfurter v2 provider. Prefer one instance per application."""

    __slots__ = (
        "_client",
        "_owned",
    )

    def __init__(self, *, client: httpx.AsyncClient | None = None, timeout: float = 5.0) -> None:
        self._owned = client is None
        self._client = client or httpx.AsyncClient(
            base_url=_API,
            timeout=timeout,
            headers={"User-Agent": f"MoneyTender/{__version__}"},
        )

    async def get_rate(self, base: CurrencyCode, quote: CurrencyCode) -> ExchangeRate:
        """Fetch one direct Frankfurter reference quote asynchronously."""
        if base == quote:
            return ExchangeRate(base, quote, Decimal("1"), RateProvenance("identity"))
        path = f"/v2/rate/{base}/{quote}"
        try:
            response = await self._client.get(path)
        except httpx.HTTPError as exc:
            raise ProviderError(f"Frankfurter network failure for {base}/{quote}: {exc}") from exc
        if response.status_code in {404, 422}:
            raise RateUnavailableError(f"Frankfurter has no usable rate for {base}/{quote}")
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise ProviderError(
                f"Frankfurter returned HTTP {response.status_code} for {base}/{quote}"
            ) from exc
        return _build(_decode(response.text), str(response.request.url))

    async def aclose(self) -> None:
        """Close the internally owned asynchronous HTTP client, if any."""
        if self._owned:
            await self._client.aclose()

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        await self.aclose()
