"""Private Photon bridge: explicit joins, resident submissions and approved notice delivery."""
from contextlib import contextmanager
from datetime import timedelta, timezone
from base64 import b64encode
import hmac
import json
import math
import os
from pathlib import Path
import re
import secrets
import sqlite3
from typing import Literal

from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict, Field

from .platform.auth import Actor, hash_token
from .platform.errors import PlatformError
from .platform.models import ReportInput, SupportInput
from .platform.router import EnvelopeRoute, make_owner_dependency
from .platform.store import dumps, new_id
from .forecast_cards import FORECAST_CARDS, forecast_card

RESIDENT_CHOICES = ("I'm okay", "I need help with access", "I need somewhere to stay", "Report damage")


def forecast_alert(property_name: str, title: str, body: str, threat: dict) -> str:
    site = threat.get("at_this_site") or {}
    hours = site.get("hours_until_tropical_storm_wind", threat.get("hours_left"))
    wind, issued = site.get("peak_wind_mph"), threat.get("forecast_issued")
    lines = [f"BRACE WEATHER ALERT · {property_name}", threat.get("name") or title]
    if threat.get("replay"):
        lines.append(f"Historical forecast replay · Issued {issued}" if issued else "Historical forecast replay")
    elif issued:
        lines.append(f"Forecast issued {issued}")
    if threat.get("kind") == "hurricane":
        if isinstance(wind, (int, float)) and math.isfinite(wind) and wind >= 0:
            lines.append(f"Sustained winds near {wind:g} mph forecast at this property.")
        if issued and isinstance(hours, (int, float)) and math.isfinite(hours) and hours >= 0:
            lines.append(f"{hours:g} hours to tropical-storm winds at forecast issue.")
    elif threat.get("kind") == "wildfire":
        if site.get("in_warning"):
            lines.append("Red Flag Warning for this area.")
        elif site.get("in_watch"):
            lines.append("Fire weather watch for this area.")
        gust = site.get("gust_mph")
        if isinstance(gust, (int, float)) and math.isfinite(gust) and gust >= 0:
            lines.append(f"Gusts up to {gust:g} mph forecast in this warning zone.")
        until = site.get("hours_until_warning")
        if issued and site.get("in_warning") and isinstance(until, (int, float)) and math.isfinite(until) and until >= 0:
            lines.append(f"{until:g} hours to the warning at forecast issue.")
    steps = next((p.splitlines()[1:] for p in body.split("\n\n")
                  if p.startswith("Resident preparation:\n")), [])
    if steps:
        lines.extend(step.removeprefix("- ") for step in steps[:2])
    lines.append("Choose an option below or reply here.")
    return "\n\n".join(lines[:1] + ["\n".join(lines[1:])])


class Inbound(BaseModel):
    model_config = ConfigDict(extra="forbid")
    message_id: str = Field(min_length=1, max_length=300)
    sender_id: str = Field(min_length=1, max_length=300)
    space_id: str = Field(min_length=1, max_length=300)
    text: str = Field(min_length=1, max_length=4000)
    poll_id: str | None = Field(default=None, max_length=300)
    option_id: str | None = Field(default=None, max_length=300)


