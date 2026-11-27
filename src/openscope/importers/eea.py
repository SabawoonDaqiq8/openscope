"""Importer for the EEA indicator "Greenhouse gas emission intensity of electricity generation".

https://www.eea.europa.eu/en/analysis/indicators/greenhouse-gas-emission-intensity-of-1

The European Environment Agency publishes the GHG intensity of electricity generation for each
EU Member State and the EU-27, from 1990, in g CO2e per kWh. openscope uses it as the
**location-based** Scope 2 factor for electricity consumed in EU countries.

Source: the country-level figure (Figure 2) of the indicator, read from the EEA website's
content API as JSON::

    https://www.eea.europa.eu/++api++/en/analysis/indicators/greenhouse-gas-emission-intensity-of-1/greenhouse-gas-emission-intensity-of-electricity-generation

The JSON's ``visualization.dataSources`` holds a ``Countries`` column and one column per year.

What the values mean (EEA methodology):

* CO2e emissions from all electricity production (main activity producers and autoproducers,
  excluding emissions attributed to heat) divided by total gross electricity generation,
  including nuclear and renewables. Emissions come from the national inventories reported to
  the UNFCCC and the EU, which use IPCC AR5 GWPs.
* **Generation-based**: electricity imports and exports are not taken into account, and
  transmission and distribution losses and upstream (well-to-tank) emissions are excluded.
* Published as whole grams per kWh. The latest year is an EEA early estimate.

Licence: EEA content may be re-used free of charge, including commercially, provided the EEA
is acknowledged as the source and the meaning is not distorted.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from openscope.errors import FactorError
from openscope.models import EmissionFactor, EnergySource, FactorStatus, Scope, Scope2Method

SOURCE_URL = (
    "https://www.eea.europa.eu/en/analysis/indicators/greenhouse-gas-emission-intensity-of-1"
)
API_URL = (
    "https://www.eea.europa.eu/++api++/en/analysis/indicators/greenhouse-gas-emission-intensity-"
    "of-1/greenhouse-gas-emission-intensity-of-electricity-generation"
)
FIRST_YEAR = 2015  # older years add size without use for current reporting

COUNTRY_CODES = {
    "Austria": "AT", "Belgium": "BE", "Bulgaria": "BG", "Croatia": "HR", "Cyprus": "CY",
    "Czech Republic": "CZ", "Czechia": "CZ", "Denmark": "DK", "Estonia": "EE", "Finland": "FI",
    "France": "FR", "Germany": "DE", "Greece": "GR", "Hungary": "HU", "Ireland": "IE",
    "Italy": "IT", "Latvia": "LV", "Lithuania": "LT", "Luxembourg": "LU", "Malta": "MT",
    "Netherlands": "NL", "Poland": "PL", "Portugal": "PT", "Romania": "RO", "Slovakia": "SK",
    "Slovenia": "SI", "Spain": "ES", "Sweden": "SE", "EU-27": "EU27", "EU27": "EU27",
}  # fmt: skip


@dataclass
class ImportReport:
    factors: list[EmissionFactor]
    countries: int = 0
    years: list[int] = field(default_factory=list)
    estimated_year: int | None = None
    unknown_countries: list[str] = field(default_factory=list)


def _country(label: str) -> str:
    """Strip markup such as ``<b>EU-27</b>``."""
    out, depth = [], 0
    for ch in label:
        if ch == "<":
            depth += 1
        elif ch == ">":
            depth = max(depth - 1, 0)
        elif not depth:
            out.append(ch)
    return "".join(out).strip()


def _value(v: Any) -> float | None:
    if v is None:
        return None
    try:
        x = float(str(v).strip().replace(",", ""))
    except ValueError:
        return None
    return x if x >= 0 else None


def parse(data: dict[str, Any], first_year: int = FIRST_YEAR) -> ImportReport:
    try:
        sources = data["visualization"]["dataSources"]
        countries = [_country(c) for c in sources["Countries"]]
    except (KeyError, TypeError) as exc:
        raise FactorError(
            "EEA: expected visualization.dataSources with a Countries column"
        ) from exc
    years = sorted(int(k) for k in sources if k.isdigit() and int(k) >= first_year)
    if not years:
        raise FactorError("EEA: no year columns found")
    latest = years[-1]
    report = ImportReport(factors=[], years=years, estimated_year=latest)
    seen: set[str] = set()
    for i, name in enumerate(countries):
        code = COUNTRY_CODES.get(name)
        if code is None:
            report.unknown_countries.append(name)
            continue
        seen.add(code)
        for year in years:
            column = sources[str(year)]
            g_per_kwh = _value(column[i]) if i < len(column) else None
            if g_per_kwh is None:
                continue
            report.factors.append(_factor(code, name, year, g_per_kwh, estimate=year == latest))
    report.countries = len(seen)
    if not report.factors:
        raise FactorError("EEA: no country values found")
    return report


def _factor(code: str, name: str, year: int, g_per_kwh: float, estimate: bool) -> EmissionFactor:
    area = "EU-27 average" if code == "EU27" else f"{name} ({code})"
    notes = (
        "Location-based grid average: GHG emissions of electricity generation per kWh "
        "generated (generation-based: imports, T&D losses and upstream emissions excluded). "
        "Published in whole g CO2e/kWh. Source: European Environment Agency (EEA)."
    )
    if estimate:
        notes += f" {year} is an EEA early estimate; replace it when the final value is out."
    return EmissionFactor(
        factor_id=f"EEA-{year}-{code}",
        name=f"Electricity: grid average, {area}",
        activity_unit="kWh",
        co2e_kg=g_per_kwh / 1000,
        gwp_basis="AR5",
        scope=Scope.SCOPE_2,
        scope2_method=Scope2Method.LOCATION_BASED,
        region=code,
        year=year,
        source=f"EEA GHG emission intensity of electricity generation {year}",
        source_url=SOURCE_URL,
        status=FactorStatus.REFERENCE,
        notes=notes,
        energy_kwh_per_unit=1.0,
        energy_source=EnergySource.ELECTRICITY,
    )


def read_json(path: str | Path, first_year: int = FIRST_YEAR) -> ImportReport:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise FactorError(f"EEA: cannot read {path}: {exc}") from exc
    return parse(data, first_year)
