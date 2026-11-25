"""Climate disclosure tables: ESRS E1-6 and IFRS S2 §29(a) GHG emissions.

What this module does
---------------------
It turns calculated inventories into the GHG emissions table each framework asks for, with
year-on-year and base-year comparison, GHG intensity per net revenue, a readiness check
(issues an assurance provider would raise) and a basis-of-preparation note generated from the
calculation metadata.

References (paragraph numbers, not XBRL element names)
------------------------------------------------------
* **ESRS E1** (Commission Delegated Regulation (EU) 2023/2772, "Set 1"), disclosure requirement
  E1-6 *Gross Scopes 1, 2, 3 and Total GHG emissions*: §44, §48 (Scope 1 and the share from
  regulated emission trading schemes), §49 (Scope 2 location- and market-based), §51 (Scope 3,
  significant categories), §52 (totals), §53-55 (GHG intensity per net revenue).
* **IFRS S2** *Climate-related Disclosures* §29(a): absolute gross Scope 1, 2 and 3 GHG
  emissions measured with the GHG Protocol Corporate Standard; Scope 2 location-based plus
  information on contractual instruments; the Scope 3 categories included.

The EU "Omnibus" simplification and EFRAG's simplified ESRS change parts of ESRS. Check the
version that applies to your reporting period. This module covers the emissions metrics only,
not targets (E1-4), transition plans (E1-1) or removals and credits (E1-7).
"""

from __future__ import annotations

import csv
import io
import json
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from enum import StrEnum

from openscope.inventory import Inventory
from openscope.models import (
    CalculationMethod,
    EmissionResult,
    Scope,
    Scope2Method,
    Scope3Category,
)


class Framework(StrEnum):
    ESRS = "esrs"
    ISSB = "issb"


class Level(StrEnum):
    BLOCKER = "blocker"  # would not survive assurance
    WARNING = "warning"  # needs action or explanation
    INFO = "info"  # disclose / explain


@dataclass
class Check:
    level: Level
    code: str
    message: str


@dataclass
class Row:
    key: str
    label: str
    reference: str
    unit: str
    current: float | None
    prior: float | None = None
    base: float | None = None
    indent: int = 0
    note: str = ""

    @property
    def change_vs_prior(self) -> float | None:
        if self.current is None or not self.prior:
            return None
        return (self.current - self.prior) / self.prior

    @property
    def change_vs_base(self) -> float | None:
        if self.current is None or not self.base:
            return None
        return (self.current - self.base) / self.base


@dataclass
class Period:
    """One inventory with its reporting year (current, prior year or base year)."""

    inventory: Inventory
    year: int | None
    gwp_set: str | None = None
    descriptions: dict[str, str] = field(default_factory=dict)


@dataclass
class Disclosure:
    framework: Framework
    title: str
    reporting_year: int | None
    prior_year: int | None
    base_year: int | None
    rows: list[Row]
    checks: list[Check]
    basis: list[str]
    revenue_currency: str | None

    @property
    def ready(self) -> bool:
        return not any(c.level == Level.BLOCKER for c in self.checks)

    def as_dict(self) -> dict[str, object]:
        rows = []
        for r in self.rows:
            d = asdict(r)
            d["change_vs_prior"] = r.change_vs_prior
            d["change_vs_base"] = r.change_vs_base
            rows.append(d)
        return {
            "framework": self.framework.value,
            "title": self.title,
            "reporting_year": self.reporting_year,
            "prior_year": self.prior_year,
            "base_year": self.base_year,
            "ready": self.ready,
            "rows": rows,
            "checks": [asdict(c) for c in self.checks],
            "basis": self.basis,
            "revenue_currency": self.revenue_currency,
        }


# -- metrics ---------------------------------------------------------------------------------
def _metrics(inv: Inventory, net_revenue: float | None) -> dict[str, float | None]:
    s1 = inv.scope1_t()
    s2l = inv.scope2_t(Scope2Method.LOCATION_BASED)
    s2m = inv.scope2_t(Scope2Method.MARKET_BASED)
    s3 = inv.scope3_t()
    total_l, total_m = s1 + s2l + s3, s1 + s2m + s3
    out: dict[str, float | None] = {
        "scope1": s1,
        "scope2_location": s2l,
        "scope2_market": s2m,
        "scope3": s3,
        "total_location": total_l,
        "total_market": total_m,
    }
    for cat, v in inv.scope3_by_category_t().items():
        out[f"scope3_cat_{int(cat)}"] = v
    if net_revenue:
        # tCO2e per million currency units, for readability
        out["intensity_location"] = total_l / net_revenue * 1e6
        out["intensity_market"] = total_m / net_revenue * 1e6
    return out


