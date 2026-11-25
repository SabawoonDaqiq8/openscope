from pathlib import Path

import pytest

from openscope import ActivityRecord, Calculator, FactorRegistry, Scope, Scope3Category
from openscope.errors import FactorError
from openscope.gwp import gwp
from openscope.importers import useeio

HEADER = (
    '"2017 NAICS Code","2017 NAICS Title","GHG","Unit",'
    '"Supply Chain Emission Factors without Margins","Margins of Supply Chain Emission Factors",'
    '"Supply Chain Emission Factors with Margins","Reference USEEIO Code"\n'
)


def by_ghg(tmp_path: Path, rows: list[tuple[str, str, float]]) -> Path:
    p = tmp_path / "byghg.csv"
    body = "".join(
        f'{code},"Title {code}","{gas}","kg/2022 USD, purchaser price",0,0,{v},"X"\n'
        for code, gas, v in rows
    )
    p.write_text(HEADER + body)
    return p


def co2e(tmp_path: Path, rows: list[tuple[str, float]]) -> Path:
    p = tmp_path / "co2e.csv"
    body = "".join(
        f'{code},"Title {code}","All GHGs","kg CO2e/2022 USD, purchaser price",{v},0,{v},"X"\n'
        for code, v in rows
    )
    p.write_text(HEADER + body)
    return p


def test_per_gas_import_and_reconciliation(tmp_path: Path) -> None:
    g = by_ghg(
        tmp_path,
        [
            ("100001", "Carbon dioxide", 0.5),
            ("100001", "Methane", 0.001),
            ("100001", "HFCs and PFCs, unspecified", 0.002),
            ("100002", "Carbon dioxide", 0.5),
        ],
    )
    c = co2e(tmp_path, [("100001", 0.5 + 0.001 * 28 + 0.002), ("100002", 0.9)])
    rep = useeio.import_factors(g, c)
    f1, f2 = rep.factors
    assert f1.factor_id == "USEEIO-1.3-100001" and f1.activity_unit == "USD"
    assert f1.gases == {"CO2": 0.5, "CH4": 0.001, "CO2E": 0.002}
    assert f1.year == 2022 and f1.region == "US"
    # 100002 does not reconcile (0.5 vs 0.9) -> published CO2e with AR5 basis
    assert f2.co2e_kg == 0.9 and f2.gwp_basis == "AR5" and not f2.gases
    assert rep.per_gas == 1 and rep.unreconciled == ["100002"]


def test_unknown_gas_is_an_error(tmp_path: Path) -> None:
    with pytest.raises(FactorError, match="Unknown gases"):
        useeio.import_factors(by_ghg(tmp_path, [("1", "Unobtainium", 1.0)]))


def test_not_an_epa_file(tmp_path: Path) -> None:
    p = tmp_path / "x.csv"
    p.write_text("a,b\n1,2\n")
    with pytest.raises(FactorError, match="not an EPA"):
        useeio.import_factors(p)


def test_every_epa_gas_has_a_gwp_in_both_sets() -> None:
    for gas in useeio.GAS_MAP.values():
        assert gwp(gas, "AR5") > 0 and gwp(gas, "AR6") > 0


def test_sf6_ar6_value() -> None:
    assert gwp("SF6", "AR6") == 25200  # IPCC AR6 WG1 Table 7.SM.7


# -- the bundled dataset ------------------------------------------------------------------------
@pytest.fixture(scope="module")
def epa() -> FactorRegistry:
    return FactorRegistry.dataset("useeio-1.3")


def test_bundled_dataset_shape(epa: FactorRegistry) -> None:
    assert len(epa) == 1016
    per_gas = [f for f in epa if f.gases]
    assert len(per_gas) == 1005
    assert all(f.activity_unit == "USD" and f.year == 2022 for f in epa)


def test_bundled_factor_matches_published_co2e_under_ar5(epa: FactorRegistry) -> None:
    f = epa.get("USEEIO-1.3-481111")  # scheduled passenger air transportation
    published = float(f.notes.split("published ")[1].split(" ")[0])  # type: ignore[union-attr]
    a = ActivityRecord(
        activity_id="air",
        quantity=1000,
        unit="USD",
        scope=Scope.SCOPE_3,
        scope3_category=Scope3Category.BUSINESS_TRAVEL,
        price_year=2022,
    )
    ar5 = Calculator(epa, gwp_set="AR5").calculate(a, f)
    ar6 = Calculator(epa, gwp_set="AR6").calculate(a, f)
    assert ar5.co2e_kg == pytest.approx(1000 * published, abs=1.0)
    assert ar6.co2e_kg > ar5.co2e_kg
