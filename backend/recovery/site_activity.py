"""Project case-scoped resident activity into the existing owner site feed."""
from __future__ import annotations

import json
import os

from fastapi import Request

from .platform.errors import PlatformError
from .platform.router import make_owner_dependency


def case_activity(request: Request, building_id: int, *, scenario: str | None = None,
                  reports_only: bool = False, replay: bool = False) -> list[dict]:
    store = getattr(request.app.state, "brace_recovery_store", None)
    if store is None:
        return []
    actor = make_owner_dependency(store)(request)
    try:
        bindings = json.loads(os.environ.get("BRACE_PREPARATION_CASES", "{}"))
    except ValueError:
        return []
    if not isinstance(bindings, dict):
        return []
    case_ids = {case for key, case in bindings.items()
                if key.partition(":")[0] == str(building_id) and isinstance(case, str)
                and (scenario is None or key == f"{building_id}:{scenario}")}
    rows = []
    for case_id in case_ids:
        try:
            snapshot = store.owner_snapshot(actor, case_id)
        except PlatformError as exc:
            if exc.status in (403, 404):
                continue
            raise
        if (snapshot.case.property_ref.id != str(building_id)
                or (replay and snapshot.case.mode != "scenario_exercise")):
            continue
        for report in snapshot.reports:
            if reports_only and report.status == "dismissed":
                continue
            location = report.location
            where = None
            if location and location.scan_id and location.binding in ("verified_unit", "verified_space"):
                where = {"scan_id": location.scan_id, "scan_name": location.label,
                         "room": location.label, "room_id": location.room_id,
                         "position_id": location.sweep_id, "thing": None}
            rows.append({"id": report.report_id, "at": report.received_at, "text": report.text,
                         "scan_id": where["scan_id"] if where else None, "where": where,
                         "src": ["resident:report"], "status": report.public_status_detail})
        for item in (() if reports_only else snapshot.support_requests):
            rows.append({"id": item.request_id, "at": item.received_at,
                         "text": f"Support request ({item.category}): {item.description}",
                         "scan_id": None, "where": None, "src": ["resident:support"],
                         "status": item.public_status_detail})
    return rows
