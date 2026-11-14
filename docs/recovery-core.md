# Recovery core: implementation and integration

Implemented November 14, 2026. This is the lead-owned domain layer for the four-person recovery build. The shared frontend wire contract remains `docs/recovery-handoffs/shared-contract.ts`; no public HTTP contract changed.

## What works

- Local CoStar property and transaction records join the existing Vexcel/Matterport caches into a dated evidence inventory.
- Full Vexcel flight inventories use a separate versioned cache; the preparation UI can retain its compact capture list. Capture-specific images retain collection identity.
- Existing building caches upgrade locally to preserve rooms, sweep-to-room associations, and model coordinates. Model creation time is separate from unknown capture time.
- Locations carry candidate associations. GPS proximity never verifies a resident's dwelling or a room's exposure to water.
- Comparable screening, sourced repair scopes, and finite-duration disruption calculate deterministically using Decimal. The model never sets financial amounts.
- The recovery agent reads evidence, inspects real images and spatial geometry, investigates reports, calls the financial engine, proposes verification/repair work, and drafts an unpublished resident update.
- AssessmentService runs frozen snapshots in a worker pool and commits through the platform. The platform must make the final revision comparison transactionally.

## Run against the local kit

From the repository root:

```bash
uv run python -m scripts.recovery 4303509 \
  --incident-name 'Hurricane Beryl recovery exercise' \
  --incident-at 2024-07-08 --as-of 2026-11-14 \
  --mode scenario_exercise
```

The default reads local kit/cache data, performs a deterministic financial screen, and writes a new run directory under ignored `data/recovery/<case_id>/<run_id>/`. It makes no model or sponsor API requests. Missing sources are explicit. Files are `seed.json`, `inventory.json`, `inputs.json`, and `screen.json`.

Add `--agent` to run the configured Claude model and write `assessment.json`. Add `--fetch-sources` separately to allow source requests and missing imagery downloads. No assessment, notice, task, resident invitation, or external message is automatically published.

`--financial-inputs /path/to/local.json` loads the financial assumptions object below. `--snapshot /path/to/owner-snapshot.json` evaluates a reviewed snapshot with existing reports/observations. Property identity, incident, cutoff, and mode must match the selected case. This is a local engineering CLI, not a resident submission API.

The historical Beryl exercise uses current source records and is intentionally labeled a scenario. Strict `historical_replay` rejects sources without established historical availability; current Matterport geometry is not smuggled into that mode. Neither a weather warning nor being near a fire perimeter establishes observed damage.

## Domain interfaces

```python
from backend.recovery.domain.sources import load_inventory
from backend.recovery.domain.service import (
    make_case_seed, valuation_inputs, screen_case, EvidenceImages, AssessmentService,
)
from backend.recovery.domain.valuation import evaluate_valuation
from backend.recovery.domain.agent import RecoveryAgent
```

`load_inventory(property_id, *, incident_at, assessment_as_of, mode='scenario_exercise', allow_network=False)` returns subject, normalized sales, Evidence records, LocationRefs, source status, limitations, scans/rooms, structures, capture inventory/pair, and private image descriptors.

`make_case_seed(inventory, *, incident_name, incident_at, assessment_as_of, mode, case_id=None)` returns the contracted OwnerCaseView with no invented condition reports, households, or tasks.

`valuation_inputs(inventory, snapshot, financial_assumptions=None)` freezes financial/spatial inputs and takes authoritative evidence from the case snapshot. When the platform changes financial assumptions or spatial bindings, it must increment analysis_revision with that mutation.

`evaluate_valuation(inputs, observations, context)` returns ValuationResult. Context is the case summary. `screen_case(snapshot, inputs)` wraps this as an explicitly deterministic screen rather than an agent assessment.

`RecoveryAgent(snapshot, valuation_inputs, *, client=None, inspect_image=None, emit=None, max_turns=20).run()` returns:

```text
{
  assessment: Assessment,
  proposed_tasks: RecoveryTask[],
  draft_notices: [{draft_id, title, body, source_ids, audience, requires_owner_review}],
  trace: [{type, run_id, at, ...tool/status metadata}]
}
```

Supply `snapshot.run_id`. All proposed_tasks have status `proposed`; drafts have no publication fields. A failed run is not a publishable assessment. Tool traces omit raw provider thinking. The full valuation retains excluded comparables; bounded tool responses keep thousands of transaction rows out of model context.

## Person 4: exact worker handshake

The launcher ticket is `{run_id: str, case_id: str, base_analysis_revision: int}`. After creating the run transaction, call `service.launch(ticket)` and return promptly. It returns a concurrent Future; repeated launches of that run ID reuse the same Future within the process.

The worker caps pending work and retains a bounded in-process deduplication history. A failed database commit remains visible on the Future; re-launching the same ticket retries its completed envelope without another model call. The store must make completion idempotent by run ID in case a commit succeeded before an acknowledgment failed. A run ID cannot be rebound to a different case/revision.

The injected store implements:

```python
snapshot_for_analysis(case_id: str) -> dict  # OwnerCaseView, with case.analysis_revision
complete_assessment(run_id: str, base_analysis_revision: int, result: dict) -> object
```

The second argument is the original input revision, and `result` is the entire domain envelope above. Save the assessment and its proposals in one transaction. If current inputs changed, save history as stale and do not replace the current assessment or activate its tasks. Never publish notices while saving a draft. A stale result detected before the worker starts skips the model entirely.

