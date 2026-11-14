// The owner recovery workspace. Presentational: the parent owns network, session and the snapshot, and
// turns OwnerCommand callbacks into HTTP calls. This component holds only local UI state.
//
// States: with a snapshot the workspace always stays mounted. state="loading" only adds a quiet "Refreshing…"
// mark; state="error", or any non-null `error`, adds an inline banner above the grid. The map and interior
// slots, open forms and drafts survive both. Full-page loading and error screens appear only when there is no
// snapshot. The slots are mounted once at a fixed place in the tree and never remounted on a case or state
// change. Tab contents are keyed by case_id, so drafts reset when (and only when) the case changes.
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import type { ReactNode } from "react";
import type { LocationRef, OwnerCaseView, OwnerCommand, RecoveryCaseSummary } from "../../recovery/contracts";
import { EmptyState, InlineError, Panel, TabPanel, Tabs } from "../recovery-ui";
import { useCommandRunner } from "./commands";
import type { CommandRunner } from "./commands";
import { evidenceMap } from "./model";
import { aerialCaptures, choiceForSelected, NO_AERIAL_CHOICE } from "./AerialCompare";
import type { AerialPairChoice } from "./AerialCompare";
import { CaseQueue } from "./CaseQueue";
import { CenterStage } from "./CenterStage";
import type { CenterView } from "./CenterStage";
import { EvidenceInspector } from "./EvidenceInspector";
import { WorkspaceTopBar } from "./WorkspaceTopBar";
import { ConditionTab } from "./ConditionTab";
import { ValueTab } from "./ValueTab";
import { RecoveryTab } from "./RecoveryTab";
import { EventTimeline } from "./EventTimeline";
import "./workspace.css";

export type RecoveryWorkspaceProps = {
  cases: RecoveryCaseSummary[];
  snapshot: OwnerCaseView | null;
  state: "loading" | "ready" | "error";
  error: string | null;
  busy: boolean;
  selected_evidence_id: string | null;
  map_slot: ReactNode;
  interior_slot: ReactNode;
  on_open_case: (case_id: string) => void;
  on_back_to_prepare: () => void;
  on_focus: (location: LocationRef) => void;
  on_select_evidence: (evidence_id: string) => void;
  on_command: (command: OwnerCommand) => Promise<void>;
};

type RightTab = "condition" | "value" | "recovery";

const TAB_ID = "rw-right";

export const LOAD_ERROR_FALLBACK = "The recovery case could not be loaded.";
/** Banner text when a shown case fails to refresh and the parent gave no message. */
export const REFRESH_ERROR_FALLBACK = "Brace could not refresh this case.";
/** What the owner can do after a case failed to load. No automatic reload is promised: there is none. */
export const LOAD_ERROR_NEXT_STEPS =
  "No data was changed. You can choose the case again in the list to try once more, pick another case, or go back to Prepare.";
export const LOAD_ERROR_NEXT_STEPS_NO_CASES = "No data was changed. You can go back to Prepare and open the recovery workspace again.";

// Layout effects warn during server rendering (tests render statically); effects never run there anyway.
const useIsomorphicLayoutEffect = typeof window === "undefined" ? useEffect : useLayoutEffect;

