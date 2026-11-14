// Full-width top bar: back link, property identity, incident, effective date, mode banner, revisions, status.
import type { CaseMode, OwnerCaseView, RecoveryCaseSummary } from "../../recovery/contracts";
import { Button, StatusMark } from "../recovery-ui";
import { formatSourceDate } from "./format";
import {
  assessmentStateLabel,
  assessmentStatusTone,
  CASE_MODE_HELP,
  CASE_MODE_LABEL,
  currentAssessment,
  isCurrentAssessmentStale,
  labelOr,
  lookupKnown,
} from "./model";

export const MODE_BANNER_TEXT: Record<CaseMode, string> = {
  scenario_exercise: "Scenario exercise: hypothetical reports and assumptions",
  historical_replay: CASE_MODE_LABEL.historical_replay,
  observed_recovery: CASE_MODE_LABEL.observed_recovery,
};

export const UNKNOWN_MODE_HELP = "This screen does not recognise this case mode. Rely on the case record's own label beside it.";

/** Banner text, help and style key for a mode. A mode this build does not know says so and is flagged for attention. */
export function modeDisplay(mode: string): { title: string; help: string; key: CaseMode | "unknown" } {
  const title = lookupKnown(MODE_BANNER_TEXT, mode);
  const help = lookupKnown(CASE_MODE_HELP, mode);
  if (title !== undefined && help !== undefined) return { title, help, key: mode as CaseMode };
  return { title: labelOr(CASE_MODE_LABEL, mode, "mode"), help: UNKNOWN_MODE_HELP, key: "unknown" };
}

export type WorkspaceTopBarProps = {
  /** The open case's snapshot, or null when no case is open. */
  view: OwnerCaseView | null;
  saving: boolean;
  /** The parent is reloading a case that is already shown (state="loading" with a snapshot). */
  refreshing?: boolean;
  on_back_to_prepare: () => void;
};

export function ModeBanner({ summary }: { summary: RecoveryCaseSummary }) {
  const mode = modeDisplay(summary.mode);
  return (
    <div className={`rw-mode rw-mode--${mode.key}`} role="note" aria-label="Case mode">
      {mode.key === "scenario_exercise" && <span className="rw-mode-hatch" aria-hidden="true" />}
      <p className="rw-mode-text">
        <strong className="rw-mode-title">{mode.title}</strong>
        <span className="rw-mode-label" title="Mode label from the case record">
          {summary.mode_label}
        </span>
        <span className="rw-mode-help">{mode.help}</span>
      </p>
      {mode.key === "scenario_exercise" && <span className="rw-mode-hatch" aria-hidden="true" />}
    </div>
  );
}

function AssessmentChip({ view }: { view: OwnerCaseView }) {
  const a = currentAssessment(view);
  if (!a) {
    return (
      <span className="rw-chip">
        <StatusMark tone="muted" shape="hollow" label="No assessment yet" />
      </span>
    );
  }
  const stale = isCurrentAssessmentStale(view);
  // A published (or draft) assessment built on older inputs is stale even before the server marks it.
  const label =
    stale && a.status !== "stale"
      ? `${assessmentStateLabel(view, a)}, stale: built on analysis rev ${a.base_analysis_revision}`
      : assessmentStateLabel(view, a);
  const mark = stale ? { tone: "pending" as const, shape: "hatched" as const } : assessmentStatusTone(a.status);
  return (
    <span className={stale ? "rw-chip rw-chip--stale" : "rw-chip"} title={a.headline}>
      <span className="rw-chip-key">Assessment</span>
      <StatusMark {...mark} label={label} />
    </span>
  );
}

export function WorkspaceTopBar({ view, saving, refreshing = false, on_back_to_prepare }: WorkspaceTopBarProps) {
  const c = view?.case ?? null;
  const activity = [saving && "Saving…", refreshing && "Refreshing…"].filter(Boolean).join(" · ");
  return (
    <header className="rw-topbar">
      <div className="rw-topbar-row">
        <Button variant="quiet" className="rw-back" onClick={on_back_to_prepare}>
          <span aria-hidden="true">←</span> Back to Prepare
        </Button>

        <div className="rw-identity">
          <p className="rw-eyebrow">Recovery workspace</p>
          {c ? (
            <>
              <h1 className="rw-title">{c.property_name}</h1>
              <p className="rw-address">
                {c.address}, {c.city}
              </p>
            </>
          ) : (
            <h1 className="rw-title">No case open</h1>
          )}
        </div>

        {c && (
          <dl className="rw-facts">
            <div>
              <dt>Incident</dt>
              <dd>
                {c.incident_name}
                <span className="rw-fact-date">{formatSourceDate(c.incident_at)}</span>
              </dd>
            </div>
            <div>
              <dt>Effective date</dt>
              <dd>Assessment as of {formatSourceDate(c.assessment_as_of)}</dd>
            </div>
          </dl>
        )}

        <div className="rw-chips">
          {c && (
            <span className="rw-chip" title="case_revision versions the whole case; analysis_revision versions only the assessment inputs">
              Case rev {c.case_revision} · analysis rev {c.analysis_revision}
            </span>
          )}
          {view && <AssessmentChip view={view} />}
          <span className="rw-saving" role="status" aria-live="polite">
            {refreshing && <span className="r-spinner rw-saving-spinner" aria-hidden="true" />}
            {activity}
          </span>
        </div>
      </div>
      {c && <ModeBanner summary={c} />}
    </header>
  );
}
