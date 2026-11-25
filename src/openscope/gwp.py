"""Global Warming Potentials (100-year time horizon).

Values from the IPCC Fifth (AR5, 2013) and Sixth (AR6, 2021) Assessment Reports.
AR5 values exclude climate-carbon feedbacks, as used by the GHG Protocol and most
national inventories. AR6 distinguishes fossil and non-fossil methane.
"""

from __future__ import annotations

from enum import StrEnum

from openscope.errors import GWPError


class GWPSet(StrEnum):
    AR5 = "AR5"
    AR6 = "AR6"


_GWP100: dict[GWPSet, dict[str, float]] = {
    GWPSet.AR5: {
        "CO2": 1,
        "CH4": 28,
        "CH4_FOSSIL": 28,
        "CH4_BIOGENIC": 28,
        "N2O": 265,
        "HFC-32": 677,
        "HFC-125": 3170,
        "HFC-134A": 1300,
        "SF6": 23500,
        "NF3": 16100,
    },
    GWPSet.AR6: {
        "CO2": 1,
        "CH4": 29.8,  # fossil methane, the conservative default
        "CH4_FOSSIL": 29.8,
        "CH4_BIOGENIC": 27.0,
        "N2O": 273,
        "HFC-32": 771,
        "HFC-125": 3740,
        "HFC-134A": 1530,
        "SF6": 24300,
        "NF3": 17400,
    },
}


def gwp(gas: str, gwp_set: GWPSet | str = GWPSet.AR6) -> float:
    """Return the 100-year GWP of ``gas`` in the given assessment report."""
    table = _GWP100[GWPSet(gwp_set)]
    try:
        return table[gas.strip().upper()]
    except KeyError:
        raise GWPError(f"No GWP for gas '{gas}' in {GWPSet(gwp_set).value}") from None


def supported_gases(gwp_set: GWPSet | str = GWPSet.AR6) -> list[str]:
    return sorted(_GWP100[GWPSet(gwp_set)])