def _value(metrics: dict[str, float | None] | None, key: str) -> float | None:
    if metrics is None:
        return None
    return metrics.get(key, 0.0 if key.startswith("scope3_cat_") else None)


# -- checks and basis of preparation ----------------------------------------------------------
def _checks(
    framework: Framework,
    period: Period,
    *,
    errors: int,
    net_revenue: float | None,
    ets_share: float | None,
    prior: Period | None,
) -> list[Check]:
    inv = period.inventory
    checks: list[Check] = []
    share = inv.illustrative_share()
    if share > 0:
        checks.append(
            Check(
                Level.BLOCKER,
                "illustrative-factors",
                f"{share:.0%} of emissions use illustrative (placeholder) factors.",
            )
        )
    if errors:
        checks.append(
            Check(
                Level.BLOCKER,
                "calculation-errors",
                f"{errors} activity lines could not be calculated, so the totals are incomplete.",
            )
        )
    if period.gwp_set and period.gwp_set != "AR6":
        checks.append(
            Check(
                Level.WARNING,
                "gwp-version",
                f"Calculated with {period.gwp_set} GWPs. ESRS and IFRS S2 expect the latest "
                "IPCC 100-year GWPs (AR6); recalculate or explain the choice.",
            )
        )
    fallback = inv.scope2_market_fallback_sites()
    if fallback:
        checks.append(
            Check(
                Level.WARNING,
                "scope2-market-fallback",
                "Market-based Scope 2 uses grid-average factors for "
                f"{', '.join(fallback)} (no contractual instruments or residual mix).",
            )
        )
    if not any(r.scope == Scope.SCOPE_2 for r in inv.results):
        checks.append(Check(Level.WARNING, "no-scope2", "No Scope 2 emissions in the inventory."))
    present = set(inv.scope3_by_category_t())
    missing = [c for c in Scope3Category if c not in present]
    if missing:
        names = ", ".join(f"{int(c)}. {c.label}" for c in missing)
        checks.append(
            Check(
                Level.INFO,
                "scope3-categories",
                f"Scope 3 categories not reported: {names}. Explain why each is not significant "
                "or not applicable.",
            )
        )
    spend = sum(r.co2e_kg for r in inv.results if r.method == CalculationMethod.SPEND_BASED)
    total = sum(r.co2e_kg for r in inv.headline_results()) or 1.0
    if spend / total > 0.5:
        checks.append(
            Check(
                Level.INFO,
                "spend-based-share",
                f"{spend / total:.0%} of emissions are spend-based estimates; disclose the method "
                "and plan to replace them with supplier-specific data.",
            )
        )
    if net_revenue is None and framework == Framework.ESRS:
        checks.append(
            Check(
                Level.WARNING,
                "net-revenue",
                "Net revenue not provided, so GHG intensity (E1-6 §53) is not calculated.",
            )
        )
    if ets_share is None and framework == Framework.ESRS and inv.scope1_t() > 0:
        checks.append(
            Check(
                Level.INFO,
                "ets-share",
                "Share of Scope 1 from regulated emission trading schemes (E1-6 §48(b)) not "
                "provided; enter 0 % if no installation is covered.",
            )
        )
    if prior is None:
        checks.append(
            Check(
                Level.INFO,
                "comparatives",
                "No prior-year inventory selected; comparative figures are left blank.",
            )
        )
    checks.append(
        Check(
            Level.INFO,
            "biogenic-co2",
            "Biogenic CO2 from biomass combustion or biodegradation is reported separately from "
            "the scopes and is not calculated by openscope yet.",
        )
    )
    order = {Level.BLOCKER: 0, Level.WARNING: 1, Level.INFO: 2}
    return sorted(checks, key=lambda c: order[c.level])


