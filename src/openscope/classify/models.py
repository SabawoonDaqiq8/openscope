"""Data models for ledger classification."""

from __future__ import annotations

import datetime as dt
from enum import StrEnum

from pydantic import BaseModel, Field

from openscope.models import Scope3Category


class LedgerLine(BaseModel):
    """One line of a general-ledger / accounts-payable export."""

    line_id: str
    description: str = ""
    supplier: str = ""
    amount: float
    currency: str
    account: str = ""
    account_name: str = ""
    date: dt.date | None = None
    cost_center: str = ""

    def prompt_view(self) -> dict[str, object]:
        """The fields shown to the language model (no internal identifiers beyond line_id)."""
        return {
            "line_id": self.line_id,
            "description": self.description,
            "supplier": self.supplier,
            "account": self.account,
            "account_name": self.account_name,
            "amount": round(self.amount, 2),
            "currency": self.currency,
        }


class Decision(StrEnum):
    CLASSIFY = "classify"  # in scope 3 inventory: category (+ factor)
    EXCLUDE = "exclude"  # not an emissions-relevant purchase (payroll, tax, ...)
    UNSURE = "unsure"


class Source(StrEnum):
    RULE = "rule"
    MEMORY = "memory"
    LLM = "llm"
    REVIEWER = "reviewer"
    NONE = "none"


class Status(StrEnum):
    AUTO_ACCEPTED = "auto_accepted"
    NEEDS_REVIEW = "needs_review"
    EXCLUDED = "excluded"
    REVIEWED = "reviewed"


class Classification(BaseModel):
    decision: Decision
    scope3_category: Scope3Category | None = None
    factor_id: str | None = None
    confidence: float = Field(ge=0, le=1)
    source: Source
    rationale: str = ""


class ClassifiedLine(BaseModel):
    line: LedgerLine
    classification: Classification
    status: Status
