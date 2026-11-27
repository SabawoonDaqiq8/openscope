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

from openscope.energy import GridMix, biogenic_t, energy_mix
from openscope.inventory import Inventory
from openscope.models import (
    CalculationMethod,
    EmissionResult,
    EnergySource,
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
    section: str = "E1-6"

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
def _metrics(
    inv: Inventory, net_revenue: float | None, grid_mix: GridMix | None = None
) -> dict[str, float | None]:
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
        "biogenic_scope1": biogenic_t(inv, Scope.SCOPE_1),
        "biogenic_scope2": biogenic_t(inv, Scope.SCOPE_2),
        "biogenic_scope3": biogenic_t(inv, Scope.SCOPE_3),
    }
    for cat, v in inv.scope3_by_category_t().items():
        out[f"scope3_cat_{int(cat)}"] = v
    m = energy_mix(inv, grid_mix)
    out |= {
        "energy_fossil": m.fossil,
        "energy_fossil_fuels": m.fossil_fuels,
        "energy_nuclear": m.nuclear,
        "energy_renewable": m.renewable,
        "energy_renewable_fuels": m.renewable_fuels,
        "energy_renewable_purchased": m.renewable_purchased,
        "energy_self_generated": None,
        "energy_undetermined": m.undetermined,
        "energy_total": m.total,
        "energy_renewable_share": m.renewable / m.total * 100 if m.total else None,
    }
    if net_revenue:
        # per million currency units, for readability
        out["intensity_location"] = total_l / net_revenue * 1e6
        out["intensity_market"] = total_m / net_revenue * 1e6
        out["energy_intensity"] = m.total / net_revenue * 1e6
    return out


def _value(metrics: dict[str, float | None] | None, key: str) -> float | None:
    if metrics is None:
        return None
    return metrics.get(key, 0.0 if key.startswith("scope3_cat_") else None)


# -- checks and basis of preparation ----------------------------------------------------------
def _cat3_checks(inv: Inventory) -> list[Check]:
    cat3 = [r for r in inv.results if r.scope3_category == Scope3Category.FUEL_AND_ENERGY_RELATED]
    derived = [r for r in cat3 if r.derived_from]
    energy = [
        r
        for r in inv.results
        if r.scope != Scope.SCOPE_3 and r.energy_source not in (None, EnergySource.NON_ENERGY)
    ]
    if derived:
        t = sum(r.co2e_kg for r in derived) / 1000
        sources = len({r.derived_from for r in derived})
        return [
            Check(
                Level.INFO,
                "cat3-derived",
                f"{len(derived)} Scope 3 Category 3 lines ({t:,.1f} tCO2e) were derived from "
                f"{sources} Scope 1/2 lines: well-to-tank emissions of fuels and electricity, "
                "and transmission and distribution losses. Each line's trace names its source.",
            )
        ]
    if energy and not cat3:
        return [
            Check(
                Level.WARNING,
                "cat3-missing",
                "The inventory has Scope 1/2 fuel and energy lines but no Scope 3 Category 3 "
                "(fuel- and energy-related activities). Recalculate with Category 3 derivation "
                "on, or add well-to-tank and transmission-loss lines.",
            )
        ]
    return []


