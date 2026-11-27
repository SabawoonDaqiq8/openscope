"""AIB European Residual Mix importer, and residual mixes feeding ESRS E1-5."""

from __future__ import annotations

from pathlib import Path

import pytest

from openscope.cli import main
from openscope.disclosure import Period, build
from openscope.energy import MIX_GRID, MIX_RESIDUAL, MIX_STATED, GridMix, energy_mix
from openscope.engine import Calculator
from openscope.errors import FactorError
from openscope.factors import FactorRegistry
from openscope.importers import aib
from openscope.inventory import Inventory
from openscope.models import ActivityRecord, EmissionFactor, Scope, Scope2Method

MIX_HEADER = (None, "RE Total", "RE wind ", "Nuclear ", "FO Total", "FO gas ", "CO2 (gCO2/kWh)")
CO2 = [
    ("Country code", "Production mix CO2", "Residual mix CO2", "Supplier mix CO2"),
    ("DE", 304.94, 701.47, 380.0),
    ("FR", 21.0, 17.11, 20.0),
    ("AT", 94.21, "NA", 69.6),
    (None, None, None, None),
]
RESIDUAL = [
    MIX_HEADER,
    ("DE", 0.016, 0.01, 0, 0.984, 0.3, 701.47),
    ("FR", "9.86%", "1%", "85.83%", "4.31%", "4%", 17.11),
    ("AT", "NA", "NA", "NA", "NA", "NA", "NA"),
]
PRODUCTION = [
    (None, "Volume [TWh]", "RE Total", "Nuclear ", "FO Total", "CO2 (gCO2/kWh)"),
    ("DE", 430.0, 0.5723, 0, 0.4277, 304.94),
    ("FR", 520.0, 0.25, 0.70, 0.045, 21.0),  # sums to 0.995: within rounding, renormalised
    ("AT", 67.2, 0.8203, 0, 0.1797, 94.21),
]


def _report() -> aib.ImportReport:
    return aib.parse(CO2, RESIDUAL, PRODUCTION, 2025)


def test_parse_builds_residual_and_production_factors() -> None:
    r = _report()
    ids = {f.factor_id: f for f in r.factors}
    assert set(ids) == {
        "AIB-2025-RM-DE", "AIB-2025-PM-DE", "AIB-2025-RM-FR", "AIB-2025-PM-FR", "AIB-2025-PM-AT"
    }  # fmt: skip
    assert r.residual == 2 and r.production == 3 and r.no_residual_mix == ["AT"]

    de = ids["AIB-2025-RM-DE"]
    assert de.gases == {"CO2": pytest.approx(0.70147)}
    assert de.scope == Scope.SCOPE_2 and de.scope2_method == Scope2Method.MARKET_BASED
    assert de.region == "DE" and de.energy_kwh_per_unit == 1
    assert de.supply_mix == pytest.approx((0.984, 0, 0.016))
    assert ids["AIB-2025-PM-DE"].scope2_method == Scope2Method.LOCATION_BASED

    # percent strings are read as fractions
    assert ids["AIB-2025-RM-FR"].supply_mix == pytest.approx((0.0431, 0.8583, 0.0986), abs=1e-4)
    assert sum(ids["AIB-2025-PM-FR"].supply_mix or ()) == pytest.approx(1)


def test_inconsistent_mix_is_left_out_not_guessed() -> None:
    bad = [*PRODUCTION[:1], ("DE", 430.0, 0.5, 0, 0.3, 304.94)]
    r = aib.parse(CO2[:2], RESIDUAL[:2], bad, 2025)
    pm = next(f for f in r.factors if f.factor_id == "AIB-2025-PM-DE")
    assert pm.supply_mix is None
    assert r.mix_not_reconciled and "DE production" in r.mix_not_reconciled[0]


def test_parse_rejects_unrecognised_sheets() -> None:
    with pytest.raises(FactorError, match="header"):
        aib.parse([("x", "y")], RESIDUAL, PRODUCTION, 2025)


