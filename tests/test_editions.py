"""Yearly factor editions: DESNZ 2024-2026 and resolving ids without a year."""

from __future__ import annotations

import collections
from datetime import date

import pytest

from openscope.disclosure import Period, build
from openscope.engine import Calculator
from openscope.errors import FactorError
from openscope.factors import FactorRegistry
from openscope.factors.registry import generic_id
from openscope.inventory import Inventory
from openscope.models import ActivityRecord, EmissionFactor, Scope

GRID = "DESNZ-7_400_4000_5"  # UK grid electricity, without a year


@pytest.fixture(scope="module")
def desnz() -> FactorRegistry:
    return FactorRegistry.dataset("desnz")


def _elec(year: int | None, qty: float = 1000) -> ActivityRecord:
    period = {"period_end": date(year, 12, 31)} if year else {}
    return ActivityRecord(activity_id=f"el-{year}", quantity=qty, unit="kWh",
                          scope=Scope.SCOPE_2, factor_id=GRID, **period)  # fmt: skip


def test_bundled_editions(desnz: FactorRegistry) -> None:
    assert {"desnz-2024", "desnz-2025", "desnz-2026"} <= set(FactorRegistry.available_datasets())
    assert desnz.editions(GRID) == [2024, 2025, 2026]
    grid = {y: desnz.get(f"DESNZ-{y}-7_400_4000_5") for y in (2024, 2025, 2026)}
    co2 = {y: f.gases["CO2"] for y, f in grid.items()}
    assert co2[2024] > co2[2025] > co2[2026]  # the UK grid keeps decarbonising
    assert all(f.year == y for y, f in grid.items())
    # the importer's derived data is there for every edition
    assert all(f.energy_kwh_per_unit for f in grid.values())
    assert all(len(f.cat3_factor_ids) == 3 for f in grid.values())


def test_ids_keep_their_meaning_across_editions(desnz: FactorRegistry) -> None:
    """Year matching relies on DESNZ ids meaning the same thing every year."""
    units: dict[str, set[str]] = collections.defaultdict(set)
    scopes: dict[str, set[object]] = collections.defaultdict(set)
    for f in desnz:
        units[generic_id(f.factor_id)].add(f.activity_unit)
        scopes[generic_id(f.factor_id)].add(f.scope)
    assert all(len(u) == 1 for u in units.values())
    assert all(len(s) == 1 for s in scopes.values())


def test_resolve_by_activity_year(desnz: FactorRegistry) -> None:
    calc = Calculator(desnz, reporting_year=2025)
    for year in (2024, 2025, 2026):
        r = calc.calculate(_elec(year))
        assert r.factor_id == f"DESNZ-{year}-7_400_4000_5"
        assert f"Edition: {year}, matching the activity year" in r.trace
    # no period: the calculator's reporting year
    assert calc.calculate(_elec(None)).factor_id == "DESNZ-2025-7_400_4000_5"
    # a later year falls back to the latest earlier edition, with a warning
    later = calc.calculate(_elec(2028))
    assert later.factor_id == "DESNZ-2026-7_400_4000_5"
    assert any(t.startswith("WARNING: no 2028 edition") for t in later.trace)
    # an earlier year than any edition uses the earliest, with a warning
    early = calc.calculate(_elec(2019))
    assert early.factor_id == "DESNZ-2024-7_400_4000_5"
    assert any("no 2019 or earlier edition" in t for t in early.trace)
    # an exact id is used as given, whatever the year
    exact = calc.calculate(_elec(2026).model_copy(update={"factor_id": "DESNZ-2024-7_400_4000_5"}))
    assert exact.factor_id == "DESNZ-2024-7_400_4000_5"
    assert not any(t.startswith("Edition") for t in exact.trace)


def test_resolve_errors_and_non_yearly_ids() -> None:
    reg = FactorRegistry([
        EmissionFactor(factor_id="USEEIO-1.3-111110", name="x", activity_unit="USD",
                       co2e_kg=1, source="t"),
    ])  # fmt: skip
    assert reg.editions("USEEIO-111110") == []  # "1.3" is a version, not a year
    with pytest.raises(FactorError, match="Unknown factor_id"):
        reg.resolve("DESNZ-7_400_4000_5", 2025)


def test_derived_cat3_follows_the_edition(desnz: FactorRegistry) -> None:
    batch = Calculator(desnz, derive_cat3=True).calculate_many([_elec(2026)])
    derived = [r.factor_id for r in batch.results if r.derived_from]
    assert derived and all(f.startswith("DESNZ-2026-") for f in derived)
    # a manual line with the year-free id still prevents double counting
    manual = ActivityRecord(activity_id="td", quantity=1000, unit="kWh", scope=Scope.SCOPE_3,
                            scope3_category=3, factor_id="DESNZ-13_402_4000_5",
                            period_end=date(2026, 12, 31))  # fmt: skip
    batch = Calculator(desnz, derive_cat3=True).calculate_many([_elec(2026), manual])
    assert batch.cat3_skipped == ["el-2026: DESNZ-2026-13_402_4000_5"]


def test_disclosure_notes_different_editions(desnz: FactorRegistry) -> None:
    def period(year: int) -> Period:
        res = Calculator(desnz, reporting_year=year).calculate_many([_elec(year)]).results
        return Period(Inventory(res), year, "AR6")

    d = build(period(2025), prior=period(2024))
    note = next(c for c in d.checks if c.code == "factor-editions")
    assert "(DESNZ): 2024 → 2025" in note.message
    same = build(period(2025), prior=period(2025))
    assert "factor-editions" not in {c.code for c in same.checks}
