"""Data-quality scoring.

A 1 (best) – 5 (worst) score in the spirit of the GHG Protocol Scope 3 data-quality
indicators and the PCAF data-quality score. The score starts from the calculation
method and is penalised for weak factor provenance.
"""

from __future__ import annotations

from collections.abc import Iterable

from openscope.models import CalculationMethod, EmissionFactor, EmissionResult, FactorStatus

_METHOD_BASE_SCORE: dict[CalculationMethod, int] = {
    CalculationMethod.SUPPLIER_SPECIFIC: 1,
    CalculationMethod.HYBRID: 2,
    CalculationMethod.AVERAGE_DATA: 3,
    CalculationMethod.SPEND_BASED: 4,
    CalculationMethod.ESTIMATED: 5,
}


def score(
    method: CalculationMethod, factor: EmissionFactor, reporting_year: int | None = None
) -> int:
    """Score a single calculation.

    Penalties (+1 each, capped at 5):
    * the factor is illustrative (not a citable source),
    * the factor is more than 5 years older than the reporting year (temporal representativeness).
    """
    s = _METHOD_BASE_SCORE[method]
    if factor.status == FactorStatus.ILLUSTRATIVE:
        s += 1
    if reporting_year and factor.year and reporting_year - factor.year > 5:
        s += 1
    return min(s, 5)


def weighted_score(results: Iterable[EmissionResult]) -> float | None:
    """Emissions-weighted average data-quality score of an inventory (None if empty)."""
    total = weighted = 0.0
    for r in results:
        total += r.co2e_kg
        weighted += r.co2e_kg * r.data_quality_score
    return round(weighted / total, 2) if total > 0 else None