def test_factor_csv_round_trips_mix(tmp_path: Path) -> None:
    out = tmp_path / "aib.csv"
    FactorRegistry(_report().factors).to_csv(out)
    back = FactorRegistry.from_csv(out).get("AIB-2025-RM-FR")
    assert back.supply_mix == pytest.approx((0.0431, 0.8583, 0.0986), abs=1e-4)


def test_partial_mix_rejected() -> None:
    with pytest.raises(ValueError, match="all of fossil"):
        EmissionFactor(factor_id="X", name="x", activity_unit="kWh", co2e_kg=0.1, source="t",
                       fossil_share=1.0)  # fmt: skip


def test_cli_import_aib(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    openpyxl = pytest.importorskip("openpyxl")
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    for name, rows in (("CO2", CO2), ("Residual Mixes", RESIDUAL), ("Production Mix", PRODUCTION)):
        ws = wb.create_sheet(name)
        for row in rows:
            ws.append(list(row))
    src = tmp_path / "2025_Final_Residual_mix_results.xlsx"
    wb.save(src)
    out = tmp_path / "aib.csv"
    assert main(["import-aib", str(src), "--out", str(out)]) == 0
    printed = capsys.readouterr().out
    assert "Wrote 5 factors" in printed and "no residual mix published:      AT" in printed
    assert "Copyright AIB" in out.read_text()
    assert "AIB-2025-RM-DE" in FactorRegistry.from_csv(out)


# -- E1-5 ------------------------------------------------------------------------------------
def _inventory(*, residual: bool = True, production: bool = True) -> Inventory:
    factors = [f for f in _report().factors
               if (residual or "-RM-" not in f.factor_id)
               and (production or "-PM-" not in f.factor_id)]  # fmt: skip
    plain = EmissionFactor(
        factor_id="GRID",
        name="grid",
        activity_unit="kWh",
        co2e_kg=0.3,
        source="t",
        energy_kwh_per_unit=1,
        energy_source="electricity",
    )
    reg = FactorRegistry([*factors, plain])
    lb = "AIB-2025-PM-DE" if production else "GRID"
    acts = [
        ActivityRecord(activity_id="lb", quantity=1_000_000, unit="kWh", scope=Scope.SCOPE_2,
                       site="Berlin", factor_id=lb),
    ]  # fmt: skip
    if residual:
        acts.append(ActivityRecord(activity_id="mb", quantity=1_000_000, unit="kWh",
                                   scope=Scope.SCOPE_2, site="Berlin",
                                   factor_id="AIB-2025-RM-DE"))  # fmt: skip
    return Inventory(Calculator(reg).calculate_many(acts).results)


def test_residual_mix_splits_uncertified_electricity() -> None:
    m = energy_mix(_inventory())
    assert m.electricity_total == pytest.approx(1000)
    assert m.electricity_fossil == pytest.approx(984)
    assert m.electricity_renewable_mix == pytest.approx(16)
    assert m.undetermined == 0 and m.mix_basis == {MIX_RESIDUAL: pytest.approx(1000)}
    # the residual mix is preferred over a stated mix and the production mix
    assert energy_mix(_inventory(), GridMix(0.5, 0.2, 0.3)).mix_basis.keys() == {MIX_RESIDUAL}


def test_stated_mix_then_production_mix() -> None:
    m = energy_mix(_inventory(residual=False), GridMix(0.5, 0.2, 0.3))
    assert m.mix_basis.keys() == {MIX_STATED} and m.nuclear == pytest.approx(200)

    p = energy_mix(_inventory(residual=False))
    assert p.mix_basis.keys() == {MIX_GRID}
    assert p.fossil == pytest.approx(427.7) and p.renewable == pytest.approx(572.3)

    none = energy_mix(_inventory(residual=False, production=False))
    assert none.fossil is None and none.undetermined == pytest.approx(1000)


def test_disclosure_uses_residual_mix_without_warning() -> None:
    d = build(Period(_inventory(), 2025, "AR6"))
    rows = {r.key: r for r in d.rows}
    assert rows["energy_fossil"].current == pytest.approx(984)
    assert rows["energy_renewable_share"].current == pytest.approx(1.6)
    codes = {c.code for c in d.checks}
    assert "energy-mix" not in codes and "energy-mix-basis" in codes
    assert any("residual mix" in p for p in d.basis)
