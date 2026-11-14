# Owner recovery workspace (Person 2)

This is the desktop workspace an owner or property manager uses after an event. It covers condition, valuation, evidence inspection, recovery tasks and approvals. It is built to `docs/recovery-handoffs/02-OWNER-UI.md` and the v1 contract in `05-SHARED-CONTRACT.md`. **It is not mounted in the app yet.** Mounting it is the lead's job; see "Wiring" below.

## What's here

| Path | What it is |
|---|---|
| `src/recovery/contracts.ts` | The lead's v1 wire contract, installed verbatim (byte-identical to `docs/recovery-handoffs/shared-contract.ts`). |
| `RecoveryWorkspace.tsx` | **The component to mount.** It is presentational: it holds only local UI state (tab, center view, drafts) and never changes server state locally. |
| `WorkspaceTopBar.tsx`, `CaseQueue.tsx` | Property identity, incident, effective date, revisions, a mode banner (observed recovery / historical replay / scenario exercise) and the case list. Cases appear in server order and are never ranked. |
| `CenterStage.tsx`, `AerialCompare.tsx`, `EvidenceInspector.tsx` | The Overview (your map), Aerial (dated before/after wipe) and Interior (your tour) views, plus details of the selected evidence. |
| `ConditionTab.tsx` | Observations grouped by review state, review and verification controls, resident reports, and spaces that weren't scanned. |
| `ValueTab.tsx`, `ComparablesList.tsx` | Benchmark, current condition and after-repair values; repair and downtime costs; comparables with reasons; assumptions; limitations; assessment history. |
| `RecoveryTab.tsx`, `TaskCard.tsx`, `NoticeComposer.tsx` | Tasks in every contract status with valid transitions only, the notice composer with two-step publish, and household invitations. |
| `EventTimeline.tsx` | Case events, newest first, with superseded publications marked. |
| `format.ts`, `model.ts`, `commands.ts` | Formatting (no time-zone shifts, never `$0` for null), labels and transitions per the contract, and the command runner (no optimistic updates; errors stay visible with Retry; state resets per case). |
| `../recovery-ui/` | Scoped primitives in Standard Response's visual language. Every selector sits under `.brace-recovery`, and no global style was changed. |
| `RecoveryPreview.tsx`, `preview.html`, `preview-main.tsx` | An opt-in, dev-only preview on synthetic fixtures. |
| `fixtures/`, `__tests__/` | Synthetic fixtures, labelled "UI fixture — not a property assessment", and dependency-free tests. |

## Wiring (lead)

```tsx
import { RecoveryWorkspace } from "./components/recovery/RecoveryWorkspace";

// Route: #/recovery/<case_id>. The workspace fills the viewport, so give it its own page.
<RecoveryWorkspace
  cases={cases}                          // RecoveryCaseSummary[], in server order
  snapshot={snapshot}                    // OwnerCaseView | null
  state={state}                          // "loading" | "ready" | "error"
  error={error}                          // string | null
  busy={busy}
  selected_evidence_id={selectedEvidence}
  map_slot={mapElement}                  // your Leaflet map (keep the element stable)
  interior_slot={tourElement}            // your Matterport TourPane (keep the element stable)
  on_open_case={(id) => { window.location.hash = `#/recovery/${id}`; }}
  on_back_to_prepare={goPrepare}
  on_focus={focusMapAndTour}
  on_select_evidence={setSelectedEvidence}
  on_command={sendCommand}
