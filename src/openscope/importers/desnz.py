"""Importer for the UK Government GHG Conversion Factors for Company Reporting (DESNZ).

Reads the official **flat-format** workbook published each June at
https://www.gov.uk/government/collections/government-conversion-factors-for-company-reporting
and converts it into openscope :class:`~openscope.models.EmissionFactor` objects.

Format notes (verified against the 2025 flat file, v1):

* Sheet ``Factors by Category``; a header row starting with ``ID`` (row 6 in 2025).
* Columns: ``ID, Scope, Level 1, Level 2, Level 3, Level 4, Column Text, UOM, GHG/Unit,
  GHG Conversion Factor <year>``.
* One logical factor = several rows sharing an ID prefix (``<prefix>_<n>``). ``GHG/Unit`` is
  ``kg CO2e`` (total) or ``kg CO2e of CO2|CH4|N2O per unit`` (per-gas, **already
  GWP-weighted**). Rows in ``kWh (Net CV)`` / ``kWh (net)`` are energy conversions and skipped.
* Blank value cells mean DESNZ publishes no factor for that combination; they are skipped.
* GWPs: AR5 (CH4 = 28, N2O = 265) for almost all factors; WTT-bioenergy remains AR4; a few
  refrigerants use AR6 where AR5 is unavailable (2025 methodology paper, §1.7 and Table 1).

Because the GWP basis is known, per-gas CO2e values are converted back to **kg of gas**
(CO2e / GWP_AR5). openscope can then re-weight DESNZ factors under AR6. If the per-gas values
don't reconcile with the published total (more than 0.5% apart), the total is used as-is.
"""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from openscope.errors import FactorError
from openscope.gwp import GWPSet, gwp
from openscope.models import (
    EmissionFactor,
    EnergySource,
    FactorStatus,
    Scope,
    Scope2Method,
    Scope3Category,
)

SOURCE_URL = (
    "https://www.gov.uk/government/collections/government-conversion-factors-for-company-reporting"
)
SHEET = "Factors by Category"
RECONCILE_TOLERANCE = 0.005

_UOM_MAP: dict[str, str] = {
    "km": "km",
    "miles": "mi",
    "tonne.km": "tkm",
    "tonnes": "t",
    "kg": "kg",
    "passenger.km": "pkm",
    "litres": "L",
    "kwh": "kWh",
    "kwh (net cv)": "kWh",
    "kwh (gross cv)": "kWh",
    "room per night": "night",
    "gj": "GJ",
    "cubic metres": "m3",
    "per fte working hour": "fte_hour",
    "million litres": "million_litres",
}

_SCOPE_MAP = {"scope 1": Scope.SCOPE_1, "scope 2": Scope.SCOPE_2, "scope 3": Scope.SCOPE_3}

# Only unambiguous Level 1 -> Scope 3 category mappings. Ambiguous ones (e.g. freight can be
# category 4 or 9, managed assets 8 or 13) are left blank; the user's activity decides.
_CATEGORY_MAP: dict[str, Scope3Category] = {
    "business travel- air": Scope3Category.BUSINESS_TRAVEL,
    "business travel- land": Scope3Category.BUSINESS_TRAVEL,
    "business travel- sea": Scope3Category.BUSINESS_TRAVEL,
    "wtt- business travel- air": Scope3Category.BUSINESS_TRAVEL,
    "wtt- business travel- sea": Scope3Category.BUSINESS_TRAVEL,
    "hotel stay": Scope3Category.BUSINESS_TRAVEL,
    "wtt- fuels": Scope3Category.FUEL_AND_ENERGY_RELATED,
    "wtt- bioenergy": Scope3Category.FUEL_AND_ENERGY_RELATED,
    "wtt- uk electricity": Scope3Category.FUEL_AND_ENERGY_RELATED,
    "wtt- heat and steam": Scope3Category.FUEL_AND_ENERGY_RELATED,
    "transmission and distribution": Scope3Category.FUEL_AND_ENERGY_RELATED,
    "uk electricity t&d for evs": Scope3Category.FUEL_AND_ENERGY_RELATED,
    "waste disposal": Scope3Category.WASTE,
    "water treatment": Scope3Category.WASTE,
    "water supply": Scope3Category.PURCHASED_GOODS_AND_SERVICES,
    "material use": Scope3Category.PURCHASED_GOODS_AND_SERVICES,
    "homeworking": Scope3Category.EMPLOYEE_COMMUTING,
}

