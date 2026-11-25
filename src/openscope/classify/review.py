"""Human review round-trip.

1. ``write_review_csv``: one row per ledger line with the proposed classification and empty
   reviewer columns, sorted so the lines needing review come first.
2. The reviewer edits it in a spreadsheet: ``review_action`` = ``accept`` | ``override`` |
   ``exclude`` (blank = no decision), plus ``review_category`` / ``review_factor_id`` /
   ``review_note`` for overrides.
3. ``apply_review``: validates the decisions, writes an append-only JSONL audit log (who, when,
   before → after, why), teaches the supplier memory, and returns the final lines.
4. ``to_activities``: turns accepted lines into spend-based :class:`ActivityRecord`s for the
   calculation engine.
"""

from __future__ import annotations

import csv
import json
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path

from openscope.classify.memory import MemoryEntry, SupplierMemory
from openscope.classify.models import (
    Classification,
    ClassifiedLine,
    Decision,
    LedgerLine,
    Source,
    Status,
)
from openscope.errors import OpenScopeError
from openscope.models import ActivityRecord, CalculationMethod, Scope, Scope3Category

REVIEW_COLUMNS = [
    "line_id",
    "date",
    "supplier",
    "description",
    "account",
    "account_name",
    "amount",
    "currency",
    "status",
    "decision",
    "scope3_category",
    "factor_id",
    "confidence",
    "source",
    "rationale",
    "review_action",
    "review_category",
    "review_factor_id",
    "review_note",
]

_STATUS_ORDER = {Status.NEEDS_REVIEW: 0, Status.AUTO_ACCEPTED: 1, Status.EXCLUDED: 2}


def write_review_csv(classified: Sequence[ClassifiedLine], path: str | Path) -> None:
    rows = sorted(classified, key=lambda c: (_STATUS_ORDER.get(c.status, 3), -abs(c.line.amount)))
    with Path(path).open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=REVIEW_COLUMNS, lineterminator="\n")
        w.writeheader()
        for c in rows:
            ln, cl = c.line, c.classification
            w.writerow(
                {
                    "line_id": ln.line_id,
                    "date": ln.date.isoformat() if ln.date else "",
                    "supplier": ln.supplier,
                    "description": ln.description,
                    "account": ln.account,
                    "account_name": ln.account_name,
                    "amount": ln.amount,
                    "currency": ln.currency,
                    "status": c.status.value,
                    "decision": cl.decision.value,
                    "scope3_category": int(cl.scope3_category) if cl.scope3_category else "",
                    "factor_id": cl.factor_id or "",
                    "confidence": f"{cl.confidence:.2f}",
                    "source": cl.source.value,
                    "rationale": cl.rationale,
                    "review_action": "",
                    "review_category": "",
                    "review_factor_id": "",
                    "review_note": "",
                }
            )


def read_review_csv(path: str | Path) -> list[tuple[ClassifiedLine, dict[str, str]]]:
    out = []
    with Path(path).open(newline="", encoding="utf-8-sig") as fh:
        for n, row in enumerate(csv.DictReader(fh), start=2):
            try:
                line = LedgerLine(
                    line_id=row["line_id"],
                    description=row["description"],
                    supplier=row["supplier"],
                    amount=float(row["amount"]),
                    currency=row["currency"],
                    account=row["account"],
                    account_name=row["account_name"],
                    date=date.fromisoformat(row["date"]) if row["date"] else None,
                )
                cat = row["scope3_category"].strip()
                cl = Classification(
                    decision=Decision(row["decision"]),
                    scope3_category=Scope3Category(int(cat)) if cat else None,
                    factor_id=row["factor_id"].strip() or None,
                    confidence=float(row["confidence"]),
                    source=Source(row["source"]),
                    rationale=row["rationale"],
                )
                status = Status(row["status"])
            except (KeyError, ValueError) as exc:
                raise OpenScopeError(f"{path}:{n}: invalid review row: {exc}") from exc
            review = {
                k: (row.get(k) or "").strip() for k in REVIEW_COLUMNS if k.startswith("review_")
            }
            out.append((ClassifiedLine(line=line, classification=cl, status=status), review))
    return out


@dataclass
class ReviewOutcome:
    lines: list[ClassifiedLine]
    audit_entries: list[dict[str, object]] = field(default_factory=list)
    still_pending: list[str] = field(default_factory=list)


