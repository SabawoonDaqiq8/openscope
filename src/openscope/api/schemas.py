"""Request/response schemas: the API contract (exported as OpenAPI for the Angular client)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class CategoryOut(BaseModel):
    value: int
    label: str


class Meta(BaseModel):
    version: str
    datasets: list[str]
    gwp_sets: list[str]
    scope3_categories: list[CategoryOut]
    llm_enabled: bool
    demo_available: bool
    public_demo: bool


class FactorOut(BaseModel):
    factor_id: str
    name: str
    activity_unit: str
    co2e_kg: float | None
    gases: dict[str, float]
    gwp_basis: str | None
    scope: int | None
    scope3_category: int | None
    scope2_method: str | None
    region: str
    year: int | None
    source: str
    source_url: str | None
    status: str
    notes: str | None


class FactorPage(BaseModel):
    total: int
    items: list[FactorOut]


class CategoryTotal(BaseModel):
    category: int
    label: str
    tco2e: float


class Hotspot(BaseModel):
    activity_id: str
    description: str
    scope: int
    scope3_category: int | None
    tco2e: float
    share: float


class QualityBucket(BaseModel):
    score: int
    tco2e: float
    lines: int


class MethodTotal(BaseModel):
    method: str
    tco2e: float


class LineError(BaseModel):
    activity_id: str
    message: str


class Totals(BaseModel):
    scope1_tco2e: float
    scope2_location_tco2e: float
    scope2_market_tco2e: float
    scope2_market_fallback_sites: list[str]
    scope3_tco2e: float
    scope3_by_category: list[CategoryTotal]
    total_tco2e: float
    data_quality_score: float | None
    illustrative_factor_share: float
    line_items: int


class Analytics(BaseModel):
    totals: Totals
    hotspots: list[Hotspot]
    data_quality: list[QualityBucket]
    by_method: list[MethodTotal]
    errors: list[LineError]


class InventoryOut(BaseModel):
    id: int
    name: str
    created_at: datetime
    source: str
    gwp_set: str
    reporting_year: int | None
    total_tco2e: float
    line_items: int
    error_count: int


class InventoryDetail(InventoryOut):
    analytics: Analytics


class LineOut(BaseModel):
    activity_id: str
    derived_from: str | None = None  # Scope 1/2 activity a derived Category 3 line comes from
    description: str
    site: str | None
    supplier: str | None
    scope: int
    scope3_category: int | None
    scope2_method: str | None
    method: str
    quantity: float
    unit: str
    factor_id: str
    factor_source: str
    factor_status: str
    gwp_set: str
    co2e_kg: float
    data_quality_score: int
    trace: list[str]


class RunOut(BaseModel):
    id: int
    name: str
    created_at: datetime
    threshold: float
    used_llm: bool
    lines: int
    by_status: dict[str, int]
    spend_by_status: dict[str, float]
    llm_usage: dict[str, Any]


class RunLineOut(BaseModel):
    line_id: str
    date: str | None
    supplier: str
    description: str
    account: str
    account_name: str
    amount: float
    currency: str
    status: str
    decision: str
    scope3_category: int | None
    factor_id: str | None
    confidence: float
    source: str
    rationale: str


class ReviewIn(BaseModel):
    reviewer: str = Field(min_length=1, max_length=200)
    action: Literal["accept", "override", "exclude"]
    scope3_category: int | None = Field(default=None, ge=1, le=15)
    factor_id: str | None = None
    note: str = Field(default="", max_length=2000)


class AuditOut(BaseModel):
    id: int
    line_id: str
    timestamp: str
    reviewer: str
    action: str
    before: dict[str, Any]
    after: dict[str, Any]
    note: str


class ExportIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    gwp_set: Literal["AR5", "AR6"] = "AR6"
    reporting_year: int | None = None


class ExportOut(BaseModel):
    inventory_id: int
    activities: int
    pending_lines: int


class DemoOut(BaseModel):
    inventory_id: int
    run_id: int


class PathwayLeverOut(BaseModel):
    id: str
    name: str
    matched_lines: int
    addressed_tco2e: float
    abatement_tco2e: float
    annualised_cost: float
    mac: float | None
    merit_rank: int
    abatement_by_target_year_tco2e: float


class PathwayGroupOut(BaseModel):
    base_tco2e: float
    target_tco2e: float
    pathway_tco2e: float
    gap_tco2e: float
    probability_meets_target: float


class PathwayOut(BaseModel):
    years: list[int]
    bau: list[float]
    pathway: list[float]
    p10: list[float]
    p50: list[float]
    p90: list[float]
    target: list[float]
    levers: list[PathwayLeverOut]
    base_tco2e: float
    target_year_tco2e: float
    target_year_gap_tco2e: float
    probability_meets_target: float
    scope12: PathwayGroupOut
    scope3: PathwayGroupOut
    currency: str


class DisclosureRowOut(BaseModel):
    key: str
    label: str
    reference: str
    unit: str
    current: float | None
    prior: float | None
    base: float | None
    indent: int
    note: str
    change_vs_prior: float | None
    change_vs_base: float | None
    section: str


class DisclosureCheckOut(BaseModel):
    level: Literal["blocker", "warning", "info"]
    code: str
    message: str


class DisclosureOut(BaseModel):
    framework: Literal["esrs", "issb"]
    title: str
    reporting_year: int | None
    prior_year: int | None
    base_year: int | None
    ready: bool
    rows: list[DisclosureRowOut]
    checks: list[DisclosureCheckOut]
    basis: list[str]
    revenue_currency: str | None
