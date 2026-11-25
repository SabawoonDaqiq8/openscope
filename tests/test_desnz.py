from pathlib import Path

import pytest

from openscope import ActivityRecord, Calculator, FactorRegistry, Scope, Scope2Method
from openscope.errors import FactorError
from openscope.importers import desnz

HEADER = (
    "ID",
    "Scope",
    "Level 1",
    "Level 2",
    "Level 3",
    "Level 4",
    "Column Text",
    "UOM",
    "GHG/Unit",
    "GHG Conversion Factor 2025",
)
PREAMBLE = [
    ("UK Government GHG Conversion Factors for Company Reporting",) + (None,) * 9,
    (None,) * 10,
]


def rows(*body: tuple[object, ...]) -> list[tuple[object, ...]]:
    return [*PREAMBLE, HEADER, *body, ("END",) + (None,) * 9]


ELEC = [
    ("7_400_4000_5_1", "Scope 2", "UK electricity", "Electricity generated", "Electricity: UK",
     "kWh", None, "kWh", "kg CO2e", 0.177),
    ("7_400_4000_5_2", "Scope 2", "UK electricity", "Electricity generated", "Electricity: UK",
     "kWh", None, "kWh", "kg CO2e of CO2 per unit", 0.17489),
    ("7_400_4000_5_3", "Scope 2", "UK electricity", "Electricity generated", "Electricity: UK",
     "kWh", None, "kWh", "kg CO2e of CH4 per unit", 0.0009),
    ("7_400_4000_5_4", "Scope 2", "UK electricity", "Electricity generated", "Electricity: UK",
     "kWh", None, "kWh", "kg CO2e of N2O per unit", 0.00122),
]  # fmt: skip


def test_per_gas_values_are_converted_back_to_gas_mass() -> None:
    rep = desnz.parse_rows(rows(*ELEC), 2025)
    (f,) = rep.factors
    assert f.factor_id == "DESNZ-2025-7_400_4000_5"
    assert f.activity_unit == "kWh"
    assert f.scope == Scope.SCOPE_2
    assert f.scope2_method == Scope2Method.LOCATION_BASED
    assert f.gases["CO2"] == pytest.approx(0.17489)
    assert f.gases["CH4"] == pytest.approx(0.0009 / 28)
    assert f.gases["N2O"] == pytest.approx(0.00122 / 265)
    assert f.co2e_kg is None and f.gwp_basis is None
    assert rep.per_gas == 1


def test_ar5_recalculation_reproduces_published_total() -> None:
    (f,) = desnz.parse_rows(rows(*ELEC), 2025).factors
    a = ActivityRecord(activity_id="e", quantity=1, unit="kWh", scope=Scope.SCOPE_2)
    ar5 = Calculator(FactorRegistry(), gwp_set="AR5").calculate(a, f)
    ar6 = Calculator(FactorRegistry(), gwp_set="AR6").calculate(a, f)
    assert ar5.co2e_kg == pytest.approx(0.177, abs=1e-4)
    assert ar6.co2e_kg > ar5.co2e_kg  # AR6 CH4/N2O GWPs are higher


def test_total_only_and_ar4_bioenergy() -> None:
    rep = desnz.parse_rows(
        rows(
            (
                "15_900_1_1_1",
                "Scope 3",
                "WTT- bioenergy",
                "Biofuel",
                "Biodiesel ME",
                None,
                None,
                "litres",
                "kg CO2e",
                0.5,
            ),
        ),  # fmt: skip
        2025,
    )
    (f,) = rep.factors
    assert f.co2e_kg == 0.5
    assert f.gwp_basis == "AR4"
    assert f.scope3_category is not None and f.scope3_category.value == 3


def test_unreconciled_gases_fall_back_to_total() -> None:
    bad = list(ELEC)
    bad[1] = (*ELEC[1][:9], 0.5)  # CO2 component no longer adds up to the total
    (f,) = desnz.parse_rows(rows(*bad), 2025).factors
    assert not f.gases
    assert f.co2e_kg == 0.177 and f.gwp_basis == "AR5"


def test_blank_values_and_energy_rows_skipped() -> None:
    rep = desnz.parse_rows(
        rows(
            (
                "1_1_1_8_1",
                "Scope 1",
                "Fuels",
                "Liquid fuels",
                "X",
                None,
                None,
                "litres",
                "kg CO2e",
                None,
            ),
            (
                "5_1_1_1_1",
                "Scope 1",
                "SECR kWh pass & delivery vehs",
                "Cars",
                "Small",
                None,
                None,
                "km",
                "kWh (Net CV)",
                0.2,
            ),
        ),  # fmt: skip
        2025,
    )
    assert rep.factors == []
    assert rep.skipped_energy_rows == 1


def test_unmapped_unit_reported() -> None:
    rep = desnz.parse_rows(
        rows(("9_1_1_1_1", "Scope 3", "Odd", "x", "y", None, None, "furlongs", "kg CO2e", 1.0)),
        2025,
    )
    assert rep.skipped_unknown_unit == {"furlongs": 1}


def test_missing_header_raises() -> None:
    with pytest.raises(FactorError, match="header"):
        desnz.parse_rows([("nothing here",)], 2025)


def test_read_workbook_detects_year(tmp_path: Path) -> None:
    openpyxl = pytest.importorskip("openpyxl")
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = desnz.SHEET
    for r in rows(*ELEC):
        ws.append(list(r))
    path = tmp_path / "flat.xlsx"
    wb.save(path)
    rep = desnz.read_workbook(path)
    assert rep.factors[0].year == 2025


# -- the bundled, real DESNZ 2025 dataset -------------------------------------------------------
@pytest.fixture(scope="module")
def desnz2025() -> FactorRegistry:
    return FactorRegistry.dataset("desnz-2025")


def test_bundled_dataset_loads(desnz2025: FactorRegistry) -> None:
    assert len(desnz2025) > 2500
    assert all(f.region == "UK" and f.year == 2025 for f in desnz2025)


def test_bundled_uk_grid_electricity(desnz2025: FactorRegistry) -> None:
    calc = Calculator(desnz2025, gwp_set="AR5")
    r = calc.calculate(
        ActivityRecord(
            activity_id="grid",
            quantity=1000,
            unit="MWh",
            scope=Scope.SCOPE_2,
            factor_id="DESNZ-2025-7_400_4000_5",
        )
    )
    assert r.co2e_t == pytest.approx(177, rel=1e-3)  # published 0.177 kg CO2e/kWh


def test_csv_roundtrip(tmp_path: Path, desnz2025: FactorRegistry) -> None:
    out = tmp_path / "rt.csv"
    desnz2025.to_csv(out, header_comment="roundtrip")
    again = FactorRegistry.from_csv(out)
    assert len(again) == len(desnz2025)
    for f in list(desnz2025)[:200]:
        assert again.get(f.factor_id) == f


def test_unknown_dataset() -> None:
    with pytest.raises(FactorError, match="Available"):
        FactorRegistry.dataset("nope")
