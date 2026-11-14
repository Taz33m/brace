import "./condition-value.css";
import { useId, useState } from "react";
import { Button, EmptyState, EvidenceBadge, InlineError, StatusMark } from "../recovery-ui";
import type { Evidence, LocationRef, Observation, ObservationStatus, OwnerCaseView, ResidentReport } from "../../recovery/contracts";
import type { CommandRunner } from "./commands";
import { formatSourceDate, formatTimestamp } from "./format";
import {
  OBSERVATION_BASIS_LABEL,
  bindingLabel,
  commandKey,
  evidenceKindLabel,
  findingEvidence,
  householdUnit,
  isKnownObservationStatus,
  isVerifiedBinding,
  labelOr,
  observationNext,
  observationStatusLabel,
  observationStatusTone,
  observationTransitionNeeds,
} from "./model";

export type ConditionTabProps = {
  view: OwnerCaseView;
  busy: boolean;
  runner: CommandRunner;
  selected_evidence_id: string | null;
  on_focus: (location: LocationRef) => void;
  on_select_evidence: (evidence_id: string) => void;
};

/** Needs attention first. */
const GROUPS: readonly { status: ObservationStatus; title: string }[] = [
  { status: "reported", title: "Reported, not yet reviewed" },
  { status: "under_review", title: "Under review" },
  { status: "verified", title: "Verified" },
  { status: "dismissed", title: "Dismissed" },
];

/** Every review move this tab can send, so a failure or a wait for any of them stays visible. */
const REVIEW_TARGETS: readonly ObservationStatus[] = ["under_review", "verified", "dismissed", "reported"];

const REVIEW_ACTION_LABEL: Record<ObservationStatus, string> = {
  reported: "Mark reported",
  under_review: "Request verification",
  verified: "Verify",
  dismissed: "Dismiss",
};

const REPORT_CATEGORY_LABEL: Record<ResidentReport["category"], string> = {
  water: "Water",
  roof: "Roof",
  smoke_or_fire: "Smoke or fire",
  power_or_access: "Power or access",
  other: "Other",
};

function locationText(loc: LocationRef): string {
  const unit = loc.unit_label && !loc.label.includes(loc.unit_label) ? `Unit ${loc.unit_label}, ` : "";
  return `${unit}${loc.label}`;
}

function BindingTag({ binding }: { binding: LocationRef["binding"] }) {
  const cls = isVerifiedBinding(binding)
    ? "rc-binding"
    : binding === "representative_layout"
      ? "rc-binding rc-binding--layout"
      : "rc-binding rc-binding--unknown";
  return <span className={cls}>{bindingLabel(binding)}</span>;
}

/** The structure a location belongs to, shown beside the location and its room association when the server gives one. */
function StructureRow({ loc }: { loc: LocationRef | null }) {
  const id = loc && typeof loc.structure_id === "string" ? loc.structure_id.trim() : "";
  if (id === "") return null;
  return (
    <div>
      <dt>Structure</dt>
      <dd>
        <code className="rc-structure" title="Structure id from the case record">
          {id}
        </code>
      </dd>
    </div>
  );
}