def _checks(
    framework: Framework,
    period: Period,
    *,
    errors: int,
    net_revenue: float | None,
    ets_share: float | None,
    prior: Period | None,
    grid_mix: GridMix | None = None,
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
    checks.extend(_cat3_checks(inv))
    biogenic = sum(biogenic_t(inv, s) for s in Scope)
    checks.append(
        Check(
            Level.INFO,
            "biogenic-co2",
            f"Biogenic CO2 of {biogenic:,.1f} t is reported outside the scopes. It is calculated "
            "only where the factor dataset publishes it (DESNZ outside-of-scopes factors)."
            if biogenic
            else "No biogenic CO2 found: none of the factors used publish a biogenic CO2 "
            "component. Check whether biomass or biofuels are used.",
        )
    )
    if framework == Framework.ESRS:
        m = energy_mix(inv, grid_mix)
        if m.electricity_undetermined > 0.0005:
            checks.append(
                Check(
                    Level.WARNING,
                    "energy-mix",
                    f"{m.electricity_undetermined:,.0f} MWh of purchased electricity is not "
                    "covered by renewable certificates and has no fossil / nuclear / renewable "
                    "split, which E1-5 §37 requires. Use electricity factors that publish their "
                    "generation mix (e.g. AIB residual mixes) or enter the supplier or grid mix.",
                )
            )
        if m.mix_basis:
            used = "; ".join(f"{b}: {v:,.0f} MWh" for b, v in m.mix_basis.items())
            checks.append(
                Check(
                    Level.INFO,
                    "energy-mix-basis",
                    f"Purchased electricity without certificates is split into fossil, nuclear "
                    f"and renewable using {used}.",
                )
            )
        if m.heat:
            checks.append(
                Check(
                    Level.WARNING,
                    "energy-heat-mix",
                    f"{m.heat:,.0f} MWh of purchased heat, steam or cooling has an undetermined "
                    "source mix; obtain it from the supplier.",
                )
            )
        if m.lines_without_energy:
            checks.append(
                Check(
                    Level.WARNING,
                    "energy-incomplete",
                    f"{m.lines_without_energy} Scope 1/2 energy lines use factors without an "
                    "energy content, so E1-5 totals are incomplete.",
                )
            )
        checks.append(
            Check(
                Level.INFO,
                "self-generated-renewables",
                "Self-generated non-fuel renewable energy (E1-5 §37(c)(iii), e.g. on-site solar) "
                "is not tracked; add it if applicable.",
            )
        )
    order = {Level.BLOCKER: 0, Level.WARNING: 1, Level.INFO: 2}
    return sorted(checks, key=lambda c: order[c.level])


def _basis(period: Period, framework: Framework, period_grid: bool = False) -> list[str]:
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
    if framework == Framework.ESRS:
        paras.append(
            "Energy consumption (E1-5) covers own operations (Scope 1 fuels, Scope 2 purchased "
            "electricity and heat) using net calorific values derived from the emission factor "
            "dataset. Purchased electricity is counted once per site; the renewable share counts "
            "electricity backed by energy attribute certificates. Other purchased electricity is "
            "split using the generation mix published with the market-based factor (a residual "
            "mix)"
            + (", then the stated supplier or grid mix" if period_grid else "")
            + ", then the mix published with the location-based factor (a production mix); "
            "any remainder is reported as undetermined."
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
    grid_mix: GridMix | None = None,
) -> Disclosure:
    fw = Framework(framework)
    cur = _metrics(current.inventory, net_revenue, grid_mix)
    pri = _metrics(prior.inventory, None, grid_mix) if prior else None
    bas = _metrics(base.inventory, None, grid_mix) if base else None

    def row(
        key: str,
        label: str,
        ref: str,
        unit: str = "tCO2e",
        indent: int = 0,
        section: str = "E1-6",
    ) -> Row:
        return Row(key, label, ref, unit, _value(cur, key), _value(pri, key), _value(bas, key),
                   indent, section=section)  # fmt: skip

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
        rows += [
            Row(
                "biogenic",
                "Biogenic CO2 emissions (outside the scopes)",
                "E1-6 AR 43, 45, 46",
                "tCO2",
                sum(v or 0 for k, v in cur.items() if k.startswith("biogenic_")),
                None
                if pri is None
                else sum(v or 0 for k, v in pri.items() if k.startswith("biogenic_")),
                None
                if bas is None
                else sum(v or 0 for k, v in bas.items() if k.startswith("biogenic_")),
            ),  # fmt: skip
            row(
                "biogenic_scope1",
                "from Scope 1 sources (e.g. biofuel blends)",
                "E1-6 AR 43",
                "tCO2",
                indent=1,
            ),  # fmt: skip
            row(
                "biogenic_scope2",
                "from purchased electricity (location-based)",
                "E1-6 AR 45",
                "tCO2",
                indent=1,
            ),  # fmt: skip
            row("biogenic_scope3", "from Scope 3 sources", "E1-6 AR 46", "tCO2", indent=1),
        ]
        e = "E1-5"
        rows += [
            row(
                "energy_fossil", "Total fossil energy consumption", "E1-5 §37(a)", "MWh", section=e
            ),  # fmt: skip
            row(
                "energy_fossil_fuels",
                "of which fossil fuels (own combustion)",
                "E1-5 §37(a)",
                "MWh",
                indent=1,
                section=e,
            ),
            row(
                "energy_nuclear",
                "Consumption from nuclear sources",
                "E1-5 §37(b)",
                "MWh",
                section=e,
            ),  # fmt: skip
            row(
                "energy_renewable",
                "Total renewable energy consumption",
                "E1-5 §37(c)",
                "MWh",
                section=e,
            ),  # fmt: skip
            row(
                "energy_renewable_fuels",
                "Fuel consumption from renewable sources, incl. biomass",
                "E1-5 §37(c)(i)",
                "MWh",
                indent=1,
                section=e,
            ),  # fmt: skip
            row(
                "energy_renewable_purchased",
                "Purchased electricity, heat, steam and cooling from renewable sources",
                "E1-5 §37(c)(ii)",
                "MWh",
                indent=1,
                section=e,
            ),  # fmt: skip
            row(
                "energy_self_generated",
                "Self-generated non-fuel renewable energy",
                "E1-5 §37(c)(iii)",
                "MWh",
                indent=1,
                section=e,
            ),  # fmt: skip
        ]
        if (cur.get("energy_undetermined") or 0) > 0:
            rows.append(
                row(
                    "energy_undetermined",
                    "Purchased energy with undetermined source mix",
                    "see readiness checks",
                    "MWh",
                    section=e,
                )  # fmt: skip
            )
        revenue_unit = f"MWh per million {revenue_currency or 'currency units'} net revenue"
        rows += [
            row("energy_total", "Total energy consumption", "E1-5 §37, AR 34", "MWh", section=e),
            row(
                "energy_renewable_share",
                "Share of renewable sources in total energy consumption",
                "E1-5 AR 34",
                "%",
                section=e,
            ),  # fmt: skip
            Row(
                "energy_intensity",
                "Energy intensity per net revenue (high climate impact sectors)",
                "E1-5 §40",
                revenue_unit,
                cur.get("energy_intensity"),
                section=e,
            ),  # fmt: skip
        ]
    else:
        rows.append(
            row("total_location", "Total Scope 1, 2 (location-based) and 3", "IFRS S2 §29(a)(i)")
        )

    if fw == Framework.ISSB:
        for r in rows:
            r.section = "S2"
    title = (
        "ESRS E1 Climate change: GHG emissions (E1-6) and energy (E1-5)"
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
            grid_mix=grid_mix,
        ),  # fmt: skip
        basis=_basis(current, fw, period_grid=grid_mix is not None),
        revenue_currency=revenue_currency,
    )


