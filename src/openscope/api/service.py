"""Application service: glue between the HTTP layer, the database and the openscope engine.

No calculation or classification logic lives here; it only orchestrates library calls.
"""

from __future__ import annotations

import dataclasses
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
    disclosure,
    targets,
    units,
)
from openscope import classify as cl
from openscope.api import db, schemas
from openscope.api.settings import Settings
from openscope.classify.memory import MemoryEntry, SupplierMemory
from openscope.energy import GridMix
from openscope.engine import BatchResult
from openscope.errors import OpenScopeError
from openscope.io import read_activities
from openscope.models import EmissionResult
from openscope.pathway import PathwayResult, Scenario
from openscope.pathway import run as run_pathway


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
            public_demo=self.settings.public_demo,
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

            # relevance: terms found in the name first, then the most specific (shortest) name
            def rank(f: EmissionFactor) -> tuple[int, int, str]:
                name = f.name.lower()
                return (-sum(t in name for t in terms), len(name), f.factor_id)

            items = sorted(items, key=rank)
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
        derive_cat3: bool = False,
    ) -> db.Inventory:
        calc = Calculator(
            self.registry,
            gwp_set=gwp_set,
            reporting_year=reporting_year,
            derive_cat3=derive_cat3,
        )
        batch = calc.calculate_many(activities)
        analytics = self.analytics(Inventory(batch.results), batch)
        acts = batch.activities(activities)
        descriptions = {k: a.description for k, a in acts.items()}
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
        derive_cat3: bool = False,
    ) -> db.Inventory:
        path = _save_upload(content)
        try:
            activities = read_activities(path)
        finally:
            path.unlink(missing_ok=True)
        row = self.create_inventory(
            session,
            name=name,
            source="upload",
            activities=activities,
            gwp_set=gwp_set,
            reporting_year=reporting_year,
            derive_cat3=derive_cat3,
        )
        self._prune(session)
        return row

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
            derived_from=r.get("derived_from"),
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
        internal: bool = False,
    ) -> db.ClassificationRun:
        if not internal:
            self._check_name(name)
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
        self._prune(session)
        return run

    # -- public demo guards --------------------------------------------------------------------
    def _check_name(self, name: str) -> None:
        """Ledger runs are protected by their name prefix, so visitors cannot reuse it.

        (Inventories are protected by ``source == "demo"``, so their names are not restricted.)
        """
        if self.settings.public_demo and name.strip().lower().startswith("demo:"):
            raise OpenScopeError("Names starting with 'Demo:' are reserved in the public demo")

    def _prune(self, session: Session) -> None:
        """Public demo: keep only the newest visitor uploads (demo data is never removed)."""
        if not self.settings.public_demo:
            return
        keep = self.settings.demo_max_uploads
        visitor_inventories = session.scalars(
            select(db.Inventory)
            .where(db.Inventory.source != "demo")
            .order_by(db.Inventory.id.desc())
            .offset(keep)
        ).all()
        visitor_runs = session.scalars(
            select(db.ClassificationRun)
            .where(db.ClassificationRun.name.not_like("Demo:%"))
            .order_by(db.ClassificationRun.id.desc())
            .offset(keep)
        ).all()
        for row in [*visitor_inventories, *visitor_runs]:
            session.delete(row)
        if visitor_inventories or visitor_runs:
            session.commit()

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
        self._prune(session)
        pending = sum(1 for c in classified if c.status == cl.Status.NEEDS_REVIEW)
        return schemas.ExportOut(
            inventory_id=inv.id, activities=len(activities), pending_lines=pending
        )

    # -- disclosure ------------------------------------------------------------------------------
    @staticmethod
    def _period(row: db.Inventory) -> disclosure.Period:
        results = [EmissionResult.model_validate(r.result) for r in row.lines]
        return disclosure.Period(Inventory(results), row.reporting_year, row.gwp_set)

    def disclosure(
        self,
        session: Session,
        row: db.Inventory,
        *,
        framework: str,
        prior_id: int | None,
        base_id: int | None,
        net_revenue: float | None,
        revenue_currency: str | None,
        ets_share: float | None,
        grid_mix: GridMix | None = None,
    ) -> disclosure.Disclosure:
        prior = self._period(self.get_inventory(session, prior_id)) if prior_id else None
        base = self._period(self.get_inventory(session, base_id)) if base_id else None
        return disclosure.build(
            self._period(row),
            framework=framework,
            prior=prior,
            base=base,
            net_revenue=net_revenue,
            revenue_currency=revenue_currency,
            ets_share=ets_share,
            calculation_errors=len(row.errors),
            grid_mix=grid_mix,
        )

    # -- pathways --------------------------------------------------------------------------------
    def pathway(self, row: db.Inventory, scenario: Scenario) -> schemas.PathwayOut:
        inventory, result = self._run_pathway(row, scenario)
        out = schemas.PathwayOut.model_validate(dataclasses.asdict(result))
        e1_4 = targets.build(inventory, scenario, result, row.reporting_year)
        out.e1_4 = schemas.TargetsOut.model_validate(e1_4.as_dict())
        return out

    def targets(self, row: db.Inventory, scenario: Scenario) -> targets.TargetDisclosure:
        inventory, result = self._run_pathway(row, scenario)
        return targets.build(inventory, scenario, result, row.reporting_year)

    @staticmethod
    def _run_pathway(row: db.Inventory, scenario: Scenario) -> tuple[Inventory, PathwayResult]:
        results = [EmissionResult.model_validate(r.result) for r in row.lines]
        descriptions = {r.activity_id: r.activity.get("description") or "" for r in row.lines}
        inventory = Inventory(results)
        return inventory, run_pathway(inventory, scenario, descriptions)

    def demo_scenario(self) -> Scenario:
        path = self._demo_file("pathway_demo_scenario.json")
        if path is None:
            raise NotFound("No demo scenario on this server")
        return Scenario.model_validate_json(path.read_text(encoding="utf-8"))

    # -- demo -----------------------------------------------------------------------------------
    def _demo_file(self, name: str) -> Path | None:
        d = self.settings.demo_dir
        if d is None or not any(n.startswith("desnz") for n in self.settings.datasets):
            return None
        p = d / name
        return p if p.is_file() else None

    def load_demo(self, session: Session) -> schemas.DemoOut:
        acts_file = self._demo_file("uk_demo_activities.csv")
        ledger_file = self._demo_file("ledger_sample.csv")
        if acts_file is None or ledger_file is None:
            raise OpenScopeError("Demo data is not available on this server")

        demo = {
            r.reporting_year: r
            for r in session.scalars(select(db.Inventory).where(db.Inventory.source == "demo"))
        }
        prior_file = self._demo_file("uk_demo_activities_2024.csv")
        if 2024 not in demo and prior_file is not None:
            demo[2024] = self.create_inventory(
                session,
                name="Demo: UK company 2024 (DESNZ factors)",
                source="demo",
                activities=read_activities(prior_file),
                gwp_set="AR5",
                reporting_year=2024,
                derive_cat3=True,
            )
        if 2025 not in demo:
            demo[2025] = self.create_inventory(
                session,
                name="Demo: UK company 2025 (DESNZ factors)",
                source="demo",
                activities=read_activities(acts_file),
                gwp_set="AR5",
                reporting_year=2025,
                derive_cat3=True,
            )
        inv = demo[2025]
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
                internal=True,
            )
        return schemas.DemoOut(inventory_id=inv.id, run_id=run.id)
