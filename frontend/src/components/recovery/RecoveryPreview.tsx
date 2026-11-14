// Explicit, opt-in preview of the workspace on synthetic fixtures. Never a fallback for failed production calls.
// on_command is a local spy: it waits ~700ms, then either rejects (when "Make next command fail" is on) or applies
// a simple update to this preview's own fixture copy, so pending, success, error and Retry are all visible.
//
// It stands in for the real parent, so it does what a real parent must do:
// - it mounts the workspace once (no key per scenario) and only changes its props;
// - it applies a command to the case whose snapshot is on screen (commands carry no case_id);
// - it reads the CommandResult of create_invitation and shows the invitation itself, because on_command
//   resolves void and the workspace never sees the token (here: in the spy panel, as a fixture token).
import { useCallback, useId, useRef, useState } from "react";
import type { ApiErrorBody, CaseEvent, CommandResult, LocationRef, OwnerCaseView, OwnerCommand, RecoveryCaseSummary } from "../../recovery/contracts";
import { FixtureBanner, Panel, SegmentedControl } from "../recovery-ui";
import { FIXTURE_LABEL, fixtureCases, fixtureSnapshot } from "./fixtures/preview-fixture";
import type { FixtureVariant } from "./fixtures/preview-fixture";
import { formatTimestamp } from "./format";
import { RecoveryWorkspace } from "./RecoveryWorkspace";
import type { RecoveryWorkspaceProps } from "./RecoveryWorkspace";
import "./workspace.css";

type Scenario = FixtureVariant | "loading" | "error" | "no_cases";

/** The parent's load state on top of a scenario that has a snapshot: a refresh in flight, or a failed one. */
type ParentState = "ready" | "refreshing" | "refresh_error";

const PARENT_STATES = [
  { value: "ready", label: "Ready" },
  { value: "refreshing", label: "Refreshing" },
  { value: "refresh_error", label: "Refresh failed" },
] as const satisfies readonly { value: ParentState; label: string }[];

const PREVIEW_REFRESH_ERROR = "Could not refresh the recovery case: the recovery service did not respond (fixture error).";

/** What a parent keeps from a confirmed create_invitation. Fixture values only. */
type InvitationEntry = { id: number; case_id: string; household: string; token: string; link: string; expires_at: string | null };

const SCENARIOS = [
  { value: "full", label: "Full" },
  { value: "conditional", label: "Conditional" },
  { value: "insufficient", label: "Insufficient" },
  { value: "stale", label: "Stale" },
  { value: "empty", label: "Empty case" },
  { value: "loading", label: "Loading" },
  { value: "error", label: "Error" },
  { value: "no_cases", label: "No cases" },
] as const satisfies readonly { value: Scenario; label: string }[];

const DEFAULT_CASE = "fx-case-1";
const PREVIEW_ERROR = "Could not load the recovery case: the recovery service did not respond (fixture error).";
const DELAY_MS = 700;

type SpyEntry = { id: number; at: string; kind: string; detail: string; outcome: "pending" | "ok" | "failed" | "info" };

function isVariant(s: Scenario): s is FixtureVariant {
  return s === "full" || s === "conditional" || s === "insufficient" || s === "stale" || s === "empty";
}

const INVITATION_TTL_MS = 7 * 24 * 3600 * 1000;

/**
 * A simple local stand-in for the server: bump case_revision, apply the status change, append an event, and
 * return the CommandResult the HTTP endpoint would return (with a fixture invitation token for create_invitation).
 */