# -- renderers ---------------------------------------------------------------------------------
SECTION_TITLES = {
    "E1-6": "E1-6 Gross Scopes 1, 2, 3 and total GHG emissions",
    "E1-5": "E1-5 Energy consumption and mix",
    "S2": "IFRS S2 §29(a) Greenhouse gas emissions",
}


def _num(v: float | None, unit: str = "") -> str:
    return "" if v is None else f"{v:,.1f}"


def _pct(v: float | None) -> str:
    return "" if v is None else f"{v:+.1%}"


def to_csv(d: Disclosure) -> str:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(
        ["section", "key", "metric", "reference", "unit", f"base year {d.base_year or ''}".strip(),
         f"N-1 {d.prior_year or ''}".strip(), f"N {d.reporting_year or ''}".strip(),
         "% N / N-1", "% N / base year"]
    )  # fmt: skip
    for r in d.rows:
        w.writerow(
            [
                r.section,
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
    lines = [f"# {d.title}"]
    section = None
    for r in d.rows:
        if r.section != section:
            section = r.section
            lines += [
                "",
                f"## {SECTION_TITLES.get(section, section)}",
                "",
                f"| Metric | Reference | Unit | {b} | {p} | {n} | % N / N-1 | % N / base |",
                "|---|---|---|--:|--:|--:|--:|--:|",
            ]
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
