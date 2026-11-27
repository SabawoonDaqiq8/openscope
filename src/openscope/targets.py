"""ESRS E1-4 GHG emission reduction targets, from a decarbonisation pathway scenario.

A pathway scenario already defines a target: a base year, a target year and a linear annual
reduction rate for Scope 1+2 and for Scope 3, plus the levers meant to deliver it. This module
turns that into the E1-4 §34 disclosure:

* (a), (b) absolute targets in tCO2e and as a % of the base year, per boundary, with the share
  of each scope in a combined target and the gases covered;
* (c) the base year and base value;
* (d) target values for 2030 and every 5 years after it, up to the target year;
* (e) how the reduction rate compares with the SBTi near-term minimum rates (an indication,
  not a validation);
* (f) the decarbonisation levers and their quantitative contributions, from the pathway.

The targets are **gross**: pathway levers only reduce emissions in the inventory. Removals,
carbon credits and avoided emissions are not part of the model.

Paragraph references are to ESRS Set 1 (Delegated Regulation (EU) 2023/2772). The EU Omnibus
simplification may change them; check the version that applies to your reporting period.
"""

from __future__ import annotations

import csv
import io
import json
from dataclasses import asdict, dataclass, field

from openscope.disclosure import Check, Level
from openscope.inventory import Inventory
from openscope.models import Scope2Method
from openscope.pathway import SBTI_NEAR_TERM_RATES, PathwayResult, Scenario

TITLE = "ESRS E1-4 Targets related to climate change mitigation: GHG emission reduction targets"
MILESTONE_STEP = 5
FIRST_MILESTONE = 2030
SCOPE3_MATERIALITY = 0.40  # SBTi: a Scope 3 target is needed when Scope 3 is >= 40 % of total


@dataclass
class Milestone:
    year: int
    target_tco2e: float
    reduction_vs_base: float  # fraction
    expected_tco2e: float  # deterministic pathway with the planned levers
    gap_tco2e: float  # expected minus target; positive = shortfall


@dataclass
class Target:
    key: str  # "scope12" or "scope3"
    boundary: str
    scopes: list[int]
    base_year: int
    base_tco2e: float
    scope_shares: dict[str, float]  # share of each scope in the base value (combined targets)
    annual_rate: float  # linear, fraction of base-year emissions a year
    target_year: int
    milestones: list[Milestone]
    probability_meets_target: float  # in the target year, Monte Carlo
    bau_tco2e: float  # business-as-usual emissions in the target year (no levers)
    required_reduction_tco2e: float  # BAU minus target, in the target year
    planned_reduction_tco2e: float  # sum of lever contributions in the target year
    ambition: str  # how the rate compares with the SBTi near-term minimum


@dataclass
class LeverContribution:
    id: str
    name: str
    scope12_tco2e: float  # abatement in the target year, deterministic pathway
    scope3_tco2e: float
    share_of_scope12_reduction: float | None  # of the planned Scope 1+2 reduction
    share_of_scope3_reduction: float | None
    assumptions: str


@dataclass
class TargetDisclosure:
    title: str
    scenario: str
    reporting_year: int | None
    base_year: int
    target_year: int
    scope2_basis: str
    gases: list[str]
    targets: list[Target]
    levers: list[LeverContribution]
    checks: list[Check]
    basis: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, object]:
        out = asdict(self)
        out["checks"] = [{**asdict(c), "level": c.level.value} for c in self.checks]
        return out


def _gases(inv: Inventory) -> list[str]:
    """Gases in the inventory; factors published only as CO2e are noted, not listed as a gas."""
    found: set[str] = set()
    for r in inv.headline_results():
        for gas, kg in r.gas_kg.items():
            if kg:
                found.add(gas)
    upper = {g.upper(): g for g in found}
    first = [g for g in ("CO2", "CH4", "N2O") if g in upper]
    rest = sorted(g for g in upper if g not in ("CO2", "CH4", "N2O", "CO2E"))
    gases = first + rest
    if "CO2E" in upper:
        gases.append("other gases within factors published only as CO2e")
    return gases


def _ambition(key: str, rate: float) -> str:
    minimum = SBTI_NEAR_TERM_RATES[key]
    goal = "1.5 °C" if key == "scope12" else "well-below 2 °C"
    if rate + 1e-12 >= minimum:
        return (
            f"{rate:.1%} a year meets the SBTi near-term minimum linear rate for {goal} "
            f"({minimum:.1%} a year)."
        )
    return (
        f"{rate:.1%} a year is below the SBTi near-term minimum linear rate for {goal} "
        f"({minimum:.1%} a year)."
    )


