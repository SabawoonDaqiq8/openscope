"""Decarbonisation pathways: abatement levers, a marginal abatement cost curve (MACC),
target trajectories and Monte Carlo uncertainty.

Method
------
* **Baseline**: the inventory's headline results (market-based Scope 2), line by line.
* **Business as usual (BAU)**: each scope's emissions grow at ``bau_growth[scope]`` a year.
* **Levers**: a lever applies to the lines matched by its selector. In year *y* it removes
  ``reduction × ramp(y)`` of what is left on each matched line, where ``ramp`` rises linearly
  from 0 to 1 over ``ramp_years`` starting in ``start_year``.
* **Interactions**: levers are applied to the remaining emissions in merit order (cheapest
  abatement first), so overlapping levers never abate the same tonne twice. Merit order comes
  from each lever's stand-alone cost per tonne; reported abatement is the interaction-adjusted,
  marginal value at full implementation and base-year activity.
* **Cost**: ``annualised cost = capex × CRF(discount rate, lifetime) + annual opex change``,
  where CRF is the capital recovery factor. MAC = annualised cost / annual abatement (currency
  per tCO2e). Negative values mean the lever saves money.
* **Target**: linear absolute contraction from the base year, separately for Scope 1+2 and
  Scope 3. Defaults are the SBTi near-term minimum rates (4.2 %/yr for Scope 1+2, aligned with
  1.5 °C; 2.5 %/yr for Scope 3, well-below 2 °C). Configure them for your own target.
* **Uncertainty**: Monte Carlo over each lever's reduction (triangular: low, mode, high) and
  BAU growth (uniform ± ``bau_growth_uncertainty``). Results are P10/P50/P90 per year and the
  probability of being at or below target in the target year.
"""

from __future__ import annotations

import math
import random
from collections.abc import Sequence
from dataclasses import dataclass, field

from pydantic import BaseModel, Field, model_validator

from openscope.inventory import Inventory
from openscope.models import EmissionResult

SBTI_NEAR_TERM_RATES = {"scope12": 0.042, "scope3": 0.025}


class LeverSelector(BaseModel):
    """Which inventory lines a lever acts on (all given conditions must match)."""

    scopes: list[int] | None = None
    scope3_categories: list[int] | None = None
    text: str | None = Field(
        default=None, description="Case-insensitive match on activity id, description or factor"
    )
    activity_ids: list[str] | None = None

    def matches(self, r: EmissionResult, description: str) -> bool:
        if self.scopes and int(r.scope) not in self.scopes:
            return False
        if self.scope3_categories and (
            r.scope3_category is None or int(r.scope3_category) not in self.scope3_categories
        ):
            return False
        if self.activity_ids and r.activity_id not in self.activity_ids:
            return False
        if self.text:
            hay = f"{r.activity_id} {description} {r.factor_id}".lower()
            if not all(t in hay for t in self.text.lower().split()):
                return False
        return True


class Lever(BaseModel):
    id: str
    name: str
    selector: LeverSelector
    reduction: float = Field(ge=0, le=1, description="Share of matched emissions removed")
    reduction_low: float | None = Field(default=None, ge=0, le=1)
    reduction_high: float | None = Field(default=None, ge=0, le=1)
    start_year: int
    ramp_years: int = Field(default=1, ge=1)
    capex: float = Field(default=0, ge=0)
    annual_opex_change: float = 0.0  # negative = savings
    lifetime_years: int = Field(default=10, ge=1)
    assumptions: str = ""

    @model_validator(mode="after")
    def _bounds(self) -> Lever:
        lo = self.reduction if self.reduction_low is None else self.reduction_low
        hi = self.reduction if self.reduction_high is None else self.reduction_high
        if not lo <= self.reduction <= hi:
            raise ValueError(f"lever {self.id}: need reduction_low <= reduction <= reduction_high")
        return self

    @property
    def low(self) -> float:
        return self.reduction if self.reduction_low is None else self.reduction_low

    @property
    def high(self) -> float:
        return self.reduction if self.reduction_high is None else self.reduction_high

    def ramp(self, year: int) -> float:
        return min(max((year - self.start_year + 1) / self.ramp_years, 0.0), 1.0)


class Scenario(BaseModel):
    name: str = "Scenario"
    currency: str = "USD"
    base_year: int
    target_year: int
    bau_growth: dict[str, float] = Field(
        default_factory=lambda: {"1": 0.0, "2": 0.0, "3": 0.0},
        description="Annual BAU growth per scope, keys '1', '2', '3'",
    )
    bau_growth_uncertainty: float = Field(default=0.01, ge=0)
    target_rate_scope12: float = Field(default=SBTI_NEAR_TERM_RATES["scope12"], ge=0, le=1)
    target_rate_scope3: float = Field(default=SBTI_NEAR_TERM_RATES["scope3"], ge=0, le=1)
    discount_rate: float = Field(default=0.08, ge=0, le=1)
    levers: list[Lever] = Field(default_factory=list)
    simulations: int = Field(default=1000, ge=10, le=20000)
    seed: int = 42

    @model_validator(mode="after")
    def _years(self) -> Scenario:
        if self.target_year <= self.base_year:
            raise ValueError("target_year must be after base_year")
        if self.target_year - self.base_year > 60:
            raise ValueError("horizon is limited to 60 years")
        ids = [lv.id for lv in self.levers]
        if len(ids) != len(set(ids)):
            raise ValueError("lever ids must be unique")
        return self


