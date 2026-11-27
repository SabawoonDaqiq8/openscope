"""EEA GHG intensity of electricity generation: EU location-based grid factors."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from openscope.cli import main
from openscope.energy import energy_mix
from openscope.engine import Calculator
from openscope.errors import FactorError
from openscope.factors import FactorRegistry
from openscope.importers import eea
from openscope.inventory import Inventory
from openscope.models import ActivityRecord, Scope, Scope2Method

FIGURE = {
    "visualization": {
        "dataSources": {
            "Countries": ["Sweden", "<b>EU-27</b>", "Germany", "Atlantis"],
            "2014": ["11", "300", "500", "1"],
            "2023": ["7", "206", "316", "1"],
            "2024": ["6", "183", "291", "1"],
            "2025": ["7", "178", "", "1"],
        }
    }
}


def test_parse() -> None:
    r = eea.parse(FIGURE)
    ids = {f.factor_id: f for f in r.factors}
    assert set(ids) == {"EEA-2023-SE", "EEA-2024-SE", "EEA-2025-SE", "EEA-2023-EU27",
                        "EEA-2024-EU27", "EEA-2025-EU27", "EEA-2023-DE", "EEA-2024-DE"}  # fmt: skip
    assert r.unknown_countries == ["Atlantis"] and r.countries == 3
    assert r.years == [2023, 2024, 2025] and r.estimated_year == 2025  # 2014 < FIRST_YEAR
    de = ids["EEA-2024-DE"]
    assert de.co2e_kg == pytest.approx(0.291) and de.gwp_basis == "AR5"
    assert de.scope == Scope.SCOPE_2 and de.scope2_method == Scope2Method.LOCATION_BASED
    assert de.region == "DE" and de.energy_kwh_per_unit == 1
    assert ids["EEA-2024-EU27"].name == "Electricity: grid average, EU-27 average"
    assert "early estimate" in (ids["EEA-2025-SE"].notes or "")
    assert "early estimate" not in (ids["EEA-2024-SE"].notes or "")


def test_parse_rejects_other_json() -> None:
    with pytest.raises(FactorError, match="dataSources"):
        eea.parse({"title": "not a figure"})


def test_bundled_dataset() -> None:
    reg = FactorRegistry.dataset("eea-electricity")
    assert len(reg) == 308  # 27 countries + EU-27, 2015-2025
    assert reg.editions("EEA-DE") == list(range(2015, 2026))
    g = {c: reg.get(f"EEA-2024-{c}").co2e_kg for c in ("SE", "FR", "EU27", "DE", "PL")}
    assert g["SE"] < g["FR"] < g["EU27"] < g["DE"] < g["PL"]
    assert g["EU27"] == pytest.approx(0.183)


def test_year_matching_and_energy() -> None:
    reg = FactorRegistry.dataset("eea-electricity")
    calc = Calculator(reg)

    def act(year: int) -> ActivityRecord:
        return ActivityRecord(activity_id=f"berlin-{year}", quantity=100_000, unit="kWh",
                              scope=Scope.SCOPE_2, factor_id="EEA-DE", site="Berlin",
                              period_end=date(year, 12, 31))  # fmt: skip

    r24 = calc.calculate(act(2024))
    assert r24.factor_id == "EEA-2024-DE" and r24.co2e_kg == pytest.approx(29_100)
    r26 = calc.calculate(act(2026))  # no 2026 value yet: latest earlier year, with a warning
    assert r26.factor_id == "EEA-2025-DE"
    assert any(t.startswith("WARNING: no 2026 edition") for t in r26.trace)
    m = energy_mix(Inventory([r24]))
    assert m.electricity_total == pytest.approx(100)  # MWh, counted for E1-5


def test_cli_import(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    src = tmp_path / "fig2.json"
    src.write_text(json.dumps(FIGURE), encoding="utf-8")
    out = tmp_path / "eea.csv"
    assert main(["import-eea", str(src), "--out", str(out), "--first-year", "2024"]) == 0
    printed = capsys.readouterr().out
    assert "Wrote 5 factors" in printed and "early estimate:           2025" in printed
    assert "European Environment Agency" in out.read_text(encoding="utf-8")
    assert "EEA-2024-DE" in FactorRegistry.from_csv(out)
