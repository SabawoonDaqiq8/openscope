"""Evaluate classification against a hand-labelled ledger.

Labels CSV columns: ``line_id, expected_decision, expected_category`` (category blank for
excluded lines). The headline metrics:

* **accuracy**: decision and category both correct, over labelled lines with a decision
* **coverage**: share of lines decided without human review
* **auto-accept precision**: accuracy over the lines that would *skip* review; this is
  the number that tells you whether the confidence threshold is safe
"""

from __future__ import annotations

import csv
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from openscope.classify.models import ClassifiedLine, Decision, Status


@dataclass
class EvalReport:
    labelled: int
    accuracy: float
    coverage: float
    auto_precision: float | None
    per_category: dict[str, dict[str, float]]
    errors: list[tuple[str, str, str]]  # (line_id, expected, predicted)

    def as_dict(self) -> dict[str, object]:
        return {
            "labelled": self.labelled,
            "accuracy": round(self.accuracy, 4),
            "coverage": round(self.coverage, 4),
            "auto_accept_precision": None
            if self.auto_precision is None
            else round(self.auto_precision, 4),
            "per_category": self.per_category,
            "errors": [{"line_id": a, "expected": b, "predicted": c} for a, b, c in self.errors],
        }


def _label(decision: str, category: str) -> str:
    return "exclude" if decision == "exclude" else f"cat{category}" if category else decision


def read_labels(path: str | Path) -> dict[str, str]:
    with Path(path).open(newline="", encoding="utf-8-sig") as fh:
        return {
            r["line_id"]: _label(r["expected_decision"].strip(), r["expected_category"].strip())
            for r in csv.DictReader(fh)
        }


def evaluate(classified: Sequence[ClassifiedLine], labels: dict[str, str]) -> EvalReport:
    rows = [c for c in classified if c.line.line_id in labels]
    if not rows:
        raise ValueError("No overlap between classified lines and labels")

    def predicted(c: ClassifiedLine) -> str:
        cl = c.classification
        if cl.decision == Decision.EXCLUDE:
            return "exclude"
        if cl.decision == Decision.CLASSIFY and cl.scope3_category:
            return f"cat{int(cl.scope3_category)}"
        return "unsure"

    correct = sum(predicted(c) == labels[c.line.line_id] for c in rows)
    auto = [c for c in rows if c.status in (Status.AUTO_ACCEPTED, Status.EXCLUDED)]
    auto_correct = sum(predicted(c) == labels[c.line.line_id] for c in auto)

    tp: dict[str, int] = defaultdict(int)
    fp: dict[str, int] = defaultdict(int)
    fn: dict[str, int] = defaultdict(int)
    errors = []
    for c in rows:
        exp, got = labels[c.line.line_id], predicted(c)
        if exp == got:
            tp[exp] += 1
        else:
            fn[exp] += 1
            fp[got] += 1
            errors.append((c.line.line_id, exp, got))

    per_cat = {}
    for k in sorted(set(tp) | set(fn)):
        p_den, r_den = tp[k] + fp[k], tp[k] + fn[k]
        per_cat[k] = {
            "precision": round(tp[k] / p_den, 3) if p_den else 0.0,
            "recall": round(tp[k] / r_den, 3) if r_den else 0.0,
            "support": r_den,
        }

    return EvalReport(
        labelled=len(rows),
        accuracy=correct / len(rows),
        coverage=len(auto) / len(rows),
        auto_precision=auto_correct / len(auto) if auto else None,
        per_category=per_cat,
        errors=errors,
    )
