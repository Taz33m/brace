"""SQLite schema and migrations, versioned with PRAGMA user_version.

Every table exists from v1 so later phases need no reshuffle. Columns hold what we
filter, join, or constrain on; `json` columns hold the contract payload.
"""
from __future__ import annotations

import sqlite3

MIGRATIONS: list[str] = [
    # v1
    """
    CREATE TABLE cases (
        case_id TEXT PRIMARY KEY,
        owner_id TEXT NOT NULL,
        case_revision INTEGER NOT NULL,
        analysis_revision INTEGER NOT NULL,
        summary_json TEXT NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    CREATE TABLE locations (
        case_id TEXT NOT NULL REFERENCES cases(case_id),
        location_id TEXT NOT NULL,
        json TEXT NOT NULL,
        PRIMARY KEY (case_id, location_id)
    );
    CREATE TABLE households (
        household_id TEXT PRIMARY KEY,
        case_id TEXT NOT NULL REFERENCES cases(case_id),
        unit_label TEXT,
        unit_confirmed INTEGER NOT NULL DEFAULT 0,
        location_ids_json TEXT NOT NULL,
        created_at TEXT NOT NULL
    );
    CREATE TABLE evidence (
        evidence_id TEXT PRIMARY KEY,
        case_id TEXT NOT NULL REFERENCES cases(case_id),
        household_id TEXT,
        json TEXT NOT NULL,
        created_at TEXT NOT NULL
    );
    CREATE TABLE observations (
        observation_id TEXT PRIMARY KEY,
        case_id TEXT NOT NULL REFERENCES cases(case_id),
        household_id TEXT,
        report_id TEXT,
        status TEXT NOT NULL,
        version INTEGER NOT NULL,
        json TEXT NOT NULL
    );
    CREATE TABLE observation_versions (
        observation_id TEXT NOT NULL,
        version INTEGER NOT NULL,
        json TEXT NOT NULL,
        actor_id TEXT NOT NULL,
        at TEXT NOT NULL,
        PRIMARY KEY (observation_id, version)
    );
    CREATE TABLE reports (
        report_id TEXT PRIMARY KEY,
        case_id TEXT NOT NULL REFERENCES cases(case_id),
        household_id TEXT NOT NULL REFERENCES households(household_id),
        observation_id TEXT NOT NULL,
        json TEXT NOT NULL,
        received_at TEXT NOT NULL
    );
    CREATE TABLE media (
        media_id TEXT PRIMARY KEY,
        upload_id TEXT UNIQUE,
        case_id TEXT NOT NULL REFERENCES cases(case_id),
        household_id TEXT,
        mime_type TEXT NOT NULL,
        sha256 TEXT NOT NULL,
        size_bytes INTEGER NOT NULL,
        original_name TEXT NOT NULL,
        display_name TEXT NOT NULL,
        received_at TEXT NOT NULL,
        attached_report_id TEXT
    );
    CREATE TABLE runs (
        run_id TEXT PRIMARY KEY,
        case_id TEXT NOT NULL REFERENCES cases(case_id),
        base_analysis_revision INTEGER NOT NULL,
        status TEXT NOT NULL,
        failure_reason TEXT,
        created_at TEXT NOT NULL,
        finished_at TEXT
    );
    CREATE UNIQUE INDEX runs_one_active ON runs(case_id, base_analysis_revision) WHERE status = 'running';
    CREATE TABLE assessments (
        assessment_id TEXT PRIMARY KEY,
        run_id TEXT NOT NULL UNIQUE,
        case_id TEXT NOT NULL REFERENCES cases(case_id),
        base_analysis_revision INTEGER NOT NULL,
        status TEXT NOT NULL,
        json TEXT NOT NULL,
        created_at TEXT NOT NULL
    );
    CREATE TABLE tasks (
        task_id TEXT PRIMARY KEY,
        case_id TEXT NOT NULL REFERENCES cases(case_id),
        revision INTEGER NOT NULL,
        status TEXT NOT NULL,
        json TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    CREATE TABLE task_versions (
        task_id TEXT NOT NULL,
        revision INTEGER NOT NULL,
        json TEXT NOT NULL,
        actor_id TEXT NOT NULL,
        note TEXT,
        at TEXT NOT NULL,
        PRIMARY KEY (task_id, revision)
    );
    CREATE TABLE notices (
        notice_id TEXT PRIMARY KEY,
        case_id TEXT NOT NULL REFERENCES cases(case_id),
        status TEXT NOT NULL CHECK (status IN ('draft', 'published')),
        household_ids_json TEXT,
        json TEXT NOT NULL,
        created_at TEXT NOT NULL
    );
    CREATE TABLE support_requests (
        request_id TEXT PRIMARY KEY,
        case_id TEXT NOT NULL REFERENCES cases(case_id),
        household_id TEXT NOT NULL REFERENCES households(household_id),
        json TEXT NOT NULL,
        received_at TEXT NOT NULL
    );
    CREATE TABLE events (
        event_id INTEGER PRIMARY KEY AUTOINCREMENT,
        case_id TEXT NOT NULL,
        type TEXT NOT NULL,
        audience TEXT NOT NULL CHECK (audience IN ('owner', 'case', 'households')),
        households_json TEXT,
        case_revision INTEGER NOT NULL,
        analysis_revision INTEGER NOT NULL,
        entity_id TEXT,
        public_summary TEXT,
        at TEXT NOT NULL
    );
    CREATE INDEX events_by_case ON events(case_id, event_id);
    CREATE TABLE invitations (
        invitation_id TEXT PRIMARY KEY,
        token_hash TEXT NOT NULL UNIQUE,
        case_id TEXT NOT NULL REFERENCES cases(case_id),
        household_id TEXT NOT NULL REFERENCES households(household_id),
        created_by TEXT NOT NULL,
        created_at TEXT NOT NULL,
        expires_at TEXT NOT NULL,
        revoked_at TEXT
    );
    CREATE TABLE sessions (
        session_hash TEXT PRIMARY KEY,
        role TEXT NOT NULL CHECK (role IN ('owner', 'resident')),
        actor_id TEXT NOT NULL,
        case_id TEXT,
        household_id TEXT,
        invitation_id TEXT,
        created_at TEXT NOT NULL,
        expires_at TEXT NOT NULL,
        revoked_at TEXT
    );
    CREATE TABLE idempotency (
        actor_id TEXT NOT NULL,
        operation TEXT NOT NULL,
        idem_key TEXT NOT NULL,
        request_hash TEXT NOT NULL,
        response_json TEXT NOT NULL,
        created_at TEXT NOT NULL,
        PRIMARY KEY (actor_id, operation, idem_key)
    );
    """,
    # v2: source evidence IDs are stable across incidents/case versions. Their
    # uniqueness and authorization boundary is the case, not the whole database.
    """
    CREATE TABLE evidence_case_scoped (
        evidence_id TEXT NOT NULL,
        case_id TEXT NOT NULL REFERENCES cases(case_id),
        household_id TEXT,
        json TEXT NOT NULL,
        created_at TEXT NOT NULL,
        PRIMARY KEY (case_id, evidence_id)
    );
    INSERT INTO evidence_case_scoped (evidence_id, case_id, household_id, json, created_at)
        SELECT evidence_id, case_id, household_id, json, created_at FROM evidence;
    DROP TABLE evidence;
    ALTER TABLE evidence_case_scoped RENAME TO evidence;
    """,
]


def migrate(conn: sqlite3.Connection) -> int:
    """Apply pending migrations; returns the resulting schema version."""
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    for index in range(version, len(MIGRATIONS)):
        conn.executescript("BEGIN IMMEDIATE;" + MIGRATIONS[index] + f"; PRAGMA user_version = {index + 1}; COMMIT;")
    return len(MIGRATIONS)
