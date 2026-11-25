"""Emission-factor registry.

Factors are loaded from CSV so that datasets (EPA, DEFRA/DESNZ, USEEIO, IEA,
supplier-specific…) can be versioned, diffed and reviewed like code.

CSV columns
-----------
factor_id, name, activity_unit, co2_kg, ch4_kg, n2o_kg, other_gases, co2e_kg,
scope, scope3_category, scope2_method, region, year, source, source_url, status, notes

``other_gases`` is a ``;``-separated list of ``GAS=kg`` pairs, e.g. ``HFC-134A=1``.
Empty cells are treated as missing.
"""

from __future__ import annotations

import csv
from collections.abc import Iterable, Iterator
from importlib import resources
from pathlib import Path

from openscope.errors import FactorError
from openscope.models import EmissionFactor, FactorStatus, Scope, Scope2Method, Scope3Category

_BUNDLED = "sample_factors.csv"


def _opt(row: dict[str, str], key: str) -> str | None:
    value = (row.get(key) or "").strip()
    return value or None


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
            scope=Scope(int(scope)) if scope else None,
            scope3_category=Scope3Category(int(cat)) if cat else None,
            scope2_method=Scope2Method(s2) if s2 else None,
            region=_opt(row, "region") or "GLOBAL",
            year=int(year) if year else None,
            source=row["source"].strip(),
            source_url=_opt(row, "source_url"),
            status=FactorStatus(_opt(row, "status") or "reference"),
            notes=_opt(row, "notes"),
        )
    except (KeyError, ValueError) as exc:
        raise FactorError(f"{origin}:{line}: invalid factor row: {exc}") from exc


class FactorRegistry:
    """An in-memory, id-addressable collection of emission factors."""

    def __init__(self, factors: Iterable[EmissionFactor] = ()) -> None:
        self._factors: dict[str, EmissionFactor] = {}
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

    def __iter__(self) -> Iterator[EmissionFactor]:
        return iter(self._factors.values())

    def __len__(self) -> int:
        return len(self._factors)

    def __contains__(self, factor_id: object) -> bool:
        return factor_id in self._factors
