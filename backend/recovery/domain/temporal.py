"""Conservative source-time comparisons, preserving date-only precision."""
from __future__ import annotations

from datetime import datetime, time, timedelta, timezone

UTC = timezone.utc
MODES = {"observed_recovery", "historical_replay", "scenario_exercise"}


def date_bounds(value: str) -> tuple[datetime, datetime]:
    """Date-only input occupies the whole UTC day; timestamps require a zone."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError("A nonempty source date is required")
    value = value.strip()
    if len(value) == 10:
        day = datetime.strptime(value, "%Y-%m-%d").date()
        start = datetime.combine(day, time.min, UTC)
        return start, start + timedelta(days=1) - timedelta(microseconds=1)
    try:
        instant = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        # Legacy Vexcel XMP dates, not an inferred capture date.
        instant = datetime.strptime(value, "%a %b %d %H:%M:%S UTC %Y").replace(tzinfo=UTC)
    if instant.tzinfo is None:
        raise ValueError("Source timestamps require a timezone")
    instant = instant.astimezone(UTC)
    return instant, instant


def normalize_date(value: str | None) -> str | None:
    if not value:
        return None
    try:
        start, end = date_bounds(value)
    except (ValueError, TypeError):
        return None
    return value if len(value) == 10 else start.isoformat().replace("+00:00", "Z")


def source_eligibility(occurred_at: str | None, available_at: str | None,
                       cutoff: str, mode: str) -> tuple[bool, str | None]:
    if mode not in MODES:
        raise ValueError("Unknown recovery case mode")
    _, end = date_bounds(cutoff)
    occurrence = normalize_date(occurred_at)
    availability = normalize_date(available_at)
    if occurred_at and occurrence is None:
        return False, "Source occurrence date is invalid"
    if available_at and availability is None:
        return False, "Source availability date is invalid"
    if occurrence and date_bounds(occurrence)[1] > end:
        return False, "Source occurrence is after the assessment cutoff"
    if availability and date_bounds(availability)[1] > end:
        return False, "Source became available after the assessment cutoff"
    if mode == "historical_replay" and (not occurrence or not availability):
        return False, "Historical replay requires known occurrence and availability dates"
    return True, None


def relative_to_incident(captured_at: str | None, incident_at: str) -> str:
    captured = normalize_date(captured_at)
    if captured is None:
        return "unknown"
    start, end = date_bounds(captured)
    incident_start, incident_end = date_bounds(incident_at)
    if end < incident_start:
        return "before"
    if start > incident_end:
        return "after"
    return "overlapping"


def select_capture_pair(captures: list[dict], incident_at: str, cutoff: str,
                        mode: str = "scenario_exercise") -> dict:
    """Nearest eligible dated flights; no pair is itself a damage finding."""
    eligible = [c for c in captures if source_eligibility(c.get("date"), c.get("available_at"), cutoff, mode)[0]]
    incident_start, incident_end = date_bounds(incident_at)

    def window(c):
        last = normalize_date(c.get("last_date") or c.get("date"))
        # New inventories declare a capture window. An unknown start must not
        # turn a mosaic ending after the incident into a wholly post-incident view.
        first = normalize_date(c.get("first_date") if "first_date" in c else c.get("date"))
        if not last or (first and date_bounds(first)[0] > date_bounds(last)[1]):
            return None
        if date_bounds(last)[1] > date_bounds(cutoff)[1]:
            return None
        return (date_bounds(first)[0] if first else None, date_bounds(last)[1])

    windows = [(c, window(c)) for c in eligible]
    before = [(c, w) for c, w in windows if w and w[1] < incident_start]
    after = [(c, w) for c, w in windows if w and w[0] is not None and w[0] > incident_end]
    return {
        "before": max(before, key=lambda item: item[1][1])[0] if before else None,
        "after": min(after, key=lambda item: item[1][0])[0] if after else None,
        "limitation": "Flights can differ in season, lighting and resolution. A visual change needs review; it does not establish cause or hidden damage.",
    }
