import pytest

from moneytender import ProviderError
from moneytender.infrastructure import (
    discover_provider_plugins,
    load_provider_plugin,
)


def test_plugin_discovery_is_safe_without_plugins():
    assert isinstance(discover_provider_plugins(), dict)


def test_missing_plugin_has_actionable_error():
    with pytest.raises(ProviderError, match="not installed"):
        load_provider_plugin("definitely-not-installed-moneytender-provider")
