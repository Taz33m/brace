// Recovery tab: tasks by status, resident notices, invitations and support requests.
// Every change is a command; this tab never edits the snapshot it is given.
import { useId, useState } from "react";
import type { LocationRef, OwnerCaseView, SupportReceipt } from "../../recovery/contracts";
import { Button, EmptyState, InlineError, StatusMark } from "../recovery-ui";
import type { ToneMark } from "../recovery-ui";
import type { CommandRunner, CommandStatus } from "./commands";
import { formatTimestamp } from "./format";
import { TASK_STATUS_LABEL, TASK_STATUS_ORDER, commandKey, householdUnit, isKnownTaskStatus, labelOr, lookupKnown, taskStatusTone } from "./model";
import { NoticeComposer } from "./NoticeComposer";
import { TaskCard } from "./TaskCard";
import "./recovery-tab.css";

export type RecoveryTabProps = {
  view: OwnerCaseView;
  busy: boolean;
  runner: CommandRunner;
  on_focus: (location: LocationRef) => void;
  on_select_evidence: (evidence_id: string) => void;
};

const SUPPORT_STATUS: Record<SupportReceipt["status"], ToneMark & { label: string }> = {
  received: { tone: "neutral", shape: "hollow", label: "Received" },
  under_review: { tone: "pending", shape: "ring", label: "Under review" },
  responded: { tone: "info", shape: "filled", label: "Responded" },
  closed: { tone: "muted", shape: "filled", label: "Closed" },
};

const SUPPORT_STATUS_LABEL: Record<string, string> = Object.fromEntries(Object.entries(SUPPORT_STATUS).map(([k, v]) => [k, v.label]));

const SUPPORT_CATEGORY: Record<SupportReceipt["category"], string> = {
  housing: "Housing",
  access: "Access",
  communication: "Communication",
  other: "Other",
};

/** What the invitations section says. It never promises that this panel shows the link: the app around it does. */
export const INVITATION_HINT =
  "Creating an invitation asks the server for a one-time resident link. The app around this panel shows that link or QR code to hand to the resident; this panel only confirms that the server created it.";
export const INVITATION_CREATED_NOTE = "Invitation created (server confirmed). The app delivers the link, outside this panel.";

const timeOf = (iso: string) => {
  const t = Date.parse(iso);
  return Number.isNaN(t) ? -Infinity : t;
};

function unitName(view: OwnerCaseView, household_id: string): string {
  const unit = householdUnit(view, household_id);
  return unit != null ? `Unit ${unit}` : "Unit not confirmed";
}

export type InvitationRowProps = {
  household_id: string;
  unit_label: string | null;
  status: CommandStatus;
  /** True once runner.run (or retry) resolved true for this household, i.e. the server confirmed. */
  created: boolean;
  disabled: boolean;
  on_create: () => void;
  on_retry: () => void;
  on_dismiss: () => void;
};

/** One household's invitation control. Shows a note only after the server has confirmed; never a link of its own. */
export function InvitationRow({ household_id, unit_label, status, created, disabled, on_create, on_retry, on_dismiss }: InvitationRowProps) {
  const who = unit_label != null ? `unit ${unit_label}` : `household ${household_id}`;
  return (
    <li className="rr-row">
      <div className="rr-row-main">
        <span className="rr-row-label">{unit_label != null ? `Unit ${unit_label}` : "Unit not confirmed"}</span>
        {unit_label == null && (
          <code className="rr-row-id" title={household_id}>
            {household_id}
          </code>
        )}
        <Button
          variant="default"
          pending={status.pending}
          pendingLabel="Creating…"
          disabled={disabled}
          onClick={on_create}
          aria-label={`Create invitation for ${who}`}
        >
          Create invitation
        </Button>
      </div>
      {created && !status.pending && status.error == null && (
        <p className="rr-invite-note" role="status">
          <StatusMark tone="info" shape="filled" label={INVITATION_CREATED_NOTE} />
        </p>
      )}
      {status.error != null && (
        <InlineError message={`Could not create the invitation for ${who}. ${status.error}`} onRetry={on_retry} retrying={status.pending} onDismiss={on_dismiss} />
      )}
    </li>
  );
}

