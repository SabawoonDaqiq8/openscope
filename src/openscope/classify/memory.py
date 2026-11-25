"""Supplier memory: decisions a reviewer confirmed, reused for future lines.

Most ledgers are dominated by a long tail of repeat suppliers. Once a reviewer has
confirmed how a supplier's spend should be treated, the same supplier is classified from
memory, with no model call and the reviewer named in the rationale.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from pydantic import BaseModel

from openscope.classify.models import Classification, Decision, LedgerLine, Source
from openscope.models import Scope3Category

_SUFFIXES = re.compile(
    r"\b(ltd|limited|llc|inc|incorporated|plc|gmbh|ag|sa|sas|bv|nv|co|corp|corporation|llp)\b\.?"
)


def normalise_supplier(name: str) -> str:
    s = name.lower()
    s = _SUFFIXES.sub(" ", s)
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return " ".join(s.split())


class MemoryEntry(BaseModel):
    decision: Decision
    scope3_category: Scope3Category | None = None
    factor_id: str | None = None
    reviewer: str
    reviewed_at: str


class SupplierMemory:
    def __init__(self, entries: dict[str, MemoryEntry] | None = None) -> None:
        self.entries = dict(entries or {})

    def __len__(self) -> int:
        return len(self.entries)

    def lookup(self, line: LedgerLine) -> Classification | None:
        key = normalise_supplier(line.supplier)
        if not key or (e := self.entries.get(key)) is None:
            return None
        return Classification(
            decision=e.decision,
            scope3_category=e.scope3_category,
            factor_id=e.factor_id,
            confidence=0.95,
            source=Source.MEMORY,
            rationale=f"supplier previously reviewed by {e.reviewer} ({e.reviewed_at[:10]})",
        )

    def remember(self, supplier: str, entry: MemoryEntry) -> None:
        key = normalise_supplier(supplier)
        if key:
            self.entries[key] = entry

    @classmethod
    def load(cls, path: str | Path) -> SupplierMemory:
        p = Path(path)
        if not p.exists():
            return cls()
        raw = json.loads(p.read_text(encoding="utf-8"))
        return cls({k: MemoryEntry.model_validate(v) for k, v in raw.items()})

    def save(self, path: str | Path) -> None:
        data = {k: v.model_dump(mode="json") for k, v in sorted(self.entries.items())}
        Path(path).write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
