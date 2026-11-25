"""Application service: glue between the HTTP layer, the database and the openscope engine.

No calculation or classification logic lives here; it only orchestrates library calls.
"""

from __future__ import annotations

import tempfile
from collections import defaultdict
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from openscope import (
    ActivityRecord,
    Calculator,
    EmissionFactor,
    FactorRegistry,
    Inventory,
    Scope3Category,
    __version__,
    units,
)
from openscope import classify as cl
from openscope.api import db, schemas
from openscope.api.settings import Settings
from openscope.classify.memory import MemoryEntry, SupplierMemory
from openscope.engine import BatchResult
from openscope.errors import OpenScopeError
from openscope.io import read_activities


class NotFound(OpenScopeError):
    pass


def _save_upload(content: bytes, suffix: str = ".csv") -> Path:
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)  # noqa: SIM115
    with tmp:
        tmp.write(content)
    return Path(tmp.name)


def _to_factor_out(f: EmissionFactor) -> schemas.FactorOut:
    return schemas.FactorOut(
        factor_id=f.factor_id,
        name=f.name,
        activity_unit=f.activity_unit,
        co2e_kg=f.co2e_kg,
        gases=f.gases,
        gwp_basis=f.gwp_basis,
        scope=int(f.scope) if f.scope else None,
        scope3_category=int(f.scope3_category) if f.scope3_category else None,
        scope2_method=f.scope2_method.value if f.scope2_method else None,
        region=f.region,
        year=f.year,
        source=f.source,
        source_url=f.source_url,
        status=f.status.value,
        notes=f.notes,
    )


