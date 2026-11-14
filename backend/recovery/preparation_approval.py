"""Bridge the existing walkthrough approval to the authenticated resident feed."""
from __future__ import annotations

import hashlib
import json
import logging
import os

from fastapi import HTTPException, Request

from .platform.errors import PlatformError
from .platform.router import check_origin, make_owner_dependency


def approve_notice(request: Request, *, building: int, scenario: str, step: str | None,
                   action_id: str, plan: dict) -> dict:
    store = getattr(request.app.state, "brace_recovery_store", None)
    if store is None:
        raise HTTPException(503, "Resident delivery is not enabled. Enable recovery before approving a notice.")
    actor = make_owner_dependency(store)(request)
    try:
        check_origin(request)
        # Explicit binding: never select a case by name, recency, or a client role.
        bindings = json.loads(os.environ.get("BRACE_PREPARATION_CASES", "{}"))
        case_id = bindings.get(f"{building}:{scenario}")
        if not isinstance(case_id, str) or not case_id:
            raise HTTPException(409, "This building and scenario have no resident case binding.")
        snapshot = store.owner_snapshot(actor, case_id)
        if snapshot.case.property_ref.id != str(building):
            raise HTTPException(409, "The configured resident case belongs to a different property.")
        if plan.get("threat", {}).get("replay") and snapshot.case.mode != "scenario_exercise":
            raise HTTPException(409, "A historical preparation demo must publish only to an exercise case.")
        notices = [m for m in plan.get("messages", [])
                   if m.get("kind") == "notice" and action_id in m.get("action_ids", [])]
        if len(notices) != 1:
            raise HTTPException(409, "Approve an action linked to exactly one resident notice.")
        notice = notices[0]
        # Content and forecast step form the durable approval identity. A new
        # forecast can send a new update; retries of this one cannot duplicate it.
        digest = hashlib.sha256(json.dumps(
            [building, scenario, step, notice], sort_keys=True, separators=(",", ":")
        ).encode()).hexdigest()
        publication = store.publish_preparation_notice(
            actor, case_id, approval_key="prepare:" + digest,
            title=notice["subject"], body=notice["body"],
            source_ids=[f"preparation:{building}:{scenario}:{step or 'now'}:{notice['id']}:{digest}"])
        say = "Approved. The notice is now published in the residents' private Brace updates."
        queued = 0
        photon = getattr(request.app.state, "brace_photon_service", None)
        if photon is not None:
            try:
                queued = photon.queue_notice(
                    case_id, publication["notice_id"], notice["subject"], notice["body"],
                    property_name=snapshot.case.property_name, threat=plan.get("threat"))
            except Exception:
                logging.getLogger(__name__).warning("Could not queue a Photon notice")
                queued = None
            if queued:
                say += " Brace also queued it for linked iMessage conversations."
        return {"ok": True, "say": say, "photon_queued": queued,
                "delivery": "resident_feed", "case_id": case_id,
                "household_count": len(snapshot.household_labels), **publication}
    except (json.JSONDecodeError, AttributeError):
        raise HTTPException(503, "The preparation-to-resident case binding is invalid.") from None
    except PlatformError as exc:
        raise HTTPException(exc.status, detail=exc.envelope()["error"]) from None
