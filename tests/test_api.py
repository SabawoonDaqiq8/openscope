from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from openscope.api.app import create_app
from openscope.api.settings import Settings

EX = Path(__file__).parent.parent / "examples"


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    settings = Settings(db_url=f"sqlite:///{tmp_path / 'test.db'}", demo_dir=EX)
    settings.add_demo_defaults()
    return TestClient(create_app(settings))


def upload(client: TestClient, path: Path, **form: Any) -> Any:
    with path.open("rb") as fh:
        return client.post(
            "/api/inventories", files={"file": (path.name, fh, "text/csv")}, data=form
        )


def test_health_and_meta(client: TestClient) -> None:
    assert client.get("/api/health").json()["status"] == "ok"
    meta = client.get("/api/meta").json()
    assert "desnz-2025" in meta["datasets"]
    assert len(meta["scope3_categories"]) == 15
    assert meta["demo_available"] is True
    assert meta["llm_enabled"] is False


def test_factor_search(client: TestClient) -> None:
    page = client.get("/api/factors", params={"search": "electricity uk", "scope": 2}).json()
    assert page["total"] >= 1
    assert any(f["factor_id"] == "DESNZ-2025-7_400_4000_5" for f in page["items"])
    spend = client.get("/api/factors", params={"spend_only": True, "limit": 2000}).json()
    assert spend["total"] > 1000 and all(f["activity_unit"] == "USD" for f in spend["items"])
    hotel = client.get("/api/factors", params={"search": "hotels motels", "spend_only": True})
    assert any(f["factor_id"] == "USEEIO-1.3-721110" for f in hotel.json()["items"])


def test_inventory_upload_and_detail(client: TestClient) -> None:
    r = upload(client, EX / "uk_demo_activities.csv", name="UK", gwp_set="AR5", reporting_year=2025)
    assert r.status_code == 201, r.text
    body = r.json()
    t = body["analytics"]["totals"]
    assert t["scope2_location_tco2e"] == pytest.approx(150.458, abs=1e-3)
    assert t["scope2_market_fallback_sites"] == ["Warehouse"]
    assert t["illustrative_factor_share"] == 0
    assert body["analytics"]["hotspots"][0]["description"]  # enriched from activities

    inv_id = body["id"]
    assert [i["id"] for i in client.get("/api/inventories").json()] == [inv_id]
    lines = client.get(f"/api/inventories/{inv_id}/lines", params={"scope": 1}).json()
    assert {ln["activity_id"] for ln in lines} == {"S1-GAS", "S1-DIESEL", "S1-REFRIG"}
    assert lines[0]["trace"][0].startswith("Factor DESNZ-2025")

    assert client.delete(f"/api/inventories/{inv_id}").status_code == 204
    assert client.get(f"/api/inventories/{inv_id}").status_code == 404


def test_bad_upload_is_400(client: TestClient, tmp_path: Path) -> None:
    bad = tmp_path / "bad.csv"
    bad.write_text("activity_id,quantity\nx,1\n")
    r = upload(client, bad, name="bad")
    assert r.status_code == 400
    assert "missing required columns" in r.json()["detail"]


