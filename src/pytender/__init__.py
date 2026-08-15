"""MoneyTender's small, stable public API.

Most applications only need :class:`Money` and :class:`MoneyConverter`.
Operational FX decorators (retry, circuit breaking, rate limiting, caching,
audit/observation, production builders) live under :mod:`moneytender.infrastructure`
so beginners do not need to understand them to use money safely.
"""

from ._version import __version__
from .exceptions import (
    AdapterError,
    AllocationError,
    CircuitOpenError,
    ConversionError,
    CurrencyError,
    CurrencyMismatchError,
    DuplicateCurrencyError,
    InvalidAmountError,
    InvalidRateError,
    MoneyError,
    ProviderError,
    RatePolicyError,
    RateUnavailableError,
    RegistryFrozenError,
    RoundingError,
    StaleRateError,
    UnknownCurrencyError,
)
from .formatting import DEFAULT_FORMATTER, MoneyFormatter, SimpleMoneyFormatter
from .fx import (
    AsyncExchangeRateProvider,
    AsyncMoneyConverter,
    ConversionResult,
    ExchangeRate,
    ExchangeRateProvider,
    MoneyConverter,
    RateProvenance,
    StaticRateProvider,
)
from .money import Money
from .policy import (
    DerivationKind,
    MissingTimestampPolicy,
    RateKind,
    RatePolicy,
    RateValidator,
)
from .registry import DEFAULT_REGISTRY, ISO_SNAPSHOT_DATE, CurrencyRegistry
from .rounding import (
    DEFAULT_ROUNDING,
    DecimalRounding,
    DownRounding,
    HalfEvenRounding,
    HalfUpRounding,
    RoundingPolicy,
    UpRounding,
    round_to_increment,
)
from .serialization import (
    MoneyPayload,
    from_dict,
    to_dict,
)
from .types import Currency, CurrencyCode, CurrencyStatus, MinorUnits

__all__ = [
    "DEFAULT_FORMATTER",
    "DEFAULT_REGISTRY",
    "DEFAULT_ROUNDING",
    "ISO_SNAPSHOT_DATE",
    "AdapterError",
    "AllocationError",
    "AsyncExchangeRateProvider",
    "AsyncMoneyConverter",
    "CircuitOpenError",
    "ConversionError",
    "ConversionResult",
    "Currency",
    "CurrencyCode",
    "CurrencyError",
    "CurrencyMismatchError",
    "CurrencyRegistry",
    "CurrencyStatus",
    "DecimalRounding",
    "DerivationKind",
    "DownRounding",
    "DuplicateCurrencyError",
    "ExchangeRate",
    "ExchangeRateProvider",
    "HalfEvenRounding",
    "HalfUpRounding",
    "InvalidAmountError",
    "InvalidRateError",
    "MinorUnits",
    "MissingTimestampPolicy",
    "Money",
    "MoneyConverter",
    "MoneyError",
    "MoneyFormatter",
    "MoneyPayload",
    "ProviderError",
    "RateKind",
    "RatePolicy",
    "RatePolicyError",
    "RateProvenance",
    "RateUnavailableError",
    "RateValidator",
    "RegistryFrozenError",
    "RoundingError",
    "RoundingPolicy",
    "SimpleMoneyFormatter",
    "StaleRateError",
    "StaticRateProvider",
    "UnknownCurrencyError",
    "UpRounding",
    "__version__",
    "from_dict",
    "round_to_increment",
    "to_dict",
]
