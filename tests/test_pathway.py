import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from openscope import (
    ActivityRecord,
    Calculator,
    EmissionFactor,
    FactorRegistry,
    Inventory,
    Scope,
    Scope3Category,
)
from openscope.cli import main
from openscope.pathway import Lever, LeverSelector, Scenario, capital_recovery_factor, run

EX = Path(__file__).parent.parent / "examples"

F = EmissionFactor(factor_id="F", name="f", activity_unit="kWh", co2e_kg=1.0, source="test")


def inventory(**lines: tuple[int, float]) -> tuple[Inventory, dict[str, str]]:
    """lines: activity_id -> (scope, tCO2e)."""
    calc = Calculator(FactorRegistry([F]))
    acts = []
    for aid, (scope, t) in lines.items():
        kw: dict[str, object] = {}
        if scope == 3:
            kw["scope3_category"] = Scope3Category.BUSINESS_TRAVEL
        acts.append(
            ActivityRecord(
                activity_id=aid,
                description=aid,
                quantity=t * 1000,
                unit="kWh",
                scope=Scope(scope),
                factor_id="F",
                **kw,
            )  # fmt: skip
        )
    return Inventory(calc.calculate_many(acts).results), {
        a.activity_id: a.description for a in acts
    }


def lever(id: str, text: str, reduction: float, **kw: object) -> Lever:
    base: dict[str, object] = {
        "id": id,
        "name": id,
        "selector": {"text": text},
        "reduction": reduction,
        "start_year": 2025,
    }
    return Lever.model_validate(base | kw)


def scenario(levers: list[Lever], **kw: object) -> Scenario:
    base: dict[str, object] = {
        "base_year": 2025,
        "target_year": 2030,
        "levers": [lv.model_dump() for lv in levers],
        "bau_growth_uncertainty": 0,
        "simulations": 50,
    }
    return Scenario.model_validate(base | kw)


def test_capital_recovery_factor() -> None:
    assert capital_recovery_factor(0, 10) == pytest.approx(0.1)
    assert capital_recovery_factor(0.08, 20) == pytest.approx(0.101852, rel=1e-5)


def test_ramp() -> None:
    lv = lever("a", "x", 0.5, start_year=2026, ramp_years=4)
    assert [lv.ramp(y) for y in (2025, 2026, 2027, 2029, 2035)] == [0, 0.25, 0.5, 1, 1]


def test_overlapping_levers_do_not_double_count_and_follow_merit_order() -> None:
    inv, desc = inventory(boiler=(1, 100.0))
    cheap = lever("cheap", "boiler", 0.5, annual_opex_change=-1000)  # negative MAC
    dear = lever("dear", "boiler", 0.5, capex=10000, lifetime_years=10)
    r = run(inv, scenario([dear, cheap]), desc)  # given in the "wrong" order
    assert [lv.id for lv in r.levers] == ["cheap", "dear"]
    assert r.levers[0].abatement_tco2e == pytest.approx(50)  # 50 % of 100
    assert r.levers[1].abatement_tco2e == pytest.approx(25)  # 50 % of the remaining 50
    assert r.pathway[-1] == pytest.approx(25)  # 100 x 0.5 x 0.5
    assert r.levers[0].mac == pytest.approx(-1000 / 50)


def test_targets_are_per_scope_group() -> None:
    inv, desc = inventory(gas=(1, 100.0), flights=(3, 100.0))
    r = run(inv, scenario([lever("hp", "gas", 1.0)]), desc)
    # 5 years at 4.2 %/yr and 2.5 %/yr
    assert r.scope12.target_tco2e == pytest.approx(100 * (1 - 0.21))
    assert r.scope3.target_tco2e == pytest.approx(100 * (1 - 0.125))
    assert r.scope12.probability_meets_target == 1.0
    assert r.scope3.probability_meets_target == 0.0
    assert r.scope3.gap_tco2e == pytest.approx(100 - 87.5)
    assert r.target[-1] == pytest.approx(79 + 87.5)


def test_bau_growth_and_monte_carlo_bands() -> None:
    inv, desc = inventory(gas=(1, 100.0))
    sc = scenario(
        [lever("hp", "gas", 0.5, reduction_low=0.2, reduction_high=0.8)],
        bau_growth={"1": 0.1},
        simulations=500,
    )
    r = run(inv, sc, desc)
    assert r.bau[-1] == pytest.approx(100 * 1.1**5)
    assert all(a <= b <= c for a, b, c in zip(r.p10, r.p50, r.p90, strict=True))
    assert r.p10[-1] < r.pathway[-1] < r.p90[-1]
    assert run(inv, sc, desc).p50 == r.p50  # seeded: reproducible


def test_lever_matching_nothing_has_no_mac() -> None:
    inv, desc = inventory(gas=(1, 10.0))
    r = run(inv, scenario([lever("none", "nothing-matches", 0.5)]), desc)
    assert r.levers[0].matched_lines == 0 and r.levers[0].mac is None


def test_selector_filters() -> None:
    inv, desc = inventory(gas=(1, 10.0), flights=(3, 10.0))
    sel = LeverSelector(scopes=[3], scope3_categories=[6])
    matched = [x.activity_id for x in inv.results if sel.matches(x, desc[x.activity_id])]
    assert matched == ["flights"]


@pytest.mark.parametrize(
    ("kw", "msg"),
    [
        ({"target_year": 2020}, "after base_year"),
        ({"levers": [{"id": "a", "name": "a", "selector": {}, "reduction": 0.5,
                      "reduction_low": 0.6, "start_year": 2025}]}, "reduction_low"),
    ],
)  # fmt: skip
def test_scenario_validation(kw: dict[str, object], msg: str) -> None:
    with pytest.raises(ValidationError, match=msg):
        Scenario.model_validate({"base_year": 2025, "target_year": 2030} | kw)


def test_demo_scenario_on_uk_demo_inventory(capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(
        [
            "pathway", str(EX / "uk_demo_activities.csv"),
            "--scenario", str(EX / "pathway_demo_scenario.json"),
            "--dataset", "desnz-2025", "--gwp", "AR5", "--json",
        ]
    )  # fmt: skip
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["base_tco2e"] == pytest.approx(650.0, abs=0.1)
    assert out["scope12"]["probability_meets_target"] == 1.0
    assert (
        out["scope3"]["probability_meets_target"] < 0.5
    )  # the demo plan under-delivers on Scope 3
    assert out["levers"][0]["id"] == "travel-policy"  # cheapest abatement first
