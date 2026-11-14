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

import hashlib
import json
import re
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Iterator, Optional

from . import models as m
from .auth import Actor, hash_token, new_token
from .errors import PlatformError, forbidden, invalid, not_found, revision_conflict
from .schema import migrate

MODE_LABELS = {
    "scenario_exercise": "Scenario exercise — hypothetical impacts; source data is real",
    "historical_replay": "Historical replay — only evidence demonstrably available by the cutoff",
    "observed_recovery": "Observed recovery — reports still require verification",
}

OWNER_EVENT_WINDOW = 100
INVITATION_TTL = timedelta(hours=72)
RESIDENT_SESSION_TTL = timedelta(days=30)
OWNER_SESSION_TTL = timedelta(hours=12)


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

    # ------------------------------------------------------------------ invitations / sessions

    def create_invitation(self, actor: Actor, case_id: str, household_id: str, expected_revision: int,
                          *, ttl: timedelta = INVITATION_TTL) -> m.CommandResult:
        token = new_token()
        expires = (self.clock() + ttl).astimezone(timezone.utc).isoformat()
        with self._write() as conn:
            row = self._owner_case(conn, actor, case_id)
            self._check_revision(row, expected_revision)
            self._household(conn, case_id, household_id)
            invitation_id = new_id("inv")
            conn.execute("INSERT INTO invitations VALUES (?,?,?,?,?,?,?,NULL)",
                         (invitation_id, hash_token(token), case_id, household_id, actor.actor_id,
                          self.now(), expires))
            case_rev, analysis_rev = self._bump(conn, case_id)
            self._event(conn, case_id, "invitation.created", entity_id=invitation_id)
        return m.CommandResult(case_revision=case_rev, analysis_revision=analysis_rev, run_id=None,
                               invitation_token=token, invitation_expires_at=expires)

    def invitations(self, actor: Actor, case_id: str) -> list[dict]:
        """Owner listing for revocation; never includes token material."""
        with self._read() as conn:
            self._owner_case(conn, actor, case_id)
            return [dict(r) for r in conn.execute(
                "SELECT invitation_id, household_id, created_at, expires_at, revoked_at FROM invitations "
                "WHERE case_id = ? ORDER BY created_at, rowid", (case_id,))]

    def revoke_invitation(self, actor: Actor, case_id: str, invitation_id: str) -> None:
        now = self.now()
        with self._write() as conn:
            self._owner_case(conn, actor, case_id)
            inv = conn.execute("SELECT * FROM invitations WHERE invitation_id = ? AND case_id = ?",
                               (invitation_id, case_id)).fetchone()
            if inv is None:
                raise not_found("This invitation")
            if inv["revoked_at"]:
                return
            conn.execute("UPDATE invitations SET revoked_at = ? WHERE invitation_id = ?", (now, invitation_id))
            conn.execute("UPDATE sessions SET revoked_at = ? WHERE invitation_id = ? AND revoked_at IS NULL",
                         (now, invitation_id))
            self._bump(conn, case_id)
            self._event(conn, case_id, "session.revoked", audience="households",
                        households=[inv["household_id"]], entity_id=invitation_id)

    def exchange_invitation(self, token: str) -> str:
        """Swap an invitation token for a resident session token (both returned raw only here)."""
        now = self.now()
        with self._write() as conn:
            inv = conn.execute("SELECT * FROM invitations WHERE token_hash = ?", (hash_token(token),)).fetchone()
            if inv is None or inv["revoked_at"] or inv["expires_at"] <= now:
                raise PlatformError(401, "invitation_invalid",
                                    "This invitation link is not valid. Ask the property team for a new one.")
            session = new_token()
            expires = (self.clock() + RESIDENT_SESSION_TTL).astimezone(timezone.utc).isoformat()
            conn.execute("INSERT INTO sessions VALUES (?,?,?,?,?,?,?,?,NULL)",
                         (hash_token(session), "resident", "resident:" + inv["household_id"], inv["case_id"],
                          inv["household_id"], inv["invitation_id"], now, expires))
        return session

    def create_owner_session(self, owner_id: str) -> str:
        """Call only after auth.check_owner_secret succeeded."""
        session = new_token()
        expires = (self.clock() + OWNER_SESSION_TTL).astimezone(timezone.utc).isoformat()
        with self._write() as conn:
            conn.execute("INSERT INTO sessions VALUES (?,?,?,NULL,NULL,NULL,?,?,NULL)",
                         (hash_token(session), "owner", owner_id, self.now(), expires))
        return session

    def resolve_session(self, token: Optional[str]) -> Optional[Actor]:
        if not token:
            return None
        with self._read() as conn:
            row = conn.execute("SELECT * FROM sessions WHERE session_hash = ?", (hash_token(token),)).fetchone()
            if row is None or row["revoked_at"] or row["expires_at"] <= self.now():
                return None
            if row["role"] == "resident":
                inv = conn.execute("SELECT revoked_at FROM invitations WHERE invitation_id = ?",
                                   (row["invitation_id"],)).fetchone()
                if inv is None or inv["revoked_at"]:
                    return None
            return Actor(role=row["role"], actor_id=row["actor_id"], case_id=row["case_id"],
                         household_id=row["household_id"])

    def end_session(self, token: Optional[str]) -> None:
        if token:
            with self._write() as conn:
                conn.execute("UPDATE sessions SET revoked_at = ? WHERE session_hash = ? AND revoked_at IS NULL",
                             (self.now(), hash_token(token)))

    @staticmethod
    def _household(conn, case_id: str, household_id: str) -> sqlite3.Row:
        row = conn.execute("SELECT * FROM households WHERE household_id = ? AND case_id = ?",
                           (household_id, case_id)).fetchone()
        if row is None:
            raise not_found("This household")
        return row

    # ------------------------------------------------------------------ owner commands

    def apply_command(self, actor: Actor, case_id: str, command, idempotency_key: Optional[str] = None,
                      *, launcher=None) -> m.CommandResult:
        """Typed dispatch of OwnerCommand. Never an arbitrary method or tool executor.

        The Idempotency-Key is optional here: expected_revision already rejects a blind
        replay. When supplied, a replay returns the original result (minus any token).
        """
        operation = f"command:{case_id}"
        body_hash = hash_token(dumps(command))
        if idempotency_key is not None:
            key = self._check_key(idempotency_key)
            with self._read() as conn:
                self._owner_case(conn, actor, case_id)
                stored = self._replay(conn, actor, operation, key, body_hash)
            if stored is not None:
                if command.type == "create_invitation":
                    raise PlatformError(409, "invitation_already_issued",
                                        "This invitation was already created. Create a new one if the link was lost.")
                return m.CommandResult(**stored)
        handler = getattr(self, "_cmd_" + command.type, None)
        if handler is None:
            raise PlatformError(422, "unsupported_command", "This command is not available yet.")
        result: m.CommandResult = handler(actor, case_id, command, launcher=launcher)
        if idempotency_key is not None:
            redacted = result.model_copy(update={"invitation_token": None})
            with self._write() as conn:
                try:
                    self._remember(conn, actor, operation, idempotency_key, body_hash, redacted)
                except sqlite3.IntegrityError:
                    pass  # a concurrent identical request recorded it first
        return result

    def _cmd_create_invitation(self, actor, case_id, command: m.CreateInvitation, **_) -> m.CommandResult:
        return self.create_invitation(actor, case_id, command.household_id, command.expected_revision)

    # ------------------------------------------------------------------ idempotency

    @staticmethod
    def _check_key(key: Optional[str]) -> str:
        if not key or not (8 <= len(key) <= 200) or not key.isprintable():
            raise invalid("An Idempotency-Key header of 8 to 200 printable characters is required.",
                          "idempotency_key_required")
        return key

    @staticmethod
    def _replay(conn, actor: Actor, operation: str, key: str, body_hash: str) -> Optional[dict]:
        row = conn.execute("SELECT request_hash, response_json FROM idempotency WHERE actor_id = ? AND "
                           "operation = ? AND idem_key = ?", (actor.actor_id, operation, key)).fetchone()
        if row is None:
            return None
        if row["request_hash"] != body_hash:
            raise PlatformError(409, "idempotency_conflict",
                                "This request key was already used for a different submission.")
        return json.loads(row["response_json"])

    def _remember(self, conn, actor: Actor, operation: str, key: str, body_hash: str, response) -> None:
        conn.execute("INSERT INTO idempotency VALUES (?,?,?,?,?,?)",
                     (actor.actor_id, operation, key, body_hash, dumps(response), self.now()))

    # ------------------------------------------------------------------ residents

    def _resident(self, conn, actor: Actor) -> tuple[sqlite3.Row, sqlite3.Row]:
        if actor.role != "resident" or not actor.case_id or not actor.household_id:
            raise forbidden()
        case = conn.execute("SELECT * FROM cases WHERE case_id = ?", (actor.case_id,)).fetchone()
        if case is None:
            raise not_found("This case")
        return case, self._household(conn, actor.case_id, actor.household_id)

    def _household_locations(self, conn, household: sqlite3.Row) -> list[m.LocationRef]:
        ids = json.loads(household["location_ids_json"])
        rows = {r["location_id"]: r["json"] for r in conn.execute(
            "SELECT location_id, json FROM locations WHERE case_id = ?", (household["case_id"],))}
        return [m.LocationRef.model_validate_json(rows[i]) for i in ids if i in rows]

    def append_report(self, actor: Actor, request: m.ReportInput, idempotency_key: Optional[str]) -> m.ReportReceipt:
        key = self._check_key(idempotency_key)
        if not request.text.strip():
            raise invalid("Describe what you see before sending.")
        _check_source_date(request.observed_at)
        body_hash = hash_token(dumps(request))
        with self._write() as conn:
            case, household = self._resident(conn, actor)
            stored = self._replay(conn, actor, "report", key, body_hash)
            if stored is not None:
                return m.ReportReceipt(**{**stored, "duplicate": True})
            location = None
            if request.selected_location_id is not None:
                location = next((loc for loc in self._household_locations(conn, household)
                                 if loc.location_id == request.selected_location_id), None)
                if location is None:
                    raise invalid("That location is not one you can report for.", "location_unavailable")
            now = self.now()
            report_id, observation_id = new_id("rpt"), new_id("obs")
            evidence_ids = self._attach_uploads(conn, actor, request.upload_ids, report_id, location, now)
            observation = m.Observation(
                observation_id=observation_id, title=f"Resident report: {CATEGORY_LABELS[request.category]}",
                description=request.text, basis="reported", status="reported", evidence_ids=evidence_ids,
                location=location, observed_at=request.observed_at, updated_at=now,
                verification_note=None, verified_by=None)
            conn.execute("INSERT INTO observations VALUES (?,?,?,?,?,?,?)",
                         (observation_id, actor.case_id, actor.household_id, report_id, "reported", 1,
                          dumps(observation)))
            conn.execute("INSERT INTO observation_versions VALUES (?,?,?,?,?)",
                         (observation_id, 1, dumps(observation), actor.actor_id, now))
            payload = {"category": request.category, "text": request.text,
                       "location": location.model_dump(mode="json") if location else None,
                       "location_description": request.location_description,
                       "observed_at": request.observed_at}
            conn.execute("INSERT INTO reports VALUES (?,?,?,?,?,?)",
                         (report_id, actor.case_id, actor.household_id, observation_id, dumps(payload), now))
            case_rev, analysis_rev = self._bump(conn, actor.case_id, analysis=True)
            self._event(conn, actor.case_id, "report.updated", audience="households",
                        households=[actor.household_id], entity_id=report_id,
                        public_summary="Report received")
            row = conn.execute("SELECT * FROM reports WHERE report_id = ?", (report_id,)).fetchone()
            receipt = m.ReportReceipt(report=self._report_view(conn, row), case_revision=case_rev,
                                      analysis_revision=analysis_rev, duplicate=False)
            self._remember(conn, actor, "report", key, body_hash, receipt)
            return receipt

    def _attach_uploads(self, conn, actor: Actor, upload_ids: list[str], report_id: str,
                        location: Optional[m.LocationRef], now: str) -> list[str]:
        """Re-check ownership at attach time; one upload belongs to at most one report."""
        if len(set(upload_ids)) != len(upload_ids):
            raise invalid("A photo is listed twice.", "upload_unavailable")
        evidence_ids = []
        for upload_id in upload_ids:
            row = conn.execute("SELECT * FROM media WHERE upload_id = ? AND case_id = ? AND household_id = ? "
                               "AND attached_report_id IS NULL",
                               (upload_id, actor.case_id, actor.household_id)).fetchone()
            if row is None:
                raise invalid("A photo could not be attached. Upload it again.", "upload_unavailable")
            conn.execute("UPDATE media SET attached_report_id = ? WHERE media_id = ?", (report_id, row["media_id"]))
            evidence = m.Evidence(
                evidence_id=new_id("ev"), kind="resident_photo", source_id=row["media_id"],
                source_label="Resident photo", captured_at=None, effective_at=None, available_at=None,
                received_at=row["received_at"], model_created_at=None, location=location,
                media=self._media_ref(row), summary="Photo attached to a resident report",
                limitations=["Unverified resident photo; when and where it was taken is not established."])
            conn.execute("INSERT INTO evidence VALUES (?,?,?,?,?)",
                         (evidence.evidence_id, actor.case_id, actor.household_id, dumps(evidence), now))
            evidence_ids.append(evidence.evidence_id)
        return evidence_ids

    # ------------------------------------------------------------------ uploads / media

    def save_upload(self, actor: Actor, data: bytes, idempotency_key: Optional[str]) -> m.UploadedMedia:
        from .uploads import decode_image

        key = self._check_key(idempotency_key)
        body_hash = hashlib.sha256(data).hexdigest()
        with self._read() as conn:
            self._resident(conn, actor)
            stored = self._replay(conn, actor, "upload", key, body_hash)
        if stored is not None:
            return m.UploadedMedia(**stored)
        mime, display = decode_image(data)  # slow work stays outside any transaction
        media_id, upload_id = new_id("med"), new_id("upl")
        case_dir = self.media_dir / _safe_component(actor.case_id)
        case_dir.mkdir(parents=True, exist_ok=True)
        original_name = f"{_safe_component(actor.case_id)}/{media_id}.orig"
        display_name = f"{_safe_component(actor.case_id)}/{media_id}.jpg"
        (self.media_dir / original_name).write_bytes(data)
        (self.media_dir / display_name).write_bytes(display)
        try:
            with self._write() as conn:
                self._resident(conn, actor)
                stored = self._replay(conn, actor, "upload", key, body_hash)
                if stored is not None:
                    raise _AlreadyStored(stored)
                conn.execute("INSERT INTO media VALUES (?,?,?,?,?,?,?,?,?,?,NULL)",
                             (media_id, upload_id, actor.case_id, actor.household_id, mime, body_hash,
                              len(data), original_name, display_name, self.now()))
                row = conn.execute("SELECT * FROM media WHERE media_id = ?", (media_id,)).fetchone()
                result = m.UploadedMedia(upload_id=upload_id, media=self._media_ref(row))
                self._remember(conn, actor, "upload", key, body_hash, result)
                return result
        except BaseException as exc:
            for name in (original_name, display_name):
                (self.media_dir / name).unlink(missing_ok=True)
            if isinstance(exc, _AlreadyStored):
                return m.UploadedMedia(**exc.stored)
            raise

    def media_bytes(self, actor: Actor, media_id: str) -> bytes:
        """Sanitized display bytes after a case/household permission check; 404 otherwise."""
        if not MEDIA_ID.fullmatch(media_id or ""):
            raise not_found("This photo")
        with self._read() as conn:
            row = conn.execute("SELECT * FROM media WHERE media_id = ?", (media_id,)).fetchone()
            if row is None:
                raise not_found("This photo")
            if actor.role == "owner":
                case = conn.execute("SELECT owner_id FROM cases WHERE case_id = ?", (row["case_id"],)).fetchone()
                allowed = case is not None and case["owner_id"] == actor.actor_id
            else:
                allowed = (actor.role == "resident" and row["case_id"] == actor.case_id
                           and row["household_id"] == actor.household_id)
            if not allowed:
                raise not_found("This photo")
        path = (self.media_dir / row["display_name"]).resolve()
        if not path.is_relative_to(self.media_dir.resolve()) or not path.is_file():
            raise not_found("This photo")
        return path.read_bytes()

    def _report_view(self, conn, row: sqlite3.Row) -> m.ResidentReport:
        data = json.loads(row["json"])
        status = conn.execute("SELECT status FROM observations WHERE observation_id = ?",
                              (row["observation_id"],)).fetchone()["status"]
        media = [self._media_ref(r) for r in conn.execute(
            "SELECT * FROM media WHERE attached_report_id = ? ORDER BY received_at, rowid", (row["report_id"],))]
        return m.ResidentReport(report_id=row["report_id"], household_id=row["household_id"],
                                received_at=row["received_at"], status=status, media=media,
                                public_status_detail=REPORT_STATUS_TEXT[status], **data)

    @staticmethod
    def _media_ref(row: sqlite3.Row) -> m.MediaRef:
        return m.MediaRef(media_id=row["media_id"], url=f"/api/recovery/media/{row['media_id']}",
                          alt="Photo submitted by a resident", mime_type="image/jpeg")

    def _support_view(self, row: sqlite3.Row) -> m.SupportReceipt:
        data = json.loads(row["json"])
        return m.SupportReceipt(request_id=row["request_id"], household_id=row["household_id"],
                                received_at=row["received_at"], duplicate=False,
                                public_status_detail=SUPPORT_STATUS_TEXT[data["status"]], **data)

    def resident_home(self, actor: Actor) -> m.ResidentHome:
        with self._read() as conn:
            case, household = self._resident(conn, actor)
            summary = json.loads(case["summary_json"])
            hh = actor.household_id
            tasks = []
            for r in conn.execute("SELECT json FROM tasks WHERE case_id = ? AND status != 'proposed' "
                                  "ORDER BY rowid", (actor.case_id,)):
                task = json.loads(r["json"])
                if hh in task["household_ids"]:
                    tasks.append(m.ResidentTask(
                        task_id=task["task_id"], revision=task["revision"], title=task["title"],
                        status=task["status"], public_status_detail=TASK_STATUS_TEXT[task["status"]],
                        confirmed_schedule=task["confirmed_schedule"], updated_at=task["updated_at"]))
            notices = [json.loads(r["json"]) for r in conn.execute(
                "SELECT json, household_ids_json FROM notices WHERE case_id = ? AND status = 'published' "
                "ORDER BY created_at, rowid", (actor.case_id,))
                if r["household_ids_json"] is None or hh in json.loads(r["household_ids_json"])]
            return m.ResidentHome(
                case_id=actor.case_id, case_revision=case["case_revision"],
                property_name=summary["property_name"], address=summary["address"],
                unit_label=household["unit_label"], unit_confirmed=bool(household["unit_confirmed"]),
                mode=summary["mode"], mode_label=summary["mode_label"],
                incident_name=summary["incident_name"], updated_at=case["updated_at"],
                selectable_locations=self._household_locations(conn, household),
                reports=[self._report_view(conn, r) for r in conn.execute(
                    "SELECT * FROM reports WHERE household_id = ? ORDER BY received_at, rowid", (hh,))],
                support_requests=[self._support_view(r) for r in conn.execute(
                    "SELECT * FROM support_requests WHERE household_id = ? ORDER BY received_at, rowid", (hh,))],
                tasks=tasks, notices=notices, event_cursor=self._cursor(conn, actor.case_id))

    # ------------------------------------------------------------------ events

    def events_after(self, actor: Actor, cursor: int, case_id: Optional[str] = None,
                     limit: int = 500) -> list[m.CaseEvent]:
        """Events with id > cursor that this actor may see, oldest first."""
        with self._read() as conn:
            if actor.role == "owner":
                if case_id is None:
                    raise invalid("A case is required.")
                self._owner_case(conn, actor, case_id)
                rows = conn.execute("SELECT * FROM events WHERE case_id = ? AND event_id > ? "
                                    "ORDER BY event_id LIMIT ?", (case_id, cursor, limit)).fetchall()
                return [self._event_model(r) for r in rows]
            self._resident(conn, actor)
            rows = conn.execute(
                f"SELECT * FROM events WHERE case_id = ? AND event_id > ? AND audience != 'owner' "
                f"AND type IN ({','.join('?' * len(RESIDENT_EVENT_TYPES))}) ORDER BY event_id LIMIT ?",
                (actor.case_id, cursor, *sorted(RESIDENT_EVENT_TYPES), limit)).fetchall()
            return [self._event_model(r) for r in rows
                    if r["audience"] == "case" or actor.household_id in json.loads(r["households_json"] or "[]")]


