# Person 2 — Owner UI and Standard Response design adaptation

## Assignment

Build Brace's desktop recovery workspace. The lead owns evidence interpretation, valuation mathematics, API integration, and existing application entry points. Your job is to make the returned data understandable, spatial, and actionable.

Read `00-START-HERE.md`, `05-SHARED-CONTRACT.md`, and `shared-contract.ts`. First install the supplied TypeScript file verbatim at `frontend/src/recovery/contracts.ts` in Brace and make it available to the other frontend owner. Contract semantics remain lead-owned.

## Exclusive write scope

- `frontend/src/components/recovery/**`
- `frontend/src/components/recovery-ui/**`
- Initial verbatim creation of `frontend/src/recovery/contracts.ts`

All paths are within `/Users/tazeemmahashin/brace` on the lead Mac. Do not edit App.tsx, existing viewers/maps, global CSS, API files, manifests, lockfiles, or backend code. Send requested wiring/dependency changes to the lead. Keep Standard Response unchanged.

## Reference files to read

Under `/Users/tazeemmahashin/Downloads/Standard-Response-CalHacks/`: `app/globals.css`; `components/ui/panel.tsx`; `components/ui/panel-desk.tsx`; `components/ui/segmented-control.tsx`; `components/system/range.tsx`; `components/rescue/rescue-map.tsx`; `components/rescue/house-card.tsx`; `components/driver/offer-cards.tsx`; `public/devpost/gallery/08-rescue-map.jpg`.

Use the reference's paper surfaces, strong hierarchy, floating panels, compact status marks, changed-state hatching, and ranges. Port the relevant component structure to Brace's plain/scoped CSS. Remove Next/Convex dependencies. Keep fonts already provisioned in Brace unless the lead approves an additional font. Do not import the reference's simulated household/fire data or rebuild its WebGL renderer.

## Component contract

Export `RecoveryWorkspace` from `frontend/src/components/recovery/RecoveryWorkspace.tsx`.

Props:

```ts
type RecoveryWorkspaceProps = {
  cases: RecoveryCaseSummary[];
  snapshot: OwnerCaseView | null;
  state: "loading" | "ready" | "error";
  error: string | null;
  busy: boolean;
  selected_evidence_id: string | null;
  map_slot: React.ReactNode;
  interior_slot: React.ReactNode;
  on_open_case: (case_id: string) => void;
  on_back_to_prepare: () => void;
  on_focus: (location: LocationRef) => void;
  on_select_evidence: (evidence_id: string) => void;
  on_command: (command: OwnerCommand) => Promise<void>;
};
```

Domain types come from the frozen contract. Parent owns network/session state and handles commands. A failed command must remain visible and retryable; never optimistically show a task accepted or notice published before the server confirms.

Lead integration update: the parent also renders `DraftNotices` for saved agent updates. It loads case-scoped drafts, shows their source references and stale state, and lets the owner edit text/select recipients before explicit publication. Keep your manual notice composer; no new required Workspace prop or shared-contract field is needed for the agent draft panel.

## Build sequence

1. Install contract. Establish scoped tokens/classes under `.brace-recovery`; add reusable Panel, SegmentedControl, EvidenceBadge, RangeDisplay, EmptyState, and ChangedBanner components. Scope all selectors so preparation screens retain their behavior.
2. Build top bar: property identity, incident, effective date, mode banner, and Back to Prepare. Modes distinguish observed recovery, historical replay, and exercise.
3. Build left queue: selected property, latest report count, pending inspections, next action. Preserve server ordering; do not invent a risk score or rank by property price.
4. Build the center with Overview / Aerial / Interior view selection. Parent supplies real map/interior slots. Implement dated aerial comparison with linked pan/zoom or a simple wipe, protected image URLs, and explicit missing-capture state. Do not compare geometrically mismatched images without a visible limitation.
5. Build Condition / Value / Recovery tabs in the right panel. Clicking a finding/task calls the focus callback and selects the cited evidence.
6. Build a compact event timeline with timestamps and superseded states. Preserve old assessment history; do not animate it as though it were current.
7. Implement loading/error/empty/stale/insufficient-evidence states before adding decorative motion. Capture the important states and test at ordinary laptop widths and a narrower viewport.

## What each tab contains

**Condition:** observations grouped by verification state; supporting image; structure/room association; capture and report dates; unknown spaces; request-verification or verify/dismiss controls through OwnerCommand. A model suggestion never gets a verified badge automatically.

**Value:** benchmark, current condition, and repair scenario; method and effective date; sourced/conditional/insufficient labels; low/high values and assumption list; repair and downtime costs separate from market-value change; comparable drawer with selection reasons. A null amount is “Not enough evidence,” never $0. A range is not a statistical confidence interval unless the payload says calibrated confidence. No green “value restored” animation when work is only proposed.

**Recovery:** tasks in proposed/approved/accepted/in-progress/completion-submitted/verified/cancelled states; exact scope and location; actor/confirmation source; changed-scope banner; owner publication controls for resident notices. Include an invitation action supplied by the parent command handler.

## Fixtures and boundaries

You may create an explicit `RecoveryPreview.tsx` and fixture under your owned directory. Use synthetic IDs and conspicuous “UI fixture — not a property assessment” labeling. Fixtures are opt-in preview inputs and never a fallback when production calls fail. The lead replaces them with source-backed data.

The lead provides a read-only evidence viewer, map slot, case client, authenticated URLs, and live subscriptions. Until then, test with slots and command spies. Ask for exact missing contract fields instead of inventing backend endpoints.

## Acceptance

- Everything is readable without a chat transcript.
- Evidence selection updates the appropriate view through callbacks.
- All three valuation bases and missing dates/prices render correctly.
- Case revision and stale/published distinction are visible where relevant.
- Proposed versus accepted work cannot be confused.
- Keyboard focus, buttons, narrow layout, error/retry, and reduced motion work.
- No unscoped style changes, hidden backend dependency, or runtime fixture fallback.
- Component tests focus on status/value/null behavior; no tests that merely repeat styling implementation. Run the available frontend typecheck/build and report any checks blocked by missing lead integration accurately.

Return changed files, screenshots, exported interface, checks/results, and requested lead wiring. Do not modify other owners' files to make the whole app mount.
