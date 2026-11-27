"""Scope 3 Category 3 (fuel- and energy-related activities) derived from Scope 1/2 lines."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from openscope.api.app import create_app
from openscope.api.settings import Settings
from openscope.disclosure import Period, build
from openscope.engine import Calculator, cat3_kind
from openscope.factors import FactorRegistry
from openscope.importers.desnz import link_cat3
from openscope.inventory import Inventory
from openscope.io import read_activities
from openscope.models import ActivityRecord, EmissionFactor, Scope, Scope2Method, Scope3Category

EX = Path(__file__).resolve().parents[1] / "examples"
ELEC = "DESNZ-2025-7_400_4000_5"
GAS = "DESNZ-2025-1_100_1004_6"  # natural gas, kWh gross CV


@pytest.fixture(scope="module")
def reg() -> FactorRegistry:
    return FactorRegistry.bundled().merge(FactorRegistry.dataset("desnz-2025"))


def _names(reg: FactorRegistry, fid: str) -> list[str]:
    return [reg.get(x).name for x in reg.get(fid).cat3_factor_ids]


def test_desnz_links(reg: FactorRegistry) -> None:
    assert _names(reg, GAS) == ["WTT- fuels / Gaseous fuels / Natural gas / Gross CV"]
    assert [cat3_kind(reg.get(x))[0] for x in reg.get(ELEC).cat3_factor_ids] == [
        "WTT", "WTT-T&D", "T&D"
    ]  # fmt: skip
    district = next(f for f in reg if f.name.startswith("Heat and steam") and "District" in f.name)
    assert len(district.cat3_factor_ids) == 3  # WTT, WTT of distribution loss, distribution loss
    hgv = next(f for f in reg if f.name.startswith("Delivery vehicles / HGV (all diesel)"))
    assert all("refrigerated" not in n for n in _names(reg, hgv.factor_id))
    linked = [f for f in reg if f.cat3_factor_ids]
    assert len(linked) == 552
    assert all(f.scope in (Scope.SCOPE_1, Scope.SCOPE_2) for f in linked)
    assert all(x in reg for f in linked for x in f.cat3_factor_ids)


def test_link_cat3_prefers_same_name_only_on_ties() -> None:
    def f(fid: str, name: str) -> EmissionFactor:
        return EmissionFactor(factor_id=fid, name=name, activity_unit="km", co2e_kg=1, source="t")

    out = link_cat3([
        f("D-5_303_3095_4", "Delivery vehicles / HGV (all diesel) / Rigid"),
        f("D-28_906_3095_4", "WTT- delivery vehs & freight / WTT- HGV (all diesel) / Rigid"),
        f("D-28_907_3095_4", "WTT- freight / WTT- HGV refrigerated (all diesel) / Rigid"),
    ])  # fmt: skip
    assert out[0].cat3_factor_ids == ("D-28_906_3095_4",)


def test_csv_round_trip(reg: FactorRegistry, tmp_path: Path) -> None:
    out = tmp_path / "f.csv"
    FactorRegistry([reg.get(ELEC)]).to_csv(out)
    assert FactorRegistry.from_csv(out).get(ELEC).cat3_factor_ids == reg.get(ELEC).cat3_factor_ids


def _act(aid: str, qty: float, unit: str, scope: int, fid: str, **kw: object) -> ActivityRecord:
    return ActivityRecord(activity_id=aid, quantity=qty, unit=unit, scope=Scope(scope),
                          factor_id=fid, **kw)  # type: ignore[arg-type]  # fmt: skip


def test_derivation_matches_manual_lines(reg: FactorRegistry) -> None:
    gas = _act("gas", 850_000, "kWh", 1, GAS, site="HQ", description="Boiler gas")
    derived = Calculator(reg, "AR5", derive_cat3=True).calculate_many([gas])
    wtt = next(r for r in derived.results if r.activity_id == "gas:WTT")
    manual = Calculator(reg, "AR5").calculate(
        _act("m", 850_000, "kWh", 3, "DESNZ-2025-11_100_1004_6", scope3_category=3)
    )
    assert wtt.co2e_kg == pytest.approx(manual.co2e_kg)
    assert wtt.scope3_category == Scope3Category.FUEL_AND_ENERGY_RELATED
    assert wtt.derived_from == "gas" and wtt.site == "HQ"
    assert wtt.trace[0].startswith("Derived from Scope 1 activity gas")
    assert derived.derived[0].description == (
        "Boiler gas: well-to-tank (upstream extraction, processing and transport of the energy)"
    )
    assert not Calculator(reg, "AR5").calculate_many([gas]).derived  # off by default


def test_electricity_once_per_site_and_units(reg: FactorRegistry) -> None:
    supplier = EmissionFactor(
        factor_id="SUPPLIER-GRID", name="Supplier tariff", activity_unit="kWh", co2e_kg=0.2,
        source="t", scope=Scope.SCOPE_2, scope2_method=Scope2Method.MARKET_BASED,
        cat3_factor_ids=("DESNZ-2025-13_402_4000_5",),
    )  # fmt: skip
    reg = reg.merge(FactorRegistry([supplier]))
    acts = [
        _act("hq-lb", 600, "MWh", 2, ELEC, site="HQ", scope2_method=Scope2Method.LOCATION_BASED),
        _act("hq-mb", 600, "MWh", 2, "SCOPE2-EAC-RENEWABLE", site="HQ",
             scope2_method=Scope2Method.MARKET_BASED),
        # a site reported market-based only: its grid electricity still has upstream emissions
        _act("shop-mb", 100, "MWh", 2, "SUPPLIER-GRID", site="Shop",
             scope2_method=Scope2Method.MARKET_BASED),
    ]  # fmt: skip
    batch = Calculator(reg, "AR5", derive_cat3=True).calculate_many(acts)
    sources = sorted({r.derived_from for r in batch.results if r.derived_from})
    assert sources == ["hq-lb", "shop-mb"]
    td = next(r for r in batch.results if r.activity_id == "hq-lb:T&D")
    assert td.converted_quantity == pytest.approx(600_000)  # MWh -> kWh


def test_lines_already_reported_are_not_derived_again(reg: FactorRegistry) -> None:
    acts = [
        _act("el", 850, "MWh", 2, ELEC, site="HQ"),
        _act("td", 850, "MWh", 3, "DESNZ-2025-13_402_4000_5", scope3_category=3),
    ]
    batch = Calculator(reg, "AR5", derive_cat3=True).calculate_many(acts)
    ids = {r.activity_id for r in batch.results}
    assert ids == {"el", "td", "el:WTT", "el:WTT-T&D"}
    assert batch.cat3_skipped == ["el: DESNZ-2025-13_402_4000_5"]


def test_disclosure_checks(reg: FactorRegistry) -> None:
    acts = read_activities(EX / "uk_demo_activities.csv")
    on = Inventory(Calculator(reg, "AR5", derive_cat3=True).calculate_many(acts).results)
    off = Inventory(Calculator(reg, "AR5").calculate_many(acts).results)
    codes_on = {c.code for c in build(Period(on, 2025, "AR5")).checks}
    codes_off = {c.code for c in build(Period(off, 2025, "AR5")).checks}
    assert "cat3-derived" in codes_on and "cat3-missing" not in codes_on
    assert "cat3-missing" in codes_off
    assert on.total_t() == pytest.approx(650.0, abs=0.05)  # the demo stays at 650 t


def test_api_upload_and_demo(tmp_path: Path) -> None:
    settings = Settings(db_url=f"sqlite:///{tmp_path / 'c.db'}", demo_dir=EX)
    settings.add_demo_defaults()
    c = TestClient(create_app(settings))
    inv = c.post("/api/demo").json()["inventory_id"]
    lines = c.get(f"/api/inventories/{inv}/lines", params={"scope": 3}).json()
    derived = [ln for ln in lines if ln["derived_from"]]
    assert {ln["activity_id"] for ln in derived} >= {"S1-GAS:WTT", "S2-HQ-LB:T&D"}
    assert next(ln for ln in derived if ln["activity_id"] == "S1-GAS:WTT")[
        "description"
    ].startswith("HQ boiler natural gas")

    csv = (EX / "uk_demo_activities.csv").read_bytes()
    for flag, expect in (("true", True), ("false", False)):
        r = c.post("/api/inventories", files={"file": ("a.csv", csv, "text/csv")},
                   data={"name": f"upload {flag}", "derive_cat3": flag})  # fmt: skip
        assert r.status_code == 201
        got = c.get(f"/api/inventories/{r.json()['id']}/lines").json()
        assert any(ln["derived_from"] for ln in got) is expect
