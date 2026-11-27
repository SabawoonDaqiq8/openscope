"""Core domain models.

The design principle is *traceability*: every :class:`EmissionResult` carries the
exact factor, unit conversion, GWP set and arithmetic that produced it, so any
number in a report can be traced back to its inputs by an auditor.
"""

from __future__ import annotations

from datetime import date
from enum import IntEnum, StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Scope(IntEnum):
    SCOPE_1 = 1
    SCOPE_2 = 2
    SCOPE_3 = 3


class Scope3Category(IntEnum):
    """The 15 categories of the GHG Protocol Corporate Value Chain (Scope 3) Standard."""

    PURCHASED_GOODS_AND_SERVICES = 1
    CAPITAL_GOODS = 2
    FUEL_AND_ENERGY_RELATED = 3
    UPSTREAM_TRANSPORTATION = 4
    WASTE = 5
    BUSINESS_TRAVEL = 6
    EMPLOYEE_COMMUTING = 7
    UPSTREAM_LEASED_ASSETS = 8
    DOWNSTREAM_TRANSPORTATION = 9
    PROCESSING_OF_SOLD_PRODUCTS = 10
    USE_OF_SOLD_PRODUCTS = 11
    END_OF_LIFE_OF_SOLD_PRODUCTS = 12
    DOWNSTREAM_LEASED_ASSETS = 13
    FRANCHISES = 14
    INVESTMENTS = 15

    @property
    def label(self) -> str:
        return _SCOPE3_LABELS[self.value]


_SCOPE3_LABELS = {
    1: "Purchased goods and services",
    2: "Capital goods",
    3: "Fuel- and energy-related activities",
    4: "Upstream transportation and distribution",
    5: "Waste generated in operations",
    6: "Business travel",
    7: "Employee commuting",
    8: "Upstream leased assets",
    9: "Downstream transportation and distribution",
    10: "Processing of sold products",
    11: "Use of sold products",
    12: "End-of-life treatment of sold products",
    13: "Downstream leased assets",
    14: "Franchises",
    15: "Investments",
}


class CalculationMethod(StrEnum):
    """How the activity data was obtained, from most to least specific.

    Ordered to align with the data-quality hierarchy used in the GHG Protocol
    Scope 3 guidance and PCAF (1 = best, 5 = worst).
    """

    SUPPLIER_SPECIFIC = "supplier_specific"  # primary data from the supplier (e.g. product PCF)
    HYBRID = "hybrid"  # supplier scope 1&2 allocated + secondary data for upstream
    AVERAGE_DATA = "average_data"  # physical activity data x secondary (average) factor
    SPEND_BASED = "spend_based"  # financial data x EEIO factor
    ESTIMATED = "estimated"  # proxies, extrapolation, assumptions


class Scope2Method(StrEnum):
    LOCATION_BASED = "location_based"
    MARKET_BASED = "market_based"


class FactorStatus(StrEnum):
    REFERENCE = "reference"  # transcribed from a published source, cite & verify version
    ILLUSTRATIVE = "illustrative"  # placeholder for demos/tests — never for real reporting
    CUSTOM = "custom"  # supplied by the user (e.g. supplier-specific)


class EnergySource(StrEnum):
    """What an activity's energy is, for ESRS E1-5 energy consumption and mix."""

    FOSSIL_FUEL = "fossil_fuel"
    RENEWABLE_FUEL = "renewable_fuel"  # biofuels, biogas, biomass
    ELECTRICITY = "electricity"  # purchased grid electricity, source mix not known
    RENEWABLE_ELECTRICITY = "renewable_electricity"  # backed by energy attribute certificates
    HEAT = "heat"  # purchased heat, steam or cooling
    NON_ENERGY = "non_energy"  # refrigerant leaks, process emissions: no energy consumed


