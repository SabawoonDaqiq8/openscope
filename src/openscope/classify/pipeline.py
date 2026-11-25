"""Hybrid classification pipeline: rules → supplier memory → LLM → human review."""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Sequence
from dataclasses import dataclass

from openscope.classify.llm import LLMClassifier
from openscope.classify.memory import SupplierMemory
from openscope.classify.models import (
    Classification,
    ClassifiedLine,
    Decision,
    LedgerLine,
    Source,
    Status,
)
from openscope.classify.rules import RuleSet

UNCLASSIFIED = Classification(
    decision=Decision.UNSURE,
    confidence=0.0,
    source=Source.NONE,
    rationale="no rule, memory or model decision",
)


@dataclass
class PipelineConfig:
    threshold: float = 0.85  # minimum confidence to skip human review
    require_factor: bool = True  # a classified line without a factor needs review


def status_for(c: Classification, cfg: PipelineConfig) -> Status:
    trusted = c.source in (Source.RULE, Source.REVIEWER) or c.confidence >= cfg.threshold
    if c.decision == Decision.EXCLUDE:
        return Status.EXCLUDED if trusted else Status.NEEDS_REVIEW
    if c.decision == Decision.CLASSIFY:
        if cfg.require_factor and not c.factor_id:
            return Status.NEEDS_REVIEW
        return Status.AUTO_ACCEPTED if trusted else Status.NEEDS_REVIEW
    return Status.NEEDS_REVIEW


def classify_ledger(
    lines: Sequence[LedgerLine],
    rules: RuleSet | None = None,
    memory: SupplierMemory | None = None,
    llm: LLMClassifier | None = None,
    config: PipelineConfig | None = None,
) -> list[ClassifiedLine]:
    cfg = config or PipelineConfig()
    decided: dict[str, Classification] = {}

    for ln in lines:
        if rules and (rule := rules.match(ln)):
            decided[ln.line_id] = rule.classification()
        elif memory and (hit := memory.lookup(ln)):
            decided[ln.line_id] = hit

    if llm is not None:
        pending = [ln for ln in lines if ln.line_id not in decided]
        if pending:
            decided.update(llm.classify(pending))

    out = []
    for ln in lines:
        c = decided.get(ln.line_id, UNCLASSIFIED)
        out.append(ClassifiedLine(line=ln, classification=c, status=status_for(c, cfg)))
    return out


def summarise(classified: Sequence[ClassifiedLine]) -> dict[str, object]:
    by_status = Counter(c.status.value for c in classified)
    by_source = Counter(c.classification.source.value for c in classified)
    spend_by_status: dict[str, float] = defaultdict(float)
    for c in classified:
        spend_by_status[c.status.value] += abs(c.line.amount)
    total = sum(spend_by_status.values()) or 1.0
    spend_by_status.setdefault(Status.NEEDS_REVIEW.value, 0.0)
    return {
        "lines": len(classified),
        "by_status": dict(by_status),
        "by_source": dict(by_source),
        "spend_share_needing_review": round(spend_by_status[Status.NEEDS_REVIEW.value] / total, 4),
    }
