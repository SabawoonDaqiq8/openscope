"""Command-line interface.

openscope calculate activities.csv [--factors my_factors.csv] [--gwp AR6] [--year 2025]
                                  [--out results.csv] [--json] [--trace]
openscope factors [--search TEXT] [--factors my_factors.csv]
"""

from __future__ import annotations

import argparse
import csv
import sys
from collections.abc import Sequence
from pathlib import Path

from openscope import __version__
from openscope.engine import Calculator
from openscope.errors import OpenScopeError
from openscope.factors import FactorRegistry
from openscope.inventory import Inventory
from openscope.io import dumps_json, read_activities, write_results
from openscope.models import EmissionFactor
from openscope.money import FXTable, PriceIndex, SpendNormaliser


def _registry(
    extra: list[str] | None, no_bundled: bool, datasets: list[str] | None = None
) -> FactorRegistry:
    reg = FactorRegistry() if no_bundled else FactorRegistry.bundled()
    for name in datasets or []:
        reg = reg.merge(FactorRegistry.dataset(name))
    for path in extra or []:
        reg = reg.merge(FactorRegistry.from_csv(path))
    return reg


def _print_summary(inv: Inventory) -> None:
    s = inv.summary()
    print("\nGHG inventory summary (tCO2e)")
    print("─" * 60)
    print(f"  Scope 1                                 {s['scope1_tco2e']:>14,.3f}")
    print(f"  Scope 2 (location-based)                {s['scope2_location_tco2e']:>14,.3f}")
    print(f"  Scope 2 (market-based)                  {s['scope2_market_tco2e']:>14,.3f}")
    if s["scope2_market_fallback_sites"]:
        sites = ", ".join(s["scope2_market_fallback_sites"])
        print(f"    (grid-average fallback for: {sites})")
    print(f"  Scope 3                                 {s['scope3_tco2e']:>14,.3f}")
    for cat, v in s["scope3_by_category_tco2e"].items():
        print(f"    {cat[:40]:<40}{v:>12,.3f}")
    print("─" * 60)
    print(f"  Total                                   {s['total_tco2e']:>14,.3f}")
    print(f"\n  Line items: {s['line_items']}   Weighted data quality: {s['data_quality_score']}/5")
    if s["illustrative_factor_share"] > 0:
        print(
            f"  ⚠  {s['illustrative_factor_share']:.0%} of emissions use ILLUSTRATIVE factors "
            "— not suitable for disclosure."
        )


def cmd_calculate(args: argparse.Namespace) -> int:
    normaliser = None
    if args.fx or args.price_index:
        normaliser = SpendNormaliser(
            fx=FXTable.from_csv(args.fx) if args.fx else FXTable(),
            prices=PriceIndex.from_csv(args.price_index) if args.price_index else PriceIndex(),
        )
    calc = Calculator(
        _registry(args.factors, args.no_bundled, args.dataset), args.gwp, args.year, normaliser
    )
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
    reg = _registry(args.factors, args.no_bundled, args.dataset)
    for f in reg.search(text=args.search):
        val = (
            f"{f.co2e_kg} kgCO2e"
            if f.co2e_kg is not None
            else ", ".join(f"{g}={v}" for g, v in f.gases.items())
        )
        print(f"{f.factor_id:<28} {f.status.value:<12} per {f.activity_unit:<6} {val:<32} {f.name}")
    return 0


def cmd_datasets(args: argparse.Namespace) -> int:
    for name in FactorRegistry.available_datasets():
        print(f"{name:<14} {len(FactorRegistry.dataset(name)):>6} factors")
    return 0


def cmd_import_desnz(args: argparse.Namespace) -> int:
    from openscope.importers import desnz

    report = desnz.read_workbook(args.workbook, args.year)
    reg = FactorRegistry(report.factors)
    reg.to_csv(
        args.out,
        header_comment=(
            f"Imported from {Path(args.workbook).name} by openscope {__version__}.\n"
            "Contains public sector information licensed under the Open Government Licence v3.0."
        ),
    )
    print(f"Wrote {len(reg)} factors to {args.out}")
    print(f"  per-gas (re-weightable to AR6): {report.per_gas}")
    print(f"  CO2e total only:                {report.total_only}")
    print(f"  energy-conversion rows skipped: {report.skipped_energy_rows}")
    if report.skipped_unknown_unit:
        print(f"  skipped (unmapped units):       {report.skipped_unknown_unit}")
    return 0


def _spend_factors(reg: FactorRegistry) -> list[EmissionFactor]:
    from openscope import units

    return [f for f in reg if units.get_unit(f.activity_unit).dimension.startswith("currency:")]


