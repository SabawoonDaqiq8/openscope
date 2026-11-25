"""Spend normalisation for spend-based (EEIO) emission factors.

A spend-based factor such as "0.35 kg CO2e per USD (2022)" is only valid for spend in
**that currency** and **that price year**. Applying it to 2025 EUR spend needs:

1. **Currency conversion** at the spend year's average exchange rate, then
2. **Deflation** from the spend year to the factor's price year with a price index for the
   factor's currency (e.g. a GDP deflator or producer price index).

``amount_factor = amount × FX(spend_ccy→factor_ccy, spend_year) × index[factor_year] /
index[spend_year]``

openscope ships **no** FX or price-index data: you supply them from an authoritative
source (central bank, statistics office), so every adjustment can be traced. Purchaser vs
basic price margins are not handled here; apply them in the factor dataset if needed.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from pathlib import Path

from openscope.errors import OpenScopeError


class SpendNormalisationError(OpenScopeError):
    """Raised when an exchange rate or price index needed for spend normalisation is missing."""


@dataclass
class FXTable:
    """Annual average FX rates: ``rates[(year, "EUR", "USD")] = 1.08`` means 1 EUR = 1.08 USD."""

    rates: dict[tuple[int, str, str], float] = field(default_factory=dict)
    source: str = "user-supplied"

    def add(self, year: int, from_ccy: str, to_ccy: str, rate: float) -> None:
        if rate <= 0:
            raise ValueError("FX rate must be positive")
        self.rates[(year, from_ccy.upper(), to_ccy.upper())] = rate

    def rate(self, year: int, from_ccy: str, to_ccy: str) -> float:
        f, t = from_ccy.upper(), to_ccy.upper()
        if f == t:
            return 1.0
        if (r := self.rates.get((year, f, t))) is not None:
            return r
        if (r := self.rates.get((year, t, f))) is not None:
            return 1 / r
        raise SpendNormalisationError(f"No {year} exchange rate between {f} and {t}")

    @classmethod
    def from_csv(cls, path: str | Path) -> FXTable:
        """CSV columns: ``year,from,to,rate`` (1 ``from`` = ``rate`` ``to``)."""
        table = cls(source=Path(path).name)
        with Path(path).open(newline="", encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                table.add(int(row["year"]), row["from"], row["to"], float(row["rate"]))
        return table


@dataclass
class PriceIndex:
    """Annual price index per currency, e.g. ``index[("USD", 2022)] = 127.2``."""

    index: dict[tuple[str, int], float] = field(default_factory=dict)
    source: str = "user-supplied"

    def add(self, currency: str, year: int, value: float) -> None:
        if value <= 0:
            raise ValueError("Price index must be positive")
        self.index[(currency.upper(), year)] = value

    def ratio(self, currency: str, from_year: int, to_year: int) -> float:
        """Multiplier converting money of ``from_year`` into ``to_year`` prices."""
        if from_year == to_year:
            return 1.0
        c = currency.upper()
        try:
            return self.index[(c, to_year)] / self.index[(c, from_year)]
        except KeyError:
            raise SpendNormalisationError(
                f"No {c} price index for {from_year} and/or {to_year}"
            ) from None

    @classmethod
    def from_csv(cls, path: str | Path) -> PriceIndex:
        """CSV columns: ``currency,year,index``."""
        pi = cls(source=Path(path).name)
        with Path(path).open(newline="", encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                pi.add(row["currency"], int(row["year"]), float(row["index"]))
        return pi


@dataclass
class SpendNormaliser:
    fx: FXTable = field(default_factory=FXTable)
    prices: PriceIndex = field(default_factory=PriceIndex)

    def normalise(
        self,
        amount: float,
        currency: str,
        spend_year: int,
        factor_currency: str,
        factor_year: int,
    ) -> tuple[float, list[str]]:
        """Return the amount in the factor's currency and price year, plus a trace."""
        trace: list[str] = []
        fx = self.fx.rate(spend_year, currency, factor_currency)
        converted = amount * fx
        if fx != 1.0:
            trace.append(
                f"FX: {amount:,.2f} {currency} × {fx:.6g} ({spend_year} avg, {self.fx.source}) "
                f"= {converted:,.2f} {factor_currency}"
            )
        ratio = self.prices.ratio(factor_currency, spend_year, factor_year)
        deflated = converted * ratio
        if ratio != 1.0:
            trace.append(
                f"Price year: {converted:,.2f} {factor_currency} ({spend_year}) × {ratio:.6g} "
                f"({self.prices.source}) = {deflated:,.2f} {factor_currency} ({factor_year} prices)"
            )
        return deflated, trace
