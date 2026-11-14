# Coordinator goal

Deliver Brace's integrated disaster-recovery flow on `main`: connect the lead-owned CoStar, Vexcel, and Matterport evidence, valuation engine, and recovery agent to the team's authenticated platform, owner workspace, and resident experience. Demonstrate a resident report leading to owner review, stale-safe reassessment, approved recovery work, and an owner-published resident update.

Preserve the preparation routes, source dates and spatial uncertainty, honest unavailable/conditional valuation states, and household isolation. Stay within the four-person file ownership split. Use parallel agents and available Claude models when useful. Run meaningful integration checks, merge and push verified changes directly to both repositories, and keep local evidence, credentials, and resident data out of Git. Do not fabricate source observations or send external resident messages.

## Completion criteria

1. The owner and resident components use the shared API contract and actual case state.
2. A resident invitation is exchanged without initiating owner-data requests or persisting its token in the URL/storage.
3. Upload/report retries are idempotent; authorized event streams reconnect from their latest cursor.
4. New evidence invalidates an in-flight assessment; old results never overwrite new inputs.
5. Money is sourced and dated; unverified reports alone cannot establish repair deductions.
6. Only authorized owners review evidence, approve work, and publish resident updates. Residents cannot read other households or private financial data.
7. The existing preparation flow still works. Backend tests, browser-client tests, frontend typecheck/build, and the integrated owner/phone walkthrough pass, with device limits stated accurately.
8. Verified code and teammate handoffs are on both repositories' `main` branches.

## Integration interfaces ready now

- `backend/recovery/domain/service.py`: frozen worker inputs, stale-safe commit handshake, bounded work, retry without repeated model spend.
- `backend/recovery/integration.py`: optional legacy API owner gate; install together with Platform's authenticated router. Its authorizer must check the requested property scope as well as owner identity. Platform namespace endpoints retain their own scoped authorization.
- `frontend/src/recovery/client.ts`: owner/resident HTTP adapters and resumable fetch-based event streams.
- `frontend/src/recovery/routes.ts`: preparation/recovery/resident route parsing and invitation cleanup before session exchange.
- `frontend/src/recovery/owner-controller.ts`: request-race protection, confirmed state, replay-safe commands, and event-driven refresh.

These integration helpers do not replace teammate-owned components, persistence, or authentication. The next checkpoint is mounting those exports and enforcing the full owner/household permission model.
