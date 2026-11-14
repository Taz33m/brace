# Recovery Platform Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Persistent, permission-checked recovery case state (cases, households, reports, uploads, observations, tasks, notices, assessments, events, sessions) behind an importable FastAPI router.

**Architecture:** `CaseStore` over stdlib `sqlite3` (WAL, `busy_timeout=5000`, one connection per call, `BEGIN IMMEDIATE` per mutation). Each mutation checks revisions, writes, bumps revisions and appends its event in one transaction. `build_router(store, assessment_launcher)` adds cookie sessions and the JSON error envelope.

**Tech Stack:** Python 3.11+, FastAPI 0.162, Pydantic 2.14, sqlite3, Pillow, sse-starlette (all already installed). No new dependencies.

**Spec:** `backend/recovery/platform/docs/2026-11-14-recovery-platform-design.md` plus `docs/recovery-handoffs/04-RECOVERY-PLATFORM.md`, `05-SHARED-CONTRACT.md`, `shared-contract.ts`, `docs/recovery-core.md`.

## Global Constraints

- Write only `backend/recovery/platform/**`, `tests/test_recovery_platform*.py`, `tests/test_recovery_permissions*.py`.
- Field names and shapes match `shared-contract.ts` exactly; snake_case; timestamps ISO 8601 with timezone; unknown money/time is `None`, never `0`.
- Error envelope `{"error": {"code", "message", "retryable", "current_revision"}}`; 401/403/404/409/413/422/503 as in the contract; no stack traces.
- Owner secret env var `BRACE_OWNER_SECRET`; unset or empty means owner login is disabled. No default.
- Invitation and session tokens are stored as SHA-256 hashes only.
- Household and case always come from the server session.
- Nothing is sent externally. The model never verifies, accepts, or confirms.
- Tests use `tmp_path`, no network, no keys.

## Review Focus

1. A resident guesses another household's `report_id`/`media_id`/`upload_id`: expect 404 (media) or 422 `upload_unavailable` (attach), never data. Tested in Tasks 5 and 6.
2. Two owner tabs submit commands at the same `expected_revision`: exactly one 200, the other 409 with `current_revision`. Tested in Task 7.
3. Phone retries a report after a timeout with the same key: one report, `duplicate: true`. A body changed under the same key gets 409 `idempotency_conflict`. Tested in Task 4.
4. A server restart while a run is `running`: the run becomes `failed` with a retryable reason. Tested in Task 8.
5. A malformed/oversized/non-image upload (a `.txt` renamed `.jpg`) gets 422 `unsupported_media` or 413. Tested in Task 6.

---

### Task 1: Errors and wire models

**Files:** Create `backend/recovery/platform/__init__.py`, `errors.py`, `models.py`. Test `tests/test_recovery_platform_models.py`.

**Produces:** `PlatformError(status: int, code: str, message: str, retryable: bool = False, current_revision: int | None = None)` with `.envelope() -> dict`. Pydantic models named exactly as the TS interfaces (`LocationRef`, `MediaRef`, `Evidence`, `Observation`, `MoneyRange`, …, `ResidentHome`, `ApiErrorBody`). `OwnerCommand` is a discriminated union on `type`. Extra: `CaseInput` (store-only bootstrap; `from_seed(seed: dict)`).

- [ ] Test `test_every_ts_interface_has_matching_model_fields`: parse `shared-contract.ts` interfaces with a regex and assert that each Pydantic model's `model_fields` keys equal the TS field set (skip `ResidentApi`).
- [ ] Test `test_owner_command_union_rejects_unknown_type` and `test_money_range_low_high_both_null_or_ordered`.
- [ ] Implement, run, commit.

### Task 2: Schema and case basics

**Files:** Create `schema.py`, `store.py`. Test `tests/test_recovery_platform_store.py`.

**Produces:** `Actor(role: Literal["owner","resident","system"], actor_id: str, case_id: str|None, household_id: str|None)` in `auth.py`. `CaseStore(db_path, media_dir=None)`, `create_case(actor, CaseInput) -> RecoveryCaseSummary`, `add_household(actor, case_id, unit_label, *, unit_confirmed=False, location_ids=()) -> str`, `list_cases(actor)`, `owner_snapshot(actor, case_id) -> OwnerCaseView`.