class Acknowledgment(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["sent", "failed"]
    provider_message_id: str | None = Field(default=None, max_length=300)
    error: str | None = Field(default=None, max_length=1000)


class PhotonService:
    def __init__(self, store, *, db_path=None):
        self.store = store
        self.db_path = Path(db_path) if db_path else Path(store.db_path).with_name("photon.sqlite3")
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._db() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS links (code_hash TEXT PRIMARY KEY, case_id TEXT NOT NULL,
                    household_id TEXT NOT NULL, session_hash TEXT NOT NULL, expires_at TEXT NOT NULL, used_at TEXT);
                CREATE TABLE IF NOT EXISTS bindings (sender_id TEXT NOT NULL, space_id TEXT NOT NULL,
                    case_id TEXT NOT NULL, household_id TEXT NOT NULL, session_hash TEXT NOT NULL,
                    joined_at TEXT NOT NULL, PRIMARY KEY(sender_id,space_id));
                CREATE TABLE IF NOT EXISTS inbound (message_id TEXT PRIMARY KEY, content_hash TEXT NOT NULL,
                    response_json TEXT NOT NULL, created_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS outbox (id TEXT PRIMARY KEY, case_id TEXT NOT NULL,
                    notice_id TEXT NOT NULL, household_id TEXT NOT NULL, sender_id TEXT NOT NULL,
                    space_id TEXT NOT NULL, session_hash TEXT NOT NULL, text TEXT NOT NULL,
                    status TEXT NOT NULL, created_at TEXT NOT NULL, claimed_at TEXT, acknowledged_at TEXT,
                    provider_message_id TEXT, error TEXT, card_asset TEXT, UNIQUE(case_id,notice_id,sender_id));
            """)
        with self._db(write=True) as conn:
            if "card_asset" not in {row["name"] for row in conn.execute("PRAGMA table_info(outbox)")}:
                conn.execute("ALTER TABLE outbox ADD COLUMN card_asset TEXT")
        self.db_path.chmod(0o600)

    @contextmanager
    def _db(self, *, write=False):
        conn = sqlite3.connect(self.db_path, timeout=5, isolation_level=None)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("BEGIN IMMEDIATE" if write else "BEGIN")
            yield conn
            if conn.in_transaction:
                conn.commit()
        except BaseException:
            if conn.in_transaction:
                conn.rollback()
            raise
        finally:
            conn.close()

    def _actor(self, binding):
        """Match the real resident session without retaining its raw credential."""
        with self.store._read() as conn:
            row = conn.execute("SELECT s.* FROM sessions s JOIN invitations i ON i.invitation_id=s.invitation_id "
                "WHERE s.session_hash=? AND s.role='resident' AND s.case_id=? AND s.household_id=? "
                "AND s.revoked_at IS NULL AND s.expires_at>? AND i.revoked_at IS NULL "
                "AND i.case_id=s.case_id AND i.household_id=s.household_id",
                (binding["session_hash"], binding["case_id"], binding["household_id"], self.store.now())).fetchone()
            if row:
                return Actor(role="resident", actor_id=row["actor_id"], case_id=row["case_id"], household_id=row["household_id"])
        return None

    def create_link(self, actor, case_id, household_id):
        snapshot = self.store.owner_snapshot(actor, case_id)
        if not any(row.household_id == household_id for row in snapshot.household_labels):
            raise PlatformError(404, "household_not_found", "This household was not found on this case.")
        invitation = self.store.create_invitation(actor, case_id, household_id, snapshot.case.case_revision)
        token = self.store.exchange_invitation(invitation.invitation_token)
        code = secrets.token_hex(6).upper()
        expires = (self.store.clock() + timedelta(minutes=10)).astimezone(timezone.utc).isoformat()
        try:
            with self._db(write=True) as conn:
                conn.execute("INSERT INTO links VALUES (?,?,?,?,?,NULL)",
                    (hash_token(code), case_id, household_id, hash_token(token), expires))
        except BaseException:
            self.store.end_session(token)
            raise
        result = {"join_code": code, "join_message": "JOIN " + code, "expires_at": expires}
        line = os.environ.get("BRACE_PHOTON_LINE", "")
        if re.fullmatch(r"\+[1-9][0-9]{7,14}", line):
            result["line"] = line
        return result

    def inbound(self, message: Inbound):
        fingerprint = hash_token(dumps(message))
        with self._db(write=True) as conn:
            old = conn.execute("SELECT * FROM inbound WHERE message_id=?", (message.message_id,)).fetchone()
            if old:
                if not hmac.compare_digest(old["content_hash"], fingerprint):
                    raise PlatformError(409, "message_conflict", "This message ID already has different content.")
                return {**json.loads(old["response_json"]), "duplicate": True}
            response = self._receive(conn, message)
            response["duplicate"] = False
            conn.execute("INSERT INTO inbound VALUES (?,?,?,?)", (message.message_id, fingerprint, dumps(response), self.store.now()))
            return response

    def _receive(self, conn, message):
        text = message.text.strip()
        if message.poll_id is not None:
            return self._select_choice(conn, message)
        join = re.fullmatch(r"JOIN\s+([A-Z0-9-]{8,40})", text, re.I)
        if join:
            code_hash = hash_token(join.group(1).replace("-", "").upper())
            link = conn.execute("SELECT * FROM links WHERE code_hash=?", (code_hash,)).fetchone()
            if not link or link["used_at"] or link["expires_at"] <= self.store.now() or not self._actor(link):
                return {"kind": "join_required", "reply": "That join code is unavailable or expired. Ask the property team for a new private JOIN code."}
            conn.execute("UPDATE links SET used_at=? WHERE code_hash=?", (self.store.now(), code_hash))
            conn.execute("INSERT INTO bindings VALUES (?,?,?,?,?,?) ON CONFLICT(sender_id,space_id) DO UPDATE SET "
                "case_id=excluded.case_id,household_id=excluded.household_id,session_hash=excluded.session_hash,joined_at=excluded.joined_at",
                (message.sender_id, message.space_id, link["case_id"], link["household_id"], link["session_hash"], self.store.now()))
            return {"kind": "joined", "reply": "You're connected to your property's Brace alerts. Choose an action when an alert arrives, or reply here if you need help."}
        binding = conn.execute("SELECT * FROM bindings WHERE sender_id=? AND space_id=?", (message.sender_id, message.space_id)).fetchone()
        actor = self._actor(binding) if binding else None
        if not actor:
            return {"kind": "join_required", "reply": "Ask your property team for a private join code, then send JOIN followed by that code here. Do not post it in a group."}
        lower = text.lower().replace("’", "'")
        # Requests take priority over damage keywords: asking for housing after
        # flooding must not silently turn into a damage-only submission.
        access_need = (re.search(r"\b(stairs|elevator|access|entry)\b", lower)
                       and re.search(r"\b(can't|cannot|can not|unable to)\b", lower))
        help_requested = bool(access_need or re.search(r"\b(help|need|request|assistance|please|can (?:you|someone)|could (?:you|someone))\b", lower))
        if help_requested:
            category = ("housing" if re.search(r"\b(housing|shelter|hotel|stay|accommodation|displaced)\b", lower) else
                        "access" if re.search(r"\b(access|locked|lockout|key|entry|stairs|elevator)\b", lower) else
                        "communication" if re.search(r"\b(call|contact|phone|update|information|translate|translation)\b", lower) else "other")
            receipt = self.store.append_support_request(actor, SupportInput(category=category, description=text),
                "photon:" + hash_token(message.message_id))
            return {"kind": "support", "request_id": receipt.request_id,
                "reply": "The property team received your request. You'll get their updates here."}
        # Only explicit observations, not hypothetical questions or negations.
        report_words = re.search(r"\b(water|flood(?:ing|ed)?|leak(?:ing)?|smoke|ash|fire|damage(?:d)?|roof|broken|power outage)\b", lower)
        observed = (re.search(r"\b(i see|i saw|i noticed|there is|there's|my|our|in (?:the|my)|report)\b", lower)
                    or re.search(r"\b(water|smoke|ash|leak(?:ing)?)\s+(?:under|by|at|near|around|through|inside|in)\b", lower))
        uncertain = "?" in lower or re.search(r"\b(no|not|if|might|could|would)\b", lower)
        if report_words and observed and not uncertain:
            category = ("smoke_or_fire" if re.search(r"\b(smoke|ash|fire)\b", lower) else
                        "water" if re.search(r"\b(water|flood(?:ing|ed)?|leak(?:ing)?)\b", lower) else
                        "roof" if "roof" in lower else "power_or_access" if "power outage" in lower else "other")
            receipt = self.store.append_report(actor, ReportInput(category=category, text=text,
                selected_location_id=None, location_description=None, observed_at=None, upload_ids=[]),
                "photon:" + hash_token(message.message_id))
            return {"kind": "report", "request_id": receipt.report.report_id,
                "reply": "Your observation was received as an unverified resident report. The property team still needs to review it; this is not a safety clearance."}
        return {"kind": "clarify", "reply": "Are you asking for help, or reporting something you observed? Say HELP and what you need, or describe the issue and where you saw it. This channel does not dispatch emergency services."}

    def _select_choice(self, conn, message):
        poll = conn.execute(
            "SELECT * FROM outbox WHERE provider_message_id=? AND sender_id=? AND space_id=? "
            "AND notice_id LIKE '%:choices' AND status='provider_accepted'",
            (message.poll_id, message.sender_id, message.space_id)).fetchone()
        if poll is None or not message.option_id or message.text not in RESIDENT_CHOICES:
            return {"kind": "ignored"}
        binding = conn.execute("SELECT * FROM bindings WHERE sender_id=? AND space_id=?",
                               (message.sender_id, message.space_id)).fetchone()
        if not binding or binding["session_hash"] != poll["session_hash"]:
            return {"kind": "ignored"}
        actor = self._actor(binding)
        if not actor:
            return {"kind": "ignored"}
        if message.text == RESIDENT_CHOICES[0]:
            return {"kind": "acknowledged", "reply": "Thanks for checking in. You can ask for help here anytime."}
        if message.text == RESIDENT_CHOICES[3]:
            return {"kind": "report_prompt", "reply": "Tell the property team what you noticed and where. For example, water is coming in under my balcony door."}
        category = "access" if message.text == RESIDENT_CHOICES[1] else "housing"
        key = "photon-choice:" + hash_token(f"{message.poll_id}:{category}")
        receipt = self.store.append_support_request(actor, SupportInput(category=category, description=message.text), key)
        return {"kind": "support", "request_id": receipt.request_id,
                "reply": None if receipt.duplicate else "The property team received your request. You'll get their updates here."}

    def queue_notice(self, case_id, notice_id, title, body, *, property_name=None, threat=None):
        with self.store._read() as conn:
            row = conn.execute("SELECT * FROM notices WHERE case_id=? AND notice_id=? AND status='published'", (case_id, notice_id)).fetchone()
            if not row:
                raise PlatformError(404, "notice_not_found", "This published notice is unavailable.")
            notice = json.loads(row["json"])
            if notice.get("title") != title or notice.get("body") != body:
                raise PlatformError(409, "notice_changed", "Only the exact approved notice can be queued.")
            households = json.loads(row["household_ids_json"]) if row["household_ids_json"] else None
        if property_name and threat:
            return self._queue(case_id, notice_id + ":alert",
                               forecast_alert(property_name, title, body, threat), households,
                               card_asset=forecast_card(property_name, threat))
        return self._queue(case_id, notice_id, title + "\n\n" + body, households)

    def queue_household_update(self, case_id, household_id, event_id, text):
        """Queue an explicitly approved support response only for its event's household."""
        if not isinstance(text, str) or not text.strip() or len(text) > 4000:
            raise PlatformError(422, "invalid_update", "A household update needs 1 to 4000 characters.")
        with self.store._read() as conn:
            event = conn.execute("SELECT * FROM events WHERE case_id=? AND event_id=? AND type='support.updated'",
                (case_id, event_id)).fetchone()
            if not event or event["audience"] != "households" or household_id not in json.loads(event["households_json"] or "[]"):
                raise PlatformError(404, "update_not_found", "This household update was not found on this case.")
        return self._queue(case_id, "support-event:" + str(event_id), text, [household_id])

    def _queue(self, case_id, notice_id, text, households, *, card_asset=None):
        count, seen = 0, set()
        with self._db(write=True) as conn:
            previous = conn.execute("SELECT text FROM outbox WHERE case_id=? AND notice_id=? LIMIT 1", (case_id, notice_id)).fetchone()
            if previous and previous["text"] != text:
                raise PlatformError(409, "update_changed", "This update was already queued with different text.")
            rows = conn.execute("SELECT * FROM bindings WHERE case_id=? ORDER BY joined_at DESC", (case_id,)).fetchall()
            for binding in rows:
                if binding["sender_id"] in seen or (households is not None and binding["household_id"] not in households) or not self._actor(binding):
                    continue
                seen.add(binding["sender_id"])
                count += conn.execute("INSERT OR IGNORE INTO outbox (id,case_id,notice_id,household_id,sender_id,space_id,session_hash,text,status,created_at,card_asset) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?)", (new_id("photon"), case_id, notice_id, binding["household_id"],
                    binding["sender_id"], binding["space_id"], binding["session_hash"], text, "pending", self.store.now(),
                    card_asset)).rowcount
        return count

    def claim_outbox(self):
        items = []
        with self._db(write=True) as conn:
            for row in conn.execute("SELECT * FROM outbox WHERE status='pending' ORDER BY created_at,id LIMIT 50").fetchall():
                binding = conn.execute("SELECT * FROM bindings WHERE sender_id=? AND space_id=?", (row["sender_id"], row["space_id"])).fetchone()
                valid = binding and all(binding[key] == row[key] for key in ("case_id", "household_id", "session_hash")) and self._actor(binding)
                if not valid:
                    conn.execute("UPDATE outbox SET status='cancelled' WHERE id=?", (row["id"],))
                    continue
                conn.execute("UPDATE outbox SET status='claimed',claimed_at=? WHERE id=?", (self.store.now(), row["id"]))
                item = {"id": row["id"], "space_id": row["space_id"], "text": row["text"]}
                if row["notice_id"].endswith(":choices"):
                    item["choices"] = list(RESIDENT_CHOICES)
                elif row["card_asset"] in FORECAST_CARDS:
                    item["card_png"] = b64encode(FORECAST_CARDS[row["card_asset"]].read_bytes()).decode("ascii")
                items.append(item)
        return {"items": items}

    def acknowledge(self, item_id, acknowledgment: Acknowledgment):
        status = "provider_accepted" if acknowledgment.status == "sent" else "failed"
        with self._db(write=True) as conn:
            row = conn.execute("SELECT * FROM outbox WHERE id=?", (item_id,)).fetchone()
            if not row:
                raise PlatformError(404, "delivery_not_found", "This queued message was not found.")
            if row["status"] == status:
                return {"ok": True, "status": status, "duplicate": True}
            if row["status"] != "claimed":
                raise PlatformError(409, "delivery_state_conflict", "This delivery cannot be acknowledged in its current state.")
            conn.execute("UPDATE outbox SET status=?,acknowledged_at=?,provider_message_id=?,error=? WHERE id=?",
                (status, self.store.now(), acknowledgment.provider_message_id,
                 "Provider send failed or delivery is uncertain; no automatic resend." if acknowledgment.status == "failed" else None, item_id))
            if status == "provider_accepted" and row["notice_id"].endswith(":alert"):
                conn.execute(
                    "INSERT OR IGNORE INTO outbox (id,case_id,notice_id,household_id,sender_id,space_id,session_hash,text,status,created_at) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (new_id("photon"), row["case_id"], row["notice_id"] + ":choices", row["household_id"],
                     row["sender_id"], row["space_id"], row["session_hash"], "What do you need?",
                     "pending", self.store.now()))
        return {"ok": True, "status": status, "duplicate": False}

    def status(self, actor, case_id):
        self.store.owner_snapshot(actor, case_id)
        with self._db() as conn:
            bindings = conn.execute("SELECT * FROM bindings WHERE case_id=? ORDER BY joined_at", (case_id,)).fetchall()
            counts = {row["status"]: row["n"] for row in conn.execute("SELECT status,count(*) n FROM outbox WHERE case_id=? GROUP BY status", (case_id,))}
            connections = [{"connection_id": hash_token(row["sender_id"] + "\0" + row["space_id"])[:20],
                "household_id": row["household_id"], "joined_at": row["joined_at"], "active": self._actor(row) is not None} for row in bindings]
        return {"case_id": case_id, "active_connections": sum(row["active"] for row in connections),
                "connections": connections, "delivery": counts,
                "delivery_note": "Provider acceptance is not confirmed delivery. Claimed or failed messages are not automatically resent."}


def build_photon_router(store, service=None):
    service = service or getattr(store, "_brace_photon_service", None) or PhotonService(store)
    store._brace_photon_service = service
    router = APIRouter(route_class=EnvelopeRoute)
    owner = make_owner_dependency(store)

    def available(request):
        request.app.state.brace_photon_service = service
        return service

    def worker(request):
        expected = os.environ.get("BRACE_PHOTON_BRIDGE_SECRET", "")
        provided = request.headers.get("authorization", "")
        if not expected:
            raise PlatformError(503, "photon_unavailable", "Photon delivery is not configured.")
        if not hmac.compare_digest(provided.encode(), ("Bearer " + expected).encode()):
            raise PlatformError(401, "worker_unauthorized", "Worker authentication is required.")

    @router.post("/api/recovery/cases/{case_id}/households/{household_id}/photon-link")
    def create_link(case_id: str, household_id: str, request: Request):
        return available(request).create_link(owner(request), case_id, household_id)

    @router.get("/api/recovery/cases/{case_id}/photon")
    def get_status(case_id: str, request: Request):
        return available(request).status(owner(request), case_id)

    @router.post("/api/recovery/photon/inbound")
    def inbound(body: Inbound, request: Request):
        worker(request)
        return available(request).inbound(body)

    @router.get("/api/recovery/photon/outbox")
    def outbox(request: Request):
        worker(request)
        return available(request).claim_outbox()

    @router.post("/api/recovery/photon/outbox/{item_id}/ack")
    def acknowledge(item_id: str, body: Acknowledgment, request: Request):
        worker(request)
        return available(request).acknowledge(item_id, body)

    return router
