from __future__ import annotations


class MoneyError(Exception):
    """Base class for all MoneyTender-defined errors."""


class InvalidAmountError(MoneyError, ValueError):
    """A monetary input cannot be represented safely."""


class CurrencyError(MoneyError, ValueError):
    """Base class for currency metadata failures."""


class UnknownCurrencyError(CurrencyError):
    """The requested currency is not registered."""


class DuplicateCurrencyError(CurrencyError):
    """Registration would overwrite an existing currency without explicit permission."""


class RegistryFrozenError(CurrencyError):
    """A caller attempted to mutate an immutable currency registry."""


class CurrencyMismatchError(CurrencyError):
    """An operation mixed incompatible currency definitions without conversion."""


class AllocationError(MoneyError, ValueError):
    """Money allocation or splitting inputs are invalid."""


class RoundingError(MoneyError, ValueError):
    """A rounding rule or increment is invalid."""


class ConversionError(MoneyError):
    """Base class for FX conversion failures."""


class InvalidRateError(ConversionError, ValueError):
    """An FX rate is non-finite, zero, negative, malformed, or internally inconsistent."""


class RateUnavailableError(ConversionError):
    """A provider cannot supply the requested currency pair."""


class RatePolicyError(ConversionError):
    """An otherwise valid FX quote violates the caller's business rate policy."""


class StaleRateError(RatePolicyError):
    """An FX quote is older than the configured business-validity window."""


class ProviderError(ConversionError):
    """An exchange-rate provider failed unexpectedly."""


class CircuitOpenError(ProviderError):
    """A provider call was rejected because its circuit breaker is open."""


class AdapterError(MoneyError):
    """An optional framework adapter cannot encode or decode a Money value."""


__all__ = [
    "AdapterError",
    "AllocationError",
    "CircuitOpenError",
    "ConversionError",
    "CurrencyError",
    "CurrencyMismatchError",
    "DuplicateCurrencyError",
    "InvalidAmountError",
    "InvalidRateError",
    "MoneyError",
    "ProviderError",
    "RatePolicyError",
    "RateUnavailableError",
    "RegistryFrozenError",
    "RoundingError",
    "StaleRateError",
    "UnknownCurrencyError",
]
