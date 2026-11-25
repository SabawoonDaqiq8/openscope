"""FastAPI application.

Run locally:  uvicorn openscope.api.app:app --reload
Interactive docs: http://localhost:8000/docs
"""

from collections.abc import Iterator
from pathlib import Path
from typing import Annotated, Literal

from fastapi import (
    APIRouter,
    Depends,
    FastAPI,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    UploadFile,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from openscope import __version__
from openscope.api import db, schemas
from openscope.api.service import NotFound, Service
from openscope.api.settings import Settings
from openscope.errors import OpenScopeError
from openscope.pathway import Scenario

MAX_UPLOAD_BYTES = 10 * 1024 * 1024


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    database = db.Database(settings.db_url)
    service = Service(settings)
    if settings.public_demo:
        # fresh (ephemeral) database on every start: make sure visitors see data
        with database.sessions() as session:
            service.load_demo(session)

    app = FastAPI(
        title="openscope API",
        version=__version__,
        description="Open-source, auditable carbon accounting: GHG Protocol Scope 1, 2 and 3.",
        docs_url="/docs",
        openapi_url="/api/openapi.json",
    )
    app.state.service = service
    app.state.database = database

    app.add_middleware(GZipMiddleware, minimum_size=1024)
    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origins,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    @app.exception_handler(NotFound)
    async def _not_found(_: Request, exc: NotFound) -> JSONResponse:
        return JSONResponse(status_code=404, content={"detail": str(exc)})

    @app.exception_handler(OpenScopeError)
    async def _bad_input(_: Request, exc: OpenScopeError) -> JSONResponse:
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    def get_session() -> Iterator[Session]:
        yield from database.session()

    SessionDep = Annotated[Session, Depends(get_session)]

    async def read_upload(file: UploadFile) -> bytes:
        content = await file.read(MAX_UPLOAD_BYTES + 1)
        if len(content) > MAX_UPLOAD_BYTES:
            raise HTTPException(413, "File too large (max 10 MB)")
        return content

    api = APIRouter(prefix="/api")

    # -- meta & factors -------------------------------------------------------------------
    @api.get("/health", tags=["meta"])
    def health() -> dict[str, str]:
        return {"status": "ok", "version": __version__}

    @api.get("/meta", tags=["meta"])
    def meta() -> schemas.Meta:
        return service.meta()

    @api.get("/factors", tags=["factors"])
    def factors(
        search: str | None = None,
        scope: Annotated[int | None, Query(ge=1, le=3)] = None,
        spend_only: bool = False,
        limit: Annotated[int, Query(ge=1, le=2000)] = 50,
        offset: Annotated[int, Query(ge=0)] = 0,
    ) -> schemas.FactorPage:
        return service.factors(search, scope, spend_only, limit, offset)

    # -- inventories ----------------------------------------------------------------------
    @api.get("/inventories", tags=["inventories"])
    def list_inventories(session: SessionDep) -> list[schemas.InventoryOut]:
        rows = session.scalars(select(db.Inventory).order_by(db.Inventory.id.desc())).all()
        return [service.inventory_out(r) for r in rows]

    @api.post("/inventories", status_code=201, tags=["inventories"])
    async def create_inventory(
        session: SessionDep,
        file: Annotated[UploadFile, File(description="Activities CSV")],
        name: Annotated[str, Form(min_length=1, max_length=200)],
        gwp_set: Annotated[Literal["AR5", "AR6"], Form()] = "AR6",
        reporting_year: Annotated[int | None, Form()] = None,
    ) -> schemas.InventoryDetail:
        content = await read_upload(file)
        row = service.create_inventory_from_csv(
            session, content, name=name, gwp_set=gwp_set, reporting_year=reporting_year
        )
        return service.inventory_out(row, detail=True)  # type: ignore[return-value]

    @api.get("/inventories/{inventory_id}", tags=["inventories"])
    def get_inventory(inventory_id: int, session: SessionDep) -> schemas.InventoryDetail:
        row = service.get_inventory(session, inventory_id)
        return service.inventory_out(row, detail=True)  # type: ignore[return-value]

    @api.get("/inventories/{inventory_id}/lines", tags=["inventories"])
    def inventory_lines(
        inventory_id: int,
        session: SessionDep,
        scope: Annotated[int | None, Query(ge=1, le=3)] = None,
    ) -> list[schemas.LineOut]:
        inv = service.get_inventory(session, inventory_id)
        return [service.line_out(r) for r in inv.lines if scope is None or r.scope == scope]

    @api.delete("/inventories/{inventory_id}", status_code=204, tags=["inventories"])
    def delete_inventory(inventory_id: int, session: SessionDep) -> None:
        session.delete(service.get_inventory(session, inventory_id))
        session.commit()

    # -- pathways --------------------------------------------------------------------------
    @api.post("/inventories/{inventory_id}/pathway", tags=["pathways"])
    def inventory_pathway(
        inventory_id: int, scenario: Scenario, session: SessionDep
    ) -> schemas.PathwayOut:
        return service.pathway(service.get_inventory(session, inventory_id), scenario)

    @api.get("/pathway/demo-scenario", tags=["pathways"])
    def demo_scenario() -> Scenario:
        return service.demo_scenario()

    # -- classification -------------------------------------------------------------------
    @api.get("/classification-runs", tags=["classification"])
    def list_runs(session: SessionDep) -> list[schemas.RunOut]:
        rows = session.scalars(
            select(db.ClassificationRun).order_by(db.ClassificationRun.id.desc())
        ).all()
        return [service.run_out(session, r) for r in rows]

    @api.post("/classification-runs", status_code=201, tags=["classification"])
    async def create_run(
        session: SessionDep,
        file: Annotated[UploadFile, File(description="Ledger CSV export")],
        name: Annotated[str, Form(min_length=1, max_length=200)],
        threshold: Annotated[float, Form(ge=0, le=1)] = 0.85,
        use_llm: Annotated[bool, Form()] = False,
        currency: Annotated[str | None, Form(max_length=3)] = None,
    ) -> schemas.RunOut:
        content = await read_upload(file)
        run = service.create_run(
            session, content, name=name, threshold=threshold, use_llm=use_llm, currency=currency
        )
        return service.run_out(session, run)

    @api.get("/classification-runs/{run_id}", tags=["classification"])
    def get_run(run_id: int, session: SessionDep) -> schemas.RunOut:
        return service.run_out(session, service.get_run(session, run_id))

    @api.get("/classification-runs/{run_id}/lines", tags=["classification"])
    def run_lines(
        run_id: int,
        session: SessionDep,
        status: str | None = None,
    ) -> list[schemas.RunLineOut]:
        run = service.get_run(session, run_id)
        rows = [r for r in run.lines if status is None or r.status == status]
        rows.sort(key=lambda r: -abs(r.amount))
        return [service.run_line_out(r) for r in rows]

    @api.post("/classification-runs/{run_id}/lines/{line_id}/review", tags=["classification"])
    def review_line(
        run_id: int, line_id: str, body: schemas.ReviewIn, session: SessionDep
    ) -> schemas.RunLineOut:
        run = service.get_run(session, run_id)
        return service.run_line_out(service.review_line(session, run, line_id, body))

    @api.get("/classification-runs/{run_id}/audit", tags=["classification"])
    def run_audit(run_id: int, session: SessionDep) -> list[schemas.AuditOut]:
        run = service.get_run(session, run_id)
        return [
            schemas.AuditOut(
                id=a.id,
                line_id=a.line_id,
                timestamp=a.timestamp,
                reviewer=a.reviewer,
                action=a.action,
                before=a.before,
                after=a.after,
                note=a.note,
            )
            for a in reversed(run.audit)
        ]

    @api.post("/classification-runs/{run_id}/export", status_code=201, tags=["classification"])
    def export_run(run_id: int, body: schemas.ExportIn, session: SessionDep) -> schemas.ExportOut:
        return service.export_run(session, service.get_run(session, run_id), body)

    # -- demo -----------------------------------------------------------------------------
    @api.post("/demo", tags=["meta"])
    def load_demo(session: SessionDep) -> schemas.DemoOut:
        return service.load_demo(session)

    app.include_router(api)

    if settings.static_dir is not None and settings.static_dir.is_dir():
        _mount_spa(app, settings.static_dir)
    return app


def _mount_spa(app: FastAPI, static_dir: Path) -> None:
    """Serve the built Angular app; unknown non-API paths fall back to index.html."""
    index = static_dir / "index.html"

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str) -> FileResponse:
        if path.startswith("api/"):
            raise HTTPException(404)
        candidate = (static_dir / path).resolve()
        if path and candidate.is_file() and static_dir.resolve() in candidate.parents:
            return FileResponse(candidate)
        return FileResponse(index)


def __getattr__(name: str) -> object:
    # `uvicorn openscope.api.app:app` builds the app lazily from environment settings
    if name == "app":
        return create_app()
    raise AttributeError(name)
