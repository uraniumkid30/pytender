from __future__ import annotations

try:
    from babel.numbers import format_currency
except ImportError as exc:  # pragma: no cover
    raise ImportError("Babel formatter requires PyTender[babel]") from exc

from ..money import Money


class BabelMoneyFormatter:
    """CLDR-backed locale-aware formatter using optional Babel."""

    __slots__ = ("locale", "pattern", "currency_digits", "decimal_quantization", "group_separator")

    def __init__(
        self,
        locale: str,
        *,
        format: str | None = None,
        currency_digits: bool = True,
        decimal_quantization: bool = True,
        group_separator: bool = True,
    ) -> None:
        self.locale = locale
        self.pattern = format
        self.currency_digits = currency_digits
        self.decimal_quantization = decimal_quantization
        self.group_separator = group_separator

    def format_money(self, money: Money) -> str:
        """Format Money using Babel/CLDR locale and currency rules."""
        return str(
            format_currency(
                money.major,
                str(money.currency.code),
                format=self.pattern,
                locale=self.locale,
                currency_digits=self.currency_digits,
                decimal_quantization=self.decimal_quantization,
                group_separator=self.group_separator,
            )
        )

    def format(self, money: Money) -> str:  # type: ignore[no-redef]
        """Implement the MoneyFormatter protocol with Babel/CLDR."""
        return self.format_money(money)