def _milestone_years(base_year: int, target_year: int) -> list[int]:
    years = {target_year}
    y = FIRST_MILESTONE
    while y <= target_year:
        if y > base_year:
            years.add(y)
        y += MILESTONE_STEP
    return sorted(years)


def build(
    inventory: Inventory,
    scenario: Scenario,
    result: PathwayResult,
    reporting_year: int | None = None,
) -> TargetDisclosure:
    base_year, target_year = scenario.base_year, scenario.target_year
    years = _milestone_years(base_year, target_year)
    s1 = inventory.scope1_t()
    s2 = inventory.scope2_t(Scope2Method.MARKET_BASED)
    base12, base3 = result.scope12.base_tco2e, result.scope3.base_tco2e

    def milestones(key: str) -> list[Milestone]:
        target = result.target_scope12 if key == "scope12" else result.target_scope3
        expected = result.pathway_scope12 if key == "scope12" else result.pathway_scope3
        base = base12 if key == "scope12" else base3
        out = []
        for y in years:
            i = y - base_year
            out.append(
                Milestone(
                    year=y,
                    target_tco2e=target[i],
                    reduction_vs_base=1 - target[i] / base if base else 0.0,
                    expected_tco2e=expected[i],
                    gap_tco2e=expected[i] - target[i],
                )
            )
        return out

    planned12 = sum(lv.abatement_by_target_year_scope12_tco2e for lv in result.levers)
    planned3 = sum(lv.abatement_by_target_year_scope3_tco2e for lv in result.levers)
    targets = [
        Target(
            key="scope12",
            boundary="Scope 1 and 2 (combined)",
            scopes=[1, 2],
            base_year=base_year,
            base_tco2e=base12,
            scope_shares={"Scope 1": s1 / base12, "Scope 2": s2 / base12} if base12 else {},
            annual_rate=scenario.target_rate_scope12,
            target_year=target_year,
            milestones=milestones("scope12"),
            probability_meets_target=result.scope12.probability_meets_target,
            bau_tco2e=result.scope12.pathway_tco2e + planned12,
            required_reduction_tco2e=result.scope12.pathway_tco2e
            + planned12
            - result.scope12.target_tco2e,
            planned_reduction_tco2e=planned12,
            ambition=_ambition("scope12", scenario.target_rate_scope12),
        ),
        Target(
            key="scope3",
            boundary="Scope 3",
            scopes=[3],
            base_year=base_year,
            base_tco2e=base3,
            scope_shares={"Scope 3": 1.0} if base3 else {},
            annual_rate=scenario.target_rate_scope3,
            target_year=target_year,
            milestones=milestones("scope3"),
            probability_meets_target=result.scope3.probability_meets_target,
            bau_tco2e=result.scope3.pathway_tco2e + planned3,
            required_reduction_tco2e=result.scope3.pathway_tco2e
            + planned3
            - result.scope3.target_tco2e,
            planned_reduction_tco2e=planned3,
            ambition=_ambition("scope3", scenario.target_rate_scope3),
        ),
    ]

    assumptions = {lv.id: lv.assumptions for lv in scenario.levers}
    levers = [
        LeverContribution(
            id=lv.id,
            name=lv.name,
            scope12_tco2e=lv.abatement_by_target_year_scope12_tco2e,
            scope3_tco2e=lv.abatement_by_target_year_scope3_tco2e,
            share_of_scope12_reduction=(
                lv.abatement_by_target_year_scope12_tco2e / planned12 if planned12 > 0 else None
            ),
            share_of_scope3_reduction=(
                lv.abatement_by_target_year_scope3_tco2e / planned3 if planned3 > 0 else None
            ),
            assumptions=assumptions.get(lv.id, ""),
        )
        for lv in result.levers
    ]

    d = TargetDisclosure(
        title=TITLE,
        scenario=scenario.name,
        reporting_year=reporting_year,
        base_year=base_year,
        target_year=target_year,
        scope2_basis="market-based",
        gases=_gases(inventory),
        targets=targets,
        levers=levers,
        checks=[],
    )
    d.checks = _checks(d, scenario, s1 + s2 + base3)
    d.basis = _basis(d)
    return d


