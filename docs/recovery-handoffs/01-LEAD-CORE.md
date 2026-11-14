# Person 1 — Tazeem + Codex: evidence, valuation, agent, and integration

## Responsibility

Own the hard domain decisions and the final working product. The other three people own the desktop interface, phone experience, and operational backend. Do not reimplement their work.

Read `00-START-HERE.md` and the shared contract. This handoff records ownership; source implementation remains pending authorization in the lead chat.

## Deliverables, in order

1. Publish the frozen wire contract and entry-point interfaces. Review proposed changes centrally. Person 2 installs the supplied TypeScript contract; Person 4 implements its backend validators.
2. Select a defensible pilot using actual source coverage. Build a dated evidence inventory and document whether the case is observed recovery, strict historical replay, or a scenario exercise.
3. Build the source adapters, spatial associations, assessment tools, and deterministic financial calculations under `backend/recovery/domain/`.
4. Implement the browser API adapter and case subscription under `frontend/src/recovery/`. Mount the owner and resident components, initialize their respective sessions, and connect the existing map and interior viewer.
5. Mount Platform's router, configure authentication gates on legacy owner APIs, and run the integrated flow.
6. Own source review, end-to-end tests, the demo story, repository publication decisions, and any paid model budget.

## Important context the other agents should not have to rediscover

- The current code already exposes last-sale values in portfolio/building responses. These are historical transaction facts, not a current valuation.
- `vexcel.captures()` currently retains only one capture per half-year. Recovery requires an unthinned inventory around the incident; keep capture-specific cache identity and invalidate/version old filtered cache entries.
- The Matterport client already fetches rooms, boundaries, sweep-to-room IDs, and model geometry. The public building bundle loses much of this. Extend it carefully rather than implementing a second GraphQL client.
- The existing `scanned` field derives from model `created`. Separate actual capture date, model-created time, and retrieval time. Unknown capture dates stay unknown.
- Some scans represent a floor plan, vacant model unit, leasing office, or other single space. No automatic binding to every dwelling of the same layout. Add explicit subject/structure/unit association and verification basis.
- Nearest indoor GPS is a candidate relationship, not proof. Use reviewed alignment and preserve uncertainty. Do not infer which lower floor was damaged from a roof change.
- Earlier Houston evidence attached a view of a solid entry door to an action about sliding balcony doors. Review current evidence again; require the displayed image to support the finding, not merely contain a valid sweep ID.
- The original Beryl plan used 2026 images with a 2024 forecast. Unless all inputs meet the historical cutoff, label the exercise honestly. An as-of filter for fire perimeters alone is insufficient.
- The updated handoff reports none of the kit's LA commercial buildings inside or within 1 km of the studied January 2025 perimeters. This does not establish individual damage conditions. Do not select an LA property and invent burn damage because it was in a Red Flag Warning.
- LA residential data has disclosed sold prices; Houston residential sales omit them. AVMs exist on some records but are not automatically dated pre-event baselines. The first slice remains commercial apartments; preserve dataset identity if residential support is added.
- Contacts in the sponsor kit have fake email/phone values, and apartment residents are not listed. Use explicit demo invitations and user-provided reports.
- Reference UI is React 19/Next/Tailwind/Convex; Brace is React 18/Vite/plain CSS/FastAPI. Dependencies and package files belong to the lead.

## Source and spatial modules

Suggested modules: `sources.py`, `spatial.py`, `evidence.py`, `comparables.py`, `costs.py`, `valuation.py`, `agent.py`, `service.py` under `backend/recovery/domain/`.

Source records retain original IDs, dataset, capture/effective/availability dates, property association, and source status. Store imagery references, not blobs, in case state. Platform stores permitted upload/media bytes; the lead supplies sponsor imagery adapters and permission-aware routes.

Choose before/after captures by explicit dates. Account for collection footprint and imaging differences. A visual difference is a candidate observation, not a determination of cause or hidden damage. Rainfall over a coarse cell is not indoor water depth.

For strict historical replay, both occurrence and information availability must satisfy the selected cutoff. Where source publication/availability cannot be established, do not claim a faithful historical knowledge state. The exercise mode supports current building data with a historical event, visibly labeled.