function applyCommand(view: OwnerCaseView, cmd: OwnerCommand, now: string): { next: OwnerCaseView; result: CommandResult } {
  const next: OwnerCaseView = JSON.parse(JSON.stringify(view));
  const c = next.case;
  c.case_revision += 1;
  let entity: string | null = null;
  let summary: string | null = null;
  let run_id: string | null = null;
  let invitation_token: string | null = null;
  let invitation_expires_at: string | null = null;

  switch (cmd.type) {
    case "transition_task": {
      const t = next.tasks.find((x) => x.task_id === cmd.task_id);
      if (t) {
        t.status = cmd.status;
        t.revision += 1;
        t.updated_at = now;
        if (cmd.confirmation_source) t.confirmation_source = cmd.confirmation_source;
        if (cmd.status === "completion_submitted") t.completion_evidence_ids = [...t.completion_evidence_ids, ...cmd.evidence_ids];
      }
      entity = cmd.task_id;
      summary = `Task moved to ${cmd.status} (preview)`;
      break;
    }
    case "review_observation": {
      const o = next.observations.find((x) => x.observation_id === cmd.observation_id);
      if (o) {
        o.status = cmd.status;
        o.updated_at = now;
        if (cmd.note) o.verification_note = cmd.note;
        if (cmd.status === "verified" || cmd.status === "dismissed") o.verified_by = "Preview owner (fixture)";
        for (const id of cmd.evidence_ids) if (!o.evidence_ids.includes(id)) o.evidence_ids.push(id);
      }
      // A reviewed condition is a new assessment input.
      c.analysis_revision += 1;
      entity = cmd.observation_id;
      break;
    }
    case "publish_notice": {
      const notice_id = `preview-notice-${c.case_revision}`;
      next.notices.push({ notice_id, title: cmd.title, body: cmd.body, published_at: now, published_by: "Preview owner (fixture)", source_ids: cmd.source_ids });
      entity = notice_id;
      summary = `Notice published: ${cmd.title}`;
      break;
    }
    case "publish_assessment": {
      const a = next.assessments.find((x) => x.assessment_id === cmd.assessment_id);
      if (a) {
        a.status = "published";
        a.published_at = now;
        next.current_assessment_id = a.assessment_id;
      }
      entity = cmd.assessment_id;
      break;
    }
    case "start_assessment": {
      const run = `preview-run-${c.case_revision}`;
      next.assessments.unshift({
        assessment_id: `preview-asmt-${c.case_revision}`,
        run_id: run,
        base_analysis_revision: c.analysis_revision,
        status: "running",
        headline: "Assessment running (preview)",
        summary: "The preview does not run a model; this run stays running.",
        created_at: now,
        published_at: null,
        valuation: null,
        observation_ids: [],
        unresolved_questions: [],
        failure_reason: null,
      });
      entity = run;
      run_id = run;
      break;
    }
    case "create_invitation":
      entity = cmd.household_id;
      invitation_token = `FIXTURE-INVITE-${cmd.household_id}-r${c.case_revision}`;
      invitation_expires_at = new Date(Date.parse(now) + INVITATION_TTL_MS).toISOString();
      break;
  }

  c.pending_tasks = next.tasks.filter((t) => t.status !== "verified" && t.status !== "cancelled").length;
  const event: CaseEvent = {
    event_id: next.event_cursor + 1,
    case_id: c.case_id,
    case_revision: c.case_revision,
    analysis_revision: c.analysis_revision,
    type: `preview.${cmd.type}`,
    at: now,
    entity_id: entity,
    public_summary: summary,
  };
  next.events.push(event);
  next.event_cursor = event.event_id;
  return {
    next,
    result: { case_revision: c.case_revision, analysis_revision: c.analysis_revision, run_id, invitation_token, invitation_expires_at },
  };
}

function commandDetail(cmd: OwnerCommand): string {
  const { type: _type, ...rest } = cmd;
  void _type;
  return JSON.stringify(rest, null, 1);
}

