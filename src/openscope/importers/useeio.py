"""Importer for the US EPA *Supply Chain GHG Emission Factors* (USEEIO-based, by NAICS-6).

Dataset: Supply Chain Greenhouse Gas Emission Factors v1.3.0 by NAICS-6, US EPA Office of
Research and Development, DOI 10.23719/1531143 (public domain). Files used:

* ``SupplyChainGHGEmissionFactors_v1.3.0_NAICS_byGHG_USD2022.csv``: kg of each gas per USD
* ``SupplyChainGHGEmissionFactors_v1.3.0_NAICS_CO2e_USD2022.csv``: kg CO2e per USD (AR5)

Columns (format-specs in USEPA/supply-chain-factors): 2017 NAICS Code, 2017 NAICS Title, GHG,
Unit, Supply Chain Emission Factors without Margins, Margins of Supply Chain Emission Factors,
Supply Chain Emission Factors with Margins, Reference USEEIO Code.

Choices:

* **With margins** (cradle to point of sale), the right basis for purchaser-price spend data.
* **Per gas**: masses are stored per gas, so factors can be recalculated under AR6. EPA's
  "HFCs and PFCs, unspecified" group is published only as CO2e (AR5) and is kept as the ``CO2E``
  pseudo-gas.
* **Reconciliation**: when the CO2e file is given, every commodity's per-gas total (AR5) is
  checked against EPA's published CO2e. A commodity that does not reconcile falls back to the
  published total with ``gwp_basis="AR5"``.
* Methane is mapped to ``CH4`` (fossil methane under AR6, the conservative default), since the
  dataset does not split fossil from biogenic methane.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from pathlib import Path

from openscope.errors import FactorError
from openscope.gwp import GWPSet, gwp
from openscope.models import EmissionFactor, FactorStatus, Scope

SOURCE = "US EPA Supply Chain GHG Emission Factors v1.3.0 (USEEIO v2.2, NAICS-6)"
SOURCE_URL = "https://doi.org/10.23719/1531143"
VALUE_COLUMN = "Supply Chain Emission Factors with Margins"
NO_MARGIN_COLUMN = "Supply Chain Emission Factors without Margins"
ABS_TOLERANCE = 0.0006  # published CO2e has 3 decimals; per-gas values 3 significant figures
REL_TOLERANCE = 0.005

GAS_MAP = {
    "Carbon dioxide": "CO2",
    "Methane": "CH4",
    "Nitrous oxide": "N2O",
    "HFC-23": "HFC-23",
    "HFC-32": "HFC-32",
    "HFC-125": "HFC-125",
    "HFC-134a": "HFC-134A",
    "HFC-143a": "HFC-143A",
    "HFC-236fa": "HFC-236FA",
    "Sulfur hexafluoride": "SF6",
    "Nitrogen trifluoride": "NF3",
    "Carbon tetrafluoride": "CF4",
    "Hexafluoroethane": "C2F6",
    "Perfluoropropane": "C3F8",
    "Perfluorocyclobutane": "C-C4F8",
    "Perfluorobutane": "C4F10",
    "Perfluorohexane": "C6F14",
    "HFCs and PFCs, unspecified": "CO2E",
}


@dataclass
class _Commodity:
    title: str
    useeio_code: str
    gases: dict[str, float] = field(default_factory=dict)
    no_margin_co2e: float | None = None


@dataclass
class ImportReport:
    factors: list[EmissionFactor]
    per_gas: int = 0
    total_only: int = 0
    unreconciled: list[str] = field(default_factory=list)
    unknown_gases: set[str] = field(default_factory=set)


def _read(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as fh:
        rows = list(csv.DictReader(fh))
    required = {"2017 NAICS Code", "2017 NAICS Title", "GHG", "Unit", VALUE_COLUMN}
    if not rows or not required <= set(rows[0]):
        raise FactorError(f"{path}: not an EPA supply chain factors file (expected {required})")
    return rows


def import_factors(
    by_ghg: str | Path, co2e: str | Path | None = None, *, year: int = 2022
) -> ImportReport:
    commodities: dict[str, _Commodity] = {}
    report = ImportReport(factors=[])

    for row in _read(Path(by_ghg)):
        code = row["2017 NAICS Code"].strip()
        c = commodities.setdefault(
            code, _Commodity(row["2017 NAICS Title"].strip(), row.get("Reference USEEIO Code", ""))
        )
        name = row["GHG"].strip()
        gas = GAS_MAP.get(name)
        if gas is None:
            report.unknown_gases.add(name)
            continue
        value = float(row[VALUE_COLUMN])
        if value:
            c.gases[gas] = c.gases.get(gas, 0.0) + value

    published: dict[str, tuple[float, float]] = {}
    if co2e is not None:
        for row in _read(Path(co2e)):
            published[row["2017 NAICS Code"].strip()] = (
                float(row[VALUE_COLUMN]),
                float(row[NO_MARGIN_COLUMN]),
            )

    if report.unknown_gases:
        raise FactorError(f"Unknown gases in EPA file: {sorted(report.unknown_gases)}")

    for code, c in sorted(commodities.items()):
        ar5 = sum(v * gwp(g, GWPSet.AR5) for g, v in c.gases.items())
        total, no_margin = published.get(code, (ar5, float("nan")))
        reconciles = abs(ar5 - total) <= ABS_TOLERANCE or (
            total > 0 and abs(ar5 - total) / total <= REL_TOLERANCE
        )
        notes = (
            f"NAICS 2017 {code}; USEEIO {c.useeio_code}; purchaser price incl. margins, "
            f"{year} USD; published {total:g} kg CO2e/USD (AR5)"
        )
        if no_margin == no_margin:  # not NaN
            notes += f", without margins {no_margin:g}"
        if reconciles and c.gases:
            report.per_gas += 1
            factor = EmissionFactor(
                factor_id=f"USEEIO-1.3-{code}",
                name=f"{c.title} (NAICS {code})",
                activity_unit="USD",
                gases=c.gases,
                scope=Scope.SCOPE_3,
                region="US",
                year=year,
                source=SOURCE,
                source_url=SOURCE_URL,
                status=FactorStatus.REFERENCE,
                notes=notes,
            )
        else:
            report.total_only += 1
            report.unreconciled.append(code)
            factor = EmissionFactor(
                factor_id=f"USEEIO-1.3-{code}",
                name=f"{c.title} (NAICS {code})",
                activity_unit="USD",
                co2e_kg=total,
                gwp_basis="AR5",
                scope=Scope.SCOPE_3,
                region="US",
                year=year,
                source=SOURCE,
                source_url=SOURCE_URL,
                status=FactorStatus.REFERENCE,
                notes=notes + "; per-gas values did not reconcile, published CO2e used",
            )
        report.factors.append(factor)
    return report
