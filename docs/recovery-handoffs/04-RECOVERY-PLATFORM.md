# Person 4 — Persistent recovery platform and permissions

## Lead integration checkpoint (November 14)

The lead has reviewed the first `p4-recovery-platform` branch and prepared the assembly code. Continue your existing ownership scope; do not edit the lead's runtime or frontend adapters.

- `CaseInput.from_seed(seed)` needs the source inventory's `locations` supplied alongside the seed. The lead will handle this bootstrap; do not infer household/unit bindings from those locations.
- `backend/recovery/runtime.py::install_recovery` takes your `build_router`, complete store, registry, owner authorizer, and a case-scoped snapshot resolver. It checks for `snapshot_for_analysis` and `complete_assessment` before mounting.
- Worker snapshots must be JSON-compatible dictionaries; HTTP snapshots may remain Pydantic models. The assessment completion call receives the entire `{assessment, proposed_tasks, draft_notices, trace}` envelope.
- Keep completing uploads/media, SSE, support, review/task/publication commands, run restart handling, and mutation Origin/CSRF checks from the assignment below. The first branch's session/invitation/text-report paths are not yet the full runtime.
- The owner viewer routes are lead-owned: `/api/recovery/cases/{case_id}/spatial` and `/api/recovery/cases/{case_id}/evidence/{evidence_id}/image`. They authorize the case before reading the immutable registered source bundle. Resident upload media remains your responsibility.

## Assignment

Own the state the product can rely on: cases, residents, reports, uploads, events, assessments, tasks, sessions, and publication. The lead owns sponsor adapters, damage interpretation, valuation mathematics, and the model loop. Do not build competing domain logic.

Read the team overview, shared contract, and TypeScript wire types. Build matching Pydantic models. Contract semantics belong to the lead; propose changes before diverging.

## Exclusive write scope

- `/Users/tazeemmahashin/brace/backend/recovery/platform/**`
- `/Users/tazeemmahashin/brace/tests/test_recovery_platform*.py`
- `/Users/tazeemmahashin/brace/tests/test_recovery_permissions*.py`

Do not edit server.py, existing config, pyproject/lockfiles, preparation logic, frontend code, or sponsor clients. Provide an importable router and a minimal wiring request to the lead. Tests may construct their own FastAPI instance. Store migrations inside your package and production data only under git-ignored local data, with temp directories in tests.

## Build order

1. Models and SQLite schema with cases, households, observations/reports, evidence metadata, upload ownership, assessments, tasks, notices, requests, events, sessions/invitations, and idempotency records.
2. Transactional case snapshot, report insertion, event append, and resident projection.
3. Owner session dependency and scoped resident invitation exchange. Protected upload/download.
4. Persistent event stream with reconnect cursor and server-side role filtering.
5. Assessment-run hook, revision checks, task transitions, publication, and audit trail.
6. Isolation, concurrency, retry, and restart tests. Return integration interface to lead.

## Revisions and transactions

`case_revision` increments on each public state mutation. `analysis_revision` increments only when assessment inputs change: evidence/report state, confirmed space binding, market/cost assumptions, or verified completion that changes condition. Notice publication and ordinary notification delivery do not invalidate the assessment.

Apply a mutation and append its event in one database transaction. Use expected `case_revision` for owner edits. Append-only resident submissions use idempotency without rejecting merely because unrelated activity advanced a case.

An assessment starts against `analysis_revision`. When the lead commits it, compare against the current analysis revision. Persist a stale result as history with status `stale`, never as the current assessment. Publishing also checks it is current. Do not let client-provided flags decide whether a command invalidates analysis.

SQLite WAL is sufficient for this local prototype. Keep transactions short and use separate connections per request/worker; no long model call inside a transaction. Enforce unique constraints for active deduplicated submissions and use a transaction/busy timeout to handle concurrent writes. Idempotency records bind actor, operation, and canonical request hash; the same key with a different body is a conflict.

## Store interface delivered to the lead

Export `CaseStore` from `platform/store.py`, Pydantic wire models from `platform/models.py`, and `build_router(store, assessment_launcher)` from `platform/router.py`.

Required store operations (Python names may be finalized in your first interface checkpoint, but semantics must remain):