MEDIA_ID = re.compile(r"med_[0-9a-f]{20}")


class _AlreadyStored(Exception):
    def __init__(self, stored: dict):
        self.stored = stored


def _safe_component(value: str) -> str:
    """Case IDs are server-issued, but never let one become a path segment unchecked."""
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", value or ""):
        raise invalid("This case cannot store photos.")
    return value


RESIDENT_EVENT_TYPES = frozenset({"report.updated", "support.updated", "task.updated", "notice.published",
                                  "session.revoked", "case.updated"})

CATEGORY_LABELS = {"water": "water", "roof": "roof", "smoke_or_fire": "smoke or fire",
                   "power_or_access": "power or access", "other": "other"}

REPORT_STATUS_TEXT = {
    "reported": "Received. The property team has not reviewed it yet.",
    "under_review": "The property team is reviewing this report.",
    "verified": "The property team confirmed this report.",
    "dismissed": "The property team closed this report after review.",
}

SUPPORT_STATUS_TEXT = {
    "received": "Received. The property team has not responded yet.",
    "under_review": "The property team is looking into this.",
    "responded": "The property team responded.",
    "closed": "This request is closed.",
}

# Residents never see `proposed` tasks (model output not yet approved by the owner).
TASK_STATUS_TEXT = {
    "proposed": "Proposed; not approved or scheduled.",
    "approved": "Approved by the property team. Not scheduled yet.",
    "accepted": "A contractor has confirmed this work.",
    "in_progress": "Work is under way.",
    "completion_submitted": "Work reported complete; waiting for the property team to check it.",
    "verified": "The property team checked the completed work. This is not an occupancy clearance.",
    "cancelled": "This task was cancelled.",
}


def _check_source_date(value: Optional[str]) -> None:
    """Null, a date-only YYYY-MM-DD, or an ISO 8601 datetime that carries a timezone."""
    if value is None:
        return
    try:
        if len(value) == 10:
            datetime.strptime(value, "%Y-%m-%d")
            return
        parsed = datetime.fromisoformat(value)
    except ValueError:
        parsed = None
    if parsed is None or parsed.tzinfo is None:
        raise invalid("Use a date (YYYY-MM-DD) or a date and time with a timezone.", "invalid_date")