def apply_review(
    rows: Sequence[tuple[ClassifiedLine, dict[str, str]]],
    reviewer: str,
    *,
    known_factor_ids: set[str] | None = None,
    memory: SupplierMemory | None = None,
    now: datetime | None = None,
) -> ReviewOutcome:
    if not reviewer.strip():
        raise OpenScopeError("A reviewer name is required for the audit trail")
    ts = (now or datetime.now(UTC)).isoformat(timespec="seconds")
    outcome = ReviewOutcome(lines=[])

    for n, (c, review) in enumerate(rows, start=2):
        action = review.get("review_action", "").lower()
        before = c.classification
        if not action:
            outcome.lines.append(c)
            if c.status == Status.NEEDS_REVIEW:
                outcome.still_pending.append(c.line.line_id)
            continue

        if action == "accept":
            if before.decision == Decision.UNSURE or (
                before.decision == Decision.CLASSIFY and not before.factor_id
            ):
                raise OpenScopeError(
                    f"row {n} ({c.line.line_id}): cannot 'accept' an incomplete proposal; "
                    "use 'override' with review_category and review_factor_id"
                )
            after = before.model_copy(update={"source": Source.REVIEWER, "confidence": 1.0})
        elif action == "exclude":
            after = Classification(
                decision=Decision.EXCLUDE,
                confidence=1.0,
                source=Source.REVIEWER,
                rationale=review.get("review_note") or "excluded by reviewer",
            )
        elif action == "override":
            cat, fid = review.get("review_category", ""), review.get("review_factor_id", "")
            if not cat or not fid:
                raise OpenScopeError(
                    f"row {n} ({c.line.line_id}): override needs review_category and "
                    "review_factor_id"
                )
            if known_factor_ids is not None and fid not in known_factor_ids:
                raise OpenScopeError(f"row {n} ({c.line.line_id}): unknown factor_id '{fid}'")
            after = Classification(
                decision=Decision.CLASSIFY,
                scope3_category=Scope3Category(int(cat)),
                factor_id=fid,
                confidence=1.0,
                source=Source.REVIEWER,
                rationale=review.get("review_note") or "set by reviewer",
            )
        else:
            raise OpenScopeError(f"row {n} ({c.line.line_id}): unknown review_action '{action}'")

        outcome.lines.append(
            ClassifiedLine(
                line=c.line,
                classification=after,
                status=Status.EXCLUDED if after.decision == Decision.EXCLUDE else Status.REVIEWED,
            )
        )
        outcome.audit_entries.append(
            {
                "timestamp": ts,
                "reviewer": reviewer,
                "line_id": c.line.line_id,
                "action": action,
                "before": before.model_dump(mode="json"),
                "after": after.model_dump(mode="json"),
                "note": review.get("review_note", ""),
            }
        )
        if memory is not None and c.line.supplier:
            memory.remember(
                c.line.supplier,
                MemoryEntry(
                    decision=after.decision,
                    scope3_category=after.scope3_category,
                    factor_id=after.factor_id,
                    reviewer=reviewer,
                    reviewed_at=ts,
                ),
            )
    return outcome


def append_audit_log(entries: Sequence[dict[str, object]], path: str | Path) -> None:
    with Path(path).open("a", encoding="utf-8") as fh:
        for e in entries:
            fh.write(json.dumps(e, ensure_ascii=False) + "\n")


def to_activities(lines: Sequence[ClassifiedLine]) -> list[ActivityRecord]:
    """Accepted, classified lines → spend-based activities (excluded/pending lines skipped)."""
    acts = []
    for c in lines:
        cl = c.classification
        if c.status not in (Status.AUTO_ACCEPTED, Status.REVIEWED):
            continue
        if cl.decision != Decision.CLASSIFY or not cl.factor_id or not cl.scope3_category:
            continue
        acts.append(
            ActivityRecord(
                activity_id=c.line.line_id,
                description=f"{c.line.supplier} - {c.line.description}".strip(" -"),
                quantity=abs(c.line.amount),
                unit=c.line.currency,
                scope=Scope.SCOPE_3,
                scope3_category=cl.scope3_category,
                factor_id=cl.factor_id,
                method=CalculationMethod.SPEND_BASED,
                price_year=c.line.date.year if c.line.date else None,
                supplier=c.line.supplier or None,
            )
        )
    return acts
