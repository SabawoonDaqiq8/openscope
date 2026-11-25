"""Aggregation of results into a GHG inventory.

Scope 2 follows the GHG Protocol *dual reporting* requirement: location-based and
market-based totals are computed separately and never summed together. The same
kWh will usually appear twice in the input (once per method).
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from typing import Any

from openscope import quality
from openscope.models import EmissionResult, FactorStatus, Scope, Scope2Method, Scope3Category


class Inventory:
    def __init__(self, results: Iterable[EmissionResult]) -> None:
        self.results = list(results)

    # -- scope totals -------------------------------------------------------------
    def _sum(self, rs: Iterable[EmissionResult]) -> float:
        return sum(r.co2e_kg for r in rs) / 1000  # tonnes

    def scope1_t(self) -> float:
        return self._sum(r for r in self.results if r.scope == Scope.SCOPE_1)

    def _scope2(self, method: Scope2Method) -> list[EmissionResult]:
        return [r for r in self.results if r.scope == Scope.SCOPE_2 and r.scope2_method == method]

    def scope2_market_fallback_sites(self) -> list[str]:
        """Sites with location-based but no market-based data.

        Per the GHG Protocol Scope 2 Guidance hierarchy, when no contractual instrument,
        supplier-specific or residual-mix factor is available, the grid-average
        (location-based) factor is used for the market-based figure.
        """
        mb_sites = {r.site for r in self._scope2(Scope2Method.MARKET_BASED)}
        lb_sites = {r.site for r in self._scope2(Scope2Method.LOCATION_BASED)}
        return sorted(s or "(no site)" for s in lb_sites - mb_sites)

    def _scope2_market_results(self) -> list[EmissionResult]:
        mb = self._scope2(Scope2Method.MARKET_BASED)
        mb_sites = {r.site for r in mb}
        fallback = [r for r in self._scope2(Scope2Method.LOCATION_BASED) if r.site not in mb_sites]
        return mb + fallback

    def scope2_t(self, method: Scope2Method = Scope2Method.LOCATION_BASED) -> float:
        """Scope 2 total. Market-based includes grid-average fallback for uncovered sites."""
        if method == Scope2Method.MARKET_BASED:
            return self._sum(self._scope2_market_results())
        return self._sum(self._scope2(method))

    def has_market_based(self) -> bool:
        return any(r.scope2_method == Scope2Method.MARKET_BASED for r in self.results)

    def scope3_t(self) -> float:
        return self._sum(r for r in self.results if r.scope == Scope.SCOPE_3)

    def scope3_by_category_t(self) -> dict[Scope3Category, float]:
        out: dict[Scope3Category, float] = defaultdict(float)
        for r in self.results:
            if r.scope == Scope.SCOPE_3 and r.scope3_category is not None:
                out[r.scope3_category] += r.co2e_kg / 1000
        return dict(sorted(out.items()))

    def total_t(self, scope2_method: Scope2Method = Scope2Method.MARKET_BASED) -> float:
        """Scope 1 + 2 + 3, using market-based Scope 2 (with fallback) unless told otherwise."""
        return self.scope1_t() + self.scope2_t(scope2_method) + self.scope3_t()

    # -- analysis -----------------------------------------------------------------
    def headline_results(self) -> list[EmissionResult]:
        """Results that make up :meth:`total_t`: market-based Scope 2, no double counting."""
        return [r for r in self.results if r.scope != Scope.SCOPE_2] + self._scope2_market_results()

    def hotspots(self, n: int = 10) -> list[EmissionResult]:
        """Largest individual line items contributing to the headline total."""
        return sorted(self.headline_results(), key=lambda r: r.co2e_kg, reverse=True)[:n]

    def data_quality(self) -> float | None:
        return quality.weighted_score(self.headline_results())

    def illustrative_share(self) -> float:
        """Share of headline emissions using illustrative factors (must be 0 to disclose)."""
        rs = self.headline_results()
        total = sum(r.co2e_kg for r in rs)
        illus = sum(r.co2e_kg for r in rs if r.factor_status == FactorStatus.ILLUSTRATIVE)
        return illus / total if total else 0.0

    def summary(self) -> dict[str, Any]:
        return {
            "scope1_tco2e": round(self.scope1_t(), 3),
            "scope2_location_tco2e": round(self.scope2_t(Scope2Method.LOCATION_BASED), 3),
            "scope2_market_tco2e": round(self.scope2_t(Scope2Method.MARKET_BASED), 3),
            "scope2_market_fallback_sites": self.scope2_market_fallback_sites(),
            "scope3_tco2e": round(self.scope3_t(), 3),
            "scope3_by_category_tco2e": {
                f"{c.value}. {c.label}": round(v, 3) for c, v in self.scope3_by_category_t().items()
            },
            "total_tco2e": round(self.total_t(), 3),
            "data_quality_score": self.data_quality(),
            "illustrative_factor_share": round(self.illustrative_share(), 4),
            "line_items": len(self.results),
        }
