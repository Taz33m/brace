import { useEffect, useRef, useState } from "react";
import type { FormEvent } from "react";
import type { OwnerCaseView } from "../../../docs/recovery-handoffs/shared-contract";
import { RecoveryApiError } from "./client";
import { createNoticeClient, DraftNoticeController, emptyNoticeState, noticeContentKey, noticeScopeKey } from "./notice-client";
import type { NoticeDraft, NoticeState, PublishNoticeInput } from "./notice-client";
import "./notice.css";

export interface DraftNoticesProps {
  snapshot: OwnerCaseView;
  on_published: () => void;
  on_session_expired: () => void;
  busy?: boolean;
}
interface Edit { title: string; body: string; all: boolean; households: string[] }
const defaults = (draft: NoticeDraft): Edit => ({ title: draft.title, body: draft.body, all: true, households: [] });

export function DraftNotices({ snapshot, on_published, on_session_expired, busy = false }: DraftNoticesProps) {
  const scope = { case_id: snapshot.case.case_id, case_revision: snapshot.case.case_revision, analysis_revision: snapshot.case.analysis_revision };
  const scopeKey = noticeScopeKey(scope);
  const currentScope = useRef(scopeKey);
  currentScope.current = scopeKey;
  const callbacks = useRef({ on_published, on_session_expired });
  callbacks.current = { on_published, on_session_expired };
  const [state, setState] = useState<NoticeState>(emptyNoticeState);
  const [edits, setEdits] = useState<{ case_id: string; rows: Record<string, Edit> }>({ case_id: scope.case_id, rows: {} });
  const [reload, setReload] = useState(0);
  const controller = useRef<DraftNoticeController | null>(null);
  if (!controller.current) controller.current = new DraftNoticeController(createNoticeClient(), setState);

  function sessionError(error: unknown) {
    if (error instanceof RecoveryApiError && (error.status === 401 || error.status === 403)) callbacks.current.on_session_expired();
  }

  useEffect(() => {
    const active = controller.current!;
    void active.load(scope).catch(sessionError);
    return () => active.cancel();
    // Scope identity is explicit so old-case results cannot survive a route/revision change.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scopeKey, reload]);

  const current = state.scope && noticeScopeKey(state.scope) === scopeKey ? state : emptyNoticeState();
  const knownHouseholds = new Set(snapshot.household_labels.map(row => row.household_id));

  function update(draft: NoticeDraft, change: Partial<Edit>) {
    setEdits(previous => ({ case_id: scope.case_id, rows: {
      ...(previous.case_id === scope.case_id ? previous.rows : {}),
      [draft.draft_id]: { ...(previous.case_id === scope.case_id ? previous.rows[draft.draft_id] : undefined) ?? defaults(draft), ...change },
    } }));
  }

  async function publish(event: FormEvent, draft: NoticeDraft, input: PublishNoticeInput) {
    event.preventDefault();
    if (busy || current.publishing_id) return;
    const requestedScope = scopeKey;
    try {
      const result = await controller.current!.publish(draft.draft_id, input);
      if (result && currentScope.current === requestedScope) callbacks.current.on_published();
    } catch (error) {
      if (currentScope.current === requestedScope) sessionError(error);
    }
  }

  return <section className="brace-notices" aria-labelledby="brace-notices-title">
    <header><div><p className="brace-notices-eyebrow">Resident updates</p><h2 id="brace-notices-title">Review an agent draft</h2></div>
      <span className="brace-notices-tag">Owner review required</span></header>
    <p className="brace-notices-intro">Review the wording and recipients, then publish an update to the resident portal. Publishing does not send an email or text.</p>
    {current.status === "loading" && <p className="brace-notices-muted" role="status">Loading drafts for this case…</p>}
    {current.status === "error" && <div className="brace-notices-error" role="alert"><p>{current.error}</p>
      <button type="button" onClick={() => setReload(value => value + 1)}>Reload drafts</button></div>}
    {current.status === "ready" && current.data?.drafts.length === 0 && <p className="brace-notices-muted">No resident update drafts yet. Complete a recovery assessment to create one.</p>}
    {current.status === "ready" && current.data?.drafts.map(draft => {
      const edit = (edits.case_id === scope.case_id ? edits.rows[draft.draft_id] : undefined) ?? defaults(draft);
      const input = { expected_revision: scope.case_revision, title: edit.title, body: edit.body,
        household_ids: edit.all ? null : edit.households };
      const eligible = draft.eligible && draft.base_analysis_revision === scope.analysis_revision;
      const valid = Boolean(edit.title.trim()) && edit.title.trim().length <= 200 && Boolean(edit.body.trim()) && edit.body.trim().length <= 4000
        && (edit.all || (edit.households.length > 0 && edit.households.every(id => knownHouseholds.has(id))));
      const published = valid && current.published[draft.draft_id] === noticeContentKey(input);
      const sending = current.publishing_id === draft.draft_id;
      const disabled = busy || current.publishing_id !== null || !eligible;
      return <form className="brace-notices-draft" key={draft.draft_id} onSubmit={event => void publish(event, draft, input)}>
        <div className="brace-notices-draft-meta"><span>{published ? "Published to resident updates" : eligible ? "Draft — unpublished"
          : draft.base_analysis_revision === null ? "Unlinked draft — read only" : "Earlier assessment — read only"}</span>
          <span>{draft.base_analysis_revision === null ? "Assessment link unavailable" : `Analysis revision ${draft.base_analysis_revision}`}</span></div>
        {!eligible && <p className="brace-notices-stale">{draft.unavailable_reason || "Case evidence changed. Run a new assessment before publishing this draft."}</p>}
        <fieldset disabled={disabled}>
          <label>Update title<input value={edit.title} maxLength={200} readOnly={!eligible} onChange={event => update(draft, { title: event.target.value })} /></label>
          <label>Message to residents<textarea value={edit.body} rows={6} maxLength={4000} readOnly={!eligible} onChange={event => update(draft, { body: event.target.value })} /></label>
          <fieldset className="brace-notices-recipients"><legend>Who should see this update?</legend>
            <label className="brace-notices-choice"><input type="radio" name={`audience-${draft.draft_id}`} checked={edit.all} onChange={() => update(draft, { all: true })} />All households in this case</label>
            <label className="brace-notices-choice"><input type="radio" name={`audience-${draft.draft_id}`} checked={!edit.all} onChange={() => update(draft, { all: false })} />Specific households</label>
            {!edit.all && <div className="brace-notices-households">
              {snapshot.household_labels.length === 0 && <p className="brace-notices-muted">No households have been added to this case.</p>}
              {snapshot.household_labels.map((household, index) => <label className="brace-notices-choice" key={household.household_id}>
                <input type="checkbox" checked={edit.households.includes(household.household_id)} onChange={event => update(draft, {
                  households: event.target.checked ? [...edit.households, household.household_id] : edit.households.filter(id => id !== household.household_id),
                })} />{household.unit_label ? `Unit ${household.unit_label}` : `Household ${index + 1}`}</label>)}
            </div>}
          </fieldset>
        </fieldset>
        <p className="brace-notices-muted">{draft.source_ids.length} source reference{draft.source_ids.length === 1 ? "" : "s"} retained with this update.</p>
        {current.publication_error?.draft_id === draft.draft_id && <p className="brace-notices-error" role="alert">{current.publication_error.message}</p>}
        {published && <p className="brace-notices-success" role="status">Published to resident updates. Edit the message or audience to prepare another update.</p>}
        <button className="brace-notices-publish" type="submit" disabled={disabled || !valid || published}>
          {sending ? "Publishing…" : published ? "Published" : "Publish to resident updates"}
        </button>
      </form>;
    })}
  </section>;
}
