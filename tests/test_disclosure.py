import csv
import io
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from openscope import (
    ActivityRecord,
    Calculator,
    EmissionFactor,
    FactorRegistry,
    FactorStatus,
    Inventory,
    Scope,
    Scope2Method,
    Scope3Category,
)
from openscope.api.app import create_app
from openscope.api.settings import Settings
from openscope.cli import main
from openscope.disclosure import Framework, Level, Period, build, to_csv, to_markdown

EX = Path(__file__).parent.parent / "examples"

REF = EmissionFactor(factor_id="R", name="r", activity_unit="kWh", co2e_kg=1.0, source="Ref DB")
ILL = EmissionFactor(
    factor_id="I", name="i", activity_unit="kWh", co2e_kg=1.0, source="Demo",
    status=FactorStatus.ILLUSTRATIVE,
)  # fmt: skip


def period(t1: float, t2: float, t3: float, *, year: int = 2025, gwp: str = "AR6",
           factor: str = "R", market: bool = True) -> Period:  # fmt: skip
    calc = Calculator(FactorRegistry([REF, ILL]))
    acts = [
        ActivityRecord(activity_id="s1", quantity=t1 * 1000, unit="kWh", scope=Scope.SCOPE_1,
                       factor_id=factor),
        ActivityRecord(activity_id="s2", quantity=t2 * 1000, unit="kWh", scope=Scope.SCOPE_2,
                       scope2_method=Scope2Method.LOCATION_BASED, factor_id="R", site="HQ"),
        ActivityRecord(activity_id="s3", quantity=t3 * 1000, unit="kWh", scope=Scope.SCOPE_3,
                       scope3_category=Scope3Category.BUSINESS_TRAVEL, factor_id="R"),
    ]  # fmt: skip
    if market:
        acts.append(
            ActivityRecord(activity_id="s2m", quantity=t2 * 500, unit="kWh", scope=Scope.SCOPE_2,
                           scope2_method=Scope2Method.MARKET_BASED, factor_id="R", site="HQ")
        )  # fmt: skip
    return Period(Inventory(calc.calculate_many(acts).results), year, gwp)


def rows(d):  # type: ignore[no-untyped-def]
    return {r.key: r for r in d.rows}


def test_esrs_table_values_comparatives_and_intensity() -> None:
    d = build(
        period(100, 50, 200),
        prior=period(120, 60, 220, year=2024),
        base=period(150, 80, 250, year=2019),
        net_revenue=10_000_000,
        revenue_currency="EUR",
        ets_share=0.25,
    )
    r = rows(d)
    assert r["scope1"].current == pytest.approx(100)
    assert r["scope2_location"].current == pytest.approx(50)
    assert r["scope2_market"].current == pytest.approx(25)
    assert r["scope3_cat_6"].current == pytest.approx(200)
    assert r["total_location"].current == pytest.approx(350)
    assert r["total_market"].current == pytest.approx(325)
    assert r["scope1"].change_vs_prior == pytest.approx(100 / 120 - 1)
    assert r["scope1"].change_vs_base == pytest.approx(100 / 150 - 1)
    assert r["scope1_ets"].current == pytest.approx(25)
    assert r["intensity_market"].current == pytest.approx(325 / 10)  # per million EUR
    assert "EUR" in r["intensity_market"].unit
    assert (d.reporting_year, d.prior_year, d.base_year) == (2025, 2024, 2019)
    assert d.ready


def test_issb_table_has_no_esrs_only_rows() -> None:
    d = build(period(1, 1, 1), framework=Framework.ISSB)
    keys = set(rows(d))
    assert {"scope1", "scope2_location", "scope2_market", "scope3"} <= keys
    assert not keys & {"scope1_ets", "total_market", "intensity_location"}
    assert all(r.reference.startswith("IFRS S2") for r in d.rows)
    assert not any(c.code == "net-revenue" for c in d.checks)


