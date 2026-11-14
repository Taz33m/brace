"""Frozen assessment inputs and the platform's background-worker integration.

No network, database, or worker starts at import. The platform owns authentication,
transactions, publication, and the final revision comparison at commit time.
"""
from __future__ import annotations

import base64
from concurrent.futures import Future, ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime, timezone
from hashlib import sha256
from io import BytesIO
import json
import math
from pathlib import Path
from threading import Lock
from typing import Any, Callable, Protocol
from uuid import uuid4

from PIL import Image, ImageOps


MODES = {
    "scenario_exercise": "Scenario exercise — hypothetical impacts; source data is real",
    "historical_replay": "Historical replay — only evidence demonstrably available by the cutoff",
    "observed_recovery": "Observed recovery — reports still require verification",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def make_case_seed(inventory: dict, *, incident_name: str, incident_at: str,
                   assessment_as_of: str, mode: str = "scenario_exercise",
                   case_id: str | None = None) -> dict:
    """A real-data owner snapshot without invented damage, residents, or tasks."""
    from .temporal import date_bounds

    if mode not in MODES:
        raise ValueError("Unknown recovery case mode")
    incident_bounds, cutoff_bounds = date_bounds(incident_at), date_bounds(assessment_as_of)
    if cutoff_bounds[1] < incident_bounds[0]:
        raise ValueError("Recovery assessment cutoff precedes the incident")
    if not incident_name.strip():
        raise ValueError("An incident name is required")
    subject = inventory["subject"]
    identity = [str(subject["id"]), incident_at, assessment_as_of, mode]
    case_id = case_id or "case_" + sha256(json.dumps(identity).encode()).hexdigest()[:20]
    case = {
        "case_id": case_id,
        "property_ref": {"dataset": "commercial_property", "id": str(subject["id"])},
        "property_name": subject.get("name") or subject.get("address") or str(subject["id"]),
        "address": subject.get("address") or "", "city": subject.get("city") or "",
        "incident_name": incident_name.strip(), "incident_at": incident_at,
        "assessment_as_of": assessment_as_of, "mode": mode, "mode_label": MODES[mode],
        "case_revision": 1, "analysis_revision": 1, "pending_reports": 0, "pending_tasks": 0,
        "next_action": "Review dated evidence and obtain verified condition and cost inputs",
    }
    return {"case": case, "evidence": deepcopy(inventory.get("evidence", [])),
            "observations": [], "assessments": [], "current_assessment_id": None,
            "tasks": [], "reports": [], "support_requests": [], "notices": [],
            "household_labels": [], "events": [], "event_cursor": 0}


def valuation_inputs(inventory: dict, snapshot: dict, financial_assumptions: dict | None = None) -> dict:
    """Use case evidence (including new reports/reviews), never a stale source copy."""
    inputs = deepcopy({"subject": inventory["subject"], "sales": inventory.get("sales", []),
                     "evidence": snapshot["evidence"],
                     "locations": inventory.get("locations", []), "scans": inventory.get("scans", []),
                     "structures": inventory.get("structures", []),
                     "source_status": inventory.get("source_status", {}),
                     "limitations": inventory.get("limitations", []),
                     "capture_pairs": inventory.get("capture_pairs", {}),
                     "image_availability": {
                         e["evidence_id"]: (
                             "cached" if inventory.get("assets", {}).get(e["evidence_id"], {}).get("kind") == "local_image"
                             else "requires_fetch" if e["evidence_id"] in inventory.get("assets", {})
                             else "metadata_only"
                         ) for e in snapshot["evidence"]
                     },
                     "source_fetch_allowed": False,
                     "financial_assumptions": financial_assumptions or {}})
    pair = inputs["capture_pairs"]
    evidence = {row["evidence_id"]: row for row in snapshot["evidence"]}
    inspection = {"limitation": pair.get("limitation", "Capture dates and visual changes do not establish damage or causation.")}
    for side in ("before", "after"):
        capture = pair.get(side) or {}
        identity = capture.get("evidence_id")
        row = evidence.get(identity)
        inspection[side] = ({**{key: capture.get(key) for key in
                               ("collection", "layer", "first_date", "last_date")},
                             "evidence_id": identity, "image_status": inputs["image_availability"].get(identity)}
                            if row and row.get("kind") == "vexcel_image" else None)
    inspection["ready"] = all(inspection[side] and inspection[side]["image_status"] == "cached"
                              for side in ("before", "after")) and inspection["before"]["evidence_id"] != inspection["after"]["evidence_id"]
    inputs["pair_inspection"] = inspection
    return inputs


def screen_case(snapshot: dict, inputs: dict) -> dict:
    """An explicit deterministic screen; never misrepresented as an agent run."""
    from .valuation import evaluate_valuation

    return {"kind": "deterministic_screen", "case_id": snapshot["case"]["case_id"],
            "base_analysis_revision": snapshot["case"]["analysis_revision"],
            "valuation": evaluate_valuation(deepcopy(inputs), deepcopy(snapshot["observations"]),
                                            deepcopy(snapshot["case"]))}


class EvidenceImages:
    """Resolve only server-created, case-scoped image descriptors.

    Paths are checked against trusted roots, bytes are decoded/re-encoded without
    EXIF, and each image is bounded before sending to the model. No arbitrary URLs.
    The same evidence ID is retained in tool output and the owner interface.
    """

    def __init__(self, assets: dict, evidence: list[dict], *, allow_network: bool = False,
                 cache_root: Path | None = None):
        from ...config import CACHE_DIR

        self.assets = deepcopy(assets)
        self.allowed = {e["evidence_id"] for e in evidence}
        self.allow_network = allow_network
        self.cache_root = (cache_root or CACHE_DIR).resolve()

    def __call__(self, evidence_id: str) -> list[dict]:
        if evidence_id not in self.allowed or evidence_id not in self.assets:
            raise ValueError("No authorized image is available for this evidence")
        descriptor = self.assets[evidence_id]
        path = self._resolve(descriptor)
        path = path.resolve()
        if not path.is_relative_to(self.cache_root):
            raise ValueError("Image path is outside the trusted evidence cache")
        if not path.is_file():
            raise ValueError("Image bytes are unavailable; enable explicit source fetching")
        if path.stat().st_size > 25 * 1024 * 1024:
            raise ValueError("Evidence image exceeds the 25 MB input limit")
        raw = path.read_bytes()
        expected_hash = descriptor.get("sha256")
        if expected_hash and sha256(raw).hexdigest() != expected_hash:
            raise ValueError("Evidence image changed after this assessment snapshot")
        with Image.open(BytesIO(raw)) as source:
            if source.width * source.height > 40_000_000:
                raise ValueError("Evidence image exceeds the pixel limit")
            image = ImageOps.exif_transpose(source).convert("RGB")
            image.thumbnail((1536, 1536))
            buf = BytesIO()
            image.save(buf, "JPEG", quality=85)
        return [{"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                              "data": base64.b64encode(buf.getvalue()).decode()}}]

    def _resolve(self, descriptor: dict) -> Path:
        kind = descriptor.get("kind")
        if kind == "local_image":
            return Path(descriptor["path"])
        if kind == "matterport_face":
            from ... import matterport

            model, sweep, face = descriptor["model_id"], descriptor["sweep_id"], descriptor["face"]
            if not isinstance(face, int) or face not in range(6):
                raise ValueError("Invalid panorama face")
            if any(not isinstance(s, str) or not s.isalnum() for s in (model, sweep)):
                raise ValueError("Invalid panorama identity")
            cached = matterport._face_path(model, sweep, face)
            if cached.exists() or not self.allow_network:
                return cached
            return matterport.face_image(model, sweep, face)
        if kind == "vexcel_capture":
            from ... import vexcel

            if not descriptor.get("collection"):
                raise ValueError("A dated capture requires an explicit collection")
            strict = any(key in descriptor for key in ("role", "incident_at", "assessment_as_of", "property_point"))
            if strict and (descriptor.get("role") not in {"before", "after"} or not all(
                descriptor.get(key) for key in ("layers", "expected_date", "incident_at", "assessment_as_of", "property_point")
            )):
                raise ValueError("A dated pair requires its layer, capture window, incident, cutoff and property point")
            try:
                path, metadata = vexcel.ortho(descriptor["area_wkt"], collection=descriptor["collection"],
                    layers=descriptor.get("layers"), buffer_m=descriptor.get("buffer_m", 8),
                    max_px=(1536, 1536), cached_only=not self.allow_network)
            except FileNotFoundError:
                raise ValueError("Capture image has not been fetched") from None
            if metadata.get("collection") != descriptor["collection"]:
                raise ValueError("Returned imagery does not match the selected capture")
            if descriptor.get("layers") and metadata.get("layer") not in {
                layer.strip() for layer in descriptor["layers"].split(",") if layer.strip()
            }:
                raise ValueError("Returned imagery does not match the selected layer")
            if descriptor.get("expected_date"):
                from .temporal import date_bounds

                start, end = date_bounds(descriptor["expected_date"])
                actual_start, actual_end = date_bounds(metadata.get("last_capture") or metadata.get("last_date"))
                if descriptor.get("expected_first_date"):
                    start = date_bounds(descriptor["expected_first_date"])[0]
                    actual_start = date_bounds(metadata.get("first_capture") or metadata.get("first_date"))[0]
                if actual_start < start or actual_end > end or actual_start > actual_end:
                    raise ValueError("Returned imagery does not match the selected capture date")
            if strict:
                self._validate_capture_context(descriptor, metadata)
            return path
        raise ValueError("Unsupported image descriptor")

    @staticmethod
    def _validate_capture_context(descriptor: dict, metadata: dict) -> None:
        from shapely import wkt
        from shapely.geometry import Point, box
        from .temporal import date_bounds

        first = date_bounds(metadata.get("first_capture") or metadata.get("first_date"))[0]
        last = date_bounds(metadata.get("last_capture") or metadata.get("last_date"))[1]
        incident_start, incident_end = date_bounds(descriptor["incident_at"])
        cutoff = date_bounds(descriptor["assessment_as_of"])[1]
        if first > last or last > cutoff:
            raise ValueError("Returned capture window is reversed or after the assessment cutoff")
        if (descriptor["role"] == "before" and last >= incident_start or
                descriptor["role"] == "after" and first <= incident_end):
            raise ValueError("Returned capture window is not wholly on the selected incident side")
        bounds = metadata.get("bounds")
        if (not isinstance(bounds, (list, tuple)) or len(bounds) != 4 or
                any(isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) for value in bounds) or
                not (-180 <= bounds[0] < bounds[2] <= 180 and -90 <= bounds[1] < bounds[3] <= 90)):
            raise ValueError("Returned imagery has no valid geographic bounds")
        point = descriptor["property_point"]
        coordinates = [point.get("longitude"), point.get("latitude")] if isinstance(point, dict) else []
        if (len(coordinates) != 2 or any(isinstance(value, bool) or not isinstance(value, (int, float)) or
                                      not math.isfinite(value) for value in coordinates)):
            raise ValueError("A valid property point is required for capture coverage")
        requested = wkt.loads(descriptor["area_wkt"])
        footprint = box(*bounds).buffer(1e-7)  # numeric rounding only, less than two centimetres
        if requested.is_empty or not requested.is_valid or not footprint.covers(requested) or not footprint.covers(Point(*coordinates)):
            raise ValueError("Returned imagery does not cover the requested area and property")


class AnalysisStore(Protocol):
    def snapshot_for_analysis(self, case_id: str) -> dict:
        """Return OwnerCaseView, frozen at the run's input revision."""
        ...

    def complete_assessment(self, run_id: str, base_analysis_revision: int, result: dict) -> Any:
        """Atomically save envelope; newer inputs MUST force stale, never current."""
        ...


def failed_result(snapshot: dict, run_id: str, reason: str, *, status: str = "failed") -> dict:
    return {"assessment": {
        "assessment_id": "assessment_" + run_id, "run_id": run_id,
        "base_analysis_revision": snapshot["case"]["analysis_revision"], "status": status,
        "headline": "Assessment needs another run", "summary": reason, "created_at": utc_now(),
        "published_at": None, "valuation": None, "observation_ids": [],
        "unresolved_questions": [], "failure_reason": reason,
    }, "proposed_tasks": [], "draft_notices": [], "trace": []}


class AssessmentService:
    """Bounded worker injected into Platform's build_router(store, launcher).

    Ticket shape: {run_id, case_id, base_analysis_revision}. input_provider takes
    the frozen OwnerCaseView and returns (valuation_inputs, inspect_image_callback).
    No evidence is silently refreshed midway through a run.
    """

    def __init__(self, store: AnalysisStore, input_provider: Callable,
                 *, agent_factory: Callable | None = None, max_workers: int = 2,
                 max_pending: int = 8, retained_runs: int = 16):
        if max_workers < 1:
            raise ValueError("At least one assessment worker is required")
        if max_pending < 1 or retained_runs < max_pending:
            raise ValueError("Run retention must accommodate the positive pending-run limit")
        self.store, self.input_provider = store, input_provider
        self.agent_factory = agent_factory
        self.max_pending, self.retained_runs = max_pending, retained_runs
        self.pool = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="brace-recovery")
        self.futures: dict[str, Future] = {}
        self.tickets: dict[str, tuple[str, int]] = {}
        self.pending_results: dict[str, dict] = {}
        self.lock = Lock()

    def launch(self, ticket: dict) -> Future:
        run_id, case_id, revision = ticket["run_id"], ticket["case_id"], ticket["base_analysis_revision"]
        if not isinstance(run_id, str) or not run_id or not isinstance(case_id, str) or not case_id:
            raise ValueError("A valid assessment run ticket is required")
        if isinstance(revision, bool) or not isinstance(revision, int) or revision < 1:
            raise ValueError("A positive base analysis revision is required")
        with self.lock:
            if run_id in self.futures:
                if self.tickets[run_id] != (case_id, revision):
                    raise ValueError("A run ID cannot be reused for different inputs")
                previous = self.futures[run_id]
                if not previous.done() or (not previous.cancelled() and previous.exception() is None):
                    return previous
                # Retry a failed database commit with the SAME completed envelope.
                # The store still checks current revision and idempotent run identity.
                if run_id in self.pending_results:
                    if sum(not f.done() for f in self.futures.values()) >= self.max_pending:
                        raise RuntimeError("Recovery assessment workers are busy; retry later")
                    future = self.pool.submit(self._commit, run_id, revision, self.pending_results[run_id])
                    self.futures[run_id] = future
                    return future
            if sum(not f.done() for f in self.futures.values()) >= self.max_pending:
                raise RuntimeError("Recovery assessment workers are busy; retry later")
            # Keep successful results only for a bounded in-process dedup window.
            for old_id in list(self.futures):
                if len(self.futures) < self.retained_runs:
                    break
                if self.futures[old_id].done() and old_id not in self.pending_results:
                    del self.futures[old_id]
                    self.tickets.pop(old_id, None)
            if len(self.futures) >= self.retained_runs:
                raise RuntimeError("Recovery results await persistence; retry pending runs first")
            # Fetch before submitting: a worker queue must not silently switch revisions.
            snapshot = deepcopy(self.store.snapshot_for_analysis(case_id))
            if snapshot["case"]["case_id"] != case_id:
                raise ValueError("Assessment snapshot does not belong to the run")
            snapshot["run_id"] = run_id
            future = self.pool.submit(self._run, deepcopy(ticket), snapshot)
            self.futures[run_id] = future
            self.tickets[run_id] = (case_id, revision)
            return future

    def _run(self, ticket: dict, snapshot: dict) -> Any:
        run_id, revision = ticket["run_id"], ticket["base_analysis_revision"]
        if snapshot["case"]["analysis_revision"] != revision:
            result = failed_result(snapshot, run_id, "Evidence changed before this run started", status="stale")
            result["assessment"]["base_analysis_revision"] = revision
        else:
            try:
                inputs, image_reader = self.input_provider(deepcopy(snapshot))
                factory = self.agent_factory
                if factory is None:
                    from .agent import RecoveryAgent

                    factory = RecoveryAgent
                result = factory(snapshot, inputs, inspect_image=image_reader).run()
                assessment = result["assessment"]
                if (assessment["run_id"] != run_id or assessment["base_analysis_revision"] != revision
                        or assessment["status"] not in {"draft", "failed", "stale"}):
                    raise ValueError("Invalid assessment result identity or state")
                if any(t["status"] != "proposed" for t in result["proposed_tasks"]):
                    raise ValueError("Agent tasks must remain proposals")
            except Exception:
                # Exception text may contain signed URLs, credentials, or resident text.
                result = failed_result(snapshot, run_id, "Assessment interrupted; retry is available")
        # A commit failure is deliberately raised on Future.result(), never swallowed.
        # Platform must compare revisions here in its transaction, not in this worker.
        with self.lock:
            self.pending_results[run_id] = deepcopy(result)
        return self._commit(run_id, revision, result)

    def _commit(self, run_id: str, revision: int, result: dict) -> Any:
        committed = self.store.complete_assessment(run_id, revision, deepcopy(result))
        with self.lock:
            self.pending_results.pop(run_id, None)
        return committed

    def close(self, *, wait: bool = True) -> None:
        self.pool.shutdown(wait=wait, cancel_futures=False)


def fresh_run_id() -> str:
    return "run_" + uuid4().hex