_GAS_RE = re.compile(r"kg co2e of (co2|ch4|n2o) per unit", re.I)


@dataclass
class _Group:
    meta: tuple[Any, ...]  # (scope, l1, l2, l3, l4, column_text, uom)
    total: float | None = None
    gases_co2e: dict[str, float] = field(default_factory=dict)


@dataclass
class ImportReport:
    factors: list[EmissionFactor]
    skipped_energy_rows: int = 0
    skipped_unknown_unit: dict[str, int] = field(default_factory=dict)
    per_gas: int = 0
    total_only: int = 0
    energy_linked: int = 0
    biogenic_linked: int = 0
    cat3_linked: int = 0


def _gwp_basis(level1: str) -> str:
    return "AR4" if level1.strip().lower() == "wtt- bioenergy" else "AR5"


def _clean(v: Any) -> str:
    return "" if v is None else str(v).strip()


def _find_header(rows: Iterator[Sequence[Any]]) -> tuple[list[str], Iterator[Sequence[Any]]]:
    for row in rows:
        if row and _clean(row[0]) == "ID":
            return [_clean(c) for c in row], rows
    raise FactorError(f"DESNZ: header row starting with 'ID' not found in sheet '{SHEET}'")


def parse_rows(rows: Iterable[Sequence[Any]], year: int) -> ImportReport:
    """Parse flat-file rows (including preamble and header) into factors."""
    header, body = _find_header(iter(rows))
    try:
        idx = {name: header.index(name) for name in ("ID", "Scope", "UOM", "GHG/Unit")}
        idx["L1"] = header.index("Level 1")
        value_col = next(i for i, h in enumerate(header) if h.startswith("GHG Conversion Factor"))
    except (ValueError, StopIteration) as exc:
        raise FactorError(f"DESNZ: unexpected header layout: {header}") from exc

    groups: dict[str, _Group] = {}
    report = ImportReport(factors=[])
    for row in body:
        rid = _clean(row[idx["ID"]])
        if not rid or rid.upper() == "END" or "_" not in rid:
            continue
        ghg_unit = _clean(row[idx["GHG/Unit"]]).lower()
        value = row[value_col]
        if value is None or value == "":
            continue
        prefix = rid.rsplit("_", 1)[0]
        meta = tuple(_clean(row[i]) for i in range(idx["Scope"], idx["Scope"] + 6)) + (
            _clean(row[idx["UOM"]]),
        )
        if ghg_unit.startswith("kwh"):
            report.skipped_energy_rows += 1
            continue
        g = groups.setdefault(prefix, _Group(meta))
        if ghg_unit == "kg co2e":
            g.total = float(value)
        elif m := _GAS_RE.fullmatch(ghg_unit):
            g.gases_co2e[m.group(1).upper()] = float(value)

    extras = _energy_and_biogenic(groups)
    unknown: dict[str, int] = defaultdict(int)
    for prefix, g in groups.items():
        factor = _to_factor(prefix, g, year, report)
        if factor is None:
            unknown[g.meta[6]] += 1
            continue
        if prefix in extras:
            update = {k: v for k, v in extras[prefix].items() if v is not None}
            factor = factor.model_copy(update=update)
            report.energy_linked += "energy_kwh_per_unit" in update
            report.biogenic_linked += "biogenic_co2_kg" in update
        report.factors.append(factor)
    report.skipped_unknown_unit = dict(unknown)
    report.factors = link_cat3(report.factors)
    report.cat3_linked = sum(1 for f in report.factors if f.cat3_factor_ids)
    return report


# Scope 1/2 sheet -> sheets holding its Category 3 upstream factors (the first part of the ID):
# fuels -> WTT fuels; bioenergy -> WTT bioenergy; owned cars and vans -> WTT of their fuel;
# grid electricity -> WTT generation, WTT of T&D and T&D losses; EV electricity -> T&D;
# heat and steam -> WTT heat and steam and the district heating distribution loss.
_CAT3_SHEETS = {1: (11,), 2: (12,), 4: (26,), 5: (28,), 7: (15, 13), 8: (14,), 10: (16, 13)}
# district heat and steam (item 4003) also loses energy in distribution (item 4004)
_CAT3_EXTRA_ITEMS = {"4003": ("4004",)}