class EmissionFactor(BaseModel):
    """An emission factor expressed per one ``activity_unit``.

    Either per-gas values (``gases``, in kg of gas per unit) or a pre-aggregated
    ``co2e_kg`` may be given. Per-gas factors are preferred because they allow
    re-calculation under a different GWP set.
    """

    model_config = ConfigDict(frozen=True)

    factor_id: str
    name: str
    activity_unit: str
    gases: dict[str, float] = Field(default_factory=dict)
    co2e_kg: float | None = None
    gwp_basis: str | None = None  # GWP set behind a pre-aggregated co2e_kg, e.g. "AR5"
    scope: Scope | None = None
    scope3_category: Scope3Category | None = None
    scope2_method: Scope2Method | None = None
    region: str = "GLOBAL"
    year: int | None = None
    source: str
    source_url: str | None = None
    status: FactorStatus = FactorStatus.REFERENCE
    notes: str | None = None
    # energy content per activity unit (kWh, net calorific value) and its source, for E1-5
    energy_kwh_per_unit: float | None = Field(default=None, ge=0)
    energy_source: EnergySource | None = None
    # biogenic CO2 per activity unit (kg), reported outside the scopes
    biogenic_co2_kg: float | None = Field(default=None, ge=0)
    # for electricity factors: the generation mix behind the factor (shares summing to 1), e.g.
    # a national residual mix. Used to split purchased electricity in ESRS E1-5.
    fossil_share: float | None = Field(default=None, ge=0, le=1)
    nuclear_share: float | None = Field(default=None, ge=0, le=1)
    renewable_share: float | None = Field(default=None, ge=0, le=1)
    # upstream factors for Scope 3 Category 3 (fuel- and energy-related activities), applied to
    # the same activity quantity: well-to-tank, transmission and distribution losses
    cat3_factor_ids: tuple[str, ...] = ()

    @model_validator(mode="after")
    def _has_values(self) -> EmissionFactor:
        if not self.gases and self.co2e_kg is None:
            raise ValueError(f"Factor {self.factor_id} needs per-gas values or co2e_kg")
        if any(v < 0 for v in self.gases.values()) or (self.co2e_kg or 0) < 0:
            raise ValueError(f"Factor {self.factor_id} has negative values")
        shares = (self.fossil_share, self.nuclear_share, self.renewable_share)
        if any(v is not None for v in shares):
            if any(v is None for v in shares):
                raise ValueError(
                    f"Factor {self.factor_id}: give all of fossil, nuclear and renewable shares"
                )
            if abs(sum(v for v in shares if v is not None) - 1) > 0.005:
                raise ValueError(f"Factor {self.factor_id}: generation mix shares must sum to 1")
        return self

    @property
    def supply_mix(self) -> tuple[float, float, float] | None:
        """(fossil, nuclear, renewable) shares of the generation behind the factor, if known."""
        if self.fossil_share is None or self.nuclear_share is None or self.renewable_share is None:
            return None
        return (self.fossil_share, self.nuclear_share, self.renewable_share)


class ActivityRecord(BaseModel):
    """One line of activity data: a fuel bill, a meter reading, a ledger line…"""

    activity_id: str
    description: str = ""
    quantity: float = Field(ge=0)
    unit: str
    scope: Scope
    scope3_category: Scope3Category | None = None
    scope2_method: Scope2Method | None = None
    factor_id: str | None = None
    method: CalculationMethod = CalculationMethod.AVERAGE_DATA
    period_start: date | None = None
    period_end: date | None = None
    price_year: int | None = None  # year the spend was incurred; defaults to the period's year
    site: str | None = None
    supplier: str | None = None

    @model_validator(mode="after")
    def _category_consistency(self) -> ActivityRecord:
        if self.scope == Scope.SCOPE_3 and self.scope3_category is None:
            raise ValueError(f"Activity {self.activity_id}: Scope 3 requires a scope3_category")
        if self.scope != Scope.SCOPE_3 and self.scope3_category is not None:
            raise ValueError(f"Activity {self.activity_id}: scope3_category only valid for Scope 3")
        if self.scope2_method is not None and self.scope != Scope.SCOPE_2:
            raise ValueError(f"Activity {self.activity_id}: scope2_method only valid for Scope 2")
        if self.period_start and self.period_end and self.period_end < self.period_start:
            raise ValueError(f"Activity {self.activity_id}: period_end before period_start")
        return self

    @property
    def spend_year(self) -> int | None:
        if self.price_year is not None:
            return self.price_year
        d = self.period_end or self.period_start
        return d.year if d else None


class EmissionResult(BaseModel):
    """The outcome of applying one factor to one activity, with a full audit trail."""

    activity_id: str
    scope: Scope
    scope3_category: Scope3Category | None
    scope2_method: Scope2Method | None
    method: CalculationMethod
    site: str | None = None
    factor_id: str
    factor_source: str
    factor_status: FactorStatus
    gwp_set: str
    quantity: float
    unit: str
    converted_quantity: float
    factor_unit: str
    gas_kg: dict[str, float]
    co2e_kg: float
    data_quality_score: int = Field(ge=1, le=5)
    trace: list[str]
    energy_kwh: float | None = None
    energy_source: EnergySource | None = None
    biogenic_co2_kg: float | None = None
    # (fossil, nuclear, renewable) generation mix of the electricity factor, if published
    supply_mix: tuple[float, float, float] | None = None
    # for a Category 3 line derived automatically: the Scope 1/2 activity it comes from
    derived_from: str | None = None

    @property
    def co2e_t(self) -> float:
        return self.co2e_kg / 1000
