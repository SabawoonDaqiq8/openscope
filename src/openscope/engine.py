"""The calculation engine: activity x factor -> traceable emission result."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field

from openscope import quality, units
from openscope.errors import FactorError, OpenScopeError
from openscope.factors import FactorRegistry
from openscope.gwp import GWPSet, gwp
from openscope.models import (
    ActivityRecord,
    CalculationMethod,
    EmissionFactor,
    EmissionResult,
    FactorStatus,
    Scope,
    Scope2Method,
    Scope3Category,
)
from openscope.money import SpendNormalisationError, SpendNormaliser


def _is_currency(unit: str) -> bool:
    return units.get_unit(unit).dimension.startswith("currency:")


def _fmt(x: float) -> str:
    return f"{x:,.6g}"


def cat3_kind(factor: EmissionFactor) -> tuple[str, str]:
    """Short code and label of a Category 3 upstream factor, from its name."""
    name = factor.name.lower()
    wtt = name.startswith("wtt") or "well-to-tank" in name
    losses = "t&d" in name or "transmission" in name or "distribution" in name
    if wtt and losses:
        return "WTT-T&D", "upstream emissions of energy lost in transmission and distribution"
    if losses:
        return "T&D", "transmission and distribution losses"
    return "WTT", "well-to-tank (upstream extraction, processing and transport of the energy)"


@dataclass
class CalculationError:
    activity_id: str
    message: str


@dataclass
class BatchResult:
    results: list[EmissionResult] = field(default_factory=list)
    errors: list[CalculationError] = field(default_factory=list)
    # Category 3 activities derived from Scope 1/2 lines (see ``Calculator.derive_cat3``)
    derived: list[ActivityRecord] = field(default_factory=list)
    # upstream factors not derived because a Category 3 line already uses them
    cat3_skipped: list[str] = field(default_factory=list)

    def activities(self, given: Iterable[ActivityRecord]) -> dict[str, ActivityRecord]:
        """Every activity behind the results, by id: the ones given plus the derived ones."""
        return {a.activity_id: a for a in (*given, *self.derived)}

    @property
    def ok(self) -> bool:
        return not self.errors


class Calculator:
    """Applies emission factors to activity data.

    Parameters
    ----------
    registry:
        Where factors are resolved from when an activity references a ``factor_id``.
    gwp_set:
        IPCC assessment report used to convert per-gas results to CO2e.
    reporting_year:
        Used for the temporal-representativeness penalty in data-quality scoring.
    spend_normaliser:
        FX rates and price indices for adapting spend to a spend-based factor's currency
        and price year. Without it, currency mismatches are errors and price-year
        mismatches produce a warning.
    derive_cat3:
        Add Scope 3 Category 3 lines (well-to-tank, transmission and distribution losses) for
        each Scope 1/2 line whose factor links upstream factors (``cat3_factor_ids``).
    """

    def __init__(
        self,
        registry: FactorRegistry | None = None,
        gwp_set: GWPSet | str = GWPSet.AR6,
        reporting_year: int | None = None,
        spend_normaliser: SpendNormaliser | None = None,
        derive_cat3: bool = False,
    ) -> None:
        self.registry = registry if registry is not None else FactorRegistry.bundled()
        self.gwp_set = GWPSet(gwp_set)
        self.reporting_year = reporting_year
        self.spend_normaliser = spend_normaliser
        self.derive_cat3 = derive_cat3

    def calculate(
        self, activity: ActivityRecord, factor: EmissionFactor | None = None
    ) -> EmissionResult:
        if factor is None:
            if not activity.factor_id:
                raise FactorError(f"Activity {activity.activity_id} has no factor_id")
            factor = self.registry.get(activity.factor_id)

        trace: list[str] = [
            f"Factor {factor.factor_id} — {factor.name} [{factor.source}"
            f"{', ' + str(factor.year) if factor.year else ''}; {factor.status.value}]"
        ]

        scope2_method = self._resolve_scope2_method(activity, factor)
        self._check_applicability(activity, factor, trace)

        if _is_currency(activity.unit) and _is_currency(factor.activity_unit):
            qty = self._normalise_spend(activity, factor, trace)
        else:
            qty = units.convert(activity.quantity, activity.unit, factor.activity_unit)
        if activity.unit != factor.activity_unit and not _is_currency(activity.unit):
            trace.append(
                f"Converted {_fmt(activity.quantity)} {activity.unit} "
                f"→ {_fmt(qty)} {factor.activity_unit}"
            )

        gas_kg: dict[str, float] = {}
        if factor.gases:
            co2e = 0.0
            for gas, per_unit in factor.gases.items():
                mass = qty * per_unit
                g = gwp(gas, self.gwp_set)
                gas_kg[gas] = mass
                co2e += mass * g
                trace.append(
                    f"{gas}: {_fmt(qty)} × {_fmt(per_unit)} kg/{factor.activity_unit} "
                    f"= {_fmt(mass)} kg × GWP {g:g} ({self.gwp_set.value}) "
                    f"= {_fmt(mass * g)} kg CO2e"
                )
        else:
            assert factor.co2e_kg is not None  # guaranteed by model validation
            co2e = qty * factor.co2e_kg
            gas_kg["CO2e"] = co2e
            basis = factor.gwp_basis or "unspecified"
            trace.append(
                f"CO2e: {_fmt(qty)} × {_fmt(factor.co2e_kg)} kg CO2e/{factor.activity_unit} "
                f"= {_fmt(co2e)} kg CO2e (pre-aggregated factor; GWP basis {basis})"
            )
            if factor.gwp_basis and factor.gwp_basis != self.gwp_set.value and co2e > 0:
                trace.append(
                    f"WARNING: factor GWP basis {factor.gwp_basis} differs from inventory "
                    f"GWP set {self.gwp_set.value}; disclose or replace with per-gas factor"
                )

        energy_kwh = biogenic = None
        if factor.energy_kwh_per_unit is not None:
            energy_kwh = qty * factor.energy_kwh_per_unit
            src = factor.energy_source.value.replace("_", " ") if factor.energy_source else "energy"
            trace.append(
                f"Energy: {_fmt(qty)} × {_fmt(factor.energy_kwh_per_unit)} kWh/"
                f"{factor.activity_unit} = {_fmt(energy_kwh)} kWh ({src})"
            )
        if (mix := factor.supply_mix) is not None:
            trace.append(
                f"Generation mix behind the factor: fossil {mix[0]:.1%}, nuclear {mix[1]:.1%}, "
                f"renewable {mix[2]:.1%}"
            )
        if factor.biogenic_co2_kg:
            biogenic = qty * factor.biogenic_co2_kg
            trace.append(
                f"Biogenic CO2 (outside the scopes, not in the total): {_fmt(qty)} × "
                f"{_fmt(factor.biogenic_co2_kg)} kg/{factor.activity_unit} = {_fmt(biogenic)} kg"
            )

        dq = quality.score(activity.method, factor, self.reporting_year)
        trace.append(f"Total: {_fmt(co2e)} kg CO2e; data quality {dq}/5 ({activity.method.value})")

        return EmissionResult(
            activity_id=activity.activity_id,
            scope=activity.scope,
            scope3_category=activity.scope3_category,
            scope2_method=scope2_method,
            method=activity.method,
            site=activity.site,
            factor_id=factor.factor_id,
            factor_source=factor.source,
            factor_status=factor.status,
            gwp_set=self.gwp_set.value,
            quantity=activity.quantity,
            unit=activity.unit,
            converted_quantity=qty,
            factor_unit=factor.activity_unit,
            gas_kg=gas_kg,
            co2e_kg=co2e,
            data_quality_score=dq,
            trace=trace,
            energy_kwh=energy_kwh,
            energy_source=factor.energy_source,
            biogenic_co2_kg=biogenic,
            supply_mix=factor.supply_mix,
        )

    def calculate_many(self, activities: Iterable[ActivityRecord]) -> BatchResult:
        """Calculate a batch; failures are collected rather than aborting the run."""
        acts = list(activities)
        batch = BatchResult()
        for a in acts:
            try:
                batch.results.append(self.calculate(a))
            except OpenScopeError as exc:
                batch.errors.append(CalculationError(a.activity_id, str(exc)))
        if self.derive_cat3:
            self._derive_cat3(acts, batch)
        return batch

    def _derive_cat3(self, activities: list[ActivityRecord], batch: BatchResult) -> None:
        """Scope 3 Category 3 lines from Scope 1 fuels and Scope 2 electricity and heat.

        Purchased electricity is counted once per site: location-based lines, or market-based
        lines where the site has no location-based line. An upstream factor that a Category 3
        line in the input already uses is not derived again, so nothing is counted twice.
        """
        manual = {
            a.factor_id
            for a in activities
            if a.scope3_category == Scope3Category.FUEL_AND_ENERGY_RELATED and a.factor_id
        }
        lb_sites = {
            r.site
            for r in batch.results
            if r.scope == Scope.SCOPE_2 and r.scope2_method == Scope2Method.LOCATION_BASED
        }
        by_id = {a.activity_id: a for a in activities}
        for r in list(batch.results):
            if r.scope == Scope.SCOPE_3 or r.factor_id not in self.registry:
                continue
            if r.scope2_method == Scope2Method.MARKET_BASED and r.site in lb_sites:
                continue
            source = by_id[r.activity_id]
            for fid in self.registry.get(r.factor_id).cat3_factor_ids:
                if fid in manual:
                    batch.cat3_skipped.append(f"{source.activity_id}: {fid}")
                    continue
                if fid not in self.registry:
                    continue
                upstream = self.registry.get(fid)
                code, label = cat3_kind(upstream)
                derived = ActivityRecord(
                    activity_id=f"{source.activity_id}:{code}",
                    description=f"{source.description or source.activity_id}: {label}",
                    quantity=source.quantity,
                    unit=source.unit,
                    scope=Scope.SCOPE_3,
                    scope3_category=Scope3Category.FUEL_AND_ENERGY_RELATED,
                    factor_id=fid,
                    method=source.method
                    if source.method != CalculationMethod.SUPPLIER_SPECIFIC
                    else CalculationMethod.AVERAGE_DATA,
                    period_start=source.period_start,
                    period_end=source.period_end,
                    site=source.site,
                    supplier=source.supplier,
                )
                try:
                    result = self.calculate(derived, upstream)
                except OpenScopeError as exc:
                    batch.errors.append(CalculationError(derived.activity_id, str(exc)))
                    continue
                note = (
                    f"Derived from Scope {int(r.scope)} activity {source.activity_id}: "
                    f"Scope 3 Category 3, {label}"
                )
                batch.derived.append(derived)
                batch.results.append(
                    result.model_copy(
                        update={"trace": [note, *result.trace], "derived_from": source.activity_id}
                    )
                )

    def _normalise_spend(
        self, activity: ActivityRecord, factor: EmissionFactor, trace: list[str]
    ) -> float:
        spend_ccy = units.get_unit(activity.unit).symbol
        factor_ccy = units.get_unit(factor.activity_unit).symbol
        spend_year, factor_year = activity.spend_year, factor.year
        same_ccy = spend_ccy == factor_ccy
        same_year = spend_year is None or factor_year is None or spend_year == factor_year

        if same_ccy and same_year:
            return activity.quantity
        if self.spend_normaliser is None:
            if not same_ccy:
                raise SpendNormalisationError(
                    f"Activity {activity.activity_id} is in {spend_ccy} but factor "
                    f"{factor.factor_id} is per {factor_ccy}; provide exchange rates"
                )
            trace.append(
                f"WARNING: spend year {spend_year} differs from factor price year "
                f"{factor_year}; no price index supplied, so inflation is not removed"
            )
            return activity.quantity
        if spend_year is None or factor_year is None:
            raise SpendNormalisationError(
                f"Activity {activity.activity_id}: spend year and factor price year are "
                "both needed to normalise spend (set price_year or period dates)"
            )
        qty, steps = self.spend_normaliser.normalise(
            activity.quantity, spend_ccy, spend_year, factor_ccy, factor_year
        )
        trace.extend(steps)
        return qty

    # -- validation helpers ------------------------------------------------------
    @staticmethod
    def _resolve_scope2_method(
        activity: ActivityRecord, factor: EmissionFactor
    ) -> Scope2Method | None:
        if activity.scope != Scope.SCOPE_2:
            return None
        method = activity.scope2_method or factor.scope2_method or Scope2Method.LOCATION_BASED
        if factor.scope2_method and factor.scope2_method != method:
            raise FactorError(
                f"Activity {activity.activity_id} is {method.value} but factor "
                f"{factor.factor_id} is {factor.scope2_method.value}"
            )
        return method

    @staticmethod
    def _check_applicability(
        activity: ActivityRecord, factor: EmissionFactor, trace: list[str]
    ) -> None:
        both_currency = _is_currency(activity.unit) and _is_currency(factor.activity_unit)
        if not both_currency and not units.is_compatible(activity.unit, factor.activity_unit):
            raise FactorError(
                f"Activity {activity.activity_id} unit '{activity.unit}' is incompatible with "
                f"factor {factor.factor_id} unit '{factor.activity_unit}'"
            )
        if factor.scope is not None and factor.scope != activity.scope:
            # Legitimate in some cases (e.g. a fuel factor reused for Scope 3 cat. 6 rentals).
            trace.append(
                f"WARNING: factor is tagged Scope {factor.scope.value}, "
                f"activity is Scope {activity.scope.value}"
            )
        if (
            factor.scope3_category is not None
            and activity.scope3_category is not None
            and factor.scope3_category != activity.scope3_category
        ):
            trace.append(
                f"WARNING: factor is tagged category {factor.scope3_category.value}, "
                f"activity is category {activity.scope3_category.value}"
            )
        if factor.status == FactorStatus.ILLUSTRATIVE:
            trace.append("WARNING: illustrative factor — not suitable for disclosure")