## Financial implementation

Produce `ValuationResult` exactly as contracted. Three bases: `market_supported`, `conditional`, `insufficient_evidence`.

- Comparable selection: same asset class, appropriate market/location, date and scale; deduplicate actual transactions; carry status; normalize units and currency; exclude unknown prices and unsuitable sale conditions. Portfolio totals never become one building's price. Allocated shares remain distinguishable and are excluded from the primary benchmark by default.
- Comparable dispersion is not a calibrated confidence interval. Retain included and rejected comps with reasons. A small engineering minimum for sample size is a screening policy, not proof of valuation accuracy.
- Existing last sale and AVM remain separate sourced benchmarks. Do not relabel either as a freshly calculated present value.
- Repair lines require scope, location, quantity basis, rate source/date, and explicit assumptions. No unsourced model-generated loss percentage.
- Current-condition value requires supporting market evidence/adjustments. Where it is absent, return a conditional cost-to-cure scenario or no current value.
- A cost-to-cure scenario may start with a restored-condition benchmark at the same valuation date and deduct remaining repair and incremental disruption costs. Clearly state conditions and avoid duplicate deductions. For a future restored value, account explicitly for time/discount assumptions.
- Temporary rent loss is not a perpetual NOI reduction. Asking rents do not establish collected rent or NOI. Add an income approach only with sufficient actual or clearly supplied income/expense assumptions.
- Do not infer guaranteed insurance proceeds, approval, or dollar-for-dollar recovered value from spending.
- Verified damage and merely reported damage must have separate effects. An unverified report can widen a range or request an inspection; it need not numerically reduce value.

## Agent loop

Use the existing tool-loop pattern and scripted test client. Tools read evidence, inspect views, record hypotheses, resolve questions, request verification, select comps, call deterministic calculations, propose tasks, and draft audience-specific notices.

An assessment reads a snapshot with `analysis_revision`. New evidence invalidates that analysis. Persist stale results as stale history; do not publish them. Agent output cannot change actor roles, mark evidence verified, accept contractor work, or authorize re-entry.

Evidence verification and publication are explicit owner/qualified-reviewer actions recorded by Platform. Resident notifications are published notices, not leaked internal model thoughts or unreviewed valuation text.

## Integration owned here

- Existing files including `backend/server.py`, `backend/building.py`, `backend/vexcel.py`, `backend/portfolio.py`, `frontend/src/App.tsx`, `frontend/src/api.ts`, `frontend/src/types.ts`, `frontend/src/styles.css`, configs/manifests/lockfiles.
- New root recovery package init, `backend/recovery/domain/**`, `frontend/src/recovery/**` except Person 2's frozen contract installation, domain/integration tests.
- Routes: preserve all old hashes; add `#/recovery/<case_id>` and `#/resident` plus invitation bootstrap. Resident boot must not fetch privileged owner config/building/portfolio endpoints.
- Inject map and interior-viewer slots into the desktop workspace; inject the contracted ResidentApi into the phone component.
- Authenticate all legacy owner endpoints before phone access is exposed. Keep existing Matterport localhost requirement. Do not expose owner sessions or SDK tour access through a resident invitation.
- The database and uploaded files belong in git-ignored local data. No kit records, keys, scans, photos, or resident information in commits.

## Acceptance and demonstration

Run targeted domain tests, the full `uv run pytest`, frontend `npm run typecheck` and `npm run build`, and a real two-device walkthrough. Do not assume prior test counts remain current.

Test a meaningful evidence correction: report arrives, relevant view opens, assessment becomes stale/recomputes, owner reviews the draft, a task is approved, resident sees the published status. A second update during a run must not let old output win. Verify no-report/no-price/no-capture/no-scan states.

Demo recordings and fixtures must distinguish observed source data from a scenario report. Use the same real evidence for the analysis and the displayed screenshot. Never claim the historical preparation runs predicted actual damage or prove avoided loss.

## Contract changes to settle centrally

Any new field, endpoint, permission, status, valuation formula, public dependency, or change to existing preparation behavior comes through this owner. Prioritize completing one verified loop over expanding hazards or renderer complexity.