@dataclass
class LeverResult:
    id: str
    name: str
    matched_lines: int
    addressed_tco2e: float  # base-year emissions of the matched lines
    abatement_tco2e: float  # interaction-adjusted, full implementation, base-year activity
    annualised_cost: float
    mac: float | None  # currency per tCO2e
    merit_rank: int
    abatement_by_target_year_tco2e: float  # in the target year, deterministic pathway
    abatement_by_target_year_scope12_tco2e: float = 0.0
    abatement_by_target_year_scope3_tco2e: float = 0.0


@dataclass
class GroupResult:
    """Target-year outcome for one target boundary (Scope 1+2 or Scope 3)."""

    base_tco2e: float
    target_tco2e: float
    pathway_tco2e: float
    gap_tco2e: float  # positive = shortfall
    probability_meets_target: float


@dataclass
class PathwayResult:
    years: list[int]
    bau: list[float]
    pathway: list[float]  # deterministic (mode values)
    p10: list[float]
    p50: list[float]
    p90: list[float]
    target: list[float]
    levers: list[LeverResult]
    base_tco2e: float
    target_year_tco2e: float
    target_year_gap_tco2e: float  # deterministic pathway minus target (positive = shortfall)
    probability_meets_target: float
    scope12: GroupResult
    scope3: GroupResult
    currency: str
    # deterministic pathway and target per boundary, by year
    pathway_scope12: list[float] = field(default_factory=list)
    pathway_scope3: list[float] = field(default_factory=list)
    target_scope12: list[float] = field(default_factory=list)
    target_scope3: list[float] = field(default_factory=list)


def capital_recovery_factor(rate: float, years: int) -> float:
    if rate == 0:
        return 1 / years
    f = (1 + rate) ** years
    return rate * f / (f - 1)


@dataclass
class _Line:
    scope: int
    base_t: float
    levers: list[int]  # indices into merit-ordered levers


def _descriptions(inv: Inventory, descriptions: dict[str, str] | None) -> dict[str, str]:
    return descriptions or {r.activity_id: "" for r in inv.results}


def _lines(
    results: Sequence[EmissionResult], levers: Sequence[Lever], desc: dict[str, str]
) -> list[_Line]:
    out = []
    for r in results:
        idx = [
            i for i, lv in enumerate(levers) if lv.selector.matches(r, desc.get(r.activity_id, ""))
        ]
        out.append(_Line(int(r.scope), r.co2e_kg / 1000, idx))
    return out


def _standalone_mac(lever: Lever, lines: list[_Line], lever_index: int, rate: float) -> float:
    abated = sum(ln.base_t * lever.reduction for ln in lines if lever_index in ln.levers)
    cost = (
        lever.capex * capital_recovery_factor(rate, lever.lifetime_years) + lever.annual_opex_change
    )
    return cost / abated if abated > 0 else math.inf


def _split(
    lines: list[_Line],
    levers: Sequence[Lever],
    reductions: Sequence[float],
    growth: dict[int, float],
    years: int,
    base_year: int,
) -> tuple[float, float]:
    """(Scope 1+2, Scope 3) tCO2e in ``base_year + years`` given per-lever reductions."""
    year = base_year + years
    s12 = s3 = 0.0
    for ln in lines:
        e = ln.base_t * (1 + growth[ln.scope]) ** years
        for i in ln.levers:
            e *= 1 - reductions[i] * levers[i].ramp(year)
        if ln.scope == 3:
            s3 += e
        else:
            s12 += e
    return s12, s3


def _emissions(
    lines: list[_Line],
    levers: Sequence[Lever],
    reductions: Sequence[float],
    growth: dict[int, float],
    years: int,
    base_year: int,
) -> float:
    """Total tCO2e in ``base_year + years``."""
    return sum(_split(lines, levers, reductions, growth, years, base_year))


