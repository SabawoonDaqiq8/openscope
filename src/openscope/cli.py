"""Command-line interface.

openscope calculate activities.csv [--factors my_factors.csv] [--gwp AR6] [--year 2025]
                                  [--out results.csv] [--json] [--trace]
openscope factors [--search TEXT] [--factors my_factors.csv]
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from openscope import __version__
from openscope.engine import Calculator
from openscope.errors import OpenScopeError
from openscope.factors import FactorRegistry
from openscope.inventory import Inventory
from openscope.io import dumps_json, read_activities, write_results


def _registry(extra: list[str] | None, no_bundled: bool) -> FactorRegistry:
    reg = FactorRegistry() if no_bundled else FactorRegistry.bundled()
    for path in extra or []:
        reg = reg.merge(FactorRegistry.from_csv(path))
    return reg


def _print_summary(inv: Inventory) -> None:
    s = inv.summary()
    print("\nGHG inventory summary (tCO2e)")
    print("─" * 52)
    print(f"  Scope 1                         {s['scope1_tco2e']:>14,.3f}")
    print(f"  Scope 2 (location-based)        {s['scope2_location_tco2e']:>14,.3f}")
    if s["scope2_market_tco2e"] is not None:
        print(f"  Scope 2 (market-based)          {s['scope2_market_tco2e']:>14,.3f}")
    print(f"  Scope 3                         {s['scope3_tco2e']:>14,.3f}")
    for cat, v in s["scope3_by_category_tco2e"].items():
        print(f"    {cat[:30]:<30}{v:>14,.3f}")
    print("─" * 52)
    print(f"  Total                           {s['total_tco2e']:>14,.3f}")
    print(f"\n  Line items: {s['line_items']}   Weighted data quality: {s['data_quality_score']}/5")
    if s["illustrative_factor_share"] > 0:
        print(
            f"  ⚠  {s['illustrative_factor_share']:.0%} of emissions use ILLUSTRATIVE factors "
            "— not suitable for disclosure."
        )


def cmd_calculate(args: argparse.Namespace) -> int:
    calc = Calculator(_registry(args.factors, args.no_bundled), args.gwp, args.year)
    batch = calc.calculate_many(read_activities(args.activities))
    inv = Inventory(batch.results)

    if args.out:
        write_results(batch.results, args.out)
    if args.json:
        print(
            dumps_json(
                {
                    "summary": inv.summary(),
                    "results": [r.model_dump(mode="json") for r in batch.results],
                    "errors": [e.__dict__ for e in batch.errors],
                }
            )
        )
    else:
        if args.trace:
            for r in batch.results:
                print(f"\n[{r.activity_id}]")
                for t in r.trace:
                    print(f"  {t}")
        _print_summary(inv)
        if args.out:
            print(f"\n  Results written to {args.out}")
    for e in batch.errors:
        print(f"ERROR {e.activity_id}: {e.message}", file=sys.stderr)
    return 1 if batch.errors else 0


def cmd_factors(args: argparse.Namespace) -> int:
    reg = _registry(args.factors, args.no_bundled)
    for f in reg.search(text=args.search):
        val = (
            f"{f.co2e_kg} kgCO2e"
            if f.co2e_kg is not None
            else ", ".join(f"{g}={v}" for g, v in f.gases.items())
        )
        print(f"{f.factor_id:<28} {f.status.value:<12} per {f.activity_unit:<6} {val:<32} {f.name}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="openscope", description="Open-source carbon accounting")
    p.add_argument("--version", action="version", version=f"openscope {__version__}")
    sub = p.add_subparsers(dest="command", required=True)

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--factors", action="append", help="Extra factor CSV (repeatable)")
    common.add_argument("--no-bundled", action="store_true", help="Ignore the sample factors")

    c = sub.add_parser("calculate", parents=[common], help="Calculate emissions from a CSV")
    c.add_argument("activities")
    c.add_argument("--gwp", default="AR6", choices=["AR5", "AR6"])
    c.add_argument("--year", type=int, help="Reporting year (for data-quality scoring)")
    c.add_argument("--out", help="Write line-level results CSV")
    c.add_argument("--json", action="store_true", help="Print JSON instead of a table")
    c.add_argument("--trace", action="store_true", help="Print the audit trail per line")
    c.set_defaults(func=cmd_calculate)

    f = sub.add_parser("factors", parents=[common], help="List available emission factors")
    f.add_argument("--search")
    f.set_defaults(func=cmd_factors)
    return p


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return int(args.func(args))
    except OpenScopeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