def _id_parts(factor_id: str) -> tuple[int, str, str, str] | None:
    parts = factor_id.split("-")[-1].split("_")
    if len(parts) != 4 or not parts[0].isdigit():
        return None
    return int(parts[0]), parts[1], parts[2], parts[3]


def _tail(name: str) -> str:
    """The name without its first level and 'WTT-' prefixes, for matching like with like."""
    levels = [re.sub(r"^wtt-\s*", "", p.strip().lower()) for p in name.split(" / ")[1:]]
    return " / ".join(levels)


def link_cat3(factors: list[EmissionFactor]) -> list[EmissionFactor]:
    """Link each Scope 1/2 factor to its Category 3 upstream factors (``cat3_factor_ids``).

    DESNZ IDs are ``<sheet>_<group>_<item>_<unit>``; the upstream factor of the same fuel or
    vehicle in the same unit shares the item and unit. Where one upstream sheet has several
    matches (an HGV and a refrigerated HGV), the one with the same name is kept.
    """
    index: dict[tuple[int, str, str], list[EmissionFactor]] = defaultdict(list)
    for f in factors:
        if (p := _id_parts(f.factor_id)) is not None:
            index[(p[0], p[2], p[3])].append(f)
    out = []
    for f in factors:
        p = _id_parts(f.factor_id)
        if p is None or p[0] not in _CAT3_SHEETS:
            out.append(f)
            continue
        sheet, _, item, unit = p
        links: list[str] = []
        for target in _CAT3_SHEETS[sheet]:
            for it in (item, *_CAT3_EXTRA_ITEMS.get(item, ())):
                found = index.get((target, it, unit), [])
                same = [m for m in found if _tail(m.name) == _tail(f.name)]
                if len(found) > 1 and same:
                    found = same
                links += [m.factor_id for m in found]
        out.append(f.model_copy(update={"cat3_factor_ids": tuple(links)}) if links else f)
    return out


KWH_PER_GJ = 1e3 / 3.6

_ENERGY_SOURCE = {
    ("scope 1", "fuels"): EnergySource.FOSSIL_FUEL,
    ("scope 1", "bioenergy"): EnergySource.RENEWABLE_FUEL,
    ("scope 2", "uk electricity"): EnergySource.ELECTRICITY,
    ("scope 2", "heat and steam"): EnergySource.HEAT,
    ("scope 1", "refrigerant & other"): EnergySource.NON_ENERGY,
}


def _total(g: _Group) -> float:
    return g.total if g.total is not None else sum(g.gases_co2e.values())


def _energy_and_biogenic(groups: dict[str, _Group]) -> dict[str, dict[str, Any]]:
    """Energy content, energy source and biogenic CO2 for in-scope factors.

    * Energy per unit (kWh, net CV) for fuels comes from DESNZ's own numbers: the same fuel is
      published per unit and per kWh (Net CV), so ``factor(unit) / factor(kWh Net CV)`` is the
      net calorific value of one unit. Biofuels are published per GJ instead of per kWh; the
      GJ factor is used as the reference, as published. Electricity and heat in kWh are 1 kWh
      per kWh.
    * Biogenic CO2 comes from the "Outside of Scopes" rows, linked to the in-scope factor with
      the same fuel (Level 3) and unit, only when that match is unambiguous.
    """
    out: dict[str, dict[str, Any]] = defaultdict(dict)
    # kg CO2e per kWh of energy for each fuel: from the kWh (Net CV) factor, or else the GJ factor
    net_cv: dict[tuple[str, ...], float] = {}
    per_gj: dict[tuple[str, ...], float] = {}
    for g in groups.values():
        scope, l1, l2, l3, l4, col, uom = (x.lower() for x in g.meta)
        if uom == "kwh (net cv)" and _total(g) > 0:
            net_cv[(scope, l1, l2, l3, l4, col)] = _total(g)
        elif uom == "gj" and _total(g) > 0:
            per_gj[(scope, l1, l2, l3, l4, col)] = _total(g) / KWH_PER_GJ
    for key, v in per_gj.items():
        net_cv.setdefault(key, v)

    in_scope: dict[tuple[str, str], list[str]] = defaultdict(list)
    for prefix, g in groups.items():
        scope, l1, l2, l3, l4, col, uom = (x.lower() for x in g.meta)
        source = _ENERGY_SOURCE.get((scope, l1))
        if source is None:
            continue
        out[prefix]["energy_source"] = source
        in_scope[(l3, uom)].append(prefix)
        if (
            uom in ("kwh", "kwh (net cv)")
            and source
            in (
                EnergySource.ELECTRICITY,
                EnergySource.HEAT,
            )
            or uom == "kwh (net cv)"
        ):
            out[prefix]["energy_kwh_per_unit"] = 1.0
        elif (ref := net_cv.get((scope, l1, l2, l3, l4, col))) and _total(g) > 0:
            out[prefix]["energy_kwh_per_unit"] = _total(g) / ref

    for g in groups.values():
        scope, l1, l2, l3, l4, col, uom = (x.lower() for x in g.meta)
        co2 = g.gases_co2e.get("CO2")
        if scope != "outside of scopes" or not co2:
            continue
        candidates = in_scope.get((l3, uom), [])
        if l4:
            candidates = [c for c in candidates if groups[c].meta[4].lower() == l4] or candidates
        if len(candidates) == 1:
            out[candidates[0]]["biogenic_co2_kg"] = co2  # kg CO2e of CO2 = kg CO2
    return dict(out)