export function ConditionTab({ view, busy, runner, selected_evidence_id, on_focus, on_select_evidence }: ConditionTabProps) {
  const locked = busy || runner.anyPending;
  const uid = useId();

  // Spaces we can't place: any location not bound to a verified unit or space (unmapped, unverified, representative-only,
  // or a binding this screen does not recognise) anywhere in the case, plus reports with no location.
  const unknownSpaces = new Map<string, LocationRef>();
  const collect = (loc: LocationRef | null) => {
    if (loc && !isVerifiedBinding(loc.binding) && !unknownSpaces.has(loc.location_id)) unknownSpaces.set(loc.location_id, loc);
  };
  view.observations.forEach((o) => collect(o.location));
  view.reports.forEach((r) => collect(r.location));
  view.evidence.forEach((e) => collect(e.location));
  const unplacedReports = view.reports.filter((r) => r.location == null);

  // A status this screen does not recognise is still listed, in its own group, never dropped.
  const unrecognised = view.observations.filter((o) => !isKnownObservationStatus(o.status));
  const cardProps = { view, locked, runner, selected_evidence_id, on_focus, on_select_evidence };

  return (
    <div className="rc-tab">
      <section className="rc-section" aria-labelledby={`${uid}-obs`}>
        <h3 id={`${uid}-obs`} className="rc-h">
          Observations
          <span className="rc-h-count">{view.observations.length}</span>
        </h3>
        {view.observations.length === 0 ? (
          <EmptyState title="No observations yet">
            Observations appear here once evidence or resident reports have been reviewed for this property.
          </EmptyState>
        ) : (
          <>
            {GROUPS.map((g) => {
              const items = view.observations.filter((o) => o.status === g.status);
              if (items.length === 0) return null;
              return (
                <div key={g.status} className={`rc-group rc-group--${g.status}`}>
                  <h4 className="rc-group-h">
                    {g.title} <span className="rc-group-count">({items.length})</span>
                  </h4>
                  <ul className="rc-obs-list">
                    {items.map((o) => (
                      <ObservationCard key={o.observation_id} o={o} {...cardProps} />
                    ))}
                  </ul>
                </div>
              );
            })}
            {unrecognised.length > 0 && (
              <div className="rc-group rc-group--other">
                <h4 className="rc-group-h">
                  Status not recognised <span className="rc-group-count">({unrecognised.length})</span>
                </h4>
                <p className="rc-review-hint">
                  The server sent a status this screen does not know. These are listed as received, without review actions.
                </p>
                <ul className="rc-obs-list">
                  {unrecognised.map((o) => (
                    <ObservationCard key={o.observation_id} o={o} {...cardProps} />
                  ))}
                </ul>
              </div>
            )}
          </>
        )}
      </section>

      {(unknownSpaces.size > 0 || unplacedReports.length > 0) && (
        <section className="rc-unknown" aria-labelledby={`${uid}-unknown`}>
          <h3 id={`${uid}-unknown`} className="rc-unknown-h">
            Unknown or unscanned spaces
          </h3>
          <p className="rc-unknown-lede">Condition in these places is not established by a scan of this property.</p>
          <ul className="rc-unknown-list">
            {[...unknownSpaces.values()].map((loc) => (
              <li key={loc.location_id}>
                <span className="rc-unknown-name">{locationText(loc)}</span> <BindingTag binding={loc.binding} />
              </li>
            ))}
            {unplacedReports.map((r) => (
              <li key={r.report_id}>
                <span className="rc-unknown-name">
                  {r.location_description?.trim() ? `"${r.location_description.trim()}"` : "No location given"}
                </span>{" "}
                <span className="rc-binding rc-binding--unknown">
                  {labelOr(REPORT_CATEGORY_LABEL, r.category, "category")} report
                  {r.location_description?.trim() ? ", described by resident, not mapped" : ""}
                </span>
              </li>
            ))}
          </ul>
        </section>
      )}

      <section className="rc-section" aria-labelledby={`${uid}-reports`}>
        <h3 id={`${uid}-reports`} className="rc-h">
          Resident reports
          <span className="rc-h-count">{view.reports.length}</span>
        </h3>
        {view.reports.length === 0 ? (
          <p className="rc-none">No resident reports have been received.</p>
        ) : (
          <ul className="rc-report-list">
            {view.reports.map((r) => (
              <ReportCard key={r.report_id} view={view} r={r} />
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}

/* ---------- observation ---------- */

type ObservationCardProps = {
  view: OwnerCaseView;
  o: Observation;
  locked: boolean;
  runner: CommandRunner;
  selected_evidence_id: string | null;
  on_focus: (location: LocationRef) => void;
  on_select_evidence: (evidence_id: string) => void;
};

function ObservationCard({ view, o, locked, runner, selected_evidence_id, on_focus, on_select_evidence }: ObservationCardProps) {
  // The supporting image is the latest-captured cited evidence with an image (the post-incident capture, not an older one),
  // and a click on the finding selects that same evidence.
  const { cited, missing, supporting, primary } = findingEvidence(view, o);
  const selected = selected_evidence_id != null && o.evidence_ids.includes(selected_evidence_id);
  const inferred = o.basis === "inferred";
  const mark = observationStatusTone(o.status);
  const basisLabel =
    inferred && o.status === "verified" ? "Model suggestion, since verified by a reviewer" : labelOr(OBSERVATION_BASIS_LABEL, o.basis, "basis");

  const selectObservation = () => {
    if (o.location) on_focus(o.location);
    if (primary) on_select_evidence(primary.evidence_id);
  };
  const selectEvidence = (e: Evidence) => {
    const loc = e.location ?? o.location;
    if (loc) on_focus(loc);
    on_select_evidence(e.evidence_id);
  };

  const classes = ["rc-obs", `rc-obs--${o.status}`, inferred && "rc-obs--inferred", selected && "is-selected"].filter(Boolean).join(" ");
  const media = supporting?.media ?? null;
  const body = (
    <>
      <span className="rc-obs-text">
        <span className="rc-obs-title">{o.title}</span>
        <span className="rc-obs-desc">{o.description}</span>
      </span>
      {media && (
        <span className="rc-obs-figure">
          <img className="rc-obs-img" src={media.url} alt={media.alt} loading="lazy" />
        </span>
      )}
    </>
  );

  return (
    <li className={classes}>
      <div className="rc-obs-marks">
        <StatusMark {...mark} label={observationStatusLabel(o.status)} />
        <span className={inferred ? "rc-basis rc-basis--inferred" : "rc-basis"}>{basisLabel}</span>
      </div>

      {primary || o.location ? (
        <button
          type="button"
          className="rc-obs-select"
          aria-pressed={selected}
          title={primary ? "Show this finding's location and its supporting evidence" : "Show this finding's location"}
          onClick={selectObservation}
        >
          {body}
        </button>
      ) : (
        // Nothing to show: no location and no cited evidence in this snapshot, so no button that does nothing.
        <div className="rc-obs-select rc-obs-select--static">{body}</div>
      )}

      <dl className="rc-meta">
        <div>
          <dt>Location</dt>
          <dd>
            {o.location ? (
              <>
                {locationText(o.location)} <BindingTag binding={o.location.binding} />
              </>
            ) : (
              <span className="rc-binding rc-binding--unknown">No location</span>
            )}
          </dd>
        </div>
        <StructureRow loc={o.location} />
        <div>
          <dt>Captured</dt>
          <dd>{primary ? formatSourceDate(primary.captured_at) : "No cited evidence"}</dd>
        </div>
        <div>
          <dt>Observed</dt>
          <dd>{formatSourceDate(o.observed_at)}</dd>
        </div>
        <div>
          <dt>Updated</dt>
          <dd>{formatTimestamp(o.updated_at)}</dd>
        </div>
      </dl>

      {cited.length > 0 && (
        <div className="rc-evidence" role="group" aria-label={`Evidence for ${o.title}`}>
          {cited.map((e) => (
            <EvidenceBadge
              key={e.evidence_id}
              kindLabel={evidenceKindLabel(e.kind)}
              label={e.source_label}
              date={formatSourceDate(e.captured_at)}
              selected={e.evidence_id === selected_evidence_id}
              title={e.summary}
              onClick={() => selectEvidence(e)}
            />
          ))}
        </div>
      )}
      {missing > 0 && <p className="rc-note-line">{missing} cited evidence item(s) are not available in this view.</p>}

      {(o.verification_note || o.verified_by) && (
        <p className="rc-verification">
          {o.verification_note && <span>“{o.verification_note}”</span>}
          {o.verified_by && <span className="rc-verified-by"> Reviewed by {o.verified_by}</span>}
        </p>
      )}

      <ReviewControls case_id={view.case.case_id} o={o} locked={locked} runner={runner} />
    </li>
  );
}

/* ---------- review controls ---------- */

function ReviewControls({ case_id, o, locked, runner }: { case_id: string; o: Observation; locked: boolean; runner: CommandRunner }) {
  const targets = observationNext(o.status);
  const [draftTarget, setDraft] = useState<ObservationStatus | null>(null);
  const [note, setNote] = useState("");
  const noteId = useId();
  const hintId = useId();
  // A draft for a move the server no longer allows (the status changed underneath it) is dropped.
  const draft = draftTarget != null && targets.includes(draftTarget) ? draftTarget : null;

  const keyFor = (t: ObservationStatus) => commandKey.reviewObservation(case_id, o.observation_id, t);
  const states = REVIEW_TARGETS.map((t) => ({ target: t, key: keyFor(t), allowed: targets.includes(t), ...runner.status(keyFor(t)) }));
  const statuses = states.filter((s) => s.allowed);
  const anyHerePending = states.some((s) => s.pending);
  const noEvidence = o.evidence_ids.length < observationTransitionNeeds("verified").min_evidence;

  const draftNeeds = draft ? observationTransitionNeeds(draft) : null;
  const draftStatus = draft ? states.find((s) => s.target === draft) : undefined;
  const noteMissing = draftNeeds?.note === "required" && note.trim() === "";

  const send = async (target: ObservationStatus, text: string) => {
    const ok = await runner.run(keyFor(target), {
      type: "review_observation",
      observation_id: o.observation_id,
      status: target,
      note: text,
      evidence_ids: target === "verified" ? o.evidence_ids : [],
    });
    // Close the form only once the server has confirmed. The new status arrives in the next snapshot.
    if (ok) {
      setDraft(null);
      setNote("");
    }
  };

  const onAction = (target: ObservationStatus) => {
    const needs = observationTransitionNeeds(target);
    if (needs.note === "required") {
      setDraft(target);
      return;
    }
    void send(target, "");
  };

  // Any edit after a failure clears it, so Retry can never resend text the owner has since changed.
  const onNoteChange = (value: string) => {
    setNote(value);
    if (draftStatus?.error != null) runner.dismiss(draftStatus.key);
  };

  const cancelDraft = () => {
    if (draftStatus?.error != null) runner.dismiss(draftStatus.key);
    setDraft(null);
    setNote("");
  };

  const problems = states.filter((s) => s.error != null);
  const waitingElsewhere = states.filter((s) => s.pending && !s.allowed);
  if (targets.length === 0 && problems.length === 0 && waitingElsewhere.length === 0) return null;

  return (
    <div className="rc-review">
      {draft == null && statuses.length > 0 && (
        <div className="rc-review-actions">
          {statuses.map((s) => {
            const verifyBlocked = s.target === "verified" && noEvidence;
            return (
              <Button
                key={s.target}
                variant={s.target === "dismissed" ? "quiet" : "default"}
                onClick={() => onAction(s.target)}
                disabled={locked || anyHerePending || verifyBlocked}
                pending={s.pending}
                pendingLabel="Sending…"
              >
                {REVIEW_ACTION_LABEL[s.target]}
              </Button>
            );
          })}
        </div>
      )}
      {draft == null && targets.includes("verified") && noEvidence && (
        <p className="rc-review-hint">Verify is unavailable: this observation cites no evidence. Attach evidence before verifying.</p>
      )}

      {draft != null && draftNeeds && (
        <form
          className="rc-review-form"
          onSubmit={(e) => {
            e.preventDefault();
            if (!noteMissing) void send(draft, note.trim());
          }}
        >
          <label htmlFor={noteId} className="rc-review-label">
            {draft === "verified" ? "Verification note" : "Reason for dismissing"} <span className="rc-required">(required)</span>
          </label>
          <textarea
            id={noteId}
            className="rc-review-note"
            rows={2}
            value={note}
            onChange={(e) => onNoteChange(e.target.value)}
            aria-describedby={hintId}
            disabled={draftStatus?.pending}
          />
          <p id={hintId} className="rc-review-hint">
            {draft === "verified"
              ? `Cites ${o.evidence_ids.length} evidence item${o.evidence_ids.length === 1 ? "" : "s"}. The status changes only after the server confirms.`
              : "The observation stays in history as dismissed. The status changes only after the server confirms."}
          </p>
          <div className="rc-review-actions">
            <Button
              type="submit"
              variant="primary"
              disabled={locked || noteMissing || (draft === "verified" && noEvidence)}
              pending={draftStatus?.pending}
              pendingLabel="Sending…"
            >
              {draft === "verified" ? "Verify" : "Dismiss"}
            </Button>
            <Button variant="quiet" disabled={draftStatus?.pending} onClick={cancelDraft}>
              Cancel
            </Button>
          </div>
        </form>
      )}

      {waitingElsewhere.map((s) => (
        <p key={s.key} className="rc-review-hint" role="status">
          {REVIEW_ACTION_LABEL[s.target]}: sent, waiting for the server. The status changes only after it confirms.
        </p>
      ))}

      {problems.map((s) => {
        // Inside the open form, Retry resends what the form holds now; otherwise it resends the command that failed.
        const inForm = draft != null && s.target === draft;
        const retry = !s.allowed
          ? undefined
          : inForm
            ? () => {
                if (!noteMissing) void send(s.target, note.trim());
              }
            : () => void runner.retry(s.key);
        const message = s.allowed
          ? `${REVIEW_ACTION_LABEL[s.target]} failed. ${s.error}`
          : `${REVIEW_ACTION_LABEL[s.target]} failed. ${s.error} This observation is now “${observationStatusLabel(o.status)}”, so this action no longer applies.`;
        return <InlineError key={s.key} message={message} onRetry={retry} retrying={s.pending} onDismiss={() => runner.dismiss(s.key)} />;
      })}
    </div>
  );
}

/* ---------- resident report ---------- */

function ReportCard({ view, r }: { view: OwnerCaseView; r: ResidentReport }) {
  const mark = observationStatusTone(r.status);
  const unit = householdUnit(view, r.household_id);
  const described = r.location_description?.trim() ?? "";
  return (
    <li className="rc-report">
      <div className="rc-report-head">
        <span className="rc-report-cat">{labelOr(REPORT_CATEGORY_LABEL, r.category, "category")}</span>
        <StatusMark {...mark} label={observationStatusLabel(r.status)} />
      </div>
      <p className="rc-report-text">{r.text}</p>
      <dl className="rc-meta">
        <div>
          <dt>From</dt>
          <dd>{unit ? `Household in unit ${unit}` : "Household (unit not confirmed)"}</dd>
        </div>
        <div>
          <dt>Location</dt>
          <dd>
            {r.location ? (
              <>
                {locationText(r.location)} <BindingTag binding={r.location.binding} />
              </>
            ) : described ? (
              <>
                “{described}” <span className="rc-binding rc-binding--unknown">Location described by resident, not mapped</span>
              </>
            ) : (
              <span className="rc-binding rc-binding--unknown">No location given</span>
            )}
          </dd>
        </div>
        <StructureRow loc={r.location} />
        <div>
          <dt>Seen by resident</dt>
          <dd>{formatSourceDate(r.observed_at)}</dd>
        </div>
        <div>
          <dt>Received</dt>
          <dd>{formatTimestamp(r.received_at)}</dd>
        </div>
      </dl>
      {r.media.length > 0 && (
        <div className="rc-thumbs">
          {r.media.map((m) =>
            typeof m.mime_type === "string" && m.mime_type.startsWith("image/") ? (
              <img key={m.media_id} className="rc-thumb" src={m.url} alt={m.alt} loading="lazy" />
            ) : (
              <span key={m.media_id} className="rc-thumb rc-thumb--file">
                {m.alt || "Attachment"}
              </span>
            ),
          )}
        </div>
      )}
      {typeof r.public_status_detail === "string" && r.public_status_detail.trim() !== "" && (
        <p className="rc-public">
          <span className="rc-public-label">Resident sees:</span> {r.public_status_detail}
        </p>
      )}
    </li>
  );
}
