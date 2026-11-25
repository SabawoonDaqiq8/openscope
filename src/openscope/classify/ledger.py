"""Reading ledger exports.

ERP exports name their columns differently (``Memo`` vs ``Narrative``, ``Vendor`` vs
``Supplier`` ...). Columns are matched case-insensitively against common aliases; anything
else can be mapped explicitly with ``column_map``.
"""

from __future__ import annotations

import csv
import re
from pathlib import Path

from pydantic import ValidationError

from openscope.classify.models import LedgerLine
from openscope.errors import OpenScopeError

ALIASES: dict[str, tuple[str, ...]] = {
    "line_id": ("line_id", "id", "transaction_id", "entry_id", "document_number", "doc_no"),
    "description": ("description", "memo", "narrative", "line_description", "text", "details"),
    "supplier": ("supplier", "vendor", "vendor_name", "supplier_name", "payee"),
    "amount": ("amount", "net_amount", "value", "debit", "amount_net"),
    "currency": ("currency", "ccy", "currency_code"),
    "account": ("account", "gl_account", "account_code", "gl_code", "nominal_code"),
    "account_name": ("account_name", "gl_account_name", "account_description", "nominal_name"),
    "date": ("date", "posting_date", "invoice_date", "transaction_date"),
    "cost_center": ("cost_center", "cost_centre", "department"),
}


def _norm(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.strip().lower()).strip("_")


def _resolve_columns(header: list[str], column_map: dict[str, str] | None) -> dict[str, str]:
    lower = {_norm(h): h for h in header}
    resolved: dict[str, str] = {}
    for field, aliases in ALIASES.items():
        if column_map and field in column_map:
            if column_map[field] not in header:
                raise OpenScopeError(f"Mapped column '{column_map[field]}' not in ledger header")
            resolved[field] = column_map[field]
            continue
        for alias in aliases:
            if alias in lower:
                resolved[field] = lower[alias]
                break
    missing = {"amount", "currency"} - set(resolved)
    if missing:
        raise OpenScopeError(f"Ledger is missing required columns: {sorted(missing)}")
    return resolved


def read_ledger(
    path: str | Path,
    column_map: dict[str, str] | None = None,
    default_currency: str | None = None,
) -> list[LedgerLine]:
    path = Path(path)
    with path.open(newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        header = list(reader.fieldnames or [])
        if default_currency and not any(_norm(h) in ALIASES["currency"] for h in header):
            header = [*header, "__currency"]
            column_map = {**(column_map or {}), "currency": "__currency"}
        cols = _resolve_columns(header, column_map)
        lines: list[LedgerLine] = []
        for n, row in enumerate(reader, start=2):
            if default_currency:
                row.setdefault("__currency", default_currency)
            data = {f: (row.get(c) or "").strip() for f, c in cols.items()}
            data.setdefault("line_id", "")
            if not data["line_id"]:
                data["line_id"] = f"L{n - 1:05d}"
            data["amount"] = data["amount"].replace(",", "")
            if not data.get("date"):
                data.pop("date", None)
            try:
                lines.append(LedgerLine.model_validate(data))
            except ValidationError as exc:
                raise OpenScopeError(f"{path}:{n}: {exc}") from exc
    ids = [ln.line_id for ln in lines]
    if len(ids) != len(set(ids)):
        raise OpenScopeError(f"{path}: duplicate line ids")
    return lines
