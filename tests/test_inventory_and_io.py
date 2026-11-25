from pathlib import Path

import pytest

from openscope import Calculator, FactorRegistry, Inventory
from openscope.cli import main
from openscope.errors import FactorError
from openscope.io import read_activities, write_results

DEMO = Path(__file__).parent.parent / "examples" / "demo_activities.csv"


@pytest.fixture
def inventory() -> Inventory:
    batch = Calculator(reporting_year=2025).calculate_many(read_activities(DEMO))
    assert batch.ok, batch.errors
    return Inventory(batch.results)


def test_scope2_dual_reporting_not_double_counted(inventory: Inventory) -> None:
    s = inventory.summary()
    assert s["scope2_location_tco2e"] == pytest.approx(340)
    assert s["scope2_market_tco2e"] == pytest.approx(175)
    expected_total = s["scope1_tco2e"] + s["scope2_market_tco2e"] + s["scope3_tco2e"]
    assert s["total_tco2e"] == pytest.approx(expected_total, abs=1e-3)


def test_scope3_category_breakdown_sums(inventory: Inventory) -> None:
    by_cat = inventory.scope3_by_category_t()
    assert sum(by_cat.values()) == pytest.approx(inventory.scope3_t())


def test_hotspots_exclude_location_based_duplicates(inventory: Inventory) -> None:
    ids = [r.activity_id for r in inventory.hotspots(3)]
    assert "S2-001" not in ids  # location-based row, superseded by market-based
    assert ids[0] == "S2-003"


def test_data_quality_and_illustrative_share(inventory: Inventory) -> None:
    dq = inventory.data_quality()
    assert dq is not None and 1 <= dq <= 5
    assert 0 < inventory.illustrative_share() < 1


def test_empty_inventory() -> None:
    inv = Inventory([])
    assert inv.total_t() == 0
    assert inv.data_quality() is None


def test_write_results_roundtrip(tmp_path: Path, inventory: Inventory) -> None:
    out = tmp_path / "results.csv"
    write_results(inventory.results, out)
    lines = out.read_text().splitlines()
    assert len(lines) == len(inventory.results) + 1
    assert lines[0].startswith("activity_id,scope")


def test_registry_rejects_duplicates_and_merge_overrides(tmp_path: Path) -> None:
    csv = tmp_path / "f.csv"
    csv.write_text(
        "factor_id,name,activity_unit,co2e_kg,source\n"
        "DEMO-HOTEL-NIGHT,Hotel (custom),night,15,My study\n"
    )
    merged = FactorRegistry.bundled().merge(FactorRegistry.from_csv(csv))
    assert merged.get("DEMO-HOTEL-NIGHT").co2e_kg == 15

    reg = FactorRegistry.from_csv(csv)
    with pytest.raises(FactorError, match="Duplicate"):
        reg.add(reg.get("DEMO-HOTEL-NIGHT"))


def test_bad_factor_row_reports_line(tmp_path: Path) -> None:
    csv = tmp_path / "bad.csv"
    csv.write_text("factor_id,name,activity_unit,co2e_kg,source\nX,Bad,kWh,abc,src\n")
    with pytest.raises(FactorError, match=":2:"):
        FactorRegistry.from_csv(csv)


def test_cli_smoke(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    out = tmp_path / "r.csv"
    assert main(["calculate", str(DEMO), "--year", "2025", "--out", str(out)]) == 0
    printed = capsys.readouterr().out
    assert "Scope 2 (market-based)" in printed
    assert out.exists()
