"""Deterministic classification rules.

Rules run before any model call. They are cheap, explainable and exact, so they handle
what accountants already know: GL accounts that are never emissions-relevant (payroll,
taxes, depreciation…), and supplier or keyword mappings you have decided on.

Rules CSV columns
-----------------
``rule_id, field, pattern, decision, scope3_category, factor_id, note``

* ``field``: ``description`` | ``supplier`` | ``account`` | ``account_name`` | ``any``
* ``pattern``: case-insensitive regular expression (``re.search``)
* ``decision``: ``exclude`` or ``classify``
First matching rule wins (file order).
"""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from importlib import resources
from pathlib import Path

from openscope.classify.models import Classification, Decision, LedgerLine, Source
from openscope.errors import OpenScopeError
from openscope.models import Scope3Category

_FIELDS = ("description", "supplier", "account", "account_name", "any")


@dataclass(frozen=True)
class Rule:
    rule_id: str
    field: str
    pattern: re.Pattern[str]
    decision: Decision
    scope3_category: Scope3Category | None = None
    factor_id: str | None = None
    note: str = ""

    def matches(self, line: LedgerLine) -> bool:
        if self.field == "any":
            text = " ".join((line.description, line.supplier, line.account, line.account_name))
        else:
            text = str(getattr(line, self.field))
        return bool(self.pattern.search(text))

    def classification(self) -> Classification:
        return Classification(
            decision=self.decision,
            scope3_category=self.scope3_category,
            factor_id=self.factor_id,
            confidence=1.0,
            source=Source.RULE,
            rationale=f"rule {self.rule_id}: {self.note}".rstrip(": "),
        )


class RuleSet:
    def __init__(self, rules: list[Rule] | None = None) -> None:
        self.rules = list(rules or [])

    def __len__(self) -> int:
        return len(self.rules)

    def __add__(self, other: RuleSet) -> RuleSet:
        return RuleSet(self.rules + other.rules)

    def match(self, line: LedgerLine) -> Rule | None:
        return next((r for r in self.rules if r.matches(line)), None)

    @classmethod
    def from_csv(cls, path: str | Path) -> RuleSet:
        with Path(path).open(newline="", encoding="utf-8") as fh:
            return cls._parse(fh.read().splitlines(), str(path))

    @classmethod
    def default(cls) -> RuleSet:
        """Bundled exclusion rules for spend that is not a Scope 3 purchase."""
        ref = resources.files("openscope.classify").joinpath("default_rules.csv")
        return cls._parse(ref.read_text(encoding="utf-8").splitlines(), "default_rules.csv")

    @classmethod
    def _parse(cls, lines: list[str], origin: str) -> RuleSet:
        reader = csv.DictReader(ln for ln in lines if not ln.lstrip().startswith("#"))
        rules: list[Rule] = []
        for n, row in enumerate(reader, start=2):
            try:
                field = row["field"].strip()
                if field not in _FIELDS:
                    raise ValueError(f"field must be one of {_FIELDS}")
                decision = Decision(row["decision"].strip())
                if decision == Decision.UNSURE:
                    raise ValueError("rules must be 'exclude' or 'classify'")
                cat = (row.get("scope3_category") or "").strip()
                if decision == Decision.CLASSIFY and not cat:
                    raise ValueError("classify rules need a scope3_category")
                rules.append(
                    Rule(
                        rule_id=row["rule_id"].strip(),
                        field=field,
                        pattern=re.compile(row["pattern"], re.IGNORECASE),
                        decision=decision,
                        scope3_category=Scope3Category(int(cat)) if cat else None,
                        factor_id=(row.get("factor_id") or "").strip() or None,
                        note=(row.get("note") or "").strip(),
                    )
                )
            except (KeyError, ValueError, re.error) as exc:
                raise OpenScopeError(f"{origin}:{n}: invalid rule: {exc}") from exc
        return cls(rules)