export function RecoveryPreview() {
  const [scenario, setScenario] = useState<Scenario>("full");
  const [caseId, setCaseId] = useState(DEFAULT_CASE);
  const [cases, setCases] = useState<RecoveryCaseSummary[]>(() => fixtureCases());
  const [snapshot, setSnapshot] = useState<OwnerCaseView | null>(() => fixtureSnapshot("full", DEFAULT_CASE));
  const [selected, setSelected] = useState<string | null>(null);
  const [failNext, setFailNext] = useState(false);
  const [spy, setSpy] = useState<SpyEntry[]>([]);
  const [parentState, setParentState] = useState<ParentState>("ready");
  const [invitations, setInvitations] = useState<InvitationEntry[]>([]);
  const invitesTitleId = useId();

  const snapshotRef = useRef(snapshot);
  snapshotRef.current = snapshot;
  const failNextRef = useRef(failNext);
  failNextRef.current = failNext;
  const seq = useRef(0);

  const log = useCallback((entry: Omit<SpyEntry, "id" | "at">) => {
    const id = ++seq.current;
    setSpy((s) => [{ ...entry, id, at: new Date().toISOString() }, ...s].slice(0, 50));
    return id;
  }, []);
  const settle = useCallback((id: number, outcome: SpyEntry["outcome"], extra?: string) => {
    setSpy((s) => s.map((e) => (e.id === id ? { ...e, outcome, detail: extra ? `${e.detail}\n→ ${extra}` : e.detail } : e)));
  }, []);

  const load = (next: Scenario, case_id: string) => {
    setScenario(next);
    setCaseId(case_id);
    setSelected(null);
    setCases(next === "no_cases" ? [] : fixtureCases());
    setSnapshot(isVariant(next) ? fixtureSnapshot(next, case_id) : null);
  };

  const onCommand = useCallback(
    (cmd: OwnerCommand) =>
      new Promise<void>((resolve, reject) => {
        const shouldFail = failNextRef.current;
        if (shouldFail) setFailNext(false);
        // Commands carry no case_id: a parent sends each one to the case whose snapshot was on screen when it
        // was issued, never to whatever case is open by the time it is sent.
        const target = snapshotRef.current?.case.case_id ?? null;
        const id = log({ kind: cmd.type, detail: `${commandDetail(cmd)}\ncase: ${target ?? "none"}`, outcome: "pending" });
        window.setTimeout(() => {
          const current = snapshotRef.current;
          if (shouldFail) {
            const body: ApiErrorBody = {
              error: { code: "unavailable", message: "The recovery service did not confirm this change (preview: forced failure).", retryable: true },
            };
            settle(id, "failed", body.error.message);
            reject(body);
            return;
          }
          if (!current || target == null) {
            const body: ApiErrorBody = { error: { code: "not_found", message: "No case is open in the preview.", retryable: false } };
            settle(id, "failed", body.error.message);
            reject(body);
            return;
          }
          if (current.case.case_id !== target) {
            // The owner opened another case meanwhile. The server would still apply this to its own case; the
            // preview keeps no copy of that case, so nothing on screen changes (and the workspace ignores the answer).
            settle(id, "ok", `applied to ${target}, which is no longer on screen; the preview keeps no copy of it`);
            resolve();
            return;
          }
          if (cmd.expected_revision !== current.case.case_revision) {
            const body: ApiErrorBody = {
              error: {
                code: "revision_conflict",
                message: "This case changed. Reload before applying this edit.",
                retryable: true,
                current_revision: current.case.case_revision,
              },
            };
            settle(id, "failed", body.error.message);
            reject(body);
            return;
          }
          const { next, result } = applyCommand(current, cmd, new Date().toISOString());
          snapshotRef.current = next;
          setSnapshot(next);
          setCases((list) => list.map((c) => (c.case_id === next.case.case_id ? { ...next.case } : c)));
          let outcome = `case_revision ${current.case.case_revision} → ${result.case_revision}`;
          // What a real parent must do: on_command resolves void, so the parent itself shows the invitation
          // from CommandResult.invitation_token (a link or QR code). Here it goes to the spy panel.
          if (cmd.type === "create_invitation" && result.invitation_token != null) {
            const token = result.invitation_token;
            const unit = current.household_labels.find((h) => h.household_id === cmd.household_id)?.unit_label ?? null;
            setInvitations((list) => [
              {
                id,
                case_id: next.case.case_id,
                household: unit != null ? `Unit ${unit}` : `Household ${cmd.household_id} (unit not confirmed)`,
                token,
                link: `https://brace.invalid/resident#invitation=${encodeURIComponent(token)}`,
                expires_at: result.invitation_expires_at,
              },
              ...list,
            ]);
            outcome += ` · invitation_token ${token} (fixture)`;
          }
          settle(id, "ok", outcome);
          resolve();
        }, DELAY_MS);
      }),
    [log, settle],
  );

  const onFocus = useCallback(
    (location: LocationRef) => {
      log({ kind: "on_focus", detail: `${location.label} (${location.binding})`, outcome: "info" });
    },
    [log],
  );

  const onSelectEvidence = useCallback(
    (evidence_id: string) => {
      setSelected(evidence_id);
      log({ kind: "on_select_evidence", detail: evidence_id, outcome: "info" });
    },
    [log],
  );

  // A refresh is shown on top of the snapshot it refreshes: the parent keeps passing the snapshot.
  const shownParentState: ParentState = snapshot ? parentState : "ready";
  const workspaceState: RecoveryWorkspaceProps["state"] =
    scenario === "loading" || shownParentState === "refreshing" ? "loading" : scenario === "error" || shownParentState === "refresh_error" ? "error" : "ready";
  const workspaceError = scenario === "error" ? PREVIEW_ERROR : shownParentState === "refresh_error" ? PREVIEW_REFRESH_ERROR : null;

  const props: RecoveryWorkspaceProps = {
    cases,
    snapshot,
    state: workspaceState,
    error: workspaceError,
    busy: false,
    selected_evidence_id: selected,
    map_slot: (
      <div className="rw-placeholder">
        <span>Map slot: the lead mounts Brace's map here</span>
      </div>
    ),
    interior_slot: (
      <div className="rw-placeholder">
        <span>Interior slot: the lead mounts Brace's Matterport viewer here</span>
      </div>
    ),
    on_open_case: (id) => {
      log({ kind: "on_open_case", detail: id, outcome: "info" });
      load(isVariant(scenario) ? scenario : "full", id);
    },
    on_back_to_prepare: () => log({ kind: "on_back_to_prepare", detail: "The lead routes this back to the preparation app.", outcome: "info" }),
    on_focus: onFocus,
    on_select_evidence: onSelectEvidence,
    on_command: onCommand,
  };

  const last = spy[0];

  return (
    <div className="brace-recovery rw-preview">
      <div className="rw-preview-bar">
        <FixtureBanner>{FIXTURE_LABEL}</FixtureBanner>
        <div className="rw-preview-controls">
          <SegmentedControl options={SCENARIOS} value={scenario} onChange={(s) => load(s, caseId)} ariaLabel="Preview scenario" />
          <SegmentedControl
            options={PARENT_STATES.map((o) => ({ ...o, disabled: snapshot == null && o.value !== "ready" }))}
            value={shownParentState}
            onChange={setParentState}
            ariaLabel="Parent load state (with a case open)"
          />
          <label className="rw-preview-toggle">
            <input type="checkbox" checked={failNext} onChange={(e) => setFailNext(e.target.checked)} />
            Make next command fail
          </label>
          <span className="rw-preview-last" aria-live="polite">
            {last ? `Last: ${last.kind} · ${last.outcome}` : "No commands yet. Commands appear in the spy panel below the workspace."}
          </span>
        </div>
      </div>

      {/* Mounted once, like a real parent: scenarios only change props. */}
      <RecoveryWorkspace {...props} />

      <div className="rw-preview-spy">
        <Panel title="Command spy" aside={<span>{spy.length}</span>}>
          {invitations.length > 0 && (
            <section className="rw-invites" aria-labelledby={invitesTitleId}>
              <h3 id={invitesTitleId} className="rw-invites-title">
                Invitations returned to the parent
              </h3>
              <p className="rw-preview-last">
                on_command resolves without a result, so the workspace never sees these. A real parent reads CommandResult.invitation_token
                and shows the link or QR code to the owner itself.
              </p>
              <ul className="rw-invite-list">
                {invitations.map((v) => (
                  <li key={v.id} className="rw-invite">
                    <span className="rw-invite-tag">Fixture token, not a real invitation</span>
                    <p className="rw-invite-head">
                      <strong>{v.household}</strong> <span className="rw-spy-at">{v.case_id}</span>
                    </p>
                    <dl className="rw-invite-facts">
                      <div>
                        <dt>Token (fixture)</dt>
                        <dd>
                          <code>{v.token}</code>
                        </dd>
                      </div>
                      <div>
                        <dt>Link (fixture, does not resolve)</dt>
                        <dd>
                          <code>{v.link}</code>
                        </dd>
                      </div>
                      <div>
                        <dt>Expires</dt>
                        <dd>{v.expires_at ? formatTimestamp(v.expires_at) : "No expiry returned"}</dd>
                      </div>
                    </dl>
                  </li>
                ))}
              </ul>
            </section>
          )}
          {spy.length === 0 ? (
            <p className="rw-preview-last">Nothing received yet. Use a control in Condition, Value or Recovery.</p>
          ) : (
            <ul className="rw-spy-list">
              {spy.map((e) => (
                <li key={e.id} className="rw-spy-item">
                  <strong>{e.kind}</strong>
                  <span>{e.outcome}</span>
                  <span className="rw-spy-at">{formatTimestamp(e.at)}</span>
                  <pre>{e.detail}</pre>
                </li>
              ))}
            </ul>
          )}
        </Panel>
      </div>
    </div>
  );
}
