"""Emission-factor registry.

Factors are loaded from CSV so that datasets (EPA, DEFRA/DESNZ, USEEIO, IEA,
supplier-specific…) can be versioned, diffed and reviewed like code.

CSV columns
-----------
factor_id, name, activity_unit, co2_kg, ch4_kg, n2o_kg, other_gases, co2e_kg, gwp_basis,
scope, scope3_category, scope2_method, region, year, source, source_url, status, notes,
energy_kwh_per_unit, energy_source, biogenic_co2_kg   (optional; for ESRS E1-5 and biogenic CO2)
fossil_share, nuclear_share, renewable_share         (optional; generation mix of an electricity
                                                      factor, as fractions summing to 1)
cat3_factor_ids                                      (optional; ``;``-separated upstream factors
                                                      for Scope 3 Category 3, same unit)

``other_gases`` is a ``;``-separated list of ``GAS=kg`` pairs, e.g. ``HFC-134A=1``.
Empty cells are treated as missing.
"""

from __future__ import annotations

import csv
import re
from collections.abc import Iterable, Iterator
from importlib import resources
from pathlib import Path

from openscope.errors import FactorError
from openscope.models import (
    EmissionFactor,
    EnergySource,
    FactorStatus,
    Scope,
    Scope2Method,
    Scope3Category,
)

_BUNDLED = "sample_factors.csv"
_DATASETS = {
    "sample": _BUNDLED,
    "desnz-2024": "desnz_2024.csv",
    "desnz-2025": "desnz_2025.csv",
    "desnz-2026": "desnz_2026.csv",
    "useeio-1.3": "useeio_1_3.csv",
    "eea-electricity": "eea_electricity.csv",
}

# Yearly datasets name factors "<SOURCE>-<year>-<id>", e.g. DESNZ-2025-1_100_1004_6. The same
# factor without the year ("DESNZ-1_100_1004_6") resolves to the edition for the activity's year.
_YEARLY_ID = re.compile(r"^([A-Za-z][A-Za-z0-9]*)-((?:19|20)\d\d)-(.+)$")


def generic_id(factor_id: str) -> str:
    """The factor id without its dataset year: DESNZ-2025-1_100_1004_6 -> DESNZ-1_100_1004_6."""
    m = _YEARLY_ID.match(factor_id)
    return f"{m.group(1)}-{m.group(3)}" if m else factor_id


CSV_COLUMNS = [
    "factor_id",
    "name",
    "activity_unit",
    "co2_kg",
    "ch4_kg",
    "n2o_kg",
    "other_gases",
    "co2e_kg",
    "gwp_basis",
    "scope",
    "scope3_category",
    "scope2_method",
    "region",
    "year",
    "source",
    "source_url",
    "status",
    "notes",
    "energy_kwh_per_unit",
    "energy_source",
    "biogenic_co2_kg",
    "fossil_share",
    "nuclear_share",
    "renewable_share",
    "cat3_factor_ids",
]


def _num(x: float | None) -> str:
    return "" if x is None else f"{x:.10g}"


def _to_row(f: EmissionFactor) -> dict[str, str]:
    other = ";".join(f"{g}={_num(v)}" for g, v in f.gases.items() if g not in ("CO2", "CH4", "N2O"))
    return {
        "factor_id": f.factor_id,
        "name": f.name,
        "activity_unit": f.activity_unit,
        "co2_kg": _num(f.gases.get("CO2")),
        "ch4_kg": _num(f.gases.get("CH4")),
        "n2o_kg": _num(f.gases.get("N2O")),
        "other_gases": other,
        "co2e_kg": _num(f.co2e_kg),
        "gwp_basis": f.gwp_basis or "",
        "scope": str(int(f.scope)) if f.scope else "",
        "scope3_category": str(int(f.scope3_category)) if f.scope3_category else "",
        "scope2_method": f.scope2_method.value if f.scope2_method else "",
        "region": f.region,
        "year": str(f.year) if f.year else "",
        "source": f.source,
        "source_url": f.source_url or "",
        "status": f.status.value,
        "notes": f.notes or "",
        "energy_kwh_per_unit": _num(f.energy_kwh_per_unit),
        "energy_source": f.energy_source.value if f.energy_source else "",
        "biogenic_co2_kg": _num(f.biogenic_co2_kg),
        "fossil_share": _num(f.fossil_share),
        "nuclear_share": _num(f.nuclear_share),
        "renewable_share": _num(f.renewable_share),
        "cat3_factor_ids": ";".join(f.cat3_factor_ids),
    }


