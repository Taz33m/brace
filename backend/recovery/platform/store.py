"""CaseStore: the durable shared state of the recovery slice.

Rules every public mutation follows (see 04-RECOVERY-PLATFORM.md):
- one short `BEGIN IMMEDIATE` transaction per mutation, on its own connection;
- the mutation, its revision bump, and its event are written together or not at all;
- `case_revision` increments on every public mutation; `analysis_revision` only when
  assessment inputs change (reports, observation reviews, verified completion);
- owner edits compare `expected_revision`; resident submissions use idempotency keys.
No model call or other slow work ever runs inside a transaction.
"""
from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterator, Optional

from . import models as m
from .auth import Actor
from .errors import PlatformError, forbidden, invalid, not_found, revision_conflict
from .schema import migrate

MODE_LABELS = {
    "scenario_exercise": "Scenario exercise — hypothetical impacts; source data is real",
    "historical_replay": "Historical replay — only evidence demonstrably available by the cutoff",
    "observed_recovery": "Observed recovery — reports still require verification",
}

OWNER_EVENT_WINDOW = 100


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:20]}"


def dumps(value) -> str:
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


class CaseStore:
    def __init__(self, db_path: str | Path, media_dir: str | Path | None = None, *,
                 clock: Callable[[], datetime] = _utc_now):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.media_dir = Path(media_dir) if media_dir else self.db_path.parent / "media"
        self.media_dir.mkdir(parents=True, exist_ok=True)
        self.clock = clock
        conn = self._connect()
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            migrate(conn)
        finally:
            conn.close()

    # ------------------------------------------------------------------ plumbing

    def now(self) -> str:
        return self.clock().astimezone(timezone.utc).isoformat()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=5.0, isolation_level=None, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout = 5000")
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    @contextmanager
    def _read(self) -> Iterator[sqlite3.Connection]:
        conn = self._connect()
        try:
            conn.execute("BEGIN")  # one consistent snapshot for the whole read
            yield conn
            conn.execute("COMMIT")
        finally:
            conn.close()

    @contextmanager
    def _write(self) -> Iterator[sqlite3.Connection]:
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            try:
                yield conn
            except BaseException:
                conn.execute("ROLLBACK")
                raise
            conn.execute("COMMIT")
        finally:
            conn.close()

    def _owner_case(self, conn, actor: Actor, case_id: str) -> sqlite3.Row:
        if actor.role != "owner":
            raise forbidden()
        row = conn.execute("SELECT * FROM cases WHERE case_id = ?", (case_id,)).fetchone()
        if row is None or row["owner_id"] != actor.actor_id:
            raise not_found("This case")
        return row

    @staticmethod
    def _check_revision(row: sqlite3.Row, expected: int) -> None:
        if expected != row["case_revision"]:
            raise revision_conflict(row["case_revision"])

    def _bump(self, conn, case_id: str, *, analysis: bool = False) -> tuple[int, int]:
        conn.execute("UPDATE cases SET case_revision = case_revision + 1, "
                     "analysis_revision = analysis_revision + ?, updated_at = ? WHERE case_id = ?",
                     (1 if analysis else 0, self.now(), case_id))
        row = conn.execute("SELECT case_revision, analysis_revision FROM cases WHERE case_id = ?",
                           (case_id,)).fetchone()
        if analysis:
            self._stale_drafts(conn, case_id, row["analysis_revision"])
        return row["case_revision"], row["analysis_revision"]

    def _stale_drafts(self, conn, case_id: str, analysis_revision: int) -> None:
        """Inputs moved: unpublished drafts built on older inputs become history."""
        rows = conn.execute("SELECT assessment_id, json FROM assessments WHERE case_id = ? AND "
                            "status = 'draft' AND base_analysis_revision < ?",
                            (case_id, analysis_revision)).fetchall()
        for row in rows:
            data = json.loads(row["json"])
            data["status"] = "stale"
            conn.execute("UPDATE assessments SET status = 'stale', json = ? WHERE assessment_id = ?",
                         (dumps(data), row["assessment_id"]))

    def _event(self, conn, case_id: str, type_: str, *, audience: str = "owner",
               households: Optional[list[str]] = None, entity_id: Optional[str] = None,
               public_summary: Optional[str] = None) -> int:
        revs = conn.execute("SELECT case_revision, analysis_revision FROM cases WHERE case_id = ?",
                            (case_id,)).fetchone()
        cur = conn.execute(
            "INSERT INTO events (case_id, type, audience, households_json, case_revision, "
            "analysis_revision, entity_id, public_summary, at) VALUES (?,?,?,?,?,?,?,?,?)",
            (case_id, type_, audience, json.dumps(households) if households is not None else None,
             revs["case_revision"], revs["analysis_revision"], entity_id, public_summary, self.now()))
        return cur.lastrowid

    # ------------------------------------------------------------------ cases

    def create_case(self, actor: Actor, case_input: m.CaseInput) -> m.RecoveryCaseSummary:
        if actor.role != "owner":
            raise forbidden()
        case_id = case_input.case_id or new_id("case")
        summary = {
            "case_id": case_id, "property_ref": case_input.property_ref.model_dump(),
            "property_name": case_input.property_name, "address": case_input.address,
            "city": case_input.city, "incident_name": case_input.incident_name,
            "incident_at": case_input.incident_at, "assessment_as_of": case_input.assessment_as_of,
            "mode": case_input.mode, "mode_label": case_input.mode_label or MODE_LABELS[case_input.mode],
            "next_action": case_input.next_action,
        }
        now = self.now()
        with self._write() as conn:
            if conn.execute("SELECT 1 FROM cases WHERE case_id = ?", (case_id,)).fetchone():
                raise PlatformError(409, "case_exists", "A case with this ID already exists.")
            conn.execute("INSERT INTO cases VALUES (?,?,?,?,?,?,?)",
                         (case_id, actor.actor_id, 1, 1, dumps(summary), now, now))
            for loc in case_input.locations:
                conn.execute("INSERT INTO locations VALUES (?,?,?)", (case_id, loc.location_id, dumps(loc)))
            for ev in case_input.evidence:
                conn.execute("INSERT INTO evidence VALUES (?,?,?,?,?)",
                             (ev.evidence_id, case_id, None, dumps(ev), now))
            self._event(conn, case_id, "case.created", entity_id=case_id)
            return self._summary(conn, conn.execute("SELECT * FROM cases WHERE case_id = ?",
                                                    (case_id,)).fetchone())

    def add_household(self, actor: Actor, case_id: str, unit_label: Optional[str], *,
                      unit_confirmed: bool = False, location_ids: tuple[str, ...] | list[str] = ()) -> str:
        """Lead bootstrap: register a household and the locations its resident may pick."""
        household_id = new_id("hh")
        with self._write() as conn:
            self._owner_case(conn, actor, case_id)
            known = {r["location_id"] for r in conn.execute(
                "SELECT location_id FROM locations WHERE case_id = ?", (case_id,))}
            if any(lid not in known for lid in location_ids):
                raise invalid("A household location is not registered on this case.")
            conn.execute("INSERT INTO households VALUES (?,?,?,?,?,?)",
                         (household_id, case_id, unit_label, int(unit_confirmed),
                          json.dumps(list(location_ids)), self.now()))
            self._bump(conn, case_id)
            self._event(conn, case_id, "household.added", entity_id=household_id)
        return household_id

    def list_cases(self, actor: Actor) -> list[m.RecoveryCaseSummary]:
        if actor.role != "owner":
            raise forbidden()
        with self._read() as conn:
            rows = conn.execute("SELECT * FROM cases WHERE owner_id = ? ORDER BY created_at",
                                (actor.actor_id,)).fetchall()
            return [self._summary(conn, row) for row in rows]

    def _summary(self, conn, row: sqlite3.Row) -> m.RecoveryCaseSummary:
        data = json.loads(row["summary_json"])
        case_id = row["case_id"]
        pending_reports = conn.execute(
            "SELECT COUNT(*) FROM observations WHERE case_id = ? AND report_id IS NOT NULL "
            "AND status IN ('reported', 'under_review')", (case_id,)).fetchone()[0]
        pending_tasks = conn.execute(
            "SELECT COUNT(*) FROM tasks WHERE case_id = ? AND status NOT IN ('verified', 'cancelled')",
            (case_id,)).fetchone()[0]
        proposed = conn.execute("SELECT COUNT(*) FROM tasks WHERE case_id = ? AND status = 'proposed'",
                                (case_id,)).fetchone()[0]
        next_action = data.pop("next_action")
        if pending_reports:
            next_action = f"Review {pending_reports} resident report{'s' if pending_reports != 1 else ''}"
        elif proposed:
            next_action = f"Approve or cancel {proposed} proposed task{'s' if proposed != 1 else ''}"
        return m.RecoveryCaseSummary(**data, case_revision=row["case_revision"],
                                     analysis_revision=row["analysis_revision"],
                                     pending_reports=pending_reports, pending_tasks=pending_tasks,
                                     next_action=next_action)

    def owner_snapshot(self, actor: Actor, case_id: str) -> m.OwnerCaseView:
        with self._read() as conn:
            row = self._owner_case(conn, actor, case_id)
            return self._owner_view(conn, row)

    def _owner_view(self, conn, row: sqlite3.Row) -> m.OwnerCaseView:
        case_id = row["case_id"]

        def payloads(sql: str) -> list[dict]:
            return [json.loads(r["json"]) for r in conn.execute(sql, (case_id,))]

        assessments = payloads("SELECT json FROM assessments WHERE case_id = ? ORDER BY created_at")
        published = [a for a in assessments if a["status"] == "published"]
        drafts = [a for a in assessments if a["status"] == "draft"]
        current = (published or drafts or [None])[-1]
        events = [self._event_model(r) for r in conn.execute(
            "SELECT * FROM (SELECT * FROM events WHERE case_id = ? ORDER BY event_id DESC LIMIT ?) "
            "ORDER BY event_id", (case_id, OWNER_EVENT_WINDOW))]
        return m.OwnerCaseView(
            case=self._summary(conn, row),
            evidence=payloads("SELECT json FROM evidence WHERE case_id = ? ORDER BY created_at, evidence_id"),
            observations=payloads("SELECT json FROM observations WHERE case_id = ? ORDER BY rowid"),
            assessments=assessments,
            current_assessment_id=current["assessment_id"] if current else None,
            tasks=payloads("SELECT json FROM tasks WHERE case_id = ? ORDER BY rowid"),
            reports=[self._report_view(conn, r) for r in conn.execute(
                "SELECT * FROM reports WHERE case_id = ? ORDER BY received_at, rowid", (case_id,))],
            support_requests=[self._support_view(r) for r in conn.execute(
                "SELECT * FROM support_requests WHERE case_id = ? ORDER BY received_at, rowid", (case_id,))],
            notices=payloads("SELECT json FROM notices WHERE case_id = ? AND status = 'published' "
                             "ORDER BY created_at, rowid"),
            household_labels=[{"household_id": r["household_id"], "unit_label": r["unit_label"]}
                              for r in conn.execute("SELECT household_id, unit_label FROM households "
                                                    "WHERE case_id = ? ORDER BY created_at, rowid", (case_id,))],
            events=events,
            event_cursor=self._cursor(conn, case_id),
        )

    @staticmethod
    def _cursor(conn, case_id: str) -> int:
        return conn.execute("SELECT COALESCE(MAX(event_id), 0) FROM events WHERE case_id = ?",
                            (case_id,)).fetchone()[0]

    @staticmethod
    def _event_model(row: sqlite3.Row) -> m.CaseEvent:
        return m.CaseEvent(event_id=row["event_id"], case_id=row["case_id"],
                           case_revision=row["case_revision"], analysis_revision=row["analysis_revision"],
                           type=row["type"], at=row["at"], entity_id=row["entity_id"],
                           public_summary=row["public_summary"])

    # Filled in by the reports/support tasks.
    def _report_view(self, conn, row: sqlite3.Row) -> m.ResidentReport:
        raise NotImplementedError

    def _support_view(self, row: sqlite3.Row) -> m.SupportReceipt:
        raise NotImplementedError
