"""Benchmark the Scope 3 ledger classifier against the hand-labelled sample ledger.

Configurations
--------------
* ``rules``          default + example rules only (no model; free)
* ``llm:<model>``    Claude only, no rules (measures the model on its own)
* ``hybrid:<model>`` rules + Claude, the production pipeline

Every model configuration is called once. Its classifications are then re-scored at several
confidence thresholds (no extra API calls), and the raw model output is saved so the run can
be audited and reproduced.

Usage (needs ANTHROPIC_API_KEY for model configurations):

    python scripts/benchmark_classifier.py                       # rules + default model
    python scripts/benchmark_classifier.py \
        --models claude-opus-5-5,claude-sonnet-5-5,claude-haiku-5-5
    python scripts/benchmark_classifier.py --rules-only          # free, no API key

Writes docs/benchmarks/classifier-results.json and docs/benchmarks/classifier.md.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from openscope import FactorRegistry, __version__, units
from openscope.classify import (
    ClassifiedLine,
    LLMClassifier,
    PipelineConfig,
    RuleSet,
    classify_ledger,
    evaluate,
    read_labels,
    read_ledger,
)
from openscope.classify.pipeline import status_for

ROOT = Path(__file__).resolve().parent.parent
EX = ROOT / "examples"
OUT = ROOT / "docs" / "benchmarks"
THRESHOLDS = [0.5, 0.6, 0.7, 0.8, 0.85, 0.9, 0.95]
DEFAULT_THRESHOLD = 0.85


def rescore(classified: list[ClassifiedLine], threshold: float) -> list[ClassifiedLine]:
    cfg = PipelineConfig(threshold=threshold)
    return [c.model_copy(update={"status": status_for(c.classification, cfg)}) for c in classified]


def score(classified: list[ClassifiedLine], labels: dict[str, str]) -> dict[str, Any]:
    main = evaluate(rescore(classified, DEFAULT_THRESHOLD), labels).as_dict()
    sweep = []
    for t in THRESHOLDS:
        r = evaluate(rescore(classified, t), labels)
        precision = None if r.auto_precision is None else round(r.auto_precision, 4)
        sweep.append(
            {"threshold": t, "coverage": round(r.coverage, 4), "auto_accept_precision": precision}
        )
    main["threshold_sweep"] = sweep
    return main


def run_config(
    name: str,
    lines: list[Any],
    labels: dict[str, str],
    rules: RuleSet | None,
    model: str | None,
    factors: list[Any],
    effort: str,
) -> dict[str, Any]:
    llm = LLMClassifier.from_env(factors, model=model, effort=effort) if model else None
    started = time.perf_counter()
    classified = classify_ledger(lines, rules, None, llm, PipelineConfig(DEFAULT_THRESHOLD))
    elapsed = time.perf_counter() - started
    result: dict[str, Any] = {
        "config": name,
        "model": model,
        "effort": effort if model else None,
        "seconds": round(elapsed, 1),
        **score(classified, labels),
    }
    if llm is not None:
        u = llm.usage
        result["usage"] = {
            "requests": u.requests,
            "input_tokens": u.input_tokens,
            "cache_creation_input_tokens": u.cache_creation_input_tokens,
            "cache_read_input_tokens": u.cache_read_input_tokens,
            "output_tokens": u.output_tokens,
            "failed_batches": u.failed_batches,
        }
    result["classifications"] = [
        {"line_id": c.line.line_id, **c.classification.model_dump(mode="json"),
         "status": c.status.value}
        for c in classified
    ]  # fmt: skip
    return result


def markdown(results: list[dict[str, Any]], meta: dict[str, Any]) -> str:
    def pct(v: float | None) -> str:
        return "–" if v is None else f"{v:.0%}"

    lines = [
        "# Scope 3 classifier benchmark",
        "",
        f"Run {meta['date']} with openscope {meta['version']} on the {meta['lines']}-line sample "
        "ledger (`examples/ledger_sample.csv`, labels in `examples/ledger_sample_labels.csv`). "
        f"Factor catalogue: {meta['catalogue']} ({meta['factors']} spend-based factors). "
        f"Auto-accept threshold {DEFAULT_THRESHOLD}.",
        "",
        "| Configuration | Accuracy | Coverage | Auto-accept precision | Requests | Input tokens "
        "(cached read) | Output tokens | Time |",
        "|---|--:|--:|--:|--:|--:|--:|--:|",
    ]
    for r in results:
        u = r.get("usage") or {}
        cached = u.get("cache_read_input_tokens")
        tokens = "–" if not u else f"{u['input_tokens']:,} ({cached:,})"
        lines.append(
            f"| `{r['config']}` | {pct(r['accuracy'])} | {pct(r['coverage'])} | "
            f"{pct(r['auto_accept_precision'])} | {u.get('requests', '–')} | {tokens} | "
            f"{u['output_tokens']:,} | {r['seconds']} s |"
            if u
            else f"| `{r['config']}` | {pct(r['accuracy'])} | {pct(r['coverage'])} | "
            f"{pct(r['auto_accept_precision'])} | – | – | – | {r['seconds']} s |"
        )
    lines += [
        "",
        "* **Accuracy**: decision (classify / exclude / unsure) and Scope 3 category both correct,",
        "  over all labelled lines.",
        "* **Coverage**: share of lines decided without human review.",
        "* **Auto-accept precision**: accuracy on the lines that skip review; this is the number",
        "  that tells you whether the threshold is safe.",
        "",
        "## Threshold sweep (coverage / auto-accept precision)",
        "",
        "| Configuration | " + " | ".join(str(t) for t in THRESHOLDS) + " |",
        "|---|" + "--:|" * len(THRESHOLDS),
    ]
    for r in results:
        cells = [f"{pct(s['coverage'])} / {pct(s['auto_accept_precision'])}"
                 for s in r["threshold_sweep"]]  # fmt: skip
        lines.append(f"| `{r['config']}` | " + " | ".join(cells) + " |")
    lines += ["", "## Errors at the default threshold", ""]
    for r in results:
        errs = r["errors"]
        lines.append(f"**`{r['config']}`**: {len(errs)} of {r['labelled']} lines")
        for e in errs:
            lines.append(f"- {e['line_id']}: expected `{e['expected']}`, got `{e['predicted']}`")
        lines.append("")
    lines += [
        "## Caveats",
        "",
        "* 40 synthetic lines is a smoke test, not a statistically robust benchmark. Build a",
        "  labelled sample from a real ledger before choosing a threshold for production.",
        "* Model confidence is self-reported and not calibrated; pick the threshold from",
        "  auto-accept precision on labelled data.",
        "* Labels reflect one accountant's judgement on borderline lines (e.g. office rent as",
        "  category 8, utilities excluded as Scope 1/2 activity data).",
        "",
        "Raw model output for every line is in `classifier-results.json`.",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--models", default="claude-opus-5-5")
    ap.add_argument("--effort", default="low")
    ap.add_argument("--rules-only", action="store_true")
    ap.add_argument("--no-llm-only", action="store_true", help="skip the Claude-only configs")
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args()

    lines = read_ledger(EX / "ledger_sample.csv")
    labels = read_labels(EX / "ledger_sample_labels.csv")
    rules = RuleSet.default() + RuleSet.from_csv(EX / "classification_rules_example.csv")
    catalogue = "useeio-1.3"
    factors = [
        f for f in FactorRegistry.dataset(catalogue)
        if units.get_unit(f.activity_unit).dimension.startswith("currency:")
    ]  # fmt: skip

    models = [] if args.rules_only else [m.strip() for m in args.models.split(",") if m.strip()]
    if models and not os.environ.get("ANTHROPIC_API_KEY"):
        print("ANTHROPIC_API_KEY is not set. Export it, or run with --rules-only.", file=sys.stderr)
        return 2

    results = [run_config("rules", lines, labels, rules, None, factors, args.effort)]
    try:
        for model in models:
            if not args.no_llm_only:
                results.append(run_config(f"llm:{model}", lines, labels, None, model, factors,
                                          args.effort))  # fmt: skip
            results.append(run_config(f"hybrid:{model}", lines, labels, rules, model, factors,
                                      args.effort))  # fmt: skip
    except Exception as exc:  # anthropic.APIError and friends: report, keep partial results
        print(f"Model run stopped: {type(exc).__name__}: {exc}", file=sys.stderr)
        if len(results) == 1:
            return 1

    meta = {
        "date": datetime.now(UTC).date().isoformat(),
        "version": __version__,
        "lines": len(lines),
        "catalogue": catalogue,
        "factors": len(factors),
        "threshold": DEFAULT_THRESHOLD,
    }
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "classifier-results.json").write_text(
        json.dumps({"meta": meta, "results": results}, indent=2) + "\n", encoding="utf-8"
    )
    report = markdown(results, meta)
    (args.out / "classifier.md").write_text(report, encoding="utf-8")
    print(report.split("## Threshold sweep")[0])
    failed = [r["config"] for r in results if (r.get("usage") or {}).get("failed_batches")]
    if failed:
        print(f"Batches failed in: {failed}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
