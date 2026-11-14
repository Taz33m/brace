# Shared contract v1 — owned by Tazeem / lead

The companion `shared-contract.ts` is the wire/type source for the first recovery slice. Owner UI installs it verbatim as `frontend/src/recovery/contracts.ts`. Platform implements matching Pydantic responses. The lead implements the client and domain service. No other owner changes field names, endpoints, or state semantics independently.

## Common rules

- JSON uses snake_case. IDs are opaque strings. All timestamps are ISO 8601 with timezone; unknown timestamps are null. Source dates without time retain a date-only representation when the source only supplies that precision.
- Money is USD in decimal dollars for this version; calculations use Decimal/integer cents internally and round at presentation boundaries. Unknown money is null, never zero. Range low/high must both be null or both finite, with low <= high.
- A property reference includes dataset and ID. All input IDs are resolved and authorized server-side.
- `case_revision` versions the whole case. `analysis_revision` versions only the inputs to an assessment. Starting/finishing a run or publishing a notice does not itself change analysis inputs.
- `observed_recovery` uses dated observations; `historical_replay` requires a verified knowledge cutoff; `scenario_exercise` visibly identifies hypothetical reports/assumptions. No fixture is an automatic network-error fallback.
- Error envelope: `{ "error": { "code": "revision_conflict", "message": "This case changed. Reload before applying this edit.", "retryable": true, "current_revision": 12 } }`. Use 401 unauthenticated, 403 unauthorized, 404 absent/inaccessible object, 409 conflict, 413 upload limit, 422 invalid request, 503 unavailable domain service. Do not expose stack traces or secrets.

## HTTP surface

All calls are same-origin through the existing Vite proxy. Cookies establish identity; no role or household identity is trusted from request JSON.

| Method and path | Input | Response / access |
|---|---|---|
| POST `/api/recovery/session` | `{secret}` for configured local owner bootstrap | Owner session cookie; no default credential |
| GET `/api/recovery/cases` | none | `{cases: RecoveryCaseSummary[]}`; owner |
| GET `/api/recovery/cases/{case_id}` | none | OwnerCaseView; owner assigned to case |
| POST `/api/recovery/cases/{case_id}/commands` | OwnerCommand, `Idempotency-Key` header | CommandResult; owner; compare expected_revision |
| GET `/api/recovery/cases/{case_id}/events?after={cursor}` | after or Last-Event-ID | Owner-scoped SSE |
| POST `/api/resident/session` | `{invitation_token}` | `{ok:true}` and resident session cookie |
| GET `/api/resident/home` | none | ResidentHome; case/household from session |
| POST `/api/resident/uploads` | multipart image, `Idempotency-Key` | UploadedMedia; resident ownership enforced |
| POST `/api/resident/reports` | ReportInput, `Idempotency-Key` | ReportReceipt; session-bound |
| POST `/api/resident/support` | SupportInput, `Idempotency-Key` | SupportReceipt; session-bound |
| GET `/api/resident/events?after={cursor}` | after or Last-Event-ID | Redacted resident SSE |
| GET `/api/recovery/media/{media_id}` | none | Authorized media bytes; case/household/source permission checked |

An owner command is a single endpoint to keep frontend adapters small. The server dispatches to typed handlers; it is not an arbitrary method or tool executor. Unsupported commands fail validation. Lead may add an endpoint only by amending this contract for all owners.

## Commands

All OwnerCommands include `expected_revision`. Types: `start_assessment`, `publish_assessment`, `review_observation`, `transition_task`, `publish_notice`, `create_invitation`. No command exposes arbitrary SQL, model prompts, filesystem paths, roles, or schema mutations.

`start_assessment` returns a `run_id`; repeat for the same active analysis revision returns the active run. The model worker reads a frozen snapshot. A report during the run advances analysis_revision; completion then saves a stale result and does not replace the current assessment. Publishing checks current inputs again.

Case/evidence bootstrap, market assumptions, and task proposals are lead domain operations through the store interface; they need not have a public editing screen in v1. Task proposals become visible through the case snapshot.

## States

Observation: `reported -> under_review -> verified|dismissed`. Direct reported-to-verified/dismissed is allowed only with an authorized review note/evidence basis. Corrections preserve prior versions.

Assessment: `running -> draft|stale|failed`; `draft -> published|stale`; published versions stay in history and are superseded by a later published version. Interrupted runs are marked failed with a retryable reason on restart. Task/notice updates alone do not stale an assessment; new condition/cost inputs do.

Task: `proposed -> approved -> accepted -> in_progress -> completion_submitted -> verified`. Any nonterminal state can become `cancelled` with a reason. Acceptance needs a confirmation source; completion submission needs evidence; verification needs an authorized reviewer. Changed accepted scope requires a new task revision and renewed acceptance. The model cannot make these confirmations. Occupancy clearance is a separate fact outside these transitions.

Notice: draft content stays owner-only until an explicit publish command. Published resident copy excludes private financial information and internal model analysis. No SMS/email is sent by publication in v1.

## Events

SSE `id` is a persisted integer cursor (serialized as a string in the SSE framing). Data is CaseEvent JSON. Events are committed with the corresponding mutation, ordered, and replayable. Heartbeats are comments. Resume with Last-Event-ID or `after`; server permissions are applied on every connection and replay.

Events carry IDs/revisions, not entire case snapshots or private resident text. Clients refresh their authorized snapshot when relevant events arrive. Resident event types are limited to `report.updated`, `support.updated`, `task.updated`, `notice.published`, `session.revoked`, and `case.updated` only when its public projection changes. Household-specific events are delivered only to that household. Duplicate event IDs are harmless.

## Frontend integration

Owner UI's RecoveryWorkspace is a presentational component with callbacks and map/interior slots, specified in its handoff. The lead owns the owner snapshot subscription and turns OwnerCommand callbacks into HTTP calls, then refreshes after successful mutation. API errors must remain visible.

ResidentExperience receives ResidentApi. The lead bootstraps the session from a QR/invitation fragment, removes the token, and mounts it. Resident boot does not initialize preparation/owner data requests. Person 3 can inject a fake API only in an explicit preview.

Local UI state (selected tab, selected room, draft text) belongs to the component. Confirmed work status, publication, assessment revisions, and permissions belong to the server.

## Six integration cases everyone must support

1. Missing price: value is unavailable, no $0 fallback.
2. Report with no matched unit scan: descriptive location accepted; no false exact-room selection.
3. Duplicate report retry: one report and receipt, no duplicate side effects.
4. Report during model run: prior result becomes stale; UI keeps the newer inputs.
5. Task only proposed: resident never sees “booked” or “contractor on the way.”
6. Resident from a different household: reports/media/events/finances stay inaccessible.