def _to_factor(prefix: str, g: _Group, year: int, report: ImportReport) -> EmissionFactor | None:
    scope_txt, l1, l2, l3, l4, col_text, uom = g.meta
    unit = _UOM_MAP.get(uom.lower())
    if unit is None:
        return None

    basis = _gwp_basis(l1)
    total = g.total if g.total is not None else sum(g.gases_co2e.values())
    gases: dict[str, float] = {}
    if basis == "AR5" and set(g.gases_co2e) == {"CO2", "CH4", "N2O"}:
        recon = sum(g.gases_co2e.values())
        if total == 0 or abs(recon - total) / total <= RECONCILE_TOLERANCE:
            gases = {gas: v / gwp(gas, GWPSet.AR5) for gas, v in g.gases_co2e.items()}

    descr = [p for p in (l1, l2, l3, l4, col_text) if p]
    if uom.lower() in ("kwh (net cv)", "kwh (gross cv)"):
        descr.append(uom.split("(")[1].rstrip(")"))  # keep the calorific-value basis visible
    breakdown = ", ".join(f"{k}={v:g}" for k, v in sorted(g.gases_co2e.items()))
    notes = f"DESNZ ID {prefix}; GWP basis {basis}"
    if breakdown:
        notes += f"; published per-gas kg CO2e: {breakdown}"
    if l1.lower().startswith("refrigerant"):
        notes += "; a few refrigerant GWPs use AR6 where AR5 is unavailable"

    scope = _SCOPE_MAP.get(scope_txt.lower())
    if gases:
        report.per_gas += 1
    else:
        report.total_only += 1

    return EmissionFactor(
        factor_id=f"DESNZ-{year}-{prefix}",
        name=" / ".join(descr),
        activity_unit=unit,
        gases=gases,
        co2e_kg=None if gases else total,
        gwp_basis=None if gases else basis,
        scope=scope,
        scope2_method=(
            Scope2Method.LOCATION_BASED
            if scope == Scope.SCOPE_2 and "electricity" in l1.lower()
            else None
        ),
        scope3_category=_CATEGORY_MAP.get(l1.lower()),
        region="UK",
        year=year,
        source=f"UK Government GHG Conversion Factors for Company Reporting {year} (DESNZ)",
        source_url=SOURCE_URL,
        status=FactorStatus.REFERENCE,
        notes=notes,
    )


def read_workbook(path: str | Path, year: int | None = None) -> ImportReport:
    """Parse a DESNZ flat-format ``.xlsx``. Requires ``pip install openscope[importers]``."""
    try:
        import openpyxl
    except ImportError as exc:  # pragma: no cover - exercised only without the extra
        raise FactorError(
            "Reading .xlsx needs openpyxl: pip install 'openscope[importers]'"
        ) from exc

    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    try:
        if SHEET not in wb.sheetnames:
            raise FactorError(f"DESNZ: sheet '{SHEET}' not found in {path}")
        if year is None:
            year = _detect_year(wb)
        return parse_rows(wb[SHEET].iter_rows(values_only=True), year)
    finally:
        wb.close()


def _detect_year(wb: Any) -> int:
    for row in wb[SHEET].iter_rows(max_row=10, values_only=True):
        for cell in row:
            if m := re.search(r"GHG Conversion Factor (\d{4})", _clean(cell)):
                return int(m.group(1))
    raise FactorError("DESNZ: could not detect the factor year; pass year explicitly")
