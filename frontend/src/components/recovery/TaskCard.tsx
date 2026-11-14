// One recovery task: exact scope, location, households, confirmation, schedule, evidence, and the
// transitions the contract allows from its current status. Status is never changed locally: a
// transition is a command, and the card only shows the server snapshot.
import { useId, useState } from "react";
import type { FormEvent } from "react";
import type { LocationRef, OwnerCaseView, RecoveryTask, TaskStatus } from "../../recovery/contracts";
import { Button, ChangedBanner, EvidenceBadge, InlineError, StatusMark } from "../recovery-ui";
import type { CommandBody, CommandRunner } from "./commands";
import { formatSourceDate, formatTimestamp } from "./format";
import {
  BINDING_LABEL,
  TASK_STATUS_ORDER,
  bindingLabel,
  commandKey,
  evidenceKindLabel,
  evidenceMap,
  householdUnit,
  lookupKnown,
  taskNext,
  taskSiteTarget,
  taskStatusLabel,
  taskStatusTone,
  taskTransitionNeeds,
} from "./model";
import "./recovery-tab.css";

export type TaskCardProps = {
  task: RecoveryTask;
  view: OwnerCaseView;
  busy: boolean;
  runner: CommandRunner;
  on_focus: (location: LocationRef) => void;
  on_select_evidence: (evidence_id: string) => void;
};

/** The button that opens a transition form, by target status. */
const TRANSITION_ACTION: Record<TaskStatus, string> = {
  proposed: "Mark proposed",
  approved: "Approve",
  accepted: "Record acceptance",
  in_progress: "Mark in progress",
  completion_submitted: "Submit completion",
  verified: "Verify completion",
  cancelled: "Cancel task",
};

/** What each move means, stated in the form so nobody mistakes an approval for a booking. */
const TRANSITION_HELP: Record<TaskStatus, string> = {
  proposed: "",
  approved:
    "Approving says you want this work done. It does not book anyone: the task stays unaccepted until whoever does the work confirms.",
  accepted:
    "Record acceptance only when the contractor or crew has actually confirmed. Say who confirmed and how; the model cannot confirm for anyone.",
  in_progress: "Mark in progress once work has started on site.",
  completion_submitted: "Attach the evidence that shows the work is done. It still needs verification afterwards.",
  verified: "Verify only after reviewing the completion evidence yourself. Explain what you checked.",
  cancelled: "Cancelling ends this task. Residents see that it was cancelled. Give the reason.",
};

/**
 * Accepted or later: whoever does the work has confirmed, so a schedule on file can be shown as confirmed. Every other
 * status (proposed, approved, cancelled, or one this screen does not recognise) never shows a schedule as confirmed.
 */
const SCHEDULE_CONFIRMABLE: ReadonlySet<string> = new Set<TaskStatus>(["accepted", "in_progress", "completion_submitted", "verified"]);

export type ScheduleView =
  | { kind: "none" }
  | { kind: "tentative"; date: string }
  | { kind: "confirmed"; date: string }
  | { kind: "cancelled"; date: string | null };

/** How a task's confirmed_schedule may be presented. An empty or whitespace schedule counts as no schedule. */
export function scheduleView(task: Pick<RecoveryTask, "status" | "confirmed_schedule">): ScheduleView {
  const raw = typeof task.confirmed_schedule === "string" ? task.confirmed_schedule.trim() : "";
  // A schedule string is either a SourceDate or a timestamp; formatSourceDate handles both without timezone shifts for dates.
  const date = raw === "" ? null : formatSourceDate(raw);
  if (task.status === "cancelled") return { kind: "cancelled", date };
  if (date == null) return { kind: "none" };
  return SCHEDULE_CONFIRMABLE.has(task.status) ? { kind: "confirmed", date } : { kind: "tentative", date };
}

function ScheduleText({ task }: { task: RecoveryTask }) {
  const s = scheduleView(task);
  switch (s.kind) {
    case "none":
      return <span className="rr-none">Schedule not confirmed</span>;
    case "tentative":
      // A date on an unaccepted task is not a booking; never show it as one.
      return (
        <>
          <span className="rr-none">Schedule not confirmed.</span>{" "}
          <span className="rr-schedule-note">A tentative date is on file ({s.date}). It is not a booking.</span>
        </>
      );
    case "confirmed":
      return <>{s.date}</>;
    case "cancelled":
      // A cancelled task has no current schedule; a date it once had is shown struck through, as history.
      return s.date == null ? (
        <span className="rr-none">Schedule not confirmed: task cancelled</span>
      ) : (
        <>
          <span className="rr-none">No current schedule: task cancelled.</span>{" "}
          <span className="rr-schedule-note">
            Date previously on file: <s>{s.date}</s>
          </span>
        </>
      );
  }
}

