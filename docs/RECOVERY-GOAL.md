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
- `frontend/src/App.tsx` and `recovery/RecoveryEntry.tsx`: isolated owner/resident entry points, owner sign-in, one-use invitation bootstrap, and lazy loading of the teammate-owned components.
- `backend/recovery/registry.py`: immutable private case inputs, context and source-metadata validation, and the worker input provider.
- `backend/recovery/evidence_router.py`: owner-scoped spatial manifests and SHA-256-pinned cached images, with no source fetching or filesystem paths in browser payloads.
- `backend/recovery/runtime.py`: explicit assembly of the platform, worker, evidence router, and legacy owner gate. Refuses a platform without the worker handshake.

The platform is now merged, including sessions, invitations, reports/uploads, events, worker completion, review, tasks, and publication. Integration fixes scope evidence IDs to each case and prevent event delivery after revocation or starvation behind another household's events. The local runtime connects it to registered sponsor evidence and resident-photo inspection. A scripted-model test completes the owner/resident API workflow with real persistence and revision checks.

The next checkpoint is the teammate-owned owner UI and resident screens, followed by their integrated browser/phone walkthrough. The resident branch received so far is a compiling scaffold; its screens are still being implemented. Do not mark the overall goal complete based on backend or scaffold tests alone.