def test_classification_review_and_export_flow(client: TestClient) -> None:
    with (EX / "ledger_sample.csv").open("rb") as fh:
        r = client.post(
            "/api/classification-runs",
            files={"file": ("ledger.csv", fh, "text/csv")},
            data={"name": "Q1-Q3 AP"},
        )
    assert r.status_code == 201, r.text
    run = r.json()
    assert run["lines"] == 40 and run["by_status"]["needs_review"] == 25
    rid = run["id"]

    pending = client.get(f"/api/classification-runs/{rid}/lines", params={"status": "needs_review"})
    first = pending.json()[0]
    assert first["amount"] == 42000  # largest spend first

    r = client.post(
        f"/api/classification-runs/{rid}/lines/{first['line_id']}/review",
        json={
            "reviewer": "S. Daqiq",
            "action": "override",
            "scope3_category": 2,
            "factor_id": "USEEIO-1.3-334111",
            "note": "capitalised laptops",
        },
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "reviewed" and r.json()["source"] == "reviewer"

    bad = client.post(
        f"/api/classification-runs/{rid}/lines/{first['line_id']}/review",
        json={"reviewer": "x", "action": "override", "scope3_category": 2, "factor_id": "NOPE"},
    )
    assert bad.status_code == 400

    audit = client.get(f"/api/classification-runs/{rid}/audit").json()
    assert len(audit) == 1 and audit[0]["reviewer"] == "S. Daqiq"
    assert audit[0]["after"]["factor_id"] == "USEEIO-1.3-334111"

    exp = client.post(
        f"/api/classification-runs/{rid}/export", json={"name": "Spend inventory"}
    ).json()
    assert exp["activities"] == 5  # 4 rule-classified travel lines + 1 reviewed
    assert exp["pending_lines"] == 24
    inv = client.get(f"/api/inventories/{exp['inventory_id']}").json()
    assert inv["source"] == "classification"
    assert inv["analytics"]["totals"]["scope3_tco2e"] > 0

    # the supplier is remembered for the next run
    with (EX / "ledger_sample.csv").open("rb") as fh:
        run2 = client.post(
            "/api/classification-runs",
            files={"file": ("ledger.csv", fh, "text/csv")},
            data={"name": "again"},
        ).json()
    assert run2["by_status"]["needs_review"] == 23  # both Dellmark lines now from memory


def test_llm_disabled_is_rejected(client: TestClient) -> None:
    with (EX / "ledger_sample.csv").open("rb") as fh:
        r = client.post(
            "/api/classification-runs",
            files={"file": ("l.csv", fh, "text/csv")},
            data={"name": "x", "use_llm": "true"},
        )
    assert r.status_code == 400 and "not enabled" in r.json()["detail"]


def test_demo_is_idempotent(client: TestClient) -> None:
    a = client.post("/api/demo").json()
    b = client.post("/api/demo").json()
    assert a == b
    names = [i["name"] for i in client.get("/api/inventories").json()]
    assert names == [
        "Demo: UK company 2025 (DESNZ factors)",
        "Demo: UK company 2024 (DESNZ factors)",
    ]
    assert len(client.get("/api/classification-runs").json()) == 1


def test_openapi_schema_is_exposed(client: TestClient) -> None:
    spec = client.get("/api/openapi.json").json()
    assert "/api/inventories/{inventory_id}/lines" in spec["paths"]
    assert "InventoryDetail" in spec["components"]["schemas"]


def test_spa_fallback(tmp_path: Path) -> None:
    static = tmp_path / "web"
    static.mkdir()
    (static / "index.html").write_text("<app-root></app-root>")
    (static / "main.js").write_text("console.log(1)")
    settings = Settings(db_url=f"sqlite:///{tmp_path / 'db.sqlite'}", static_dir=static)
    c = TestClient(create_app(settings))
    assert "app-root" in c.get("/inventories/3").text  # client-side route
    assert c.get("/main.js").text == "console.log(1)"
    assert c.get("/../../etc/passwd").status_code in (200, 404)
    assert "root:" not in c.get("/../../etc/passwd").text
    assert c.get("/api/nope").status_code == 404


def test_public_demo_mode_preloads_data(tmp_path: Path) -> None:
    settings = Settings(db_url=f"sqlite:///{tmp_path / 'demo.db'}", demo_dir=EX, public_demo=True)
    settings.add_demo_defaults()
    c = TestClient(create_app(settings))
    assert c.get("/api/meta").json()["public_demo"] is True
    assert len(c.get("/api/inventories").json()) == 2
    assert len(c.get("/api/classification-runs").json()) == 1
    # restarting against the same database does not duplicate the demo
    c2 = TestClient(create_app(settings))
    assert len(c2.get("/api/inventories").json()) == 2


def test_pathway_endpoint_on_demo(client: TestClient) -> None:
    demo = client.post("/api/demo").json()
    scenario = client.get("/api/pathway/demo-scenario").json()
    assert scenario["currency"] == "GBP" and len(scenario["levers"]) == 6
    scenario["simulations"] = 200
    r = client.post(f"/api/inventories/{demo['inventory_id']}/pathway", json=scenario)
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["years"][0] == 2025 and out["years"][-1] == 2035
    assert out["scope3"]["gap_tco2e"] > 0  # the demo plan misses its Scope 3 target
    assert out["levers"][0]["mac"] < 0

    bad = dict(scenario, target_year=2020)
    assert (
        client.post(f"/api/inventories/{demo['inventory_id']}/pathway", json=bad).status_code == 422
    )