- `create_case(actor, case_input)`
- `list_cases(actor)` and `owner_snapshot(actor, case_id)`
- `resident_home(actor)` with a separate allowlisted projection
- `append_report(actor, request, idempotency_key)` and `append_support_request(...)`
- `add_evidence(actor, case_id, evidence_input, expected_revision)`
- `verify_observation(actor, case_id, observation_id, decision, expected_revision)`
- `snapshot_for_analysis(case_id)` returning immutable inputs plus analysis revision
- `create_assessment_run(actor, case_id, expected_revision)` returning a run ticket
- `complete_assessment(run_id, base_analysis_revision, result)` applying stale detection
- `publish_assessment(actor, case_id, assessment_id, expected_revision)`
- `transition_task(actor, case_id, task_id, command, expected_revision)`
- `publish_notice(actor, case_id, notice, expected_revision)`
- `events_after(actor, cursor)` and invitation/session/upload operations

The injected assessment launcher receives a run ticket and returns promptly; the lead performs domain work in its own worker and commits through the store. If no launcher is wired, return a structured 503 `assessment_unavailable`, never fabricated output. Repeated start requests for the same active analysis revision return the existing run. On restart, unfinished in-memory work must become explicitly interrupted/retryable; do not leave a permanent “running” state.

## Permission model

Authenticated `owner` access is restricted to assigned properties/cases. Resident invitations are high-entropy, scoped to one case and household, expiring and revocable; store token hashes only. Exchange the invitation in a POST body for an HttpOnly session and remove it from the browser fragment. Secure cookie on HTTPS, same-origin requests, and CSRF protection/origin validation for state changes.

Residents read only their own reports/support/task projections and notices intended for them or the whole case. A report identity and case binding come from the server session, never a client-supplied household ID. No owner valuations, other households, unpublished notices, internal agent text, or unrestricted site imagery in resident responses/events.

Expose an owner-auth dependency the lead can attach to existing owner endpoints. Gating only the new routes is insufficient because the old building/plan/image endpoints are currently accessible. Phone access is not ready until those legacy endpoints are also gated by the lead.

For local demo owner login, propose a small environment-configured secret/session bootstrap with no unauthenticated default or hardcoded credential. Put environment setup in the handoff to the lead; do not edit or print existing .env contents.

## Upload and media behavior

Accept only supported image types after decoding, with a documented size limit. Generate server filenames; reject traversal; bind temporary uploads to the resident session; attaching them rechecks case/household ownership. Do not let one resident attach another's upload ID.

Serve protected media through role-checked endpoints, not a public static directory. Keep original evidence metadata and a sanitized display derivative; avoid leaking EXIF location to other viewers. Record a content hash and server receive time. Client observation time is separate and may be null. Do not fetch arbitrary URLs supplied in resident report text.

## Workflow and publication

Observation states: reported, under_review, verified, dismissed. Verification requires an authorized actor, note, and evidence basis. The model cannot self-verify.

Task states and transitions are in the shared contract. Every accepted/verified step records confirmation source and actor. An owner may record a contractor's confirmed acceptance, but cannot manufacture a contractor acknowledgment through an automatic model action. Changes to accepted scope create a new revision and require acknowledgment again; prior scope stays in history.

Published notices are separate from drafts. Sending through SMS/email is not part of this assignment. Resident read status never masquerades as physical repair completion. Occupancy clearance, if supplied later, is a separate sourced fact, never inferred from the task status.

## Acceptance tests

- Persistence survives reopening the store; pending run restart behavior is explicit.
- Concurrent owner edits yield a 409 for the stale version.
- Retrying a resident submission returns the original receipt; altered body with same key conflicts.
- A report arriving during analysis makes older results stale; publishing notices alone does not.
- Resident A cannot read/report as/upload for Resident B, access owner finances, enumerate private media, or subscribe to private events.
- Expired/revoked invitations and sessions fail safely.
- Unsupported/oversized/malformed uploads are rejected.
- Invalid task transitions and missing confirmation/evidence are rejected.
- Reconnect resumes after the event ID without duplicating mutation side effects.
- Fake dates/values/hidden effects are not supplied to make the demo look complete.

Return router/store exports, schema/migration notes, environment requirements, integration diff request, test results, and remaining limits. No live messages, deployment, credential changes, or valuation implementation.
