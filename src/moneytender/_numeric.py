from __future__ import annotations


def integer_decimal_digits(value: int) -> int:
    """Return a safe upper bound for base-10 digits without converting ``int`` to text.

    Python can intentionally reject decimal string conversion of extremely large
    integers. Precision sizing only needs a conservative upper bound, so derive it
    from ``bit_length`` using a slight upper approximation of log10(2).
    """
    if value == 0:
        return 1
    bits = abs(value).bit_length()
    return max(1, (bits * 30_103) // 100_000 + 1)