function unitText(view: OwnerCaseView, household_id: string): string {
  const unit = householdUnit(view, household_id);
  return unit != null ? `Unit ${unit}` : "Unit not confirmed";
}

export function TaskCard({ task, view, busy, runner, on_focus, on_select_evidence }: TaskCardProps) {
  const formId = useId();
  const [openTarget, setOpenTarget] = useState<TaskStatus | null>(null);
  // The task revision the form was opened against. A command is never sent for a version the owner did not see.
  const [formRevision, setFormRevision] = useState<number | null>(null);
  const [note, setNote] = useState("");
  const [confirmation, setConfirmation] = useState("");
  const [picked, setPicked] = useState<string[]>([]);
  const [touched, setTouched] = useState(false);

  const evidence = evidenceMap(view);
  const keyFor = (t: TaskStatus) => commandKey.transitionTask(view.case.case_id, task.task_id, t);
  const next = taskNext(task.status);
  // If the server has moved the task on, a form for a target that is no longer allowed disappears.
  const target = openTarget != null && next.includes(openTarget) ? openTarget : null;
  const key = target != null ? keyFor(target) : null;
  const st = key != null ? runner.status(key) : { pending: false, error: null };
  const needs = target != null ? taskTransitionNeeds(target) : null;
  const tone = taskStatusTone(task.status);
  const statusLabel = taskStatusLabel(task.status);
  const revisionChanged = target != null && formRevision != null && formRevision !== task.revision;

  // Every transition this card can have sent. A wait or a failure stays visible on the card whether or not its form is
  // open (the open form shows its own), so switching tabs or closing the form never hides it.
  const commands = TASK_STATUS_ORDER.map((t) => ({ target: t, key: keyFor(t), allowed: next.includes(t), ...runner.status(keyFor(t)) })).filter(
    (c) => (c.pending || c.error != null) && c.target !== target,
  );

  const resetForm = () => {
    setOpenTarget(null);
    setFormRevision(null);
    setNote("");
    setConfirmation("");
    setPicked([]);
    setTouched(false);
  };

  const openForm = (t: TaskStatus) => {
    setOpenTarget(t);
    setFormRevision(task.revision);
    setNote("");
    setConfirmation("");
    setPicked([]);
    setTouched(false);
  };

  const closeForm = () => {
    if (key != null) runner.dismiss(key);
    resetForm();
  };

  // Any edit after a failure clears it, so Retry can never resend text the owner has since changed.
  const edited = () => {
    if (key != null && st.error != null) runner.dismiss(key);
  };

  // Only evidence still in this snapshot counts or is sent.
  const chosen = picked.filter((id) => evidence.has(id));
  const noteMissing = needs?.note === "required" && note.trim() === "";
  const confirmationMissing = needs?.confirmation_source === true && confirmation.trim() === "";
  const evidenceMissing = needs?.evidence === true && chosen.length === 0;
  const invalid = noteMissing || confirmationMissing || evidenceMissing;

  /** Sends what the form holds now. Used by submit and by Retry inside the open form. */
  const send = async () => {
    setTouched(true);
    if (target == null || key == null || needs == null || invalid || revisionChanged) return;
    const body: CommandBody = {
      type: "transition_task",
      task_id: task.task_id,
      expected_task_revision: formRevision ?? task.revision,
      status: target,
      note: note.trim(),
      confirmation_source: needs.confirmation_source ? confirmation.trim() : null,
      evidence_ids: needs.evidence ? chosen : [],
    };
    const ok = await runner.run(key, body);
    if (ok) resetForm();
  };

  const submit = (e: FormEvent) => {
    e.preventDefault();
    void send();
  };

  const togglePicked = (id: string) => {
    setPicked((p) => (p.includes(id) ? p.filter((x) => x !== id) : [...p, id]));
    edited();
  };

  const evidenceChip = (id: string) => {
    const ev = evidence.get(id);
    if (!ev) {
      return <EvidenceBadge key={id} label={`Evidence ${id}`} kindLabel="Not in snapshot" title="This evidence is not in the current case snapshot." />;
    }
    return (
      <EvidenceBadge key={id} label={ev.source_label} kindLabel={evidenceKindLabel(ev.kind)} title={ev.summary} onClick={() => on_select_evidence(id)} />
    );
  };

  // One clear way to see the task on site: focus its location and select its first cited evidence.
  const site = taskSiteTarget(view, task);
  const showOnSite = () => {
    if (site.location) on_focus(site.location);
    if (site.evidence_id) on_select_evidence(site.evidence_id);
  };
  const showLabel = site.location ? "Show on site" : "Show evidence";

  const binding = task.location?.binding;
  const bindingClass = binding != null && lookupKnown(BINDING_LABEL, binding) ? `rr-binding rr-binding--${binding}` : "rr-binding rr-binding--unverified";

  const isProposed = task.status === "proposed";
  const showCompletion =
    task.completion_evidence_ids.length > 0 || task.status === "completion_submitted" || task.status === "verified";
  const disabled = busy || runner.anyPending;

  return (
    <article className={`rr-task rr-task--${task.status}`} aria-label={`${task.title}: ${statusLabel}`}>
      {task.status === "cancelled" && <span className="rr-task-hatch" aria-hidden="true" />}
      <header className="rr-task-head">
        <h4 className="rr-task-title">{task.title}</h4>
        <span className="rr-task-rev" title={`Updated ${formatTimestamp(task.updated_at)}`}>
          Task rev {task.revision}
        </span>
      </header>
      <div className="rr-task-sub">
        <StatusMark {...tone} label={statusLabel} className="rr-task-status" />
        {(site.location != null || site.evidence_id != null) && (
          <Button
            variant="default"
            className="rr-show"
            onClick={showOnSite}
            aria-label={`${showLabel}: ${task.title}`}
            title={
              site.location && site.evidence_id
                ? "Show this task's location and its first cited evidence"
                : site.location
                  ? "Show this task's location"
                  : "Show this task's first cited evidence"
            }
          >
            {showLabel}
          </Button>
        )}
      </div>

      {isProposed && (
        <p className="rr-task-callout">
          <strong>Proposed only: not approved, not booked.</strong> Nobody has agreed to do this work and nothing is scheduled.
        </p>
      )}
      {task.status === "approved" && (
        <p className="rr-task-callout rr-task-callout--approved">
          Approved by the owner, but not booked: nobody doing the work has confirmed yet.
        </p>
      )}

      {task.superseded_scope != null && task.superseded_scope.trim() !== "" && (
        <ChangedBanner title="Scope changed: needs renewed acceptance" previous={task.superseded_scope}>
          The current scope below (task rev {task.revision}) replaces the struck-through one. Any earlier acceptance does not
          cover it.
        </ChangedBanner>
      )}

      <dl className="rr-facts">
        <div className="rr-fact rr-fact--wide">
          <dt>Exact scope</dt>
          <dd className="rr-scope">{task.scope}</dd>
        </div>
        <div className="rr-fact rr-fact--wide">
          <dt>Location</dt>
          <dd>
            {task.location ? (
              <button
                type="button"
                className="rr-link"
                onClick={() => task.location && on_focus(task.location)}
                title="Show this location"
              >
                <span className="rr-link-label">{task.location.label}</span>
                <span className={bindingClass}>{bindingLabel(task.location.binding)}</span>
              </button>
            ) : (
              <span className="rr-none">No location recorded</span>
            )}
          </dd>
        </div>
        <div className="rr-fact">
          <dt>Households</dt>
          <dd>
            {task.household_ids.length === 0 ? (
              <span className="rr-none">None linked</span>
            ) : (
              <span className="rr-units">
                {task.household_ids.map((h) => (
                  <span key={h} className="rr-unit" title={h}>
                    {unitText(view, h)}
                  </span>
                ))}
              </span>
            )}
          </dd>
        </div>
        <div className="rr-fact">
          <dt>Assignee</dt>
          <dd>{task.assignee_label ?? <span className="rr-none">No assignee</span>}</dd>
        </div>
        <div className="rr-fact rr-fact--wide">
          <dt>Confirmation</dt>
          <dd>
            {task.confirmation_source != null && task.confirmation_source.trim() !== "" ? (
              <>Confirmed by: {task.confirmation_source}</>
            ) : (
              <span className="rr-none">No confirmation recorded</span>
            )}
          </dd>
        </div>
        <div className="rr-fact rr-fact--wide">
          <dt>Schedule</dt>
          <dd>
            <ScheduleText task={task} />
          </dd>
        </div>
      </dl>

      <div className="rr-evidence-row">
        <span className="rr-evidence-head">Evidence</span>
        {task.evidence_ids.length === 0 ? (
          <span className="rr-none">No evidence cited</span>
        ) : (
          <span className="rr-chips">{[...new Set(task.evidence_ids)].map(evidenceChip)}</span>
        )}
      </div>
      {showCompletion && (
        <div className="rr-evidence-row">
          <span className="rr-evidence-head">Completion evidence</span>
          {task.completion_evidence_ids.length === 0 ? (
            <span className="rr-none">No completion evidence recorded</span>
          ) : (
            <span className="rr-chips">{[...new Set(task.completion_evidence_ids)].map(evidenceChip)}</span>
          )}
        </div>
      )}

      {commands.length > 0 && (
        <div className="rr-task-commands">
          {commands.map((c) =>
            c.pending ? (
              <p key={c.key} className="rr-task-wait" role="status">
                <StatusMark tone="pending" shape="ring" label={`${TRANSITION_ACTION[c.target]}: waiting for the server`} />
                <span>The status changes only after the server confirms.</span>
              </p>
            ) : (
              <InlineError
                key={c.key}
                message={
                  c.allowed
                    ? `${TRANSITION_ACTION[c.target]} failed: ${c.error}`
                    : `${TRANSITION_ACTION[c.target]} failed: ${c.error} The task is now “${statusLabel}”, so this action no longer applies.`
                }
                onRetry={c.allowed ? () => void runner.retry(c.key) : undefined}
                onDismiss={() => runner.dismiss(c.key)}
              />
            ),
          )}
        </div>
      )}

      {next.length > 0 && target == null && (
        <div className="rr-actions">
          {next.map((t) => (
            <Button key={t} variant={t === "cancelled" ? "quiet" : "default"} disabled={disabled} onClick={() => openForm(t)}>
              {TRANSITION_ACTION[t]}
            </Button>
          ))}
        </div>
      )}

      {target != null && needs != null && (
        <form className="rr-form" onSubmit={submit} aria-labelledby={`${formId}-title`} noValidate>
          <p id={`${formId}-title`} className="rr-form-title">
            {TRANSITION_ACTION[target]} → {taskStatusLabel(target)}
          </p>
          <p className="rr-form-help">{TRANSITION_HELP[target]}</p>

          {revisionChanged && (
            <ChangedBanner title="This task changed while the form was open">
              It is now task rev {task.revision} (the form was opened on rev {formRevision}). Go back and reopen the form to act on
              the current version.
            </ChangedBanner>
          )}

          {needs.confirmation_source && (
            <div className="rr-field">
              <label htmlFor={`${formId}-conf`}>Who confirmed, and how? (required)</label>
              <input
                id={`${formId}-conf`}
                className="rr-input"
                type="text"
                value={confirmation}
                onChange={(e) => {
                  setConfirmation(e.target.value);
                  edited();
                }}
                placeholder="e.g. Signed work order from the contractor"
                aria-invalid={touched && confirmationMissing}
                disabled={st.pending}
              />
              {touched && confirmationMissing && <p className="rr-field-error">Say who confirmed and how.</p>}
            </div>
          )}

          {needs.evidence && (
            <fieldset className="rr-field rr-checklist" aria-invalid={touched && evidenceMissing}>
              <legend>Completion evidence (pick at least one)</legend>
              {view.evidence.length === 0 ? (
                <p className="rr-none">This case has no evidence to attach yet.</p>
              ) : (
                <ul className="rr-check-list">
                  {view.evidence.map((ev) => (
                    <li key={ev.evidence_id}>
                      <label className="rr-check">
                        <input
                          type="checkbox"
                          checked={picked.includes(ev.evidence_id)}
                          onChange={() => togglePicked(ev.evidence_id)}
                          disabled={st.pending}
                        />
                        <span>
                          <span className="rr-check-kind">{evidenceKindLabel(ev.kind)}</span> {ev.source_label}
                          <span className="rr-check-date"> · {formatSourceDate(ev.captured_at ?? ev.effective_at)}</span>
                        </span>
                      </label>
                    </li>
                  ))}
                </ul>
              )}
              {touched && evidenceMissing && <p className="rr-field-error">Pick at least one piece of evidence.</p>}
            </fieldset>
          )}

          <div className="rr-field">
            <label htmlFor={`${formId}-note`}>
              {target === "cancelled" ? "Reason" : "Note"} {needs.note === "required" ? "(required)" : "(optional)"}
            </label>
            <textarea
              id={`${formId}-note`}
              className="rr-input rr-textarea"
              rows={2}
              value={note}
              onChange={(e) => {
                setNote(e.target.value);
                edited();
              }}
              aria-invalid={touched && noteMissing}
              disabled={st.pending}
            />
            {touched && noteMissing && (
              <p className="rr-field-error">{target === "cancelled" ? "Give a reason for cancelling." : "A note is required."}</p>
            )}
          </div>

          {st.error != null && (
            // Retry here resends what the form holds now (an edit has already cleared this error).
            <InlineError
              message={`${TRANSITION_ACTION[target]} failed: ${st.error}`}
              onRetry={revisionChanged ? undefined : () => void send()}
              retrying={st.pending}
              onDismiss={() => key && runner.dismiss(key)}
            />
          )}

          <div className="rr-form-actions">
            <Button
              type="submit"
              variant={target === "cancelled" ? "danger" : "primary"}
              pending={st.pending}
              pendingLabel="Waiting for server…"
              disabled={busy || (runner.anyPending && !st.pending) || revisionChanged}
            >
              {TRANSITION_ACTION[target]}
            </Button>
            <Button variant="quiet" onClick={closeForm} disabled={st.pending}>
              Back
            </Button>
          </div>
        </form>
      )}
    </article>
  );
}
