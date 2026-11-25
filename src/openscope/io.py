"""CSV import/export for activity data and results."""

from __future__ import annotations

import csv
import json
from collections.abc import Iterable
from datetime import date
from pathlib import Path

from pydantic import ValidationError

from openscope.errors import OpenScopeError
from openscope.models import ActivityRecord, EmissionResult

ACTIVITY_COLUMNS = [
    "activity_id",
    "description",
    "quantity",
    "unit",
    "scope",
    "scope3_category",
    "scope2_method",
    "factor_id",
    "method",
    "period_start",
    "period_end",
    "site",
    "supplier",
]


def read_activities(path: str | Path) -> list[ActivityRecord]:
    """Read activity data from CSV. Raises with the offending line number on bad rows."""
    path = Path(path)
    out: list[ActivityRecord] = []
    with path.open(newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        missing = {"activity_id", "quantity", "unit", "scope"} - set(reader.fieldnames or [])
        if missing:
            raise OpenScopeError(f"{path}: missing required columns {sorted(missing)}")
        for line, row in enumerate(reader, start=2):
            data = {k: v.strip() for k, v in row.items() if k and v is not None and v.strip()}
            try:
                out.append(ActivityRecord.model_validate(data))
            except ValidationError as exc:
                raise OpenScopeError(f"{path}:{line}: {exc}") from exc
    return out


RESULT_COLUMNS = [
    "activity_id",
    "scope",
    "scope3_category",
    "scope2_method",
    "method",
    "quantity",
    "unit",
    "factor_id",
    "factor_source",
    "factor_status",
    "gwp_set",
    "co2e_kg",
    "data_quality_score",
    "gas_kg",
    "trace",
]


def write_results(results: Iterable[EmissionResult], path: str | Path) -> None:
    with Path(path).open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=RESULT_COLUMNS)
        writer.writeheader()
        for r in results:
            writer.writerow(
                {
                    "activity_id": r.activity_id,
                    "scope": int(r.scope),
                    "scope3_category": int(r.scope3_category) if r.scope3_category else "",
                    "scope2_method": r.scope2_method.value if r.scope2_method else "",
                    "method": r.method.value,
                    "quantity": r.quantity,
                    "unit": r.unit,
                    "factor_id": r.factor_id,
                    "factor_source": r.factor_source,
                    "factor_status": r.factor_status.value,
                    "gwp_set": r.gwp_set,
                    "co2e_kg": round(r.co2e_kg, 6),
                    "data_quality_score": r.data_quality_score,
                    "gas_kg": json.dumps({k: round(v, 9) for k, v in r.gas_kg.items()}),
                    "trace": " | ".join(r.trace),
                }
            )


def _json_default(o: object) -> str:
    if isinstance(o, date):
        return o.isoformat()
    raise TypeError(type(o))


def dumps_json(obj: object) -> str:
    return json.dumps(obj, indent=2, default=_json_default)
