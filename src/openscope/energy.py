"""Energy consumption and mix (ESRS E1-5) and biogenic CO2, from calculated results.

Energy covers own operations: Scope 1 fuels and Scope 2 purchased electricity and heat.
Scope 3 is excluded.

Purchased electricity appears twice in a dual-reported inventory (location-based and
market-based rows for the same kWh). Physical consumption is taken from the location-based
rows of each site, or the market-based rows where a site has none. The renewable part is the
energy covered by renewable energy attribute certificates on the market-based rows, capped at
the site's consumption. The rest of the purchased electricity is split into fossil, nuclear and
renewable using, in order of preference: the generation mix published with the market-based
factor (a national residual mix, e.g. from the AIB), a supplier or grid mix stated by the user,
then the mix published with the location-based factor (a national production mix). Whatever
no mix covers stays undetermined.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

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
    # split of ``electricity_other`` where a generation mix is known (factor or stated mix)
    electricity_fossil: float = 0.0
    electricity_nuclear: float = 0.0
    electricity_renewable_mix: float = 0.0
    # MWh of ``electricity_other`` split by each basis
    mix_basis: dict[str, float] = field(default_factory=dict)
    grid_mix: GridMix | None = None

    @property
    def electricity_undetermined(self) -> float:
        known = self.electricity_fossil + self.electricity_nuclear + self.electricity_renewable_mix
        return max(self.electricity_other - known, 0.0)

    @property
    def _split_known(self) -> bool:
        return self.electricity_other == 0 or bool(self.mix_basis)

    @property
    def total(self) -> float:
        return self.fossil_fuels + self.renewable_fuels + self.electricity_total + self.heat

    @property
    def fossil(self) -> float | None:
        return self.fossil_fuels + self.electricity_fossil if self._split_known else None

    @property
    def nuclear(self) -> float | None:
        return self.electricity_nuclear if self._split_known else None

    @property
    def renewable_purchased(self) -> float:
        return self.electricity_renewable_certificates + self.electricity_renewable_mix

    @property
    def renewable(self) -> float:
        return self.renewable_fuels + self.renewable_purchased

    @property
    def undetermined(self) -> float:
        """Purchased energy whose fossil / nuclear / renewable split is not known."""
        return self.electricity_undetermined + self.heat


# bases for splitting uncertified electricity, in order of preference
MIX_RESIDUAL = "market-based factor mix"  # e.g. a national residual mix
MIX_STATED = "stated supplier or grid mix"
MIX_GRID = "location-based factor mix"  # e.g. a national production mix


@dataclass
class _Site:
    lb: float = 0.0
    lb_rows: int = 0
    mb: float = 0.0
    mb_renewable: float = 0.0
    # MWh-weighted generation mixes found on the site's factors: [mwh, fossil, nuclear, renew]
    mb_mix: list[float] = field(default_factory=lambda: [0.0, 0.0, 0.0, 0.0])
    lb_mix: list[float] = field(default_factory=lambda: [0.0, 0.0, 0.0, 0.0])


def _add_mix(acc: list[float], mwh: float, mix: tuple[float, float, float] | None) -> None:
    if mix is None or mwh <= 0:
        return
    acc[0] += mwh
    for i, share in enumerate(mix, start=1):
        acc[i] += mwh * share


def energy_mix(inventory: Inventory, grid_mix: GridMix | None = None) -> EnergyMix:
    fossil = renewable_fuel = heat = 0.0
    missing = 0
    by_site: dict[str | None, _Site] = defaultdict(_Site)
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
                site.mb += mwh
                if src == EnergySource.RENEWABLE_ELECTRICITY:
                    site.mb_renewable += mwh
                else:
                    _add_mix(site.mb_mix, mwh, r.supply_mix)
            else:
                site.lb += mwh
                site.lb_rows += 1
                _add_mix(site.lb_mix, mwh, r.supply_mix)
        else:
            missing += 1

    total_el = certified = 0.0
    split = [0.0, 0.0, 0.0]
    basis: dict[str, float] = defaultdict(float)
    stated = (grid_mix.fossil, grid_mix.nuclear, grid_mix.renewable) if grid_mix else None
    for s in by_site.values():
        consumed = s.lb if s.lb_rows else s.mb
        covered = min(s.mb_renewable, consumed)
        total_el += consumed
        certified += covered
        remaining = consumed - covered
        # residual (market-based) mix: covers the share of uncertified market-based MWh it was on
        uncertified_mb = s.mb - s.mb_renewable
        candidates: list[tuple[str, list[float] | None, float]] = []
        if s.mb_mix[0] and uncertified_mb > 0:
            candidates.append((MIX_RESIDUAL, s.mb_mix, min(s.mb_mix[0] / uncertified_mb, 1.0)))
        if stated:
            candidates.append((MIX_STATED, None, 1.0))
        if s.lb_mix[0] and s.lb > 0:
            candidates.append((MIX_GRID, s.lb_mix, min(s.lb_mix[0] / s.lb, 1.0)))
        left = remaining
        for name, acc, coverage in candidates:
            if left <= 1e-12:
                break
            part = left if acc is None else min(left, remaining * coverage)
            shares = stated if acc is None else (acc[1] / acc[0], acc[2] / acc[0], acc[3] / acc[0])
            assert shares is not None
            for i in range(3):
                split[i] += part * shares[i]
            basis[name] += part
            left -= part
    return EnergyMix(
        fossil_fuels=fossil,
        renewable_fuels=renewable_fuel,
        electricity_total=total_el,
        electricity_renewable_certificates=certified,
        electricity_other=total_el - certified,
        heat=heat,
        lines_without_energy=missing,
        electricity_fossil=split[0],
        electricity_nuclear=split[1],
        electricity_renewable_mix=split[2],
        mix_basis=dict(basis),
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
