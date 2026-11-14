// Owner-only draft of a resident notice. Nothing leaves the browser until the owner confirms;
// publishing is a two-step command, and the form clears only after the server confirms.
import { useId, useMemo, useState } from "react";
import type { OwnerCaseView } from "../../recovery/contracts";
import { Button, InlineError, SegmentedControl } from "../recovery-ui";
import type { CommandRunner } from "./commands";
import { commandKey, evidenceKindLabel } from "./model";
import "./recovery-tab.css";

export type NoticeComposerProps = {
  view: OwnerCaseView;
  busy: boolean;
  runner: CommandRunner;
};

type Audience = "case" | "households";

const AUDIENCE_OPTIONS = [
  { value: "case", label: "Whole case" },
  { value: "households", label: "Selected households" },
] as const;

function householdName(unit_label: string | null): string {
  return unit_label != null ? `Unit ${unit_label}` : "Unit not confirmed";
}

export function NoticeComposer({ view, busy, runner }: NoticeComposerProps) {
  const id = useId();
  const [title, setTitle] = useState("");
  const [body, setBody] = useState("");
  const [audience, setAudience] = useState<Audience>("case");
  const [households, setHouseholds] = useState<string[]>([]);
  const [sources, setSources] = useState<string[]>([]);
  const [confirming, setConfirming] = useState(false);

  // A draft never follows the owner into another case, even if this component is reused rather than remounted.
  const caseId = view.case.case_id;
  const [draftCase, setDraftCase] = useState(caseId);
  if (draftCase !== caseId) {
    setDraftCase(caseId);
    setTitle("");
    setBody("");
    setAudience("case");
    setHouseholds([]);
    setSources([]);
    setConfirming(false);
  }

  const noticeKey = commandKey.publishNotice(caseId);
  const st = runner.status(noticeKey);

  // Notices cite source ids; one entry per source, labelled from the first evidence item that uses it.
  const sourceOptions = useMemo(() => {
    const seen = new Map<string, string>();
    for (const ev of view.evidence) {
      if (!seen.has(ev.source_id)) seen.set(ev.source_id, `${evidenceKindLabel(ev.kind)}: ${ev.source_label}`);
    }
    return [...seen.entries()].map(([source_id, label]) => ({ source_id, label }));
  }, [view.evidence]);

  // Only choices that still exist in this snapshot are counted or sent.
  const chosenHouseholds = households.filter((h) => view.household_labels.some((x) => x.household_id === h));
  const chosenSources = sources.filter((s) => sourceOptions.some((o) => o.source_id === s));

  const missingText = title.trim() === "" || body.trim() === "";
  const missingAudience = audience === "households" && chosenHouseholds.length === 0;
  const canPublish = !missingText && !missingAudience;

  // Any edit after a failure or during confirmation returns to step one, so Retry never sends stale text.
  const edited = () => {
    if (confirming) setConfirming(false);
    if (st.error != null) runner.dismiss(noticeKey);
  };

  const toggle = (list: string[], v: string) => (list.includes(v) ? list.filter((x) => x !== v) : [...list, v]);

  const clear = () => {
    setTitle("");
    setBody("");
    setAudience("case");
    setHouseholds([]);
    setSources([]);
    setConfirming(false);
  };

  const publish = async () => {
    if (!canPublish) return;
    const ok = await runner.run(noticeKey, {
      type: "publish_notice",
      title: title.trim(),
      body: body.trim(),
      household_ids: audience === "case" ? null : chosenHouseholds,
      source_ids: chosenSources,
    });
    if (ok) clear();
  };

  // Retry resends what the form holds now. An edit has already cleared the error, so this is the text that failed,
  // minus any household or source that is no longer in the snapshot.
  const retry = () => publish();

  const audienceSummary =
    audience === "case"
      ? "every household in this case"
      : view.household_labels
          .filter((h) => chosenHouseholds.includes(h.household_id))
          .map((h) => householdName(h.unit_label))
          .join(", ");

  const locked = st.pending;

  return (
    <div className="rr-composer">
      <p className="rr-composer-title">New notice</p>
      <p className="rr-hint">
        Residents see this in the app after publishing. Nothing is sent by SMS or email.
      </p>
      <p className="rr-hint rr-hint--warn">
        Do not include private finances, valuations, repair costs, or internal model analysis. Residents see exactly what you write.
      </p>

      <div className="rr-field">
        <label htmlFor={`${id}-title`}>Title</label>
        <input
          id={`${id}-title`}
          className="rr-input"
          type="text"
          value={title}
          disabled={locked}
          onChange={(e) => {
            setTitle(e.target.value);
            edited();
          }}
        />
      </div>
      <div className="rr-field">
        <label htmlFor={`${id}-body`}>Message</label>
        <textarea
          id={`${id}-body`}
          className="rr-input rr-textarea"
          rows={4}
          value={body}
          disabled={locked}
          onChange={(e) => {
            setBody(e.target.value);
            edited();
          }}
        />
      </div>

      <div className="rr-field">
        <span className="rr-field-label" id={`${id}-aud`}>
          Audience
        </span>
        <SegmentedControl
          ariaLabel="Notice audience"
          options={AUDIENCE_OPTIONS.map((o) => ({ ...o, disabled: locked }))}
          value={audience}
          onChange={(v) => {
            setAudience(v);
            edited();
          }}
        />
        {audience === "households" &&
          (view.household_labels.length === 0 ? (
            <p className="rr-none">No households are linked to this case yet.</p>
          ) : (
            <ul className="rr-check-list" aria-labelledby={`${id}-aud`}>
              {view.household_labels.map((h) => (
                <li key={h.household_id}>
                  <label className="rr-check">
                    <input
                      type="checkbox"
                      checked={households.includes(h.household_id)}
                      disabled={locked}
                      onChange={() => {
                        setHouseholds((l) => toggle(l, h.household_id));
                        edited();
                      }}
                    />
                    <span>
                      {householdName(h.unit_label)}
                      {h.unit_label == null && <span className="rr-check-date"> · {h.household_id}</span>}
                    </span>
                  </label>
                </li>
              ))}
            </ul>
          ))}
      </div>

      <details className="rr-sources">
        <summary>
          Cite sources (optional){chosenSources.length > 0 ? `: ${chosenSources.length} selected` : ""}
        </summary>
        {sourceOptions.length === 0 ? (
          <p className="rr-none">No evidence sources in this case.</p>
        ) : (
          <ul className="rr-check-list">
            {sourceOptions.map((s) => (
              <li key={s.source_id}>
                <label className="rr-check">
                  <input
                    type="checkbox"
                    checked={sources.includes(s.source_id)}
                    disabled={locked}
                    onChange={() => {
                      setSources((l) => toggle(l, s.source_id));
                      edited();
                    }}
                  />
                  <span>{s.label}</span>
                </label>
              </li>
            ))}
          </ul>
        )}
      </details>

      {st.error != null && (
        <InlineError
          message={st.error}
          onRetry={() => void retry()}
          retrying={st.pending}
          onDismiss={() => runner.dismiss(noticeKey)}
        />
      )}

      {!confirming ? (
        <div className="rr-form-actions">
          <Button variant="default" disabled={!canPublish || busy} onClick={() => setConfirming(true)}>
            Publish to residents
          </Button>
          {!canPublish && (title !== "" || body !== "") && (
            <span className="rr-hint">
              {missingText ? "Add a title and a message." : "Pick at least one household."}
            </span>
          )}
        </div>
      ) : (
        <div className="rr-confirm" role="group" aria-label="Confirm publishing">
          <p className="rr-confirm-text">
            Publish “{title.trim()}” to {audienceSummary}? It appears in residents’ app right away and cannot be unpublished
            here.
          </p>
          <div className="rr-form-actions">
            <Button
              variant="primary"
              pending={st.pending}
              pendingLabel="Publishing…"
              disabled={busy || (runner.anyPending && !st.pending) || !canPublish}
              onClick={() => void publish()}
            >
              Confirm publish
            </Button>
            <Button variant="quiet" disabled={st.pending} onClick={() => setConfirming(false)}>
              Keep editing
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}