def _opt(row: dict[str, str], key: str) -> str | None:
    value = (row.get(key) or "").strip()
    return value or None


def _share(row: dict[str, str], key: str) -> float | None:
    value = _opt(row, key)
    return None if value is None else float(value)


def _parse_row(row: dict[str, str], line: int, origin: str) -> EmissionFactor:
    try:
        gases: dict[str, float] = {}
        for col, gas in (("co2_kg", "CO2"), ("ch4_kg", "CH4"), ("n2o_kg", "N2O")):
            if (v := _opt(row, col)) is not None:
                gases[gas] = float(v)
        if other := _opt(row, "other_gases"):
            for pair in other.split(";"):
                gas, _, kg = pair.partition("=")
                gases[gas.strip().upper()] = float(kg)

        scope = _opt(row, "scope")
        cat = _opt(row, "scope3_category")
        s2 = _opt(row, "scope2_method")
        year = _opt(row, "year")
        co2e = _opt(row, "co2e_kg")
        return EmissionFactor(
            factor_id=row["factor_id"].strip(),
            name=row["name"].strip(),
            activity_unit=row["activity_unit"].strip(),
            gases=gases,
            co2e_kg=float(co2e) if co2e else None,
            gwp_basis=_opt(row, "gwp_basis"),
            scope=Scope(int(scope)) if scope else None,
            scope3_category=Scope3Category(int(cat)) if cat else None,
            scope2_method=Scope2Method(s2) if s2 else None,
            region=_opt(row, "region") or "GLOBAL",
            year=int(year) if year else None,
            source=row["source"].strip(),
            source_url=_opt(row, "source_url"),
            status=FactorStatus(_opt(row, "status") or "reference"),
            notes=_opt(row, "notes"),
            energy_kwh_per_unit=float(e) if (e := _opt(row, "energy_kwh_per_unit")) else None,
            energy_source=EnergySource(src) if (src := _opt(row, "energy_source")) else None,
            biogenic_co2_kg=float(b) if (b := _opt(row, "biogenic_co2_kg")) else None,
            fossil_share=_share(row, "fossil_share"),
            nuclear_share=_share(row, "nuclear_share"),
            renewable_share=_share(row, "renewable_share"),
            cat3_factor_ids=tuple(
                x.strip() for x in (_opt(row, "cat3_factor_ids") or "").split(";") if x.strip()
            ),
        )
    except (KeyError, ValueError) as exc:
        raise FactorError(f"{origin}:{line}: invalid factor row: {exc}") from exc


