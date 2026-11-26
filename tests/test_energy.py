from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from openscope import (
    ActivityRecord,
    Calculator,
    EmissionFactor,
    FactorRegistry,
    Inventory,
    Scope,
    Scope2Method,
)
from openscope.api.app import create_app
from openscope.api.settings import Settings
from openscope.cli import main
from openscope.disclosure import Period, build
from openscope.energy import GridMix, biogenic_t, energy_mix
from openscope.importers import desnz
from openscope.io import read_activities
from openscope.models import EnergySource

EX = Path(__file__).parent.parent / "examples"


@pytest.fixture(scope="module")
def desnz2025() -> FactorRegistry:
    return FactorRegistry.dataset("desnz-2025")


# -- importer: energy content and biogenic CO2 from DESNZ's own numbers ------------------------
def test_desnz_derived_net_calorific_values(desnz2025: FactorRegistry) -> None:
    diesel = desnz2025.get("DESNZ-2025-1_101_1011_8")  # diesel (average biofuel blend), litres
    assert diesel.energy_source == EnergySource.FOSSIL_FUEL
    assert diesel.energy_kwh_per_unit == pytest.approx(9.906, abs=0.01)
    gas_gross = desnz2025.get("DESNZ-2025-1_100_1004_6")  # natural gas, kWh gross CV
    assert gas_gross.energy_kwh_per_unit == pytest.approx(0.9026, abs=0.001)  # net / gross
    biodiesel = desnz2025.get("DESNZ-2025-2_103_1032_8")  # via the GJ factor
    assert biodiesel.energy_source == EnergySource.RENEWABLE_FUEL
    assert biodiesel.energy_kwh_per_unit == pytest.approx(9.2, abs=0.05)


def test_desnz_biogenic_links(desnz2025: FactorRegistry) -> None:
    assert desnz2025.get("DESNZ-2025-1_101_1011_8").biogenic_co2_kg == pytest.approx(0.14)
    grid = desnz2025.get("DESNZ-2025-7_400_4000_5")
    assert grid.energy_source == EnergySource.ELECTRICITY and grid.energy_kwh_per_unit == 1
    assert grid.biogenic_co2_kg == pytest.approx(0.11507)
    refrigerant = desnz2025.get("DESNZ-2025-3_201_2156_3")
    assert refrigerant.energy_source == EnergySource.NON_ENERGY


def test_ambiguous_biogenic_match_is_not_linked() -> None:
    header = ("ID", "Scope", "Level 1", "Level 2", "Level 3", "Level 4", "Column Text", "UOM",
              "GHG/Unit", "GHG Conversion Factor 2025")  # fmt: skip
    rows = [
        header,
        ("1_1_1_8_1", "Scope 1", "Fuels", "Liquid fuels", "X", None, None, "litres", "kg CO2e", 2),
        ("1_2_1_8_1", "Scope 1", "Fuels", "Other liquid", "X", None, None, "litres", "kg CO2e", 3),
        ("99_1_1_8_2", "Outside of Scopes", "Outside of scopes", "Y", "X", None, None, "litres",
         "kg CO2e of CO2 per unit", 0.5),
    ]  # fmt: skip
    rep = desnz.parse_rows(rows, 2025)
    assert rep.biogenic_linked == 0


# -- engine and energy mix ----------------------------------------------------------------------
def test_engine_traces_energy_and_biogenic(desnz2025: FactorRegistry) -> None:
    r = Calculator(desnz2025).calculate(
        ActivityRecord(
            activity_id="d",
            quantity=1000,
            unit="L",
            scope=Scope.SCOPE_1,
            factor_id="DESNZ-2025-1_101_1011_8",
        )  # fmt: skip
    )
    assert r.energy_kwh == pytest.approx(9906, abs=10)
    assert r.biogenic_co2_kg == pytest.approx(140)
    assert any(t.startswith("Energy:") for t in r.trace)
    assert any("outside the scopes" in t for t in r.trace)


def _mixed_inventory() -> Inventory:
    grid = EmissionFactor(
        factor_id="G",
        name="grid",
        activity_unit="kWh",
        co2e_kg=0.2,
        source="t",
        energy_kwh_per_unit=1,
        energy_source="electricity",
        biogenic_co2_kg=0.1,
        scope2_method=Scope2Method.LOCATION_BASED,
    )
    rego = EmissionFactor(
        factor_id="R",
        name="rego",
        activity_unit="kWh",
        co2e_kg=0.0,
        source="t",
        energy_kwh_per_unit=1,
        energy_source="renewable_electricity",
        scope2_method=Scope2Method.MARKET_BASED,
    )
    gas = EmissionFactor(
        factor_id="F",
        name="gas",
        activity_unit="kWh",
        co2e_kg=0.18,
        source="t",
        energy_kwh_per_unit=1,
        energy_source="fossil_fuel",
    )
    calc = Calculator(FactorRegistry([grid, rego, gas]))
    a = [
        ActivityRecord(activity_id="hq-lb", quantity=1000_000, unit="kWh", scope=Scope.SCOPE_2,
                       site="HQ", factor_id="G"),
        # certificates for more than the site uses: capped at consumption
        ActivityRecord(activity_id="hq-mb", quantity=1200_000, unit="kWh", scope=Scope.SCOPE_2,
                       site="HQ", factor_id="R"),
        ActivityRecord(activity_id="wh-lb", quantity=500_000, unit="kWh", scope=Scope.SCOPE_2,
                       site="WH", factor_id="G"),
        ActivityRecord(activity_id="boiler", quantity=2000_000, unit="kWh", scope=Scope.SCOPE_1,
                       factor_id="F"),
    ]  # fmt: skip
    return Inventory(calc.calculate_many(a).results)