def _basis(period: Period, framework: Framework) -> list[str]:
    inv = period.inventory
    results: Sequence[EmissionResult] = inv.headline_results()
    total = sum(r.co2e_kg for r in results) or 1.0
    by_source: dict[str, float] = defaultdict(float)
    methods: dict[str, float] = defaultdict(float)
    for r in results:
        by_source[r.factor_source] += r.co2e_kg
        methods[r.method.value.replace("_", "-")] += r.co2e_kg

    def share(v: float) -> str:
        return "<1%" if v / total < 0.005 else f"{v / total:.0%}"

    ranked = sorted(by_source.items(), key=lambda kv: -kv[1])
    sources = "; ".join(f"{s} ({share(v)})" for s, v in ranked)
    method_mix = ", ".join(
        f"{m} {share(v)}" for m, v in sorted(methods.items(), key=lambda kv: -kv[1])
    )
    dq = inv.data_quality()
    paras = [
        "Emissions are calculated with the GHG Protocol Corporate Standard, Scope 2 Guidance "
        "and Corporate Value Chain (Scope 3) Standard, using openscope. Every figure is traceable "
        "to activity data, an emission factor, unit conversion and GWP.",
        f"Global warming potentials: IPCC {period.gwp_set or 'as set per factor'} 100-year values.",
        f"Emission factor sources (share of emissions): {sources}.",
        f"Calculation methods (share of emissions): {method_mix}.",
        "Scope 2 is reported location-based and market-based. Market-based figures use "
        "contractual instruments where held"
        + (
            f"; grid-average factors are used for {', '.join(fallback)}."
            if (fallback := inv.scope2_market_fallback_sites())
            else "."
        ),
    ]
    if dq is not None:
        paras.append(
            f"Emissions-weighted data quality score: {dq:.1f} (1 = supplier-specific, "
            "5 = estimated)."
        )
    if framework == Framework.ISSB:
        paras.append(
            "IFRS S2 §29(a)(v): information about contractual instruments that inform the "
            "market-based Scope 2 figure is given in the Scope 2 rows."
        )
    return paras


# -- table assembly ----------------------------------------------------------------------------
def build(
    current: Period,
    *,
    framework: Framework | str = Framework.ESRS,
    prior: Period | None = None,
    base: Period | None = None,
    net_revenue: float | None = None,
    revenue_currency: str | None = None,
    ets_share: float | None = None,
    calculation_errors: int = 0,
) -> Disclosure:
    fw = Framework(framework)
    cur = _metrics(current.inventory, net_revenue)
    pri = _metrics(prior.inventory, None) if prior else None
    bas = _metrics(base.inventory, None) if base else None

    def row(key: str, label: str, ref: str, unit: str = "tCO2e", indent: int = 0) -> Row:
        return Row(key, label, ref, unit, _value(cur, key), _value(pri, key), _value(bas, key),
                   indent)  # fmt: skip

    rows: list[Row] = []
    if fw == Framework.ESRS:
        rows += [
            row("scope1", "Gross Scope 1 GHG emissions", "E1-6 §48(a)"),
            Row(
                "scope1_ets",
                "Percentage of Scope 1 from regulated emission trading schemes",
                "E1-6 §48(b)",
                "%",
                ets_share * 100 if ets_share is not None else None,
                indent=1,
            ),  # fmt: skip
            row("scope2_location", "Gross location-based Scope 2 GHG emissions", "E1-6 §49(a)"),
            row("scope2_market", "Gross market-based Scope 2 GHG emissions", "E1-6 §49(b)"),
            row("scope3", "Total gross indirect (Scope 3) GHG emissions", "E1-6 §51"),
        ]
    else:
        rows += [
            row("scope1", "Absolute gross Scope 1 GHG emissions", "IFRS S2 §29(a)(i)(1)"),
            row(
                "scope2_location",
                "Absolute gross Scope 2 GHG emissions (location-based)",
                "IFRS S2 §29(a)(i)(2), §29(a)(v)",
            ),  # fmt: skip
            row(
                "scope2_market",
                "Scope 2 GHG emissions (market-based, contractual instruments)",
                "IFRS S2 §29(a)(v)",
            ),  # fmt: skip
            row("scope3", "Absolute gross Scope 3 GHG emissions", "IFRS S2 §29(a)(i)(3)"),
        ]
    cats = sorted(
        {int(c) for c in current.inventory.scope3_by_category_t()}
        | ({int(k.rsplit("_", 1)[1]) for k in pri if k.startswith("scope3_cat_")} if pri else set())
    )
    cat_ref = "E1-6 §51, AR 46" if fw == Framework.ESRS else "IFRS S2 §29(a)(vi)"
    for c in cats:
        rows.append(row(f"scope3_cat_{c}", f"{c}. {Scope3Category(c).label}", cat_ref, indent=1))
    if fw == Framework.ESRS:
        rows += [
            row("total_location", "Total GHG emissions (location-based)", "E1-6 §52(a)"),
            row("total_market", "Total GHG emissions (market-based)", "E1-6 §52(b)"),
        ]
        unit = f"tCO2e per million {revenue_currency or 'currency units'} net revenue"
        rows += [
            Row(
                "intensity_location",
                "GHG intensity per net revenue (location-based)",
                "E1-6 §53",
                unit,
                cur.get("intensity_location"),
            ),  # fmt: skip
            Row(
                "intensity_market",
                "GHG intensity per net revenue (market-based)",
                "E1-6 §53",
                unit,
                cur.get("intensity_market"),
            ),  # fmt: skip
        ]
    else:
        rows.append(
            row("total_location", "Total Scope 1, 2 (location-based) and 3", "IFRS S2 §29(a)(i)")
        )

    title = (
        "ESRS E1-6 Gross Scopes 1, 2, 3 and Total GHG emissions"
        if fw == Framework.ESRS
        else "IFRS S2 §29(a) Greenhouse gas emissions"
    )
    return Disclosure(
        framework=fw,
        title=title,
        reporting_year=current.year,
        prior_year=prior.year if prior else None,
        base_year=base.year if base else None,
        rows=rows,
        checks=_checks(
            fw,
            current,
            errors=calculation_errors,
            net_revenue=net_revenue,
            ets_share=ets_share,
            prior=prior,
        ),  # fmt: skip
        basis=_basis(current, fw),
        revenue_currency=revenue_currency,
    )