def _checks(d: TargetDisclosure, scenario: Scenario, total: float) -> list[Check]:
    checks: list[Check] = []
    s12, s3 = d.targets
    if d.target_year < FIRST_MILESTONE:
        checks.append(
            Check(
                Level.WARNING,
                "target-2030",
                f"The target year is {d.target_year}. E1-4 §34(d) asks for target values for "
                "2030 at least (and 2050 if available); extend the scenario to 2030.",
            )
        )
    if d.reporting_year and d.base_year != d.reporting_year:
        checks.append(
            Check(
                Level.WARNING,
                "base-year-inventory",
                f"The base value comes from the {d.reporting_year} inventory but the scenario's "
                f"base year is {d.base_year}. Use the base-year inventory as the pathway baseline.",
            )
        )
    horizon = d.target_year - d.base_year
    if not 5 <= horizon <= 10:
        checks.append(
            Check(
                Level.INFO,
                "near-term-horizon",
                f"The target covers {horizon} years. SBTi near-term targets cover 5 to 10 years; "
                "a longer horizon is a long-term target and needs its own criteria.",
            )
        )
    for t in d.targets:
        minimum = SBTI_NEAR_TERM_RATES[t.key]
        if t.annual_rate and t.annual_rate + 1e-12 < minimum:
            checks.append(
                Check(
                    Level.WARNING,
                    f"ambition-{t.key}",
                    f"{t.boundary}: {t.ambition} Explain why the target is still compatible with "
                    "the Paris Agreement, or raise it (§34(e)).",
                )
            )
    if total and s3.base_tco2e / total >= SCOPE3_MATERIALITY and not s3.annual_rate:
        checks.append(
            Check(
                Level.WARNING,
                "scope3-target",
                f"Scope 3 is {s3.base_tco2e / total:.0%} of total emissions but has no reduction "
                "target. SBTi expects one when Scope 3 is 40 % or more.",
            )
        )
    for t in d.targets:
        final = t.milestones[-1]
        if t.base_tco2e and final.gap_tco2e > 0.05:
            checks.append(
                Check(
                    Level.WARNING,
                    f"gap-{t.key}",
                    f"{t.boundary}: the planned levers fall short of the {t.target_year} target by "
                    f"{final.gap_tco2e:,.1f} tCO2e (probability of meeting it: "
                    f"{t.probability_meets_target:.0%}). Add levers or explain the plan (§34(f)).",
                )
            )
    illustrative = [lv.name for lv in scenario.levers if "illustrative" in lv.assumptions.lower()]
    if illustrative:
        which = (
            f"All {len(illustrative)} levers have"
            if len(illustrative) == len(scenario.levers)
            else f"{len(illustrative)} levers ({', '.join(illustrative)}) have"
        )
        checks.append(
            Check(
                Level.BLOCKER,
                "illustrative-levers",
                f"{which} illustrative assumptions. Replace them with real estimates of cost and "
                "reduction before disclosing.",
            )
        )
    checks.append(
        Check(
            Level.INFO,
            "science-based",
            "openscope compares the reduction rates with the SBTi near-term minimum rates. That "
            "is not a validation: say whether the targets are validated by the SBTi or another "
            "body, and which framework and scenario they follow (§34(e)).",
        )
    )
    order = {Level.BLOCKER: 0, Level.WARNING: 1, Level.INFO: 2}
    return sorted(checks, key=lambda c: order[c.level])


def _basis(d: TargetDisclosure) -> list[str]:
    s12, _ = d.targets
    shares = ", ".join(f"{k} {v:.0%}" for k, v in s12.scope_shares.items())
    return [
        f"Targets are set from the decarbonisation scenario '{d.scenario}' as a linear absolute "
        f"reduction from the {d.base_year} base year to {d.target_year}.",
        f"The Scope 1 and 2 target is combined ({shares} of the base value); Scope 2 is "
        f"{d.scope2_basis}. Scope 3 has a separate target covering all reported categories.",
        f"Gases covered: all gases in the inventory ({', '.join(d.gases) or 'none'}).",
        "The targets are gross: they are met by reducing the emissions in the inventory, not by "
        "GHG removals, carbon credits or avoided emissions.",
        "Target boundaries match the GHG inventory (E1-6), which uses the same operational "
        "boundary and calculation methods.",
        "Lever contributions are the reduction each lever achieves in the target year in the "
        "deterministic pathway, applied in merit order (cheapest first) so no tonne is counted "
        "twice. Shares are of the planned reduction in each boundary.",
    ]


