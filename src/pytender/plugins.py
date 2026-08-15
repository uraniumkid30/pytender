from __future__ import annotations

from importlib.metadata import EntryPoint, entry_points
from typing import Any, Protocol, runtime_checkable

from .exceptions import ProviderError
from .fx import ExchangeRateProvider

FX_PROVIDER_GROUP = "moneytender.fx_providers"


@runtime_checkable
class ProviderFactory(Protocol):
    """Factory contract used by third-party FX provider entry points."""

    def __call__(self, **config: Any) -> ExchangeRateProvider: ...


def discover_provider_plugins() -> dict[str, EntryPoint]:
    """Return installed FX provider entry points keyed by their advertised name."""
    return {ep.name: ep for ep in entry_points(group=FX_PROVIDER_GROUP)}


def load_provider_plugin(name: str, **config: Any) -> ExchangeRateProvider:
    """Load and construct an installed provider plugin by entry-point name."""
    plugins = discover_provider_plugins()
    try:
        ep = plugins[name]
    except KeyError as exc:
        available = ", ".join(sorted(plugins)) or "none"
        raise ProviderError(
            f"FX provider plugin {name!r} is not installed; available plugins: {available}"
        ) from exc
    try:
        factory = ep.load()
        provider = factory(**config)
    except Exception as exc:
        raise ProviderError(
            f"FX provider plugin {name!r} failed to initialize: {exc}"
        ) from exc
    if not isinstance(provider, ExchangeRateProvider):
        raise ProviderError(
            f"FX provider plugin {name!r} returned {type(provider).__name__}, "
            "which does not satisfy ExchangeRateProvider"
        )
    return provider