export function RecoveryWorkspace(props: RecoveryWorkspaceProps) {
  const { cases, snapshot, state, error, busy, selected_evidence_id, on_open_case, on_back_to_prepare, on_focus, on_select_evidence, on_command } = props;
  const view = snapshot;
  const caseId = view?.case.case_id ?? null;
  // Scoped to the open case: a case switch drops the previous case's pending flags, errors and Retry bodies.
  const runner = useCommandRunner(on_command, view?.case.case_revision ?? 0, caseId);

  const [tab, setTab] = useState<RightTab>("condition");
  const [center, setCenter] = useState<CenterView>("overview");
  const [aerialChoice, setAerialChoice] = useState<AerialPairChoice>(NO_AERIAL_CHOICE);

  // A different case starts from the default aerial pair.
  const [choiceCase, setChoiceCase] = useState<string | null>(caseId);
  if (choiceCase !== caseId) {
    setChoiceCase(caseId);
    setAerialChoice(NO_AERIAL_CHOICE);
  }

  const captures = useMemo(() => (view ? aerialCaptures(view.evidence) : []), [view]);

  // Committed values for the stable callbacks below.
  const latest = useRef({ view, captures, aerialChoice, on_select_evidence });
  useIsomorphicLayoutEffect(() => {
    latest.current = { view, captures, aerialChoice, on_select_evidence };
  });

  // Brings up the center view that shows a piece of evidence: an aerial capture opens Aerial (as one side of
  // the pair), a scan opens Interior. Other kinds leave the center as it is; the inspector shows them.
  const handled = useRef<string | null>(null);
  const showEvidence = useCallback((evidence_id: string) => {
    const { view: v, captures: caps, aerialChoice: choice } = latest.current;
    const ev = v ? evidenceMap(v).get(evidence_id) : undefined;
    if (!v || !ev) return;
    handled.current = evidence_id;
    if (ev.kind === "vexcel_image") {
      const next = choiceForSelected(caps, v.case.incident_at, choice, ev.evidence_id);
      if (next) setAerialChoice(next);
      setCenter("aerial");
    } else if (ev.kind === "matterport_view") {
      setCenter("interior");
    }
  }, []);

  // Every selection made inside the workspace (tabs, inspector, aerial, scan list) comes through here, so
  // selecting evidence always switches the center, even when that id is already selected and the owner
  // has since switched the view by hand. Then the parent's callback runs.
  const selectEvidence = useCallback(
    (evidence_id: string) => {
      showEvidence(evidence_id);
      latest.current.on_select_evidence(evidence_id);
    },
    [showEvidence],
  );

  // A selection the parent makes on its own (e.g. from the map) moves the view once per change of
  // selected_evidence_id. A refreshed snapshot alone does not move it. An id that is not in this snapshot
  // yet is tried again when the next snapshot arrives.
  useEffect(() => {
    if (selected_evidence_id == null) {
      handled.current = null;
      return;
    }
    if (handled.current !== selected_evidence_id) showEvidence(selected_evidence_id);
  }, [selected_evidence_id, view, showEvidence]);

  const saving = busy || runner.anyPending;
  const errorText = error != null && error.trim() !== "" ? error.trim() : null;
  const loadFailed = view == null && state === "error";
  const refreshing = view != null && state === "loading";
  const bannerText = loadFailed ? null : (errorText ?? (view != null && state === "error" ? REFRESH_ERROR_FALLBACK : null));

  const fullWidthError = loadFailed && cases.length === 0;
  const gridClass = view != null || state === "loading" ? "rw-grid" : fullWidthError ? "rw-grid rw-grid--one" : "rw-grid rw-grid--two";

  const selectedEvidence = view && selected_evidence_id ? (evidenceMap(view).get(selected_evidence_id) ?? null) : null;

  // Every child below keeps its type and position in all states, so nothing that must survive is remounted.
  return (
    <div className="brace-recovery rw-root" aria-busy={(view == null && state === "loading") || undefined}>
      <WorkspaceTopBar view={view} saving={saving} refreshing={refreshing} on_back_to_prepare={on_back_to_prepare} />

      {bannerText != null && (
        <div className="rw-banner">
          <InlineError message={bannerText} />
          {view && <p className="rw-banner-note">The workspace still shows the last case data received (case rev {view.case.case_revision}).</p>}
        </div>
      )}

      <div className={gridClass}>
        {!fullWidthError && (
          <div className="rw-col rw-col--left">
            {view == null && state === "loading" && cases.length === 0 ? (
              <LoadingCard lines={4} />
            ) : (
              <CaseQueue cases={cases} selected_case_id={caseId} on_open_case={on_open_case} />
            )}
          </div>
        )}

        <div className="rw-col rw-col--center">
          <CenterStage
            view={view}
            title={loadFailed ? "Could not load this case" : undefined}
            placeholder={view ? undefined : <NoCaseShown state={state} errorText={errorText} hasCases={cases.length > 0} />}
            center={center}
            on_center={setCenter}
            captures={captures}
            aerial_choice={aerialChoice}
            on_aerial_choice={setAerialChoice}
            selected_evidence_id={selected_evidence_id}
            on_select_evidence={selectEvidence}
            map_slot={props.map_slot}
            interior_slot={props.interior_slot}
          />
          {view && <EvidenceInspector selected_evidence_id={selected_evidence_id} evidence={selectedEvidence} on_focus={on_focus} on_select_evidence={selectEvidence} />}
        </div>

        {view ? (
          <div className="rw-col rw-col--right">
            <RightPanels view={view} tab={tab} onTab={setTab} busy={busy} runner={runner} selected_evidence_id={selected_evidence_id} on_focus={on_focus} on_select_evidence={selectEvidence} />
          </div>
        ) : state === "loading" ? (
          <div className="rw-col rw-col--right">
            <LoadingCard lines={6} />
          </div>
        ) : null}
      </div>
    </div>
  );
}

