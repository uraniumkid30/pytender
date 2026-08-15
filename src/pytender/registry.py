from __future__ import annotations

from collections.abc import Iterable, Iterator
from threading import RLock
from types import MappingProxyType

from .exceptions import DuplicateCurrencyError, RegistryFrozenError, UnknownCurrencyError
from .iso4217 import ISO_4217_DATA, ISO_SNAPSHOT_DATE
from .types import Currency, CurrencyCode, CurrencyStatus


def _iso_defaults() -> tuple[Currency, ...]:
    return tuple(
        Currency(CurrencyCode(code), exponent, symbol, name, numeric, cash_increment)
        for code, (numeric, exponent, symbol, name, cash_increment) in ISO_4217_DATA.items()
    )


class CurrencyRegistry:
    """Thread-safe registry for currency metadata.

    The process-wide :data:`DEFAULT_REGISTRY` is frozen. Applications that need
    private currencies or metadata overrides should call ``DEFAULT_REGISTRY.clone()``
    (or ``CurrencyRegistry.iso4217()``), modify that application-owned registry,
    and pass it explicitly to constructors/converters.
    """

    __slots__ = (
        "_currencies",
        "_frozen",
        "_lock",
    )

    def __init__(self, currencies: Iterable[Currency] = (), *, frozen: bool = False) -> None:
        self._currencies: dict[CurrencyCode, Currency] = {}
        self._lock = RLock()
        self._frozen = False
        self.register_many(currencies)
        self._frozen = frozen

    @classmethod
    def iso4217(cls, *, frozen: bool = False) -> "CurrencyRegistry":
        """Create an independent registry populated with PyTender's ISO snapshot."""
        return cls(_iso_defaults(), frozen=frozen)

    @property
    def is_frozen(self) -> bool:
        """Return whether mutation has been disabled for this registry."""
        with self._lock:
            return self._frozen

    def freeze(self) -> "CurrencyRegistry":
        """Freeze this registry in place and return it for fluent construction."""
        with self._lock:
            self._frozen = True
        return self

    def clone(self, *, frozen: bool = False) -> "CurrencyRegistry":
        """Return an independent copy, mutable by default."""
        return CurrencyRegistry(self.snapshot().values(), frozen=frozen)

    def register(self, currency: Currency, *, replace: bool = False) -> None:
        """Register ``currency`` or explicitly replace an existing definition."""
        code = CurrencyCode(str(currency.code).upper())
        with self._lock:
            self._require_mutable()
            if code in self._currencies and not replace:
                raise DuplicateCurrencyError(
                    f"currency {code} is already registered; pass replace=True to override it"
                )
            self._currencies[code] = currency

    def register_many(self, currencies: Iterable[Currency], *, replace: bool = False) -> None:
        """Register several currencies as one validated batch.

        When ``replace`` is false, all duplicate checks happen before any mutation so
        a failing batch cannot leave the registry partially updated.
        """
        batch = tuple(currencies)
        with self._lock:
            self._require_mutable()
            if not replace:
                seen: set[CurrencyCode] = set()
                for currency in batch:
                    code = CurrencyCode(str(currency.code).upper())
                    if code in seen or code in self._currencies:
                        raise DuplicateCurrencyError(
                            f"currency {code} is already registered; pass replace=True to override it"
                        )
                    seen.add(code)
            for currency in batch:
                code = CurrencyCode(str(currency.code).upper())
                self._currencies[code] = currency

    def unregister(self, code: str | CurrencyCode) -> Currency:
        """Remove and return a currency definition."""
        normalized = CurrencyCode(str(code).upper())
        with self._lock:
            self._require_mutable()
            try:
                return self._currencies.pop(normalized)
            except KeyError as exc:
                raise UnknownCurrencyError(f"currency {normalized!r} is not registered") from exc

    def get(self, code: str | CurrencyCode) -> Currency:
        """Resolve a currency by its normalized three-letter code."""
        normalized = CurrencyCode(str(code).upper())
        with self._lock:
            try:
                return self._currencies[normalized]
            except KeyError as exc:
                raise UnknownCurrencyError(
                    f"currency {normalized!r} is not registered; use an application-owned "
                    "CurrencyRegistry and register custom currencies there"
                ) from exc

    def contains(self, code: str | CurrencyCode) -> bool:
        """Return whether ``code`` is registered."""
        normalized = CurrencyCode(str(code).upper())
        with self._lock:
            return normalized in self._currencies

    def snapshot(self) -> MappingProxyType[CurrencyCode, Currency]:
        """Return an immutable point-in-time copy safe for concurrent iteration."""
        with self._lock:
            return MappingProxyType(dict(self._currencies))

    def current(self) -> tuple[Currency, ...]:
        """Return current currencies in deterministic code order."""
        values = self.snapshot().values()
        return tuple(
            sorted(
                (currency for currency in values if currency.status is CurrencyStatus.CURRENT),
                key=lambda currency: currency.code,
            )
        )

    def historical(self) -> tuple[Currency, ...]:
        """Return historical currencies in deterministic code order."""
        values = self.snapshot().values()
        return tuple(
            sorted(
                (currency for currency in values if currency.status is CurrencyStatus.HISTORICAL),
                key=lambda currency: currency.code,
            )
        )

    def __len__(self) -> int:
        with self._lock:
            return len(self._currencies)

    def __iter__(self) -> Iterator[Currency]:
        return iter(tuple(self.snapshot().values()))

    def _require_mutable(self) -> None:
        if self._frozen:
            raise RegistryFrozenError(
                "this CurrencyRegistry is frozen; clone DEFAULT_REGISTRY and mutate the clone instead"
            )


DEFAULT_REGISTRY = CurrencyRegistry.iso4217(frozen=True)

__all__ = [
    "DEFAULT_REGISTRY",
    "ISO_SNAPSHOT_DATE",
    "CurrencyRegistry",
]
