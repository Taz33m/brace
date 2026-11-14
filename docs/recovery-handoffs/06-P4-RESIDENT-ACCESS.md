# P4 next — owner-controlled resident access

The household-creation endpoint is implemented and the lead is wiring its form. Own the next platform slice: an owner can inspect and revoke a household's access without a local script.

Stay within `backend/recovery/platform/` and focused platform tests. Do not change the lead's source registry, agent, shared frontend, or P2 workspace.

## Implement

- Expose an authenticated, case-scoped access listing with household identity and invitation IDs, creation/expiry/revocation dates, and active-session counts. Reuse `CaseStore.invitations`; never return raw tokens, token hashes, or session identifiers.
- Add an owner mutation to revoke all currently issued invitations and active sessions for one household. Require `expected_revision` and `Idempotency-Key`; authorize the owner and household against the case inside the transaction. Reuse the existing invitation revocation semantics, extending them atomically for the household operation.
- Increment case revision once, retain analysis revision, and emit an owner audit event plus a household-scoped `session.revoked` event. Preserve reports, media, support requests, and household identity. A new invitation may subsequently restore access; revocation is not deletion.
- Revocation must stop existing resident HTTP requests and streams, and prevent exchange of old invitation links. Other households and cases must remain unaffected. Concurrent invitation creation must serialize with revocation so the outcome is well defined.

## Proposed API — confirm the exact shape to the lead before UI wiring

`GET /api/recovery/cases/{case_id}/households/access`

Return `{case_id, case_revision, households:[{household_id, unit_label, active_session_count, invitations:[{invitation_id, created_at, expires_at, revoked_at}]}]}`.

`POST /api/recovery/cases/{case_id}/households/{household_id}/revoke-access`

Body: `{expected_revision}`. Required header: `Idempotency-Key`.

Return `{case_id, household_id, case_revision, analysis_revision, revoked_invitation_count, revoked_session_count, duplicate}`.

Use the existing structured errors, private/no-store responses, origin gate, and idempotency machinery. A lost response followed by the same request must replay the receipt without another revision bump.

## Deliver

Merge/push the platform implementation and send the endpoint shape to the lead/P2. Verify one owner/household success path, a retry, a stale-revision rejection, and cross-case/other-household isolation. Lead/P2 own the small access-management control.
