from pytender import (
    DEFAULT_REGISTRY,
    ISO_SNAPSHOT_DATE,
)

def test_catalog_is_large_and_current_snapshot():
    assert len(DEFAULT_REGISTRY) >= 180
    assert ISO_SNAPSHOT_DATE == "2026-08-15"
    assert DEFAULT_REGISTRY.contains("XCG")
    assert DEFAULT_REGISTRY.contains("ZWG")
    assert not DEFAULT_REGISTRY.contains("BGN")
def test_three_decimal_currency(): assert DEFAULT_REGISTRY.get("KWD").exponent == 3
def test_zero_decimal_currency(): assert DEFAULT_REGISTRY.get("JPY").exponent == 0