def cmd_classify(args: argparse.Namespace) -> int:
    from openscope import classify as cl

    reg = _registry(args.factors, args.no_bundled, args.dataset)
    lines = cl.read_ledger(args.ledger, default_currency=args.currency)
    rules = cl.RuleSet() if args.no_default_rules else cl.RuleSet.default()
    for path in args.rules or []:
        rules = rules + cl.RuleSet.from_csv(path)
    memory = cl.SupplierMemory.load(args.memory) if args.memory else None
    llm = None
    if args.llm:
        llm = cl.LLMClassifier.from_env(
            _spend_factors(reg), model=args.model, effort=args.effort, batch_size=args.batch_size
        )
    classified = cl.classify_ledger(
        lines, rules, memory, llm, cl.PipelineConfig(threshold=args.threshold)
    )
    cl.write_review_csv(classified, args.out)

    s = cl.summarise(classified)
    print(f"Classified {s['lines']} ledger lines -> {args.out}")
    print(f"  by status: {s['by_status']}")
    print(f"  by source: {s['by_source']}")
    print(f"  spend share needing review: {s['spend_share_needing_review']:.1%}")
    if llm is not None:
        u = llm.usage
        print(
            f"  model {llm.model}: {u.requests} requests, {u.input_tokens:,} input "
            f"(+{u.cache_read_input_tokens:,} cached) / {u.output_tokens:,} output tokens"
        )
        for f in u.failed_batches:
            print(f"  ! batch left for review: {f}", file=sys.stderr)
    if args.labels:
        report = cl.evaluate(classified, cl.read_labels(args.labels))
        print(dumps_json(report.as_dict()))
    return 0


def cmd_review_apply(args: argparse.Namespace) -> int:
    from openscope import classify as cl
    from openscope.io import ACTIVITY_COLUMNS

    reg = _registry(args.factors, args.no_bundled, args.dataset)
    memory = cl.SupplierMemory.load(args.memory) if args.memory else None
    outcome = cl.apply_review(
        cl.read_review_csv(args.review),
        args.reviewer,
        known_factor_ids={f.factor_id for f in reg},
        memory=memory,
    )
    if args.audit_log:
        cl.append_audit_log(outcome.audit_entries, args.audit_log)
    if memory is not None and args.memory:
        memory.save(args.memory)
    acts = cl.to_activities(outcome.lines)
    with open(args.activities_out, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=ACTIVITY_COLUMNS, lineterminator="\n")
        w.writeheader()
        for a in acts:
            row = a.model_dump(mode="json")
            w.writerow({k: "" if row.get(k) is None else row[k] for k in ACTIVITY_COLUMNS})
    print(f"Applied {len(outcome.audit_entries)} review decisions by {args.reviewer}")
    print(f"Wrote {len(acts)} spend-based activities to {args.activities_out}")
    if outcome.still_pending:
        print(f"  {len(outcome.still_pending)} lines still need review (not exported)")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="openscope", description="Open-source carbon accounting")
    p.add_argument("--version", action="version", version=f"openscope {__version__}")
    sub = p.add_subparsers(dest="command", required=True)

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--factors", action="append", help="Extra factor CSV (repeatable)")
    common.add_argument("--no-bundled", action="store_true", help="Ignore the sample factors")
    common.add_argument(
        "--dataset", action="append", help="Bundled dataset, e.g. desnz-2025 (repeatable)"
    )

    c = sub.add_parser("calculate", parents=[common], help="Calculate emissions from a CSV")
    c.add_argument("activities")
    c.add_argument("--gwp", default="AR6", choices=["AR5", "AR6"])
    c.add_argument("--year", type=int, help="Reporting year (for data-quality scoring)")
    c.add_argument("--fx", help="Exchange rates CSV: year,from,to,rate")
    c.add_argument("--price-index", help="Price index CSV: currency,year,index")
    c.add_argument("--out", help="Write line-level results CSV")
    c.add_argument("--json", action="store_true", help="Print JSON instead of a table")
    c.add_argument("--trace", action="store_true", help="Print the audit trail per line")
    c.set_defaults(func=cmd_calculate)

    f = sub.add_parser("factors", parents=[common], help="List available emission factors")
    f.add_argument("--search")
    f.set_defaults(func=cmd_factors)

    d = sub.add_parser("datasets", help="List bundled factor datasets")
    d.set_defaults(func=cmd_datasets)

    i = sub.add_parser("import-desnz", help="Convert a DESNZ flat-format .xlsx to factor CSV")
    i.add_argument("workbook")
    i.add_argument("--out", required=True)
    i.add_argument("--year", type=int, help="Factor year (auto-detected if omitted)")
    i.set_defaults(func=cmd_import_desnz)

    k = sub.add_parser(
        "classify", parents=[common], help="Classify a ledger export into Scope 3 categories"
    )
    k.add_argument("ledger")
    k.add_argument("--out", required=True, help="Review CSV to write")
    k.add_argument("--rules", action="append", help="Extra rules CSV (repeatable)")
    k.add_argument("--no-default-rules", action="store_true")
    k.add_argument("--memory", help="Supplier memory JSON (read)")
    k.add_argument("--llm", action="store_true", help="Use Claude for lines rules can't decide")
    k.add_argument("--model", default="claude-opus-5-5")
    k.add_argument("--effort", default="low", choices=["low", "medium", "high", "xhigh", "max"])
    k.add_argument("--batch-size", type=int, default=25)
    k.add_argument("--threshold", type=float, default=0.85, help="Auto-accept confidence")
    k.add_argument("--currency", help="Currency when the ledger has no currency column")
    k.add_argument("--labels", help="Labelled CSV: print an evaluation report")
    k.set_defaults(func=cmd_classify)

    r = sub.add_parser(
        "review-apply", parents=[common], help="Apply reviewer decisions from a review CSV"
    )
    r.add_argument("review")
    r.add_argument("--reviewer", required=True)
    r.add_argument("--activities-out", required=True)
    r.add_argument("--audit-log", help="Append-only JSONL audit log")
    r.add_argument("--memory", help="Supplier memory JSON (read and updated)")
    r.set_defaults(func=cmd_review_apply)
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
