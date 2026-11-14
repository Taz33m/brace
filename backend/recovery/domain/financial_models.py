"""Small, dependency-free financial primitives. Unknown money is never zero."""
from __future__ import annotations

from datetime import date, datetime, time, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any


class FinancialInputError(ValueError):
    pass


def number(value: Any, label: str, *, positive: bool = False) -> Decimal:
    if value is None or isinstance(value, bool):
        raise FinancialInputError(f"{label} is missing or is not a number.")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise FinancialInputError(f"{label} is not a number.") from None
    if not result.is_finite() or result < 0 or (positive and result == 0):
        raise FinancialInputError(f"{label} must be finite and {'positive' if positive else 'nonnegative'}.")
    # Keep JSON and downstream browser arithmetic finite, too.
    if result > Decimal('1e15'):
        raise FinancialInputError(f"{label} exceeds the supported numeric range.")
    return result


def bounds(low: Any, high: Any, label: str) -> tuple[Decimal, Decimal]:
    a, b = number(low, f"{label} low"), number(high, f"{label} high")
    if a > b:
        raise FinancialInputError(f"{label} low exceeds high.")
    return a, b


def instant(value: str | None, *, end: bool = False) -> datetime:
    if not value or not isinstance(value, str):
        raise FinancialInputError("A dated source or effective date is required.")
    try:
        if len(value) == 10:
            return datetime.combine(date.fromisoformat(value), time.max if end else time.min, timezone.utc)
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError("timezone required")
        return parsed.astimezone(timezone.utc)
    except ValueError:
        raise FinancialInputError("Source dates must be ISO dates or timezone-aware timestamps.") from None


def money(low: Decimal, high: Decimal, *, method: str, source_ids: list[str],
          basis: str = "conditional", range_kind: str = "scenario", point: Decimal | None = None) -> dict:
    def dollars(value: Decimal | None) -> float | None:
        if value is None:
            return None
        return float(number(value, "calculated amount").quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
    if low > high:
        raise FinancialInputError("Calculated range is inverted.")
    if point is not None and not low <= point <= high:
        raise FinancialInputError("Calculated point lies outside the range.")
    return {"currency": "USD", "low": dollars(low), "high": dollars(high), "point": dollars(point),
            "basis": basis, "range_kind": range_kind, "method": method,
            "source_ids": list(dict.fromkeys(source_ids)), "unavailable_reason": None}


def unavailable(reason: str, *, method: str = "Not calculated") -> dict:
    return {"currency": "USD", "low": None, "high": None, "point": None,
            "basis": "insufficient_evidence", "range_kind": "source_range", "method": method,
            "source_ids": [], "unavailable_reason": reason}


def source_index(evidence: list[dict]) -> dict[str, dict]:
    result = {}
    for row in evidence:
        for key in (row.get("evidence_id"), row.get("source_id")):
            if key:
                result[str(key)] = row
    return result


def validate_sources(source_ids: Any, evidence: dict[str, dict], context: dict,
                     *, kinds: set[str] | None = None) -> list[str]:
    if not isinstance(source_ids, list) or not source_ids or not all(isinstance(x, str) for x in source_ids):
        raise FinancialInputError("A nonempty list of source IDs is required.")
    cutoff = instant(context["assessment_as_of"], end=True)
    for sid in source_ids:
        row = evidence.get(sid)
        if row is None:
            raise FinancialInputError(f"Financial source {sid} is not in the evidence inventory.")
        if kinds and row.get("kind") not in kinds:
            raise FinancialInputError(f"Source {sid} is not a suitable financial or inspection source.")
        occurred = row.get("effective_at") or row.get("captured_at")
        if instant(occurred, end=True) > cutoff:
            raise FinancialInputError(f"Financial source {sid} is later than the assessment cutoff.")
        available = row.get("available_at")
        if context.get("mode") == "historical_replay" and not available:
            raise FinancialInputError(f"Financial source {sid} has no established historical availability.")
        if available and instant(available, end=True) > cutoff:
            raise FinancialInputError(f"Financial source {sid} was unavailable at the assessment cutoff.")
    return list(dict.fromkeys(source_ids))


def same_effective_date(value: Any, context: dict) -> None:
    # A future restored appraisal cannot be deducted without a discount model.
    if instant(value) != instant(context["assessment_as_of"]):
        raise FinancialInputError("The financial estimate and assessment must have the same effective date.")


def assumption(aid: str, label: str, value: str, source_ids: list[str], basis: str = "source") -> dict:
    return {"assumption_id": aid, "label": label, "value": value, "basis": basis,
            "source_ids": list(dict.fromkeys(source_ids))}


def validate_financial_shape(value: Any) -> dict:
    """Reject malformed containers before they can leak into output or crash math.

    This is boundary validation, not source verification. Numeric/date semantics
    remain checked by the individual calculations and their evidence rules.
    """
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise FinancialInputError("Financial assumptions must be an object.")
    records = []
    for field in ("repairs", "reviewed_values"):
        items = value.get(field)
        if items is None:
            continue
        if not isinstance(items, list) or any(not isinstance(item, dict) for item in items):
            raise FinancialInputError(f"Financial {field} must be a list of objects.")
        records.extend(items)
    downtime = value.get("downtime")
    if downtime is not None:
        if not isinstance(downtime, dict):
            raise FinancialInputError("Financial downtime must be an object.")
        records.append(downtime)
    records.append(value)
    text_fields = {"line_id", "scope_key", "description", "quantity_unit", "quantity_basis", "basis",
                   "condition", "method", "reviewed_by", "review_note"}
    for row in records:
        for field in text_fields:
            if row.get(field) is not None and not isinstance(row[field], str):
                raise FinancialInputError(f"Financial {field} must be text.")
        for field in ("source_ids", "observation_ids", "repair_scope_source_ids"):
            refs = row.get(field)
            if refs is not None and (not isinstance(refs, list) or any(not isinstance(ref, str) or not ref for ref in refs)):
                raise FinancialInputError(f"Financial {field} must be a list of nonempty source identifiers.")
        location = row.get("location")
        if location is not None and (not isinstance(location, dict) or not isinstance(location.get("location_id"), str)):
            raise FinancialInputError("Financial location must be an identified location object.")
    return value