class Service:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        reg = FactorRegistry.bundled()
        for name in settings.datasets:
            reg = reg.merge(FactorRegistry.dataset(name))
        for path in settings.factor_files:
            reg = reg.merge(FactorRegistry.from_csv(path))
        self.registry = reg
        self.rules = cl.RuleSet.default()
        for path in settings.rule_files:
            self.rules = self.rules + cl.RuleSet.from_csv(path)
        self.spend_factors = [
            f for f in reg if units.get_unit(f.activity_unit).dimension.startswith("currency:")
        ]
        self._factor_list = sorted(reg, key=lambda f: f.factor_id)

    # -- meta & factors -----------------------------------------------------------------------
    def meta(self) -> schemas.Meta:
        return schemas.Meta(
            version=__version__,
            datasets=["sample", *self.settings.datasets]
            + [p.name for p in self.settings.factor_files],
            gwp_sets=["AR5", "AR6"],
            scope3_categories=[
                schemas.CategoryOut(value=int(c), label=c.label) for c in Scope3Category
            ],
            llm_enabled=self.llm_available(),
            demo_available=self._demo_file("uk_demo_activities.csv") is not None,
        )

    def llm_available(self) -> bool:
        if not self.settings.llm_enabled:
            return False
        try:
            import anthropic  # noqa: F401
        except ImportError:
            return False
        return True

    def factors(
        self,
        search: str | None,
        scope: int | None,
        spend_only: bool,
        limit: int,
        offset: int,
    ) -> schemas.FactorPage:
        items = self.spend_factors if spend_only else self._factor_list
        if search:
            terms = search.lower().split()
            items = [
                f
                for f in items
                if all(t in f"{f.factor_id} {f.name} {f.source}".lower() for t in terms)
            ]
        if scope is not None:
            items = [f for f in items if f.scope is not None and int(f.scope) == scope]
        page = items[offset : offset + limit]
        return schemas.FactorPage(total=len(items), items=[_to_factor_out(f) for f in page])

    # -- inventories --------------------------------------------------------------------------
    @staticmethod
    def analytics(inv: Inventory, batch: BatchResult) -> schemas.Analytics:
        s = inv.summary()
        headline = inv.headline_results()
        total_kg = sum(r.co2e_kg for r in headline) or 1.0

        dq: dict[int, list[float]] = defaultdict(lambda: [0.0, 0.0])
        methods: dict[str, float] = defaultdict(float)
        for r in headline:
            dq[r.data_quality_score][0] += r.co2e_kg / 1000
            dq[r.data_quality_score][1] += 1
            methods[r.method.value] += r.co2e_kg / 1000

        return schemas.Analytics(
            totals=schemas.Totals(
                scope1_tco2e=s["scope1_tco2e"],
                scope2_location_tco2e=s["scope2_location_tco2e"],
                scope2_market_tco2e=s["scope2_market_tco2e"],
                scope2_market_fallback_sites=s["scope2_market_fallback_sites"],
                scope3_tco2e=s["scope3_tco2e"],
                scope3_by_category=[
                    schemas.CategoryTotal(category=int(c), label=c.label, tco2e=round(v, 3))
                    for c, v in inv.scope3_by_category_t().items()
                ],
                total_tco2e=s["total_tco2e"],
                data_quality_score=s["data_quality_score"],
                illustrative_factor_share=s["illustrative_factor_share"],
                line_items=s["line_items"],
            ),
            hotspots=[
                schemas.Hotspot(
                    activity_id=r.activity_id,
                    description="",
                    scope=int(r.scope),
                    scope3_category=int(r.scope3_category) if r.scope3_category else None,
                    tco2e=round(r.co2e_t, 3),
                    share=round(r.co2e_kg / total_kg, 4),
                )
                for r in inv.hotspots(10)
            ],
            data_quality=[
                schemas.QualityBucket(score=k, tco2e=round(v[0], 3), lines=int(v[1]))
                for k, v in sorted(dq.items())
            ],
            by_method=[
                schemas.MethodTotal(method=k, tco2e=round(v, 3))
                for k, v in sorted(methods.items(), key=lambda kv: -kv[1])
            ],
            errors=[
                schemas.LineError(activity_id=e.activity_id, message=e.message)
                for e in batch.errors
            ],
        )

    def create_inventory(
        self,
        session: Session,
        *,
        name: str,
        source: str,
        activities: Sequence[ActivityRecord],
        gwp_set: str,
        reporting_year: int | None,
    ) -> db.Inventory:
        calc = Calculator(self.registry, gwp_set=gwp_set, reporting_year=reporting_year)
        batch = calc.calculate_many(activities)
        analytics = self.analytics(Inventory(batch.results), batch)
        descriptions = {a.activity_id: a.description for a in activities}
        for h in analytics.hotspots:
            h.description = descriptions.get(h.activity_id, "")

        row = db.Inventory(
            name=name,
            source=source,
            gwp_set=gwp_set,
            reporting_year=reporting_year,
            summary=analytics.model_dump(mode="json"),
            errors=[e.model_dump() for e in analytics.errors],
        )
        acts = {a.activity_id: a for a in activities}
        for r in batch.results:
            row.lines.append(
                db.ResultLine(
                    activity_id=r.activity_id,
                    scope=int(r.scope),
                    co2e_kg=r.co2e_kg,
                    activity=acts[r.activity_id].model_dump(mode="json"),
                    result=r.model_dump(mode="json"),
                )
            )
        session.add(row)
        session.commit()
        return row

    def create_inventory_from_csv(
        self,
        session: Session,
        content: bytes,
        *,
        name: str,
        gwp_set: str,
        reporting_year: int | None,
    ) -> db.Inventory:
        path = _save_upload(content)
        try:
            activities = read_activities(path)
        finally:
            path.unlink(missing_ok=True)
        return self.create_inventory(
            session,
            name=name,
            source="upload",
            activities=activities,
            gwp_set=gwp_set,
            reporting_year=reporting_year,
        )

    @staticmethod
    def inventory_out(row: db.Inventory, detail: bool = False) -> schemas.InventoryOut:
        analytics = schemas.Analytics.model_validate(row.summary)
        base = {
            "id": row.id,
            "name": row.name,
            "created_at": row.created_at,
            "source": row.source,
            "gwp_set": row.gwp_set,
            "reporting_year": row.reporting_year,
            "total_tco2e": analytics.totals.total_tco2e,
            "line_items": analytics.totals.line_items,
            "error_count": len(row.errors),
        }
        if detail:
            return schemas.InventoryDetail(**base, analytics=analytics)
        return schemas.InventoryOut(**base)

    @staticmethod
    def line_out(row: db.ResultLine) -> schemas.LineOut:
        r, a = row.result, row.activity
        return schemas.LineOut(
            activity_id=r["activity_id"],
            description=a.get("description") or "",
            site=a.get("site"),
            supplier=a.get("supplier"),
            scope=r["scope"],
            scope3_category=r["scope3_category"],
            scope2_method=r["scope2_method"],
            method=r["method"],
            quantity=r["quantity"],
            unit=r["unit"],
            factor_id=r["factor_id"],
            factor_source=r["factor_source"],
            factor_status=r["factor_status"],
            gwp_set=r["gwp_set"],
            co2e_kg=r["co2e_kg"],
            data_quality_score=r["data_quality_score"],
            trace=r["trace"],
        )

    @staticmethod
    def get_inventory(session: Session, inventory_id: int) -> db.Inventory:
        row = session.get(db.Inventory, inventory_id)
        if row is None:
            raise NotFound(f"Inventory {inventory_id} not found")
        return row

    # -- classification -----------------------------------------------------------------------
    def _memory(self, session: Session) -> SupplierMemory:
        rows = session.scalars(select(db.SupplierMemoryRow)).all()
        return SupplierMemory({r.key: MemoryEntry.model_validate(r.data) for r in rows})

    def _save_memory(self, session: Session, memory: SupplierMemory) -> None:
        for key, entry in memory.entries.items():
            session.merge(db.SupplierMemoryRow(key=key, data=entry.model_dump(mode="json")))

    def create_run(
        self,
        session: Session,
        content: bytes,
        *,
        name: str,
        threshold: float,
        use_llm: bool,
        currency: str | None,
    ) -> db.ClassificationRun:
        path = _save_upload(content)
        try:
            lines = cl.read_ledger(path, default_currency=currency)
        finally:
            path.unlink(missing_ok=True)
        llm = None
        if use_llm:
            if not self.llm_available():
                raise OpenScopeError("Claude classification is not enabled on this server")
            llm = cl.LLMClassifier.from_env(self.spend_factors, model=self.settings.llm_model)
        classified = cl.classify_ledger(
            lines, self.rules, self._memory(session), llm, cl.PipelineConfig(threshold=threshold)
        )
        usage: dict[str, Any] = {}
        if llm is not None:
            u = llm.usage
            usage = {
                "model": llm.model,
                "requests": u.requests,
                "input_tokens": u.input_tokens,
                "cache_read_input_tokens": u.cache_read_input_tokens,
                "output_tokens": u.output_tokens,
                "failed_batches": u.failed_batches,
            }
        run = db.ClassificationRun(
            name=name, threshold=threshold, used_llm=llm is not None, llm_usage=usage
        )
        for c in classified:
            run.lines.append(self._run_line_row(c))
        session.add(run)
        session.commit()
        return run

    @staticmethod
    def _run_line_row(c: cl.ClassifiedLine) -> db.RunLine:
        return db.RunLine(
            line_id=c.line.line_id,
            status=c.status.value,
            amount=c.line.amount,
            data=c.model_dump(mode="json"),
        )

    @staticmethod
    def get_run(session: Session, run_id: int) -> db.ClassificationRun:
        row = session.get(db.ClassificationRun, run_id)
        if row is None:
            raise NotFound(f"Classification run {run_id} not found")
        return row

    @staticmethod
    def run_out(session: Session, run: db.ClassificationRun) -> schemas.RunOut:
        counts = session.execute(
            select(db.RunLine.status, func.count(), func.sum(func.abs(db.RunLine.amount)))
            .where(db.RunLine.run_id == run.id)
            .group_by(db.RunLine.status)
        ).all()
        return schemas.RunOut(
            id=run.id,
            name=run.name,
            created_at=run.created_at,
            threshold=run.threshold,
            used_llm=run.used_llm,
            lines=sum(int(c[1]) for c in counts),
            by_status={str(s): int(n) for s, n, _ in counts},
            spend_by_status={str(s): round(float(a or 0), 2) for s, _, a in counts},
            llm_usage=run.llm_usage,
        )

    @staticmethod
    def run_line_out(row: db.RunLine) -> schemas.RunLineOut:
        c = cl.ClassifiedLine.model_validate(row.data)
        ln, k = c.line, c.classification
        return schemas.RunLineOut(
            line_id=ln.line_id,
            date=ln.date.isoformat() if ln.date else None,
            supplier=ln.supplier,
            description=ln.description,
            account=ln.account,
            account_name=ln.account_name,
            amount=ln.amount,
            currency=ln.currency,
            status=c.status.value,
            decision=k.decision.value,
            scope3_category=int(k.scope3_category) if k.scope3_category else None,
            factor_id=k.factor_id,
            confidence=k.confidence,
            source=k.source.value,
            rationale=k.rationale,
        )

    def review_line(
        self, session: Session, run: db.ClassificationRun, line_id: str, review: schemas.ReviewIn
    ) -> db.RunLine:
        row = session.scalars(
            select(db.RunLine).where(db.RunLine.run_id == run.id, db.RunLine.line_id == line_id)
        ).first()
        if row is None:
            raise NotFound(f"Line {line_id} not found in run {run.id}")
        current = cl.ClassifiedLine.model_validate(row.data)
        decision = {
            "review_action": review.action,
            "review_category": str(review.scope3_category or ""),
            "review_factor_id": review.factor_id or "",
            "review_note": review.note,
        }
        memory = self._memory(session)
        outcome = cl.apply_review(
            [(current, decision)],
            review.reviewer,
            known_factor_ids={f.factor_id for f in self.registry},
            memory=memory,
        )
        (updated,) = outcome.lines
        row.status = updated.status.value
        row.data = updated.model_dump(mode="json")
        for e in outcome.audit_entries:
            run.audit.append(
                db.AuditEntry(
                    line_id=str(e["line_id"]),
                    timestamp=str(e["timestamp"]),
                    reviewer=str(e["reviewer"]),
                    action=str(e["action"]),
                    before=dict(e["before"]),  # type: ignore[call-overload]
                    after=dict(e["after"]),  # type: ignore[call-overload]
                    note=str(e["note"]),
                )
            )
        self._save_memory(session, memory)
        session.commit()
        return row

    def export_run(
        self, session: Session, run: db.ClassificationRun, body: schemas.ExportIn
    ) -> schemas.ExportOut:
        classified = [cl.ClassifiedLine.model_validate(r.data) for r in run.lines]
        activities = cl.to_activities(classified)
        if not activities:
            raise OpenScopeError("No accepted, classified lines to export yet")
        inv = self.create_inventory(
            session,
            name=body.name,
            source="classification",
            activities=activities,
            gwp_set=body.gwp_set,
            reporting_year=body.reporting_year,
        )
        pending = sum(1 for c in classified if c.status == cl.Status.NEEDS_REVIEW)
        return schemas.ExportOut(
            inventory_id=inv.id, activities=len(activities), pending_lines=pending
        )

    # -- demo -----------------------------------------------------------------------------------
    def _demo_file(self, name: str) -> Path | None:
        d = self.settings.demo_dir
        if d is None or "desnz-2025" not in self.settings.datasets:
            return None
        p = d / name
        return p if p.is_file() else None

    def load_demo(self, session: Session) -> schemas.DemoOut:
        acts_file = self._demo_file("uk_demo_activities.csv")
        ledger_file = self._demo_file("ledger_sample.csv")
        if acts_file is None or ledger_file is None:
            raise OpenScopeError("Demo data is not available on this server")

        inv = session.scalars(
            select(db.Inventory).where(db.Inventory.source == "demo").order_by(db.Inventory.id)
        ).first()
        if inv is None:
            inv = self.create_inventory(
                session,
                name="Demo: UK company 2025 (DESNZ factors)",
                source="demo",
                activities=read_activities(acts_file),
                gwp_set="AR5",
                reporting_year=2025,
            )
        run = session.scalars(
            select(db.ClassificationRun).where(db.ClassificationRun.name.like("Demo:%"))
        ).first()
        if run is None:
            run = self.create_run(
                session,
                ledger_file.read_bytes(),
                name="Demo: AP ledger 2025",
                threshold=0.85,
                use_llm=False,
                currency=None,
            )
        return schemas.DemoOut(inventory_id=inv.id, run_id=run.id)