def run(
    inventory: Inventory, scenario: Scenario, descriptions: dict[str, str] | None = None
) -> PathwayResult:
    desc = _descriptions(inventory, descriptions)
    results = inventory.headline_results()
    rate = scenario.discount_rate

    # 1. merit order from stand-alone MACs
    prelim = _lines(results, scenario.levers, desc)
    order = sorted(
        range(len(scenario.levers)),
        key=lambda i: (_standalone_mac(scenario.levers[i], prelim, i, rate), scenario.levers[i].id),
    )
    levers = [scenario.levers[i] for i in order]
    lines = _lines(results, levers, desc)

    # 2. interaction-adjusted abatement at full implementation, base-year activity
    lever_results: list[LeverResult] = []
    remaining = [ln.base_t for ln in lines]
    for rank, (i, lv) in enumerate(enumerate(levers), start=1):
        abated = addressed = 0.0
        matched = 0
        for k, ln in enumerate(lines):
            if i in ln.levers:
                matched += 1
                addressed += ln.base_t
                cut = remaining[k] * lv.reduction
                remaining[k] -= cut
                abated += cut
        cost = lv.capex * capital_recovery_factor(rate, lv.lifetime_years) + lv.annual_opex_change
        lever_results.append(
            LeverResult(
                id=lv.id,
                name=lv.name,
                matched_lines=matched,
                addressed_tco2e=addressed,
                abatement_tco2e=abated,
                annualised_cost=cost,
                mac=cost / abated if abated > 0 else None,
                merit_rank=rank,
                abatement_by_target_year_tco2e=0.0,
            )
        )

    # 3. deterministic trajectories
    years = list(range(scenario.base_year, scenario.target_year + 1))
    n = len(years)
    growth = {s: scenario.bau_growth.get(str(s), 0.0) for s in (1, 2, 3)}
    modes = [lv.reduction for lv in levers]
    zeros = [0.0] * len(levers)
    bau = [_emissions(lines, levers, zeros, growth, t, scenario.base_year) for t in range(n)]
    pathway = [_emissions(lines, levers, modes, growth, t, scenario.base_year) for t in range(n)]

    # marginal contribution of each lever in the target year (in merit order)
    horizon = n - 1
    applied = [0.0] * len(levers)
    previous = _split(lines, levers, applied, growth, horizon, scenario.base_year)
    for i, lv in enumerate(levers):
        applied[i] = lv.reduction
        now = _split(lines, levers, applied, growth, horizon, scenario.base_year)
        lr = lever_results[i]
        lr.abatement_by_target_year_scope12_tco2e = previous[0] - now[0]
        lr.abatement_by_target_year_scope3_tco2e = previous[1] - now[1]
        lr.abatement_by_target_year_tco2e = sum(previous) - sum(now)
        previous = now
    split_path = [_split(lines, levers, modes, growth, t, scenario.base_year) for t in range(n)]

    base12 = sum(ln.base_t for ln in lines if ln.scope in (1, 2))
    base3 = sum(ln.base_t for ln in lines if ln.scope == 3)
    t12 = [max(base12 * (1 - scenario.target_rate_scope12 * t), 0.0) for t in range(n)]
    t3 = [max(base3 * (1 - scenario.target_rate_scope3 * t), 0.0) for t in range(n)]
    target = [a + b for a, b in zip(t12, t3, strict=True)]

    # 4. Monte Carlo
    rng = random.Random(scenario.seed)
    sims: list[list[float]] = []
    final_split: list[tuple[float, float]] = []
    for _ in range(scenario.simulations):
        red = [
            rng.triangular(lv.low, lv.high, lv.reduction) if lv.high > lv.low else lv.reduction
            for lv in levers
        ]
        u = scenario.bau_growth_uncertainty
        g = {s: growth[s] + rng.uniform(-u, u) for s in growth}
        sims.append([_emissions(lines, levers, red, g, t, scenario.base_year) for t in range(n)])
        final_split.append(_split(lines, levers, red, g, horizon, scenario.base_year))

    def pct(values: list[float], q: float) -> float:
        s = sorted(values)
        pos = (len(s) - 1) * q
        lo, hi = math.floor(pos), math.ceil(pos)
        return s[lo] + (s[hi] - s[lo]) * (pos - lo)

    columns = [[sim[t] for sim in sims] for t in range(n)]
    meets = sum(1 for sim in sims if sim[-1] <= target[-1] + 1e-9) / len(sims)
    det12, det3 = _split(lines, levers, modes, growth, horizon, scenario.base_year)

    def group(base: float, tgt: float, det: float, idx: int) -> GroupResult:
        ok = sum(1 for f in final_split if f[idx] <= tgt + 1e-9) / len(final_split)
        return GroupResult(base, tgt, det, det - tgt, ok)

    return PathwayResult(
        years=years,
        bau=bau,
        pathway=pathway,
        p10=[pct(c, 0.1) for c in columns],
        p50=[pct(c, 0.5) for c in columns],
        p90=[pct(c, 0.9) for c in columns],
        target=target,
        levers=lever_results,
        base_tco2e=bau[0],
        target_year_tco2e=target[-1],
        target_year_gap_tco2e=pathway[-1] - target[-1],
        probability_meets_target=meets,
        scope12=group(base12, t12[-1], det12, 0),
        scope3=group(base3, t3[-1], det3, 1),
        currency=scenario.currency,
        pathway_scope12=[s[0] for s in split_path],
        pathway_scope3=[s[1] for s in split_path],
        target_scope12=t12,
        target_scope3=t3,
    )