The lead supplies `input_provider(snapshot) -> (inputs, inspect_image_callback)`. It must use registered source/financial inputs for this case; source refreshes belong in separate versioned input mutations. `AssessmentService(store, input_provider)` owns a default two-worker executor; pass its `.launch` to `build_router`. Call `.close()` during application shutdown. Observe the returned Future for a persistence failure, which is not swallowed. On process restart, the platform must mark unfinished runs interrupted/retryable as specified in its handoff.

No new unauthenticated HTTP endpoint was added. Platform router mounting, legacy owner API authentication, and the owner/resident components are the next integration checkpoint once those teammates deliver their exports.

The lead-owned `backend.recovery.integration.install_legacy_owner_gate(app, authorize_owner)` is now available for that checkpoint. Install it with the platform router before startup. The callback receives the request and must establish owner identity and property scope from server state; do not pass a role-only check when access is property-restricted. Its API responses are private/no-store, including legacy images and event streams. Development proxies preserve the original Host/Origin and forward the original scheme, so the platform can validate allowed origins and issue secure phone cookies; trust forwarded headers only from the loopback proxy.

Browser integration is in `frontend/src/recovery/`: `client.ts` implements the shared owner/resident endpoints and reconnecting event streams; `routes.ts` isolates resident routing and scrubs invitation fragments; `owner-controller.ts` protects against stale fetches and keeps idempotency keys across lost command responses. These modules currently import the canonical handoff types until Person 2 installs the identical frontend contract. Run `npm run test:recovery` in `frontend` for transport, routing, and controller checks.

## Image identity and permissions

`EvidenceImages(assets, snapshot['evidence'], allow_network=False)` is the agent image callback. It only accepts registered evidence IDs and trusted-cache files. Local bytes are SHA-256 pinned at inventory creation, bounded in size, decoded, and re-encoded without EXIF. Capture requests require an explicit collection and validate returned collection/date. Arbitrary URLs and paths from report text are never fetched.

Private `assets` descriptors are not browser payloads. Evidence.media remains null until the platform registers an authorized media projection. Its resolver must authorize the case/household first, then map a server-issued media_id to the descriptor. Do not expose absolute paths, sponsor credentials, or an unrestricted legacy image route. Resident-upload imagery requires a separately authorized platform loader; the core does not assume residents can view sponsor interiors.

## Financial assumptions input

All fields are optional; missing values remain unavailable. References must resolve against dated case Evidence. The model has no tool to invent this object.

| Field | Required contents when supplied |
|---|---|
| `reviewed_values[]` | `condition` current/restored; `low_usd`, `high_usd`, `effective_at`, `source_ids`, `reviewed_by`, `review_note`, `method`, `basis` source/user_supplied/scenario |
| `repairs[]` | `line_id`, unique `scope_key`, description, LocationRef, quantity/unit/basis, low/high unit rate, rate_effective_at, source_ids including a cost source, observation_ids, basis verified/scenario, remaining=true |
| `repair_scope_complete` | Explicit true only when the supplied remaining scope was reviewed as complete |
| `repair_scope_source_ids` | Inspection/cost evidence supporting that scope review |
| `downtime` | low/high USD, same effective_at, source_ids, method, incremental=true, includes_repair_costs=false, basis source/user_supplied/scenario |

The comparable benchmark is a descriptive range normalized by unit count or gross area. Screening requires three unique qualifying sales; its geographic, age, and scale thresholds are engineering policies, not accuracy guarantees. Unknown prices, currency, allocated portfolio shares, unsuitable sale conditions, and future evidence are excluded with reasons.

Current-condition value is either a reviewed same-date sourced estimate or a conditional calculation: restored-condition estimate minus complete remaining repair costs minus incremental disruption. An already supplied current-condition estimate is not deducted again. A future restored estimate is rejected rather than silently ignoring discounting. Reports alone do not create verified repair deductions; hypothetical scopes remain labeled assumptions. There is no automatic insurance recovery, perpetual rent-loss capitalization, or promised dollar-for-dollar market value gain.

As background, [Fannie Mae's condition guidance](https://selling-guide.fanniemae.com/sel/b4-1.3-06/property-condition-and-quality-construction-improvements) distinguishes current and subject-to-repair conditions, and its [comparable guidance](https://selling-guide.fanniemae.com/sel/b4-1.3-08/comparable-sales) requires relevant property characteristics. These are residential references, not a claim that this commercial decision-support prototype is a compliant appraisal.

## Validation

```bash
uv run pytest
cd frontend
npm run typecheck
npm run build
```

Domain tests cover temporal/spatial leakage, capture identity, missing prices, allocation, deduplication, finite money, cost completeness, report verification, conflicting bindings, bounded model tools, prompt-supplied invented references, immutable snapshots, and stale commits. Integration tests run a scripted model through the real valuation engine and worker; a corrected measured quantity changes the conditional value, while an unverified report cannot establish a deduction.

Verified on November 14: 186 backend tests passed; frontend typecheck and production build passed. An actual Claude Opus 5.5 run on the Houston cache produced a draft with five verification tasks, six unresolved questions, and one resident notice after inspecting aerial/interior views. A separate Los Angeles data screen loaded all three layers and 17 eligible comparable rows. Strict historical replay rejected unavailable historical records instead of reusing current spatial data. Claude Fable 5.2 independently reviewed the core; its transient-commit retry finding was fixed and regression-tested. These checks do not constitute the still-pending integrated owner/phone walkthrough.

Keep sponsor records, local runs/reviews, photos, keys, and resident information in ignored data paths. Commit code, synthetic tests, and these implementation notes only.
