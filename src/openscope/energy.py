"""Energy consumption and mix (ESRS E1-5) and biogenic CO2, from calculated results.

Energy covers own operations: Scope 1 fuels and Scope 2 purchased electricity and heat.
Scope 3 is excluded.

Purchased electricity appears twice in a dual-reported inventory (location-based and
market-based rows for the same kWh). Physical consumption is taken from the location-based
rows of each site, or the market-based rows where a site has none. The renewable part is the
energy covered by renewable energy attribute certificates on the market-based rows, capped at
the site's consumption. The rest of the purchased electricity has an undetermined source mix
unless a grid mix (fossil / nuclear / renewable shares) is supplied.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from openscope.inventory import Inventory
from openscope.models import EnergySource, Scope, Scope2Method


@dataclass
class GridMix:
    """Shares of the purchased electricity not covered by certificates (must sum to 1)."""

    fossil: float
    nuclear: float
    renewable: float

    def __post_init__(self) -> None:
        if min(self.fossil, self.nuclear, self.renewable) < 0:
            raise ValueError("grid mix shares must be non-negative")
        if abs(self.fossil + self.nuclear + self.renewable - 1) > 0.005:
            raise ValueError("grid mix shares must sum to 100 %")


@dataclass
class EnergyMix:
    """All values in MWh."""

    fossil_fuels: float
    renewable_fuels: float
    electricity_total: float
    electricity_renewable_certificates: float
    electricity_other: float  # not covered by certificates
    heat: float  # purchased heat/steam/cooling, source mix not determined
    lines_without_energy: int  # Scope 1/2 energy lines whose factor has no energy content
    grid_mix: GridMix | None = None

    @property
    def total(self) -> float:
        return self.fossil_fuels + self.renewable_fuels + self.electricity_total + self.heat

    @property
    def fossil(self) -> float | None:
        if self.grid_mix is None:
            return None
        return self.fossil_fuels + self.electricity_other * self.grid_mix.fossil

    @property
    def nuclear(self) -> float | None:
        return None if self.grid_mix is None else self.electricity_other * self.grid_mix.nuclear

    @property
    def renewable_purchased(self) -> float:
        extra = self.electricity_other * self.grid_mix.renewable if self.grid_mix else 0.0
        return self.electricity_renewable_certificates + extra

    @property
    def renewable(self) -> float:
        return self.renewable_fuels + self.renewable_purchased

    @property
    def undetermined(self) -> float:
        """Purchased energy whose fossil / nuclear / renewable split is not known."""
        return (0.0 if self.grid_mix else self.electricity_other) + self.heat


def energy_mix(inventory: Inventory, grid_mix: GridMix | None = None) -> EnergyMix:
    fossil = renewable_fuel = heat = 0.0
    missing = 0
    by_site: dict[str | None, dict[str, float]] = defaultdict(
        lambda: {"lb": 0.0, "mb": 0.0, "mb_renewable": 0.0, "lb_rows": 0.0}
    )
    for r in inventory.results:
        if r.scope == Scope.SCOPE_3 or r.energy_source == EnergySource.NON_ENERGY:
            continue
        if r.energy_kwh is None:
            missing += 1
            continue
        mwh = r.energy_kwh / 1000
        src = r.energy_source
        if src == EnergySource.FOSSIL_FUEL:
            fossil += mwh
        elif src == EnergySource.RENEWABLE_FUEL:
            renewable_fuel += mwh
        elif src == EnergySource.HEAT:
            heat += mwh
        elif src in (EnergySource.ELECTRICITY, EnergySource.RENEWABLE_ELECTRICITY):
            site = by_site[r.site]
            if r.scope2_method == Scope2Method.MARKET_BASED:
                site["mb"] += mwh
                if src == EnergySource.RENEWABLE_ELECTRICITY:
                    site["mb_renewable"] += mwh
            else:
                site["lb"] += mwh
                site["lb_rows"] += 1
        else:
            missing += 1

    total_el = certified = 0.0
    for s in by_site.values():
        consumed = s["lb"] if s["lb_rows"] else s["mb"]
        total_el += consumed
        certified += min(s["mb_renewable"], consumed)
    return EnergyMix(
        fossil_fuels=fossil,
        renewable_fuels=renewable_fuel,
        electricity_total=total_el,
        electricity_renewable_certificates=certified,
        electricity_other=total_el - certified,
        heat=heat,
        lines_without_energy=missing,
        grid_mix=grid_mix,
    )


def biogenic_t(inventory: Inventory, scope: Scope) -> float:
    """Biogenic CO2 (tonnes) reported outside the scopes.

    Scope 2 uses the location-based rows (the physical grid), so dual-reported electricity is
    not counted twice.
    """
    total = 0.0
    for r in inventory.results:
        if r.scope != scope or not r.biogenic_co2_kg:
            continue
        if scope == Scope.SCOPE_2 and r.scope2_method == Scope2Method.MARKET_BASED:
            continue
        total += r.biogenic_co2_kg
    return total / 1000