type RightPanelsProps = {
  view: OwnerCaseView;
  tab: RightTab;
  onTab: (t: RightTab) => void;
  busy: boolean;
  runner: CommandRunner;
  selected_evidence_id: string | null;
  on_focus: (location: LocationRef) => void;
  on_select_evidence: (evidence_id: string) => void;
};

/**
 * Condition / Value / Recovery. All three panels stay rendered and the inactive ones are `hidden`, so drafts,
 * open forms and their errors survive a tab switch. Their contents are keyed by case_id: a new case starts clean.
 */
function RightPanels({ view, tab, onTab, busy, runner, selected_evidence_id, on_focus, on_select_evidence }: RightPanelsProps) {
  const caseKey = view.case.case_id;
  const tabs = [
    { value: "condition" as const, label: "Condition", count: view.observations.length },
    { value: "value" as const, label: "Value" },
    { value: "recovery" as const, label: "Recovery", count: view.tasks.length },
  ];
  return (
    <>
      <section className="r-card rw-tabs-card" aria-label="Case details">
        <Tabs tabs={tabs} value={tab} onChange={onTab} ariaLabel="Case details" idBase={TAB_ID} allPanelsRendered />
        <TabPanel idBase={TAB_ID} value="condition" hidden={tab !== "condition"} className="rw-tabpanel">
          <ConditionTab
            key={caseKey}
            view={view}
            busy={busy}
            runner={runner}
            selected_evidence_id={selected_evidence_id}
            on_focus={on_focus}
            on_select_evidence={on_select_evidence}
          />
        </TabPanel>
        <TabPanel idBase={TAB_ID} value="value" hidden={tab !== "value"} className="rw-tabpanel">
          <ValueTab key={caseKey} view={view} busy={busy} runner={runner} on_select_evidence={on_select_evidence} />
        </TabPanel>
        <TabPanel idBase={TAB_ID} value="recovery" hidden={tab !== "recovery"} className="rw-tabpanel">
          <RecoveryTab key={caseKey} view={view} busy={busy} runner={runner} on_focus={on_focus} on_select_evidence={on_select_evidence} />
        </TabPanel>
      </section>
      <Panel title="Timeline" aside={<span>{view.events.length}</span>} collapsible className="rw-timeline">
        <EventTimeline events={view.events} case_revision={view.case.case_revision} analysis_revision={view.case.analysis_revision} />
      </Panel>
    </>
  );
}

/** What the stage shows when there is no snapshot: loading, a load error, or nothing selected yet. */
function NoCaseShown({ state, errorText, hasCases }: { state: RecoveryWorkspaceProps["state"]; errorText: string | null; hasCases: boolean }) {
  if (state === "loading") {
    return (
      <div className="rw-status" role="status">
        <span className="r-spinner" aria-hidden="true" /> Loading the recovery case…
      </div>
    );
  }
  if (state === "error") {
    return (
      <div className="rw-status rw-status--error">
        <InlineError message={errorText ?? LOAD_ERROR_FALLBACK} />
        <p className="rw-error-note">{hasCases ? LOAD_ERROR_NEXT_STEPS : LOAD_ERROR_NEXT_STEPS_NO_CASES}</p>
      </div>
    );
  }
  return hasCases ? (
    <EmptyState title="Select a case">Choose a property from the list to open its recovery workspace.</EmptyState>
  ) : (
    <EmptyState title="No recovery cases yet">A recovery case appears here once one is opened for a property.</EmptyState>
  );
}

function LoadingCard({ lines }: { lines: number }) {
  return (
    <div className="r-card rw-skeleton" aria-hidden="true">
      <span className="rw-skel rw-skel--title" />
      {Array.from({ length: lines }, (_, i) => (
        <span key={i} className="rw-skel" style={{ width: `${88 - ((i * 17) % 40)}%` }} />
      ))}
    </div>
  );
}
