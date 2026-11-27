"""Importer for the AIB European Residual Mixes (Association of Issuing Bodies).

The AIB publishes, each spring, the residual mix of each European country for the previous
calendar year: https://www.aib-net.org/facts/european-residual-mix

The **residual mix** is what is left of a country's generation after the attributes claimed
through guarantees of origin are taken out. Under the GHG Protocol Scope 2 Guidance it is the
market-based factor for electricity bought without a contractual instrument. The same workbook
gives the **production mix** (the generation inside the country), which is used here as the
location-based factor.

Format notes (verified against the 2025 results workbook, published May 2026):

* Sheet ``CO2``: ``Country code, Production mix CO2, Residual mix CO2, Supplier mix CO2`` in
  g CO2/kWh. ``NA`` where no residual mix is published (AT, CH and NL in 2025); use the
  supplier's disclosed mix for electricity bought there.
* Sheets ``Residual Mixes`` and ``Production Mix``: one row per country with shares for
  ``RE Total``, ``Nuclear`` and ``FO Total`` (fractions, or ``"9.78%"`` text in a few rows).

What the factors cover: **direct CO2 from combustion only**. No CH4 or N2O, no upstream
(life-cycle) emissions and no transmission and distribution losses. State this in the basis
of preparation.

Licence: the AIB data is copyright of the AIB and is not redistributed with openscope. Run this
importer on a workbook you have downloaded yourself and cite the AIB wherever you use it.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from openscope.errors import FactorError
from openscope.models import EmissionFactor, EnergySource, FactorStatus, Scope, Scope2Method

SOURCE_URL = "https://www.aib-net.org/facts/european-residual-mix"
MIX_TOLERANCE = 0.01  # shares are published to 4 decimals; allow rounding

COUNTRIES = {
    "AT": "Austria", "BA": "Bosnia and Herzegovina", "BE": "Belgium", "BG": "Bulgaria",
    "CH": "Switzerland", "CY": "Cyprus", "CZ": "Czechia", "DE": "Germany", "DK": "Denmark",
    "EE": "Estonia", "ES": "Spain", "FI": "Finland", "FR": "France", "GB": "Great Britain",
    "GR": "Greece", "HR": "Croatia", "HU": "Hungary", "IE": "Ireland", "IS": "Iceland",
    "IT": "Italy", "LT": "Lithuania", "LU": "Luxembourg", "LV": "Latvia", "ME": "Montenegro",
    "MK": "North Macedonia", "MT": "Malta", "NL": "Netherlands", "NO": "Norway",
    "PL": "Poland", "PT": "Portugal", "RO": "Romania", "RS": "Serbia", "SE": "Sweden",
    "SI": "Slovenia", "SK": "Slovakia", "UA": "Ukraine", "XK": "Kosovo",
}  # fmt: skip

_COUNTRY = re.compile(r"^[A-Z]{2}$")


@dataclass
class ImportReport:
    factors: list[EmissionFactor]
    residual: int = 0
    production: int = 0
    with_mix: int = 0
    no_residual_mix: list[str] = field(default_factory=list)  # published as NA
    mix_not_reconciled: list[str] = field(default_factory=list)


def _number(v: Any) -> float | None:
    """A cell as a number; ``"9.78%"`` becomes 0.0978. ``NA`` and blanks are None."""
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, int | float):
        return float(v)
    text = str(v).strip().replace(",", ".")
    if not text or text.upper() in ("NA", "N/A", "-"):
        return None
    try:
        return float(text[:-1]) / 100 if text.endswith("%") else float(text)
    except ValueError:
        return None


def _header(cell: Any) -> str:
    return " ".join(str(cell or "").split()).lower()


def _rows_by_country(rows: Iterable[Sequence[Any]]) -> tuple[list[str], dict[str, Sequence[Any]]]:
    """Header (lower-cased) and data rows keyed by two-letter country code."""
    header: list[str] = []
    out: dict[str, Sequence[Any]] = {}
    for row in rows:
        if not row:
            continue
        first = str(row[0] or "").strip()
        if not header and any(_header(c) in ("re total", "residual mix co2") for c in row):
            header = [_header(c) for c in row]
            continue
        if header and _COUNTRY.match(first):
            out[first] = row
    if not header:
        raise FactorError("AIB workbook: header row not found")
    return header, out


def _col(header: list[str], *names: str) -> int:
    for name in names:
        if name in header:
            return header.index(name)
    raise FactorError(f"AIB workbook: column {names[0]!r} not found")


def _mix(header: list[str], row: Sequence[Any]) -> tuple[float, float, float] | None | Exception:
    """(fossil, nuclear, renewable) shares; None if not published; an error if inconsistent."""
    values = [
        _number(row[_col(header, name)]) if _col(header, name) < len(row) else None
        for name in ("fo total", "nuclear", "re total")
    ]
    if any(v is None for v in values):
        return None
    fossil, nuclear, renewable = (v or 0.0 for v in values)
    total = fossil + nuclear + renewable
    if abs(total - 1) > MIX_TOLERANCE or min(fossil, nuclear, renewable) < 0:
        return ValueError(f"shares sum to {total:.4f}")
    return (fossil / total, nuclear / total, renewable / total)


def parse(
    co2_rows: Iterable[Sequence[Any]],
    residual_rows: Iterable[Sequence[Any]],
    production_rows: Iterable[Sequence[Any]],
    year: int,
) -> ImportReport:
    co2_header, co2 = _rows_by_country(co2_rows)
    rm_header, residual = _rows_by_country(residual_rows)
    pm_header, production = _rows_by_country(production_rows)
    i_pm = _col(co2_header, "production mix co2")
    i_rm = _col(co2_header, "residual mix co2")

    report = ImportReport(factors=[])
    for code in sorted(co2):
        row = co2[code]
        country = COUNTRIES.get(code, code)
        for kind, idx, mixes, header in (
            ("residual", i_rm, residual, rm_header),
            ("production", i_pm, production, pm_header),
        ):
            g_per_kwh = _number(row[idx]) if idx < len(row) else None
            if g_per_kwh is None:
                if kind == "residual":
                    report.no_residual_mix.append(code)
                continue
            mix = _mix(header, mixes[code]) if code in mixes else None
            if isinstance(mix, Exception):
                report.mix_not_reconciled.append(f"{code} {kind}: {mix}")
                mix = None
            report.factors.append(_factor(code, country, kind, g_per_kwh, mix, year))
            if kind == "residual":
                report.residual += 1
            else:
                report.production += 1
            report.with_mix += mix is not None
    if not report.factors:
        raise FactorError("AIB workbook: no country factors found")
    return report


def _factor(
    code: str,
    country: str,
    kind: str,
    g_per_kwh: float,
    mix: tuple[float, float, float] | None,
    year: int,
) -> EmissionFactor:
    residual = kind == "residual"
    scope_note = (
        "Market-based factor for electricity bought without guarantees of origin or another "
        "contractual instrument."
        if residual
        else "National production mix (generation inside the country, before trade), used as "
        "the location-based factor."
    )
    return EmissionFactor(
        factor_id=f"AIB-{year}-{'RM' if residual else 'PM'}-{code}",
        name=f"Electricity: {kind} mix, {country} ({code})",
        activity_unit="kWh",
        gases={"CO2": g_per_kwh / 1000},
        scope=Scope.SCOPE_2,
        scope2_method=Scope2Method.MARKET_BASED if residual else Scope2Method.LOCATION_BASED,
        region=code,
        year=year,
        source=f"AIB European Residual Mixes {year}",
        source_url=SOURCE_URL,
        status=FactorStatus.REFERENCE,
        notes=f"{scope_note} Direct CO2 from combustion only: no CH4/N2O, upstream emissions "
        "or grid losses. Source: Association of Issuing Bodies (AIB).",
        energy_kwh_per_unit=1.0,
        energy_source=EnergySource.ELECTRICITY,
        fossil_share=mix[0] if mix else None,
        nuclear_share=mix[1] if mix else None,
        renewable_share=mix[2] if mix else None,
    )


def read_workbook(path: str | Path, year: int | None = None) -> ImportReport:
    try:
        import openpyxl
    except ImportError as exc:  # pragma: no cover - optional dependency
        raise FactorError("Reading AIB workbooks needs openpyxl: pip install openpyxl") from exc

    path = Path(path)
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    try:
        for sheet in ("CO2", "Residual Mixes", "Production Mix"):
            if sheet not in wb.sheetnames:
                raise FactorError(f"{path.name}: sheet {sheet!r} not found; is this the AIB file?")
        if year is None:
            found = re.search(r"20\d\d", path.name)
            if not found:
                raise FactorError(f"{path.name}: cannot tell the year from the name; pass --year")
            year = int(found.group())
        return parse(
            wb["CO2"].iter_rows(values_only=True),
            wb["Residual Mixes"].iter_rows(values_only=True),
            wb["Production Mix"].iter_rows(values_only=True),
            year,
        )
    finally:
        wb.close()