- [ ] Tests: a case persists after reopening the store; `list_cases` hides other owners' cases; `owner_snapshot` of a missing or foreign case raises 404.
- [ ] Implement migrations through `PRAGMA user_version`. Create all tables now.
- [ ] Run and commit.

### Task 3: Invitations and sessions

**Files:** `auth.py`, `store.py`. Test `tests/test_recovery_permissions.py`.

**Produces:** `store.create_invitation(actor, case_id, household_id, expected_revision, ttl=timedelta(hours=72)) -> CommandResult`, `store.exchange_invitation(token) -> str` (session token), `store.create_owner_session(owner_id) -> str`, `store.resolve_session(token) -> Actor | None`, `store.revoke_invitation(actor, case_id, invitation_id)`. `auth.check_owner_secret(secret) -> bool`.

- [ ] Tests: expired invitation fails; revoked invitation fails and kills its sessions; the DB never contains a raw token; owner login fails when the env var is unset.
- [ ] Implement, run, commit.

### Task 4: Reports, resident home, events

**Produces:** `append_report(actor, ReportInput, idempotency_key) -> ReportReceipt`, `resident_home(actor) -> ResidentHome`, `events_after(actor, cursor, case_id=None, limit=500) -> list[CaseEvent]`.

- [ ] Tests: retry returns one report with `duplicate=True`; same key with a different body gives 409; a report bumps both revisions; resident B's home excludes A's report; a resident's events exclude owner-only types.
- [ ] Implement, run, commit.

### Task 5: Phase-1 router

**Files:** `router.py`. Test `tests/test_recovery_platform_api.py`.

**Produces:** `build_router(store, assessment_launcher=None) -> APIRouter`; `make_owner_dependency(store)`.

- [ ] Tests: the full HTTP loop of owner login → create_invitation → resident exchange → report → owner sees it. Plus 401 without a cookie, cross-household 403/404, a cookie that is HttpOnly, and the error envelope shape.
- [ ] Implement, run, commit, push.

### Task 6: Uploads and media

**Files:** `uploads.py`, `store.py`, `router.py`. Limit `MAX_UPLOAD_BYTES = 10 * 1024 * 1024`; JPEG/PNG/WEBP; display copy re-encoded as JPEG without EXIF, max 2048 px.

- [ ] Tests: a valid PNG uploads; a fake image gives 422; an oversized upload gives 413; GPS EXIF is absent from the served copy; another resident's media gives 404; attaching another household's upload gives 422.
- [ ] Implement, run, commit.

### Task 7: Owner commands with revisions

**Produces:** `review_observation`, `transition_task`, `publish_notice`, dispatched by `store.apply_command(actor, case_id, OwnerCommand, idempotency_key)`.

- [ ] Tests: a stale `expected_revision` gives 409 with `current_revision`; concurrent threads produce one success and one 409; invalid task transitions are rejected; acceptance without `confirmation_source` is rejected; completion without evidence is rejected; a notice stays hidden from other households.
- [ ] Implement, run, commit.

### Task 8: Assessment hook

**Produces:** `start_assessment` command, `snapshot_for_analysis(case_id)`, `complete_assessment(run_id, base_analysis_revision, result)`, `publish_assessment` command, `recover_interrupted_runs()` (called in `__init__`).

- [ ] Tests: no launcher gives 503 `assessment_unavailable`; a repeat start returns the same run; a report during a run makes the result stale; a notice alone does not; a restart fails running runs; completion is idempotent by run id; publishing a stale draft gives 409.
- [ ] Implement, run, commit, push.

### Task 9 (Phase 3): SSE, support, origin check

- [ ] SSE `/events` for owner and resident (`after` / `Last-Event-ID`, heartbeat comment), `POST /api/resident/support`, an origin check for state-changing routes controlled by `BRACE_ALLOWED_ORIGINS`.
- [ ] Tests, commit, push.

### Task 10: Review and PR

- [ ] Fresh reviewer on the whole branch; fix findings; full `uv run pytest`; open a PR with the return note.