def test_energy_mix_counts_electricity_once_and_caps_certificates() -> None:
    m = energy_mix(_mixed_inventory())
    assert m.electricity_total == pytest.approx(1500)  # MWh, location-based rows only
    assert m.electricity_renewable_certificates == pytest.approx(1000)  # capped at HQ use
    assert m.electricity_other == pytest.approx(500)
    assert m.fossil_fuels == pytest.approx(2000)
    assert m.total == pytest.approx(3500)
    assert m.fossil is None and m.undetermined == pytest.approx(500)

    g = energy_mix(_mixed_inventory(), GridMix(0.5, 0.2, 0.3))
    assert g.fossil == pytest.approx(2000 + 250)
    assert g.nuclear == pytest.approx(100)
    assert g.renewable == pytest.approx(1000 + 150)
    assert g.undetermined == 0


def test_biogenic_scope2_uses_location_based_rows() -> None:
    assert biogenic_t(_mixed_inventory(), Scope.SCOPE_2) == pytest.approx(150)  # 1.5 GWh x 0.1 kg


def test_grid_mix_validation() -> None:
    with pytest.raises(ValueError, match="sum to 100"):
        GridMix(0.5, 0.5, 0.5)


# -- disclosure ------------------------------------------------------------------------------
def test_esrs_disclosure_has_energy_section_and_biogenic_rows() -> None:
    d = build(Period(_mixed_inventory(), 2025, "AR6"), net_revenue=10_000_000)
    rows = {r.key: r for r in d.rows}
    assert rows["energy_total"].section == "E1-5"
    assert rows["energy_total"].current == pytest.approx(3500)
    assert rows["energy_fossil"].current is None  # undetermined without a grid mix
    assert rows["energy_fossil_fuels"].current == pytest.approx(2000)
    assert rows["energy_renewable_share"].current == pytest.approx(1000 / 3500 * 100)
    assert rows["energy_intensity"].current == pytest.approx(350)
    assert rows["biogenic"].current == pytest.approx(150)
    assert {c.code for c in d.checks} >= {"energy-mix", "biogenic-co2", "self-generated-renewables"}

    with_mix = build(Period(_mixed_inventory(), 2025, "AR6"), grid_mix=GridMix(0.5, 0.2, 0.3))
    assert "energy-mix" not in {c.code for c in with_mix.checks}
    assert {r.key: r for r in with_mix.rows}["energy_fossil"].current == pytest.approx(2250)


def test_issb_has_no_energy_section() -> None:
    d = build(Period(_mixed_inventory(), 2025, "AR6"), framework="issb")
    assert {r.section for r in d.rows} == {"S2"}


def test_api_and_cli_grid_mix(tmp_path: Path) -> None:
    settings = Settings(db_url=f"sqlite:///{tmp_path / 'e.db'}", demo_dir=EX)
    settings.add_demo_defaults()
    c = TestClient(create_app(settings))
    inv = c.post("/api/demo").json()["inventory_id"]
    mix = {"grid_fossil": 40, "grid_nuclear": 15, "grid_renewable": 45}
    ok = c.get(f"/api/inventories/{inv}/disclosure", params=mix).json()
    fossil = next(r for r in ok["rows"] if r["key"] == "energy_fossil")
    assert fossil["current"] == pytest.approx(1183.3 + 250 * 0.4, abs=0.5)
    bad = c.get(f"/api/inventories/{inv}/disclosure",
                params={"grid_fossil": 40, "grid_nuclear": 15, "grid_renewable": 5})  # fmt: skip
    assert bad.status_code == 422 and "sum to 100" in bad.json()["detail"]

    out = tmp_path / "d.csv"
    args = ["--year", "2025", "--grid-mix", "40,15,45", "--format", "csv", "--out", str(out)]
    rc = main(["disclose", str(EX / "uk_demo_activities.csv"), "--dataset", "desnz-2025", *args])
    assert rc == 0 and "E1-5,energy_total" in out.read_text()


def test_demo_inventory_energy(desnz2025: FactorRegistry) -> None:
    reg = FactorRegistry.bundled().merge(desnz2025)
    acts = read_activities(EX / "uk_demo_activities.csv")
    inv = Inventory(Calculator(reg).calculate_many(acts).results)
    m = energy_mix(inv)
    assert m.fossil_fuels == pytest.approx(1183.3, abs=0.5)  # gas 767 + diesel 416 MWh
    assert m.electricity_renewable_certificates == pytest.approx(600)
    assert m.lines_without_energy == 0  # the refrigerant line is non-energy
