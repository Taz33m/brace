import { useEffect, useRef, useState } from "react";
import type { FormEvent } from "react";
import type { OwnerCaseView, SupportReceipt } from "../../../docs/recovery-handoffs/shared-contract";
import { RecoveryApiError } from "./client";
import { respondToSupport } from "./support-client";
import type { SupportReply } from "./support-client";
import "./support.css";

const labels: Record<SupportReceipt["status"], string> = {
  received: "Received", under_review: "Under review", responded: "Responded", closed: "Closed",
};
interface Props {
  snapshot: OwnerCaseView;
  busy?: boolean;
  on_updated: () => void;
  on_session_expired: () => void;
}

function RequestCard({ request, household, caseId, revision, busy, on_updated, on_session_expired }: {
  request: SupportReceipt; household: string; caseId: string; revision: number;
} & Omit<Props, "snapshot">) {
  const [status, setStatus] = useState<SupportReply["status"]>(request.status === "received" ? "under_review" : request.status);
  const [message, setMessage] = useState("");
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const [uncertain, setUncertain] = useState(false);
  const flight = useRef<AbortController | null>(null);
  const attempt = useRef<{ content: string; body: SupportReply; key: string } | null>(null);
  const callbacks = useRef({ on_updated, on_session_expired });
  callbacks.current = { on_updated, on_session_expired };
  useEffect(() => () => { flight.current?.abort(); flight.current = null; }, []);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (busy || flight.current || !message.trim()) return;
    const content = JSON.stringify([status, message.trim()]);
    if (!attempt.current || attempt.current.content !== content) attempt.current = {
      content, body: { expected_revision: revision, status, public_status_detail: message.trim() },
      key: crypto.randomUUID(),
    };
    const operation = attempt.current, controller = new AbortController();
    flight.current = controller;
    setSending(true); setError(null); setSaved(false);
    try {
      await respondToSupport(caseId, request.request_id, operation.body, operation.key, controller.signal);
      if (controller.signal.aborted) return;
      setSaved(true); setUncertain(false);
      callbacks.current.on_updated();
    } catch (problem) {
      if (controller.signal.aborted) return;
      if (problem instanceof RecoveryApiError && (problem.status === 401 || problem.status === 403)) {
        callbacks.current.on_session_expired(); return;
      }
      const revisionConflict = problem instanceof RecoveryApiError && problem.code === "revision_conflict";
      if (revisionConflict) { attempt.current = null; callbacks.current.on_updated(); }
      setUncertain(problem instanceof RecoveryApiError && (problem.retryable || problem.status === 0));
      setError(problem instanceof Error ? problem.message : "Could not update this request.");
    } finally {
      if (flight.current === controller) flight.current = null;
      if (!controller.signal.aborted) setSending(false);
    }
  }
  const received = new Date(request.received_at);
  return <article className="brace-support-card">
    <header><div><h3>{household}</h3><p>{request.category === "other" ? "Other support" : `${request.category[0].toUpperCase()}${request.category.slice(1)} support`}
      {!Number.isNaN(received.getTime()) && <> · {received.toLocaleString()}</>}</p></div>
      <span className={`brace-support-status is-${request.status}`}>{labels[request.status]}</span></header>
    <p className="brace-support-description">{request.description}</p>
    <div className="brace-support-current"><strong>Resident currently sees</strong><p>{request.public_status_detail}</p></div>
    <form onSubmit={event => void submit(event)}>
      <fieldset disabled={busy || sending || uncertain}>
        <label>Request status<select value={status} onChange={event => { setStatus(event.target.value as SupportReply["status"]); setSaved(false); }}>
          <option value="under_review">Under review</option><option value="responded" disabled={request.status === "closed"}>Responded</option><option value="closed">Closed</option>
        </select></label>
        <label>Response visible to this household<textarea rows={3} maxLength={1200} required value={message}
          placeholder="Explain the next step, contact, or confirmed arrangement."
          onChange={event => { setMessage(event.target.value); setSaved(false); }} /></label>
      </fieldset>
      {error && <p className="brace-support-error" role="alert">{error}</p>}
      {uncertain && <p className="brace-support-hint">Retry the original response to confirm whether it was saved.</p>}
      {saved && <p className="brace-support-success" role="status">Response saved to this household’s portal.</p>}
      <button type="submit" disabled={busy || sending || saved || !message.trim()}>
        {sending ? "Saving…" : saved ? "Response saved" : uncertain ? "Retry response" : "Save resident response"}
      </button>
    </form>
  </article>;
}

export function SupportInbox({ snapshot, busy = false, on_updated, on_session_expired }: Props) {
  const [showClosed, setShowClosed] = useState(false);
  const open = snapshot.support_requests.filter(request => request.status !== "closed");
  const requests = showClosed ? snapshot.support_requests : open;
  const household = (id: string) => {
    const index = snapshot.household_labels.findIndex(row => row.household_id === id);
    const label = snapshot.household_labels[index]?.unit_label;
    return label || (index >= 0 ? `Household ${index + 1}` : "Household label unavailable");
  };
  return <section className="brace-support" aria-labelledby="brace-support-heading">
    <header><div><p className="brace-support-eyebrow">Resident care</p><h2 id="brace-support-heading">Support inbox</h2>
      <p className="brace-support-hint">Respond to housing, access, and communication requests. Each response is visible to the requesting household.</p></div>
      <span className="brace-support-count">{open.length} open</span></header>
    {snapshot.support_requests.some(request => request.status === "closed") && <label className="brace-support-filter">
      <input type="checkbox" checked={showClosed} onChange={event => setShowClosed(event.target.checked)} />Show closed requests</label>}
    {requests.length === 0 && <p className="brace-support-empty">{snapshot.support_requests.length ? "All support requests are closed." : "No support requests yet."}</p>}
    <div className="brace-support-grid">{requests.map(request => <RequestCard key={`${snapshot.case.case_id}:${request.request_id}`} request={request}
      household={household(request.household_id)} caseId={snapshot.case.case_id} revision={snapshot.case.case_revision}
      busy={busy} on_updated={on_updated} on_session_expired={on_session_expired} />)}</div>
  </section>;
}
