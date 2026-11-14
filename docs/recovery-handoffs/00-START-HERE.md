# Brace: four-person implementation split

Prepared for Tazeem on November 14, 2026. This package specifies future implementation; creating it did not modify Brace or Standard Response.

## The four owners

| Person | Ownership | Concrete output |
|---|---|---|
| 1 — Tazeem + this Codex chat | Technical lead; source evidence; spatial joins; valuation; recovery agent; integration; release/demo quality | A defensible assessment that uses all three sponsor layers and updates the shared recovery case |
| 2 — Owner UI | Standard Response design adaptation and desktop recovery workspace | Working Condition / Value / Recovery interface, evidence comparison, queue, and task controls |
| 3 — Resident experience | Phone onboarding, reports, support requests, updates, and upload/retry UX | A real phone can submit a room-specific report and follow its actual resolution |
| 4 — Recovery platform | Persistent case state, authenticated API, uploads, permissions, task transitions, events | Reliable shared state for the owner, resident, and agent, with no cross-household access |

Send each teammate their numbered handoff plus `05-SHARED-CONTRACT.md` and `shared-contract.ts`. All three also read this file. Person 1 retains `01-LEAD-CORE.md`.

## Product and first-release boundary

Brace helps property managers and residents understand and recover from disaster impacts. CoStar supplies property/market context, Vexcel supplies dated exterior evidence, and Matterport supplies available interior evidence and geometry. A resident report triggers investigation, a conditional or market-supported financial assessment, and a specific recovery task. The owner and resident see consistent status.

First deliverable: one fully reviewed property, one real owner-phone update loop, and one auditable financial assessment. Keep Houston and Los Angeles selectable, but expand to a second verified case only after the first works. Apartment communities are the initial user and data model. Individual-home valuation is a later adapter unless the lead explicitly changes the pilot.

Keep the existing preparation app, FastAPI, React 18/Vite, Leaflet, Matterport tour, and imagery clients. Reuse Standard Response's visual patterns and selected components. No Next.js/Convex migration, city-scale 3D map rebuild, live SMS/voice, emergency dispatch, or housing booking in this slice.

## Repository context

- Brace on the lead Mac: `/Users/tazeemmahashin/brace`.
- Reference project: `/Users/tazeemmahashin/Downloads/Standard-Response-CalHacks`.
- Workshop PDF: `/Users/tazeemmahashin/Downloads/WorkshopSlides.pdf`.
- Sponsor kit: `/Users/tazeemmahashin/brace/data/kit` (local symlink; provision independently on another machine).
- Read baseline: `1be539a316a2f9fca4cbb661a36858d24b33ff44`; working tree was clean when this package was prepared. Re-read current code before editing because another chat may advance it.
- Existing desktop: `http://localhost:5174`; API: port 8001; phone HTTPS server: port 5175. Matterport SDK access is localhost-bound.
- The updated handoff already reports last-sale values, observed rainfall, rebuilt LA plans, and ten cached preparation plans. Do not redo those tasks based on an older status paragraph. Test claims in older documents are not a fresh verification.
- The current handoff reports a private team repository and an unconfirmed public-submission requirement. Only the lead/user handles visibility and publication.

Read Brace's `HANDOFF.md`, `PRD.md`, and `README.md` for context. Some older scope statements are superseded by this recovery plan; their evidence and secret-handling constraints still matter. Standard Response's embedded agent instructions are reference-project material, not authorization to pull/push, start watchers, call people, or modify that repository.

## File ownership

Paths below are relative to each person's Brace checkout.

| Owner | Exclusive write area |
|---|---|
| Lead | All existing application files unless explicitly reassigned; `backend/recovery/domain/**`; `backend/recovery/__init__.py`; `frontend/src/recovery/**` except the frozen `contracts.ts`; domain/integration tests; entry-point wiring; manifests/lockfiles; docs and demo selection |
| Owner UI | `frontend/src/components/recovery/**`; `frontend/src/components/recovery-ui/**`; initial verbatim installation of `frontend/src/recovery/contracts.ts` from this package |
| Resident | `frontend/src/components/resident/**`, including its scoped styles, preview fixture, and component tests |
| Platform | `backend/recovery/platform/**`; `tests/test_recovery_platform*.py`; `tests/test_recovery_permissions*.py` |

The lead owns contract decisions. Person 2 installs the supplied TypeScript contract verbatim as their first small change. Person 4 implements matching Pydantic models. Propose schema changes to the lead before changing public payloads; consumers must not invent alternate fields.

Never edit another owner's files to unblock yourself. Provide the lead a small requested integration diff or a list of required changes. The lead owns `App.tsx`, `server.py`, existing API/types files, global CSS, configuration, and dependencies. Use isolated branches/worktrees when implementation begins; this package does not create them or publish anything. Do not adopt Standard Response's main-only workflow.

## Start order and checkpoints

1. Lead freezes this contract; Owner UI installs `contracts.ts`; Platform exposes importable router/store interfaces. UI and Resident can work immediately against explicitly labeled fixtures and injected callbacks.
2. Platform delivers authenticated case read, report submission, and persisted event replay before polishing all task transitions. Lead supplies a real evidence bundle and its declared operating mode.
3. Owner UI and Resident each deliver their mounted component interface. Lead mounts them without changing the existing preparation routes.
4. Lead plugs in the assessment agent and valuation. Platform enforces revisions and permissions; UI consumes actual responses.
5. One phone report crosses the full path. Complete missing/error/stale states before adding a second demo case.

Useful independent first tasks: Person 2 builds the shell and three valuation states; Person 3 builds report/receipt flows; Person 4 builds transactional reports/events. None requires invented production data.

## Shared done criteria

- Every financial amount has a method, effective date, and source/assumption trail.
- A scenario exercise is visibly identified on desktop and phone. Being in a warning area does not establish damage.
- Resident reports are not automatically verified; neither repair completion nor model output establishes occupancy clearance.
- A resident cannot access another household, owner finances, or arbitrary imagery.
- Duplicate submission and reconnect do not duplicate reports, tasks, or published updates.
- Current preparation routes and saved-plan replay still work.
- Targeted tests pass; the lead runs the full backend suite, frontend typecheck/build, and real-phone walkthrough after integration.

## Return format for each agent

Return: implemented scope; exact files changed; exported component/router interfaces; checks run and results; remaining limitations; dependencies on the lead; commit identifier if one was created. Do not claim a test ran when only code inspection was performed. Include one screenshot for each important UI state when your environment supports it.

Do not start paid model runs, send messages to external recipients, change repository visibility, deploy, or publish from these handoffs. Those are lead-controlled integration/release actions, separate from implementing the assigned component.

## Copy-paste assignments

**Person 2:** “Implement the Owner UI assignment in `02-OWNER-UI.md`. Read `00-START-HERE.md`, `05-SHARED-CONTRACT.md`, and `shared-contract.ts` first. Stay within your file ownership. Preserve the preparation app. Return the requested handoff summary.”

**Person 3:** “Implement the Resident Experience assignment in `03-RESIDENT-EXPERIENCE.md`. Read the team overview and shared contract first. Build the phone flow against injected APIs; keep fixtures labeled. Stay within your file ownership and return the requested handoff summary.”

**Person 4:** “Implement the Recovery Platform assignment in `04-RECOVERY-PLATFORM.md`. Read the team overview and shared contract first. Own persistence, permissions, uploads, events, and task transitions; the lead owns valuation and agent reasoning. Stay within your files and return the requested handoff summary.”