def test_readiness_checks() -> None:
    d = build(period(10, 10, 10, factor="I", gwp="AR5", market=False), calculation_errors=2)
    codes = {c.code: c.level for c in d.checks}
    assert codes["illustrative-factors"] == Level.BLOCKER
    assert codes["calculation-errors"] == Level.BLOCKER
    assert codes["gwp-version"] == Level.WARNING
    assert codes["scope2-market-fallback"] == Level.WARNING
    assert codes["net-revenue"] == Level.WARNING
    assert codes["scope3-categories"] == Level.INFO
    assert not d.ready
    assert [c.level for c in d.checks] == sorted(
        (c.level for c in d.checks), key=[Level.BLOCKER, Level.WARNING, Level.INFO].index
    )


def test_basis_of_preparation_mentions_sources_and_gwp() -> None:
    d = build(period(1, 1, 1, gwp="AR6"))
    text = " ".join(d.basis)
    assert "AR6" in text and "Ref DB" in text and "GHG Protocol" in text


def test_renderers() -> None:
    d = build(period(100, 50, 200), prior=period(120, 60, 220, year=2024))
    data = list(csv.DictReader(io.StringIO(to_csv(d))))
    s1 = next(x for x in data if x["key"] == "scope1")
    assert float(s1["N 2025"]) == 100 and float(s1["% N / N-1"]) == pytest.approx(-16.67, abs=0.01)
    md = to_markdown(d)
    assert (
        md.startswith("# ESRS E1")
        and "## E1-6 Gross Scopes" in md
        and "| 2024 | 2025 |" in md
        and "## Readiness checks" in md
    )


def test_cli_exit_code_reflects_blockers(tmp_path: Path) -> None:
    out = tmp_path / "d.md"
    # demo_activities.csv uses illustrative factors -> blocker -> exit 1
    assert main(["disclose", str(EX / "demo_activities.csv"), "--out", str(out)]) == 1
    assert "illustrative-factors" in out.read_text()
    # UK demo uses only DESNZ reference factors -> exit 0
    assert (
        main(
            [
                "disclose",
                str(EX / "uk_demo_activities.csv"),
                "--dataset",
                "desnz-2025",
                "--year",
                "2025",
                "--format",
                "csv",
                "--out",
                str(out),
            ]
        )  # fmt: skip
        == 0
    )


def test_api_disclosure_and_export(tmp_path: Path) -> None:
    settings = Settings(db_url=f"sqlite:///{tmp_path / 'd.db'}", demo_dir=EX)
    settings.add_demo_defaults()
    c = TestClient(create_app(settings))
    inv = c.post("/api/demo").json()["inventory_id"]
    params = {"net_revenue": 12_500_000, "revenue_currency": "GBP", "ets_share": 0}
    d = c.get(f"/api/inventories/{inv}/disclosure", params=params).json()
    assert d["framework"] == "esrs" and d["ready"] is True
    by_key = {r["key"]: r for r in d["rows"]}
    assert by_key["scope2_location"]["current"] == pytest.approx(150.458, abs=1e-3)
    assert by_key["intensity_market"]["current"] == pytest.approx(650.0 / 12.5, abs=0.01)
    assert any(ch["code"] == "gwp-version" for ch in d["checks"])  # demo is AR5

    r = c.get(f"/api/inventories/{inv}/disclosure/export", params={"format": "md"})
    assert r.status_code == 200
    assert "attachment" in r.headers["content-disposition"]
    assert r.text.startswith("# ESRS E1") and "## E1-5 Energy consumption and mix" in r.text
    r = c.get(f"/api/inventories/{inv}/disclosure/export",
              params={"format": "csv", "framework": "issb"})  # fmt: skip
    assert "ifrs-s2" in r.headers["content-disposition"]
    assert c.get(f"/api/inventories/{inv}/disclosure", params={"prior_id": 999}).status_code == 404

    prior = next(i["id"] for i in c.get("/api/inventories").json() if i["reporting_year"] == 2024)
    d = c.get(f"/api/inventories/{inv}/disclosure", params={"prior_id": prior}).json()
    s2m = next(r for r in d["rows"] if r["key"] == "scope2_market")
    assert d["prior_year"] == 2024 and s2m["change_vs_prior"] < -0.5  # renewable tariff from 2025