# -- renderers ---------------------------------------------------------------------------------
def _t(v: float) -> str:
    return f"{v:,.1f}"


def _share(v: float | None) -> str:
    return "" if v is None else f"{v:.0%}"


def to_markdown(d: TargetDisclosure) -> str:
    lines = [f"# {d.title}", "", f"Scenario: {d.scenario}", ""]
    lines += [
        "## GHG emission reduction targets (§34(a)-(e))",
        "",
        "| Boundary | Base year | Base value (tCO2e) | Year | Target (tCO2e) | Reduction vs "
        "base | Expected with levers (tCO2e) | Gap (tCO2e) |",
        "|---|--:|--:|--:|--:|--:|--:|--:|",
    ]
    for t in d.targets:
        for m in t.milestones:
            lines.append(
                f"| {t.boundary} | {t.base_year} | {_t(t.base_tco2e)} | {m.year} | "
                f"{_t(m.target_tco2e)} | {m.reduction_vs_base:.1%} | {_t(m.expected_tco2e)} | "
                f"{_t(m.gap_tco2e)} |"
            )
    lines += [""]
    for t in d.targets:
        lines.append(
            f"- **{t.boundary}**: {t.ambition} Against business-as-usual emissions of "
            f"{_t(t.bau_tco2e)} tCO2e in {t.target_year}, the target needs "
            f"{_t(max(t.required_reduction_tco2e, 0))} tCO2e of reduction; the levers plan "
            f"{_t(t.planned_reduction_tco2e)} tCO2e (probability of meeting the target: "
            f"{t.probability_meets_target:.0%})."
        )
    lines += [
        "",
        f"## Decarbonisation levers and their contributions in {d.target_year} (§34(f))",
        "",
        "| Lever | Scope 1+2 (tCO2e) | Share of planned Scope 1+2 | Scope 3 (tCO2e) | "
        "Share of planned Scope 3 |",
        "|---|--:|--:|--:|--:|",
    ]
    for lv in d.levers:
        lines.append(
            f"| {lv.name} | {_t(lv.scope12_tco2e)} | {_share(lv.share_of_scope12_reduction)} | "
            f"{_t(lv.scope3_tco2e)} | {_share(lv.share_of_scope3_reduction)} |"
        )
    lines += ["", "## Basis of preparation", ""] + [f"- {p}" for p in d.basis]
    lines += ["", "## Readiness checks", ""]
    lines += [f"- **{c.level.value}** ({c.code}): {c.message}" for c in d.checks]
    lines += [
        "",
        "_Generated by openscope. Paragraph references are to ESRS Set 1 (Delegated Regulation "
        "(EU) 2023/2772); check the version applicable to your reporting period._",
        "",
    ]
    return "\n".join(lines)


def to_csv(d: TargetDisclosure) -> str:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(["section", "boundary", "item", "year", "value", "unit", "reference"])
    for t in d.targets:
        w.writerow(["target", t.boundary, "base value", t.base_year, f"{t.base_tco2e:.3f}",
                    "tCO2e", "E1-4 §34(c)"])  # fmt: skip
        w.writerow(["target", t.boundary, "annual linear reduction rate", "",
                    f"{t.annual_rate * 100:.2f}", "%", "E1-4 §34(e)"])  # fmt: skip
        for m in t.milestones:
            w.writerow(["target", t.boundary, "target value", m.year, f"{m.target_tco2e:.3f}",
                        "tCO2e", "E1-4 §34(a),(d)"])  # fmt: skip
            w.writerow(["target", t.boundary, "reduction vs base year", m.year,
                        f"{m.reduction_vs_base * 100:.2f}", "%", "E1-4 §34(a)"])  # fmt: skip
            w.writerow(["target", t.boundary, "expected with planned levers", m.year,
                        f"{m.expected_tco2e:.3f}", "tCO2e", "E1-4 §34(f)"])  # fmt: skip
    for lv in d.levers:
        for boundary, v in (("Scope 1 and 2 (combined)", lv.scope12_tco2e),
                            ("Scope 3", lv.scope3_tco2e)):  # fmt: skip
            w.writerow(["lever", boundary, lv.name, d.target_year, f"{v:.3f}", "tCO2e",
                        "E1-4 §34(f)"])  # fmt: skip
    return buf.getvalue()


def to_json(d: TargetDisclosure) -> str:
    return json.dumps(d.as_dict(), indent=2)


__all__ = ["TargetDisclosure", "build", "to_csv", "to_json", "to_markdown"]
