from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from openscope.api.app import create_app
from openscope.api.protection import WriteRateLimitMiddleware
from openscope.api.settings import Settings

EX = Path(__file__).parent.parent / "examples"
ACTS = (EX / "uk_demo_activities.csv").read_bytes()


def demo_client(tmp_path: Path, **kw: object) -> TestClient:
    settings = Settings(db_url=f"sqlite:///{tmp_path / 'p.db'}", demo_dir=EX, public_demo=True)
    for k, v in kw.items():
        setattr(settings, k, v)
    settings.add_demo_defaults()
    return TestClient(create_app(settings))


def upload(c: TestClient, name: str, content: bytes = ACTS) -> int:
    r = c.post("/api/inventories", files={"file": ("a.csv", content, "text/csv")},
               data={"name": name, "gwp_set": "AR5"})  # fmt: skip
    return r.status_code


def test_security_headers_on_api_and_docs(tmp_path: Path) -> None:
    c = TestClient(create_app(Settings(db_url=f"sqlite:///{tmp_path / 'h.db'}")))
    h = c.get("/api/health").headers
    assert h["x-content-type-options"] == "nosniff"
    assert h["x-frame-options"] == "DENY"
    assert "frame-ancestors 'none'" in h["content-security-policy"]
    assert "script-src 'self';" in h["content-security-policy"]
    docs = c.get("/docs").headers["content-security-policy"]
    assert "cdn.jsdelivr.net" in docs  # Swagger UI assets


def test_public_demo_blocks_deletes(tmp_path: Path) -> None:
    c = demo_client(tmp_path)
    inv = c.get("/api/inventories").json()[0]["id"]
    r = c.delete(f"/api/inventories/{inv}")
    assert r.status_code == 403 and "disabled" in r.json()["detail"]
    assert len(c.get("/api/inventories").json()) == 2


def test_public_demo_upload_size_and_reserved_run_names(tmp_path: Path) -> None:
    c = demo_client(tmp_path)
    assert upload(c, "big", ACTS + b"#" * (1024 * 1024)) == 413
    assert upload(c, "mine") == 201
    ledger = (EX / "ledger_sample.csv").read_bytes()
    r = c.post("/api/classification-runs", files={"file": ("l.csv", ledger, "text/csv")},
               data={"name": "Demo: fake"})  # fmt: skip
    assert r.status_code == 400


def test_public_demo_export_of_the_demo_ledger_works(tmp_path: Path) -> None:
    # regression: the exported inventory is named after the demo run ("Demo: ...")
    c = demo_client(tmp_path)
    run = next(r for r in c.get("/api/classification-runs").json() if r["name"].startswith("Demo:"))
    r = c.post(f"/api/classification-runs/{run['id']}/export",
               json={"name": "Demo: AP ledger 2025 (spend-based)"})  # fmt: skip
    assert r.status_code == 201, r.text


def test_public_demo_keeps_only_newest_visitor_uploads(tmp_path: Path) -> None:
    c = demo_client(tmp_path, demo_max_uploads=2)
    for name in ("one", "two", "three"):
        assert upload(c, name) == 201
    names = [i["name"] for i in c.get("/api/inventories").json()]
    assert names[:2] == ["three", "two"] and "one" not in names
    assert sum(n.startswith("Demo:") for n in names) == 2  # demo data untouched

    ledger = (EX / "ledger_sample.csv").read_bytes()
    for name in ("l1", "l2", "l3"):
        r = c.post("/api/classification-runs", files={"file": ("l.csv", ledger, "text/csv")},
                   data={"name": name})  # fmt: skip
        assert r.status_code == 201
    runs = [r["name"] for r in c.get("/api/classification-runs").json()]
    assert runs == ["l3", "l2", "Demo: AP ledger 2025"]


def test_public_demo_rate_limits_writes_only(tmp_path: Path) -> None:
    c = demo_client(tmp_path, demo_write_limit=3)
    assert [upload(c, f"u{i}") for i in range(3)] == [201, 201, 201]
    r = c.post("/api/inventories", files={"file": ("a.csv", ACTS, "text/csv")},
               data={"name": "u4"})  # fmt: skip
    assert r.status_code == 429
    assert int(r.headers["retry-after"]) > 0 and "Try again" in r.json()["detail"]
    assert c.get("/api/inventories").status_code == 200  # reads are never limited


def test_rate_limit_window_expires() -> None:
    now = [0.0]
    app = FastAPI()

    @app.post("/api/x")
    def x() -> dict[str, bool]:
        return {"ok": True}

    app.add_middleware(WriteRateLimitMiddleware, limit=2, window=60, clock=lambda: now[0])
    c = TestClient(app)
    assert [c.post("/api/x").status_code for _ in range(3)] == [200, 200, 429]
    now[0] = 61
    assert c.post("/api/x").status_code == 200


def test_self_hosted_keeps_full_control(tmp_path: Path) -> None:
    c = TestClient(create_app(Settings(db_url=f"sqlite:///{tmp_path / 's.db'}")))
    assert upload(c, "Demo: allowed when self-hosted") == 201
    inv = c.get("/api/inventories").json()[0]["id"]
    assert c.delete(f"/api/inventories/{inv}").status_code == 204
