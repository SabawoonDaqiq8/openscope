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


# Sources: AR5 from IPCC AR5 WG1 Table 8.A.1 (no climate-carbon feedbacks); AR6 from IPCC AR6
# WG1 Chapter 7 (Table 7.15 for CH4 fossil/non-fossil, Table 7.SM.7 for other gases).
# Cross-checked against openclimatedata/globalwarmingpotentials (AR5GWP100 / AR6GWP100).
#
# "CO2E" is a pseudo-gas for components that a source publishes only as CO2e (e.g. EPA's
# "HFCs and PFCs, unspecified"); it carries GWP 1 in every set, so it keeps the source's basis.
_GWP100: dict[GWPSet, dict[str, float]] = {
    GWPSet.AR5: {
        "CO2": 1,
        "CO2E": 1,
        "CH4": 28,
        "CH4_FOSSIL": 28,
        "CH4_BIOGENIC": 28,
        "N2O": 265,
        "HFC-23": 12400,
        "HFC-32": 677,
        "HFC-125": 3170,
        "HFC-134A": 1300,
        "HFC-143A": 4800,
        "HFC-236FA": 8060,
        "SF6": 23500,
        "NF3": 16100,
        "CF4": 6630,
        "C2F6": 11100,
        "C3F8": 8900,
        "C-C4F8": 9540,
        "C4F10": 9200,
        "C6F14": 7910,
    },
    GWPSet.AR6: {
        "CO2": 1,
        "CO2E": 1,
        "CH4": 29.8,  # fossil methane, the conservative default
        "CH4_FOSSIL": 29.8,
        "CH4_BIOGENIC": 27.0,
        "N2O": 273,
        "HFC-23": 14600,
        "HFC-32": 771,
        "HFC-125": 3740,
        "HFC-134A": 1530,
        "HFC-143A": 5810,
        "HFC-236FA": 8690,
        "SF6": 25200,
        "NF3": 17400,
        "CF4": 7380,
        "C2F6": 12400,
        "C3F8": 9290,
        "C-C4F8": 10200,
        "C4F10": 10000,
        "C6F14": 8620,
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