class FactorRegistry:
    """An in-memory, id-addressable collection of emission factors."""

    def __init__(self, factors: Iterable[EmissionFactor] = ()) -> None:
        self._factors: dict[str, EmissionFactor] = {}
        self._editions: dict[str, dict[int, str]] = {}  # generic id -> {year: factor id}
        for f in factors:
            self.add(f)

    # -- construction -------------------------------------------------------
    @classmethod
    def from_csv(cls, path: str | Path) -> FactorRegistry:
        path = Path(path)
        with path.open(newline="", encoding="utf-8") as fh:
            return cls(cls._read(fh, str(path)))

    @classmethod
    def bundled(cls) -> FactorRegistry:
        """The small sample dataset shipped with the package (see its ``status`` column)."""
        ref = resources.files("openscope.factors.data").joinpath(_BUNDLED)
        with ref.open("r", encoding="utf-8") as fh:
            return cls(cls._read(fh, _BUNDLED))

    @classmethod
    def dataset(cls, name: str) -> FactorRegistry:
        """Load a published dataset bundled with openscope, e.g. ``"desnz-2025"``.

        A name without a year (``"desnz"``) loads every bundled edition, so factor ids without
        a year resolve to the edition for each activity's year.
        """
        editions = sorted(n for n in _DATASETS if n.startswith(f"{name.lower()}-"))
        if name.lower() not in _DATASETS and editions:
            merged = cls()
            for n in editions:
                merged = merged.merge(cls.dataset(n))
            return merged
        file = _DATASETS.get(name.lower())
        if file is None:
            raise FactorError(f"Unknown dataset '{name}'. Available: {sorted(_DATASETS)}")
        ref = resources.files("openscope.factors.data").joinpath(file)
        with ref.open("r", encoding="utf-8") as fh:
            return cls(cls._read(fh, file))

    @staticmethod
    def available_datasets() -> list[str]:
        return sorted(_DATASETS)

    @staticmethod
    def _read(fh: Iterable[str], origin: str) -> Iterator[EmissionFactor]:
        reader = csv.DictReader(line for line in fh if not line.lstrip().startswith("#"))
        for i, row in enumerate(reader, start=2):
            yield _parse_row(row, i, origin)

    # -- mutation -----------------------------------------------------------
    def add(self, factor: EmissionFactor, *, override: bool = False) -> None:
        if factor.factor_id in self._factors and not override:
            raise FactorError(f"Duplicate factor_id '{factor.factor_id}'")
        self._factors[factor.factor_id] = factor
        if m := _YEARLY_ID.match(factor.factor_id):
            key = f"{m.group(1)}-{m.group(3)}"
            self._editions.setdefault(key, {})[int(m.group(2))] = factor.factor_id

    def merge(self, other: FactorRegistry) -> FactorRegistry:
        """Return a new registry where ``other``'s factors override this one's."""
        merged = FactorRegistry(self)
        for f in other:
            merged.add(f, override=True)
        return merged

    # -- access -------------------------------------------------------------
    def get(self, factor_id: str) -> EmissionFactor:
        try:
            return self._factors[factor_id]
        except KeyError:
            raise FactorError(f"Unknown factor_id '{factor_id}'") from None

    def resolve(self, factor_id: str, year: int | None) -> tuple[EmissionFactor, str | None]:
        """A factor by exact id, or by id without its year (the edition for ``year``).

        Returns the factor and, when an edition was chosen, a note for the audit trail. The
        edition is the one for ``year``, else the latest earlier one, else the earliest one.
        """
        if factor_id in self._factors:
            return self._factors[factor_id], None
        editions = self._editions.get(factor_id)
        if not editions:
            raise FactorError(f"Unknown factor_id '{factor_id}'")
        years = sorted(editions)
        if year is None:
            chosen = years[-1]
            note = f"Edition: {chosen} (latest; the activity has no year)"
        elif year in editions:
            chosen = year
            note = f"Edition: {chosen}, matching the activity year"
        elif earlier := [y for y in years if y < year]:
            chosen = earlier[-1]
            note = (
                f"WARNING: no {year} edition of {factor_id}; using {chosen}, the latest earlier one"
            )
        else:
            chosen = years[0]
            note = (
                f"WARNING: no {year} or earlier edition of {factor_id}; using {chosen}, "
                "the earliest available"
            )
        return self._factors[editions[chosen]], note

    def editions(self, factor_id: str) -> list[int]:
        """Years available for an id without its year (empty if it has none)."""
        return sorted(self._editions.get(factor_id, {}))

    def search(
        self,
        *,
        text: str | None = None,
        scope: Scope | None = None,
        scope3_category: Scope3Category | None = None,
        region: str | None = None,
    ) -> list[EmissionFactor]:
        out = []
        for f in self:
            if text and text.lower() not in f"{f.factor_id} {f.name}".lower():
                continue
            if scope is not None and f.scope != scope:
                continue
            if scope3_category is not None and f.scope3_category != scope3_category:
                continue
            if region and f.region.upper() != region.upper():
                continue
            out.append(f)
        return out

    def to_csv(self, path: str | Path, header_comment: str | None = None) -> None:
        """Write factors in openscope's CSV format (round-trips with :meth:`from_csv`)."""
        with Path(path).open("w", newline="", encoding="utf-8") as fh:
            if header_comment:
                for line in header_comment.splitlines():
                    fh.write(f"# {line}\n")
            writer = csv.DictWriter(fh, fieldnames=CSV_COLUMNS, lineterminator="\n")
            writer.writeheader()
            for f in self:
                writer.writerow(_to_row(f))

    def __iter__(self) -> Iterator[EmissionFactor]:
        return iter(self._factors.values())

    def __len__(self) -> int:
        return len(self._factors)

    def __contains__(self, factor_id: object) -> bool:
        return factor_id in self._factors
