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
    EmissionFactor,
    EmissionResult,
    FactorStatus,
    Scope,
    Scope2Method,
)


def _fmt(x: float) -> str:
    return f"{x:,.6g}"


@dataclass
class CalculationError:
    activity_id: str
    message: str


@dataclass
class BatchResult:
    results: list[EmissionResult] = field(default_factory=list)
    errors: list[CalculationError] = field(default_factory=list)

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
    """

    def __init__(
        self,
        registry: FactorRegistry | None = None,
        gwp_set: GWPSet | str = GWPSet.AR6,
        reporting_year: int | None = None,
    ) -> None:
        self.registry = registry if registry is not None else FactorRegistry.bundled()
        self.gwp_set = GWPSet(gwp_set)
        self.reporting_year = reporting_year

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

        qty = units.convert(activity.quantity, activity.unit, factor.activity_unit)
        if activity.unit != factor.activity_unit:
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
            trace.append(
                f"CO2e: {_fmt(qty)} × {_fmt(factor.co2e_kg)} kg CO2e/{factor.activity_unit} "
                f"= {_fmt(co2e)} kg CO2e (pre-aggregated factor; GWP set fixed by source)"
            )

        dq = quality.score(activity.method, factor, self.reporting_year)
        trace.append(f"Total: {_fmt(co2e)} kg CO2e; data quality {dq}/5 ({activity.method.value})")

        return EmissionResult(
            activity_id=activity.activity_id,
            scope=activity.scope,
            scope3_category=activity.scope3_category,
            scope2_method=scope2_method,
            method=activity.method,
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
        )

    def calculate_many(self, activities: Iterable[ActivityRecord]) -> BatchResult:
        """Calculate a batch; failures are collected rather than aborting the run."""
        batch = BatchResult()
        for a in activities:
            try:
                batch.results.append(self.calculate(a))
            except OpenScopeError as exc:
                batch.errors.append(CalculationError(a.activity_id, str(exc)))
        return batch

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
        if not units.is_compatible(activity.unit, factor.activity_unit):
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