export function RecoveryTab({ view, busy, runner, on_focus, on_select_evidence }: RecoveryTabProps) {
  const idBase = useId();
  // Invitation keys the server has confirmed. Keys carry the case id, so a confirmation never shows on another case.
  const [created, setCreated] = useState<ReadonlySet<string>>(() => new Set());

  const groups = TASK_STATUS_ORDER.map((status) => ({
    status,
    tasks: view.tasks.filter((t) => t.status === status), // server order kept within a group
  })).filter((g) => g.tasks.length > 0);
  // A status outside the known order still gets a full card (with no actions), rather than vanishing.
  const unknown = view.tasks.filter((t) => !isKnownTaskStatus(t.status));
  const cardProps = { view, busy, runner, on_focus, on_select_evidence };

  const invite = async (household_id: string, mode: "run" | "retry") => {
    const key = commandKey.createInvitation(view.case.case_id, household_id);
    setCreated((s) => {
      if (!s.has(key)) return s;
      const n = new Set(s);
      n.delete(key);
      return n;
    });
    const ok = mode === "run" ? await runner.run(key, { type: "create_invitation", household_id }) : await runner.retry(key);
    // runner.run resolves true only after on_command resolved, i.e. the server confirmed.
    if (ok) setCreated((s) => new Set(s).add(key));
  };

  return (
    <div className="rr-tab">
      {/* ---------- tasks ---------- */}
      <section className="rr-section" aria-labelledby={`${idBase}-tasks`}>
        <header className="rr-section-head">
          <h3 id={`${idBase}-tasks`} className="rr-section-title">
            Recovery tasks
          </h3>
          <span className="rr-count">{view.tasks.length}</span>
        </header>
        <p className="rr-hint">
          Proposed and approved tasks are not bookings. A task counts as accepted only when whoever does the work has confirmed.
        </p>
        {view.tasks.length === 0 ? (
          <EmptyState title="No recovery tasks yet">Task proposals appear here once they are added to the case.</EmptyState>
        ) : (
          <>
            {groups.map((g) => (
              <div key={g.status} className={`rr-group rr-group--${g.status}`}>
                <h4 className="rr-group-head">
                  <StatusMark {...taskStatusTone(g.status)} label={TASK_STATUS_LABEL[g.status]} />
                  <span className="rr-group-count">{g.tasks.length}</span>
                </h4>
                <div className="rr-task-list">
                  {g.tasks.map((t) => (
                    <TaskCard key={t.task_id} task={t} {...cardProps} />
                  ))}
                </div>
              </div>
            ))}
            {unknown.length > 0 && (
              <div className="rr-group rr-group--unrecognised">
                <h4 className="rr-group-head">
                  <StatusMark tone="neutral" shape="hollow" label="Status not recognised" />
                  <span className="rr-group-count">{unknown.length}</span>
                </h4>
                <p className="rr-hint rr-hint--warn">
                  {unknown.length} task{unknown.length === 1 ? " has" : "s have"} a status this screen does not recognise. They are shown as
                  received, with no actions and no confirmed schedule.
                </p>
                <div className="rr-task-list">
                  {unknown.map((t) => (
                    <TaskCard key={t.task_id} task={t} {...cardProps} />
                  ))}
                </div>
              </div>
            )}
          </>
        )}
      </section>

      {/* ---------- notices ---------- */}
      <section className="rr-section" aria-labelledby={`${idBase}-notices`}>
        <header className="rr-section-head">
          <h3 id={`${idBase}-notices`} className="rr-section-title">
            Resident notices
          </h3>
          <span className="rr-count">{view.notices.length} published</span>
        </header>
        {view.notices.length === 0 ? (
          <EmptyState title="No notices published">Residents have not been sent any notices for this case.</EmptyState>
        ) : (
          <ul className="rr-list">
            {view.notices
              .slice()
              .sort((a, b) => timeOf(b.published_at) - timeOf(a.published_at))
              .map((n) => (
                <li key={n.notice_id} className="rr-item">
                  <p className="rr-item-title">{n.title}</p>
                  <p className="rr-item-body">{n.body}</p>
                  <p className="rr-item-meta">
                    Published {formatTimestamp(n.published_at)} by {n.published_by}
                    {n.source_ids.length > 0 && ` · ${n.source_ids.length} source${n.source_ids.length === 1 ? "" : "s"} cited`}
                  </p>
                </li>
              ))}
          </ul>
        )}
        <NoticeComposer view={view} busy={busy} runner={runner} />
      </section>

      {/* ---------- invitations ---------- */}
      <section className="rr-section" aria-labelledby={`${idBase}-invites`}>
        <header className="rr-section-head">
          <h3 id={`${idBase}-invites`} className="rr-section-title">
            Resident invitations
          </h3>
          <span className="rr-count">{view.household_labels.length}</span>
        </header>
        <p className="rr-hint">{INVITATION_HINT}</p>
        {view.household_labels.length === 0 ? (
          <EmptyState title="No households linked">Households appear here once they are linked to this case.</EmptyState>
        ) : (
          <ul className="rr-list rr-list--rows">
            {view.household_labels.map((h) => {
              const key = commandKey.createInvitation(view.case.case_id, h.household_id);
              const st = runner.status(key);
              return (
                <InvitationRow
                  key={h.household_id}
                  household_id={h.household_id}
                  unit_label={h.unit_label}
                  status={st}
                  created={created.has(key)}
                  disabled={busy || (runner.anyPending && !st.pending)}
                  on_create={() => void invite(h.household_id, "run")}
                  on_retry={() => void invite(h.household_id, "retry")}
                  on_dismiss={() => runner.dismiss(key)}
                />
              );
            })}
          </ul>
        )}
      </section>

      {/* ---------- support requests ---------- */}
      <section className="rr-section" aria-labelledby={`${idBase}-support`}>
        <header className="rr-section-head">
          <h3 id={`${idBase}-support`} className="rr-section-title">
            Support requests
          </h3>
          <span className="rr-count">{view.support_requests.length}</span>
        </header>
        <p className="rr-hint">A request is not a booking or a commitment. The status detail is what the resident sees.</p>
        {view.support_requests.length === 0 ? (
          <EmptyState title="No support requests">Residents have not asked for support on this case.</EmptyState>
        ) : (
          <ul className="rr-list">
            {view.support_requests.map((r) => {
              const s = lookupKnown(SUPPORT_STATUS, r.status);
              return (
                <li key={r.request_id} className="rr-item">
                  <div className="rr-item-top">
                    <span className="rr-item-title">
                      {labelOr(SUPPORT_CATEGORY, r.category, "category")} · {unitName(view, r.household_id)}
                    </span>
                    <StatusMark tone={s?.tone ?? "neutral"} shape={s?.shape ?? "hollow"} label={labelOr(SUPPORT_STATUS_LABEL, r.status, "status")} />
                  </div>
                  <p className="rr-item-body">{r.description}</p>
                  <p className="rr-item-detail">
                    <span className="rr-item-detail-label">Resident sees:</span> {r.public_status_detail}
                  </p>
                  <p className="rr-item-meta">Received {formatTimestamp(r.received_at)}</p>
                </li>
              );
            })}
          </ul>
        )}
      </section>
    </div>
  );
}
