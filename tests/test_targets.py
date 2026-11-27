"""ESRS E1-4 GHG emission reduction targets from pathway scenarios."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from openscope import targets
from openscope.api.app import create_app
from openscope.api.settings import Settings
from openscope.cli import main
from openscope.engine import Calculator
from openscope.factors import FactorRegistry
from openscope.inventory import Inventory
from openscope.models import ActivityRecord, EmissionFactor, Scope
from openscope.pathway import Lever, LeverSelector, Scenario, run

EX = Path(__file__).resolve().parents[1] / "examples"


def _inventory() -> Inventory:
    reg = FactorRegistry([
        EmissionFactor(factor_id="GAS", name="gas", activity_unit="kWh", gases={"CO2": 0.2},
                       source="t"),
        EmissionFactor(factor_id="EL", name="grid", activity_unit="kWh", co2e_kg=0.1, source="t"),
        EmissionFactor(factor_id="AIR", name="flights", activity_unit="pkm", co2e_kg=0.2,
                       source="t"),
    ])  # fmt: skip
    acts = [
        ActivityRecord(activity_id="gas", description="boiler gas", quantity=300_000,
                       unit="kWh", scope=Scope.SCOPE_1, factor_id="GAS"),
        ActivityRecord(activity_id="el", description="office", quantity=400_000, unit="kWh",
                       scope=Scope.SCOPE_2, factor_id="EL"),
        ActivityRecord(activity_id="air", description="flights", quantity=500_000, unit="pkm",
                       scope=Scope.SCOPE_3, scope3_category=6, factor_id="AIR"),
    ]  # fmt: skip
    return Inventory(Calculator(reg).calculate_many(acts).results)  # 60 + 40 t, 100 t


def _scenario(**kw: object) -> Scenario:
    levers = [
        Lever(id="hp", name="Heat pumps", selector=LeverSelector(text="gas"), reduction=1.0,
              start_year=2026),
        Lever(id="travel", name="Travel policy", selector=LeverSelector(scopes=[3]),
              reduction=0.2, start_year=2026),
    ]  # fmt: skip
    data: dict[str, object] = {"name": "Test", "base_year": 2025, "target_year": 2035,
                               "levers": levers, "simulations": 50} | kw  # fmt: skip
    return Scenario.model_validate(data)


def _build(**kw: object) -> targets.TargetDisclosure:
    inv, sc = _inventory(), _scenario(**kw)
    return targets.build(inv, sc, run(inv, sc), reporting_year=2025)


def test_targets_milestones_and_values() -> None:
    d = _build()
    s12, s3 = d.targets
    assert (s12.base_tco2e, s3.base_tco2e) == (pytest.approx(100), pytest.approx(100))
    assert s12.scope_shares == {"Scope 1": pytest.approx(0.6), "Scope 2": pytest.approx(0.4)}
    assert [m.year for m in s12.milestones] == [2030, 2035]  # 2030, then every 5 years
    m2030 = s12.milestones[0]
    assert m2030.target_tco2e == pytest.approx(100 * (1 - 0.042 * 5))
    assert m2030.reduction_vs_base == pytest.approx(0.21)
    assert m2030.expected_tco2e == pytest.approx(40)  # heat pumps remove the gas
    assert s12.milestones[-1].gap_tco2e < 0
    assert s3.milestones[-1].expected_tco2e == pytest.approx(80)
    assert s3.milestones[-1].gap_tco2e == pytest.approx(80 - 75)
    assert s3.required_reduction_tco2e == pytest.approx(25)
    assert s3.planned_reduction_tco2e == pytest.approx(20)
    assert "meets the SBTi near-term minimum" in s12.ambition
    assert d.gases == ["CO2", "other gases within factors published only as CO2e"]


def test_lever_contributions_sum_to_planned() -> None:
    d = _build()
    hp = next(lv for lv in d.levers if lv.id == "hp")
    assert hp.scope12_tco2e == pytest.approx(60) and hp.share_of_scope12_reduction == 1.0
    travel = next(lv for lv in d.levers if lv.id == "travel")
    assert travel.scope3_tco2e == pytest.approx(20) and travel.share_of_scope3_reduction == 1.0
    assert travel.share_of_scope12_reduction == 0.0


def test_checks() -> None:
    codes = {c.code for c in _build().checks}
    assert "gap-scope3" in codes and "gap-scope12" not in codes
    assert "science-based" in codes and "target-2030" not in codes

    weak = {c.code for c in _build(target_year=2028, target_rate_scope12=0.02).checks}
    assert {"target-2030", "near-term-horizon", "ambition-scope12"} <= weak
    no_s3 = {c.code for c in _build(target_rate_scope3=0.0).checks}
    assert "scope3-target" in no_s3  # Scope 3 is half of the total

    inv, sc = _inventory(), _scenario(base_year=2024)
    other = targets.build(inv, sc, run(inv, sc), reporting_year=2025)
    assert "base-year-inventory" in {c.code for c in other.checks}


def test_renderers() -> None:
    d = _build()
    md = targets.to_markdown(d)
    assert "| Scope 1 and 2 (combined) | 2025 | 100.0 | 2030 | 79.0 | 21.0% |" in md
    assert "## Decarbonisation levers and their contributions in 2035 (§34(f))" in md
    assert "gross" in md
    rows = targets.to_csv(d).splitlines()
    assert rows[0] == "section,boundary,item,year,value,unit,reference"
    assert 'target,Scope 3,target value,2035,75.000,tCO2e,"E1-4 §34(a),(d)"' in rows
    data = json.loads(targets.to_json(d))
    assert data["targets"][0]["key"] == "scope12" and data["checks"][0]["level"] == "warning"


def test_api_and_cli(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    settings = Settings(db_url=f"sqlite:///{tmp_path / 't.db'}", demo_dir=EX)
    settings.add_demo_defaults()
    c = TestClient(create_app(settings))
    inv = c.post("/api/demo").json()["inventory_id"]
    scenario = c.get("/api/pathway/demo-scenario").json()
    out = c.post(f"/api/inventories/{inv}/pathway", json=scenario).json()
    e1_4 = out["e1_4"]
    assert [t["key"] for t in e1_4["targets"]] == ["scope12", "scope3"]
    s3 = e1_4["targets"][1]
    assert s3["milestones"][-1]["gap_tco2e"] == pytest.approx(out["scope3"]["gap_tco2e"])
    codes = {ch["code"] for ch in e1_4["checks"]}
    assert {"illustrative-levers", "gap-scope3"} <= codes

    r = c.post(f"/api/inventories/{inv}/pathway/e1-4", params={"format": "csv"}, json=scenario)
    assert r.status_code == 200 and r.text.startswith("section,boundary")
    assert 'filename="openscope-esrs-e1-4-2025-2035.csv"' in r.headers["content-disposition"]

    md = tmp_path / "e14.md"
    rc = main(["pathway", str(EX / "uk_demo_activities.csv"), "--scenario",
               str(EX / "pathway_demo_scenario.json"), "--dataset", "desnz-2025", "--gwp", "AR5",
               "--derive-cat3", "--year", "2025", "--e1-4", "md", "--out", str(md)])  # fmt: skip
    assert rc == 0 and "ESRS E1-4" in md.read_text()