# -- renderers ---------------------------------------------------------------------------------
def _num(v: float | None, unit: str = "") -> str:
    return "" if v is None else f"{v:,.1f}"


def _pct(v: float | None) -> str:
    return "" if v is None else f"{v:+.1%}"


def to_csv(d: Disclosure) -> str:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(["key", "metric", "reference", "unit", f"base year {d.base_year or ''}".strip(),
                f"N-1 {d.prior_year or ''}".strip(), f"N {d.reporting_year or ''}".strip(),
                "% N / N-1", "% N / base year"])  # fmt: skip
    for r in d.rows:
        w.writerow(
            [
                r.key,
                r.label,
                r.reference,
                r.unit,
                "" if r.base is None else round(r.base, 3),
                "" if r.prior is None else round(r.prior, 3),
                "" if r.current is None else round(r.current, 3),
                "" if r.change_vs_prior is None else round(r.change_vs_prior * 100, 2),
                "" if r.change_vs_base is None else round(r.change_vs_base * 100, 2),
            ]
        )
    return buf.getvalue()


def to_markdown(d: Disclosure) -> str:
    n, p, b = d.reporting_year or "N", d.prior_year or "N-1", d.base_year or "Base year"
    lines = [
        f"# {d.title}",
        "",
        f"| Metric | Reference | Unit | {b} | {p} | {n} | % N / N-1 | % N / base |",
        "|---|---|---|--:|--:|--:|--:|--:|",
    ]
    for r in d.rows:
        label = ("&nbsp;&nbsp;&nbsp;&nbsp;" * r.indent) + r.label
        lines.append(
            f"| {label} | {r.reference} | {r.unit} | {_num(r.base, r.unit)} | "
            f"{_num(r.prior, r.unit)} | {_num(r.current, r.unit)} | {_pct(r.change_vs_prior)} | "
            f"{_pct(r.change_vs_base)} |"
        )
    lines += ["", "## Basis of preparation", ""] + [f"- {p}" for p in d.basis]
    lines += ["", "## Readiness checks", ""]
    lines += [f"- **{c.level.value}** ({c.code}): {c.message}" for c in d.checks]
    lines += [
        "",
        "_Generated by openscope. Paragraph references are to ESRS Set 1 (Delegated Regulation "
        "(EU) 2023/2772) and IFRS S2; check the version applicable to your reporting period._",
        "",
    ]
    return "\n".join(lines)


def to_json(d: Disclosure) -> str:
    return json.dumps(d.as_dict(), indent=2)