/>
```

What the parent has to do:

1. **`on_command`**
   - Send the command, then resolve only after the server has confirmed *and* the refreshed snapshot is in, because forms close when the promise resolves.
   - On failure, reject with the `ApiErrorBody` or an `Error` so the message shows.
   - The workspace injects `expected_revision` from the current snapshot.
2. **Idempotency-Key.** Keep it stable for the same command body, ignoring `expected_revision`. Retry re-sends the same body, so a lost response must not publish a notice twice.
3. **Refreshes.** Keep passing the previous snapshot while you refresh. With a snapshot present:
   - `state="loading"` shows "Refreshing…" and keeps the map, tour and drafts mounted.
   - `state="error"`, or `"ready"` with `error` set, shows an inline error banner.
   - A full-page loading or error screen appears only when there is no snapshot.
4. **Invitations.** `create_invitation` returns a `CommandResult` with `invitation_token`, but `on_command` returns `void`, so the workspace never sees it. Show the link or QR code from your handler (the preview demonstrates this), or amend the contract so `on_command` returns the `CommandResult`.
5. **Selected evidence.** Clear `selected_evidence_id` when the case changes. The workspace switches the center view itself: Vexcel evidence goes to Aerial, Matterport evidence to Interior.
6. **`on_focus`**
   - `verified_unit` and `verified_space` bindings may go to an exact sweep or room.
   - `representative_layout`, `unverified` and `unmapped` must not be shown as the resident's exact room.
7. **Package script.** Please add `"test:owner-ui": "node src/components/recovery/__tests__/run.mjs"` to `frontend/package.json` (yours to change). `test:recovery` is already taken by your own `tests/recovery-*.test.mjs`.

## Preview (no server, no keys)

```bash
cd frontend && npm run dev
# open http://localhost:5174/src/components/recovery/preview.html
```

The preview has a scenario switcher: full, conditional, insufficient, stale, empty, loading, error and no cases. It also has a "Make next command fail" toggle and a spy panel showing every callback. It never runs as a fallback in the app.

## Tests

```bash
cd frontend && node src/components/recovery/__tests__/run.mjs
```

The tests use no new dependencies: esbuild (already installed with Vite) plus `react-dom/server`. They cover:
- money and null handling;
- date precision;
- contract transitions;
- the command runner (per-case reset, late results, retry);
- workspace states;
- each tab's truth rules (an inferred observation is never verified, a proposed task is never booked, stale vs published wording);
- the fixtures.

There is no DOM test library, so click handlers are tested through the pure helpers they call.

## Checks run (Sat 14 Nov 2026, 04:30, branch `kevin/owner-ui`)

| Check | Result |
|---|---|
| `npx tsc --noEmit` | Passes |
| `node src/components/recovery/__tests__/run.mjs` | 82 passed, 0 failed |
| `npm run build` | Passes. The existing >500 kB chunk warning comes from the preparation app; recovery code isn't bundled until it is mounted. |
| CSS scope audit | Every selector is under `.brace-recovery` |
| Fixture isolation | Only `RecoveryPreview.tsx` and the tests import the fixture |
| Backend calls | None in the recovery code (no `fetch`, `/api` or `EventSource`) |
| Contract | `src/recovery/contracts.ts` is byte-identical to `docs/recovery-handoffs/shared-contract.ts` |
| Ownership | No tracked file was modified. All files are new under `components/recovery/`, `components/recovery-ui/` and `src/recovery/`. |
| Runtime check (scratch fake DOM, with effects running) | Slots mount once across every state and case switch. Drafts survive tab switches and reset on a case switch. A failed or pending command never leaks into another case. Re-clicking evidence brings back its view. |

The checks did not cover a real browser click-through against your API, because the API doesn't exist yet. They also did not cover the real Leaflet map and Matterport tour in the slots.

## Screenshots

Taken from the preview at 1440 px unless noted. The data is synthetic fixture data.

| File | State |
|---|---|
| `screenshots/01-condition.png` | Condition tab: a model suggestion marked "not verified", a representative-layout warning, structure, capture and observation dates |
| `screenshots/02-value.png` | Value tab: market-supported valuation with basis, method, effective date, ranges and range kinds |
| `screenshots/03-recovery.png` | Recovery tab: a proposed task reading "not approved, not booked", "Schedule not confirmed" |
| `screenshots/04-aerial.png` | Aerial before/after wipe with dated captures and the limitation note |
| `screenshots/05-insufficient.png` | Insufficient evidence: "Not enough evidence" with no dollar figures |
| `screenshots/06-stale.png` | Published assessment whose inputs changed afterwards (integration case 4) |
| `screenshots/07-error.png` | Load error with no case open (no promise of a reload) |
| `screenshots/08-narrow.png` | 1000 px: columns stack |

## Contract questions for the lead

1. Do `source_ids` on money ranges and assumptions refer to `Evidence.source_id`? The UI links them that way.
2. When an accepted task's scope changes, does it go back to `approved` with `superseded_scope` set? Is `superseded_scope` cleared once the new scope is accepted? The changed-scope banner shows whenever it is non-null.
3. Can `current_assessment_id` point to a draft? If it can, the UI would label the last *published* assessment "superseded".
4. Historical replay has no knowledge-cutoff field, so the mode banner can't show the cutoff date.
5. `CommandResult` (`run_id`, `invitation_token`) isn't visible to the workspace; see point 4 of "Wiring".
