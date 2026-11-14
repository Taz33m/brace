import { useEffect, useRef, useState } from "react";
import type { FormEvent } from "react";
import type { OwnerCaseView, OwnerCommand } from "../../../docs/recovery-handoffs/shared-contract";
import { createRecoveryClient, RecoveryApiError } from "./client";
import type { HouseholdAccessView, HouseholdInput, HouseholdReceipt, RevokeAccessReceipt } from "./client";
import "./household-onboarding.css";

const client = createRecoveryClient();
type Attempt = { input: HouseholdInput; key: string };

/** Mount with the case ID as key: private household state never crosses cases. */
export function HouseholdOnboarding({ snapshot, busy, on_command, on_session_expired, on_access_revoked }: {
  snapshot: OwnerCaseView;
  busy: boolean;
  on_command: (command: OwnerCommand) => Promise<void>;
  on_session_expired: () => void;
  on_access_revoked?: (household_id: string) => void;
}) {
  const [label, setLabel] = useState("");
  const [saving, setSaving] = useState(false);
  const [pendingRetry, setPendingRetry] = useState(false);
  const [created, setCreated] = useState<HouseholdReceipt | null>(null);
  const [inviting, setInviting] = useState<string | null>(null);
  const [inviteRetry, setInviteRetry] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [access, setAccess] = useState<HouseholdAccessView | null>(null);
  const [accessLoading, setAccessLoading] = useState(true);
  const [accessError, setAccessError] = useState<string | null>(null);
  const [accessReload, setAccessReload] = useState(0);
  const [confirmRevoke, setConfirmRevoke] = useState<string | null>(null);
  const [revoking, setRevoking] = useState<string | null>(null);
  const [revokeRetry, setRevokeRetry] = useState<string | null>(null);
  const [revoked, setRevoked] = useState<RevokeAccessReceipt | null>(null);
  const revokeAttempt = useRef<{ household_id: string; input: { expected_revision: number }; key: string } | null>(null);
  const attempt = useRef<Attempt | null>(null);
  const invitation = useRef<OwnerCommand | null>(null);
  const active = useRef(true);
  const inFlight = useRef(false);
  const callbacks = useRef({ on_session_expired, on_access_revoked });
  callbacks.current = { on_session_expired, on_access_revoked };
  useEffect(() => { active.current = true; return () => { active.current = false; }; }, []);
  const requestedRevision = Math.max(snapshot.case.case_revision, created?.case_revision ?? 0, revoked?.case_revision ?? 0);
  const latestRevision = Math.max(requestedRevision, access?.case_revision ?? 0);
  useEffect(() => {
    const abort = new AbortController();
    setAccessLoading(true); setAccessError(null);
    client.get_household_access(snapshot.case.case_id, abort.signal).then(value => {
      if (abort.signal.aborted) return;
      if (value.case_id !== snapshot.case.case_id || value.case_revision < requestedRevision) {
        throw new Error("Access details changed. Refresh them before continuing.");
      }
      setAccess(value);
    }).catch(problem => {
      if (abort.signal.aborted) return;
      setAccessError(problem instanceof Error ? problem.message : "Access details could not be loaded.");
      if (problem instanceof RecoveryApiError && [401, 403].includes(problem.status)) callbacks.current.on_session_expired();
    }).finally(() => { if (!abort.signal.aborted) setAccessLoading(false); });
    return () => abort.abort();
  }, [snapshot.case.case_id, requestedRevision, accessReload]);

  function showError(problem: unknown) {
    setError(problem instanceof Error ? problem.message : "This update could not be completed. Try again.");
    if (problem instanceof RecoveryApiError && [401, 403].includes(problem.status)) on_session_expired();
  }

  async function add(event: FormEvent) {
    event.preventDefault();
    if (busy || inFlight.current) return;
    inFlight.current = true;
    setSaving(true); setError(null);
    // Retain both original revision and key after uncertain transport failures.
    // An SSE revision update must not create another household on retry.
    const request = attempt.current ?? { input: { unit_label: label.trim() || null,
      expected_revision: latestRevision }, key: crypto.randomUUID() };
    attempt.current = request;
    try {
      const receipt = await client.create_household(snapshot.case.case_id, request.input, request.key);
      if (!active.current) return;
      if (receipt.case_id !== snapshot.case.case_id) throw new Error("The response belongs to a different case. Reload before continuing.");
      attempt.current = null;
      setPendingRetry(false); setCreated(receipt); setLabel("");
    } catch (problem) {
      if (!active.current) return;
      // A definite rejection did not commit. Let the next attempt use fresh input.
      if (problem instanceof RecoveryApiError && [400, 401, 403, 404, 409, 422].includes(problem.status)) {
        attempt.current = null; setPendingRetry(false);
      } else setPendingRetry(true);
      showError(problem);
    } finally {
      inFlight.current = false;
      if (active.current) setSaving(false);
    }
  }

  async function invite(householdId: string) {
    if (busy || inFlight.current || (inviteRetry && inviteRetry !== householdId)) return;
    inFlight.current = true;
    setInviting(householdId); setError(null);
    const request = invitation.current ?? { type: "create_invitation" as const, household_id: householdId,
      expected_revision: latestRevision };
    invitation.current = request;
    try {
      await on_command(request);
      if (!active.current) return;
      invitation.current = null; setInviteRetry(null);
      setRevoked(value => value?.household_id === householdId ? null : value);
      setAccessReload(value => value + 1);
    } catch (problem) {
      if (!active.current) return;
      if (problem instanceof RecoveryApiError && [400, 401, 403, 404, 409, 422].includes(problem.status)) {
        invitation.current = null; setInviteRetry(null);
      } else setInviteRetry(householdId);
      showError(problem);
    } finally {
      inFlight.current = false;
      if (active.current) setInviting(null);
    }
  }

  async function revoke(householdId: string) {
    if (busy || inFlight.current || (revokeRetry && revokeRetry !== householdId)) return;
    inFlight.current = true; setRevoking(householdId); setError(null);
    const request = revokeAttempt.current ?? { household_id: householdId,
      input: { expected_revision: latestRevision }, key: crypto.randomUUID() };
    revokeAttempt.current = request;
    try {
      const receipt = await client.revoke_household_access(snapshot.case.case_id, householdId, request.input, request.key);
      if (!active.current) return;
      if (receipt.case_id !== snapshot.case.case_id || receipt.household_id !== householdId) throw new Error("Access response did not match this household. Reload before continuing.");
      revokeAttempt.current = null; setRevokeRetry(null); setConfirmRevoke(null); setRevoked(receipt);
      callbacks.current.on_access_revoked?.(householdId);
      setAccessReload(value => value + 1);
    } catch (problem) {
      if (!active.current) return;
      if (problem instanceof RecoveryApiError && [400, 401, 403, 404, 409, 422].includes(problem.status)) {
        revokeAttempt.current = null; setRevokeRetry(null); setConfirmRevoke(null);
        setAccessReload(value => value + 1);
      } else setRevokeRetry(householdId);
      showError(problem);
    } finally {
      inFlight.current = false;
      if (active.current) setRevoking(null);
    }
  }

  const households = [...snapshot.household_labels];
  if (created && !households.some(row => row.household_id === created.household.household_id)) households.push(created.household);
  const disabled = busy || saving || inviting !== null || revoking !== null;
  const mutationPending = pendingRetry || inviteRetry !== null || revokeRetry !== null;
  const accessReady = !accessLoading && !accessError && access !== null && access.case_revision >= requestedRevision;
  return <section className="brace-households" aria-labelledby="brace-households-title">
    <header className="brace-household-row"><div><p>Resident access</p><h2 id="brace-households-title">Manage household access</h2></div>
      <button className="brace-household-cancel" type="button" disabled={accessLoading || disabled}
        onClick={() => setAccessReload(value => value + 1)}>{accessLoading ? "Checking access…" : "Refresh access"}</button></header>
    <p>Invite residents into their own recovery space. You control when their links and signed-in sessions stop working.</p>
    <form onSubmit={event => void add(event)}>
      <label htmlFor="brace-household-label">Household or unit label <span>(optional)</span></label>
      <div className="brace-households-form-row"><input id="brace-household-label" value={label} maxLength={120}
        placeholder="For example, Unit 204" autoComplete="off" disabled={disabled || mutationPending}
        onChange={event => setLabel(event.target.value)} />
        <button disabled={disabled || inviteRetry !== null || revokeRetry !== null} type="submit">{saving ? "Adding…" : pendingRetry ? "Retry household addition" : "Add household"}</button></div>
    </form>
    {pendingRetry && <p role="status">The result is not confirmed. Retry this same addition to check it without creating a duplicate.</p>}
    {created && <p className="brace-households-success" role="status">Added {created.household.unit_label || "a household"}. Generate its private invitation below.</p>}
    {error && <p className="brace-households-error" role="alert">{error}</p>}
    {accessError && <p className="brace-households-error" role="alert">{accessError} Use Refresh access to try again.</p>}
    {households.length > 0 ? <ul>{households.map(row => {
      const detail = accessReady ? access.households.find(item => item.household_id === row.household_id) : null;
      const signedIn = (detail?.active_session_count ?? 0) > 0;
      const hasLinks = (detail?.active_invitation_count ?? 0) > 0;
      const wasRevoked = detail?.invitations.some(item => item.revoked_at !== null);
      const status = !detail ? "Checking access…" : signedIn ? "Signed in" : hasLinks ? "Invited" : wasRevoked ? "Access revoked" : "Not invited";
      return <li key={row.household_id} className="brace-household-card">
        <div className="brace-household-row"><div><strong>{row.unit_label || "Unlabelled household"}</strong>
          <span className={`brace-household-badge ${signedIn ? "is-active" : wasRevoked && !hasLinks ? "is-revoked" : ""}`}>{status}</span>
          {detail && <small>{detail.active_session_count} signed-in {detail.active_session_count === 1 ? "session" : "sessions"} · {detail.active_invitation_count} active {detail.active_invitation_count === 1 ? "link" : "links"}</small>}
        </div><div className="brace-household-actions">
          <button type="button" disabled={disabled || pendingRetry || revokeRetry !== null || (inviteRetry !== null && inviteRetry !== row.household_id)}
            onClick={() => void invite(row.household_id)}>{inviting === row.household_id ? "Creating link…"
              : inviteRetry === row.household_id ? "Retry invitation" : wasRevoked && !hasLinks && !signedIn ? "Invite again" : "Generate private invitation"}</button>
          {detail && (signedIn || hasLinks || revokeRetry === row.household_id) && <button className="brace-household-revoke" type="button"
            disabled={disabled || pendingRetry || inviteRetry !== null || (revokeRetry !== null && revokeRetry !== row.household_id)}
            onClick={() => setConfirmRevoke(row.household_id)}>Revoke access</button>}
        </div></div>
        {confirmRevoke === row.household_id && <div className="brace-household-confirm" role="group" aria-label={`Revoke access for ${row.unit_label || "this household"}`}>
          <p>Sign out <strong>{row.unit_label || "this household"}</strong> and disable all their existing invitation links? Their reports and requests will be kept.</p>
          {revokeRetry === row.household_id && <p>The result is not confirmed. Retry this same action to check it.</p>}
          <button className="brace-household-revoke" type="button" disabled={disabled} onClick={() => void revoke(row.household_id)}>{revoking === row.household_id ? "Revoking…" : revokeRetry ? "Retry revocation" : "Revoke access now"}</button>
          <button className="brace-household-cancel" type="button" disabled={disabled || revokeRetry !== null} onClick={() => setConfirmRevoke(null)}>Keep access</button>
        </div>}
        {accessReady && revoked?.household_id === row.household_id && !signedIn && !hasLinks && <p className="brace-households-success" role="status">Access revoked. Existing links no longer work. You can invite this household again when ready.</p>}
        {detail && <details className="brace-household-details"><summary>Access history</summary>
          <small>Household {row.household_id}</small>
          {detail.invitations.length ? detail.invitations.map(item => <p key={item.invitation_id}>
            Created {new Date(item.created_at).toLocaleString()} · {item.revoked_at ? `Revoked ${new Date(item.revoked_at).toLocaleString()}` : `Expires ${new Date(item.expires_at).toLocaleString()}`}
          </p>) : <p>No invitations yet.</p>}
        </details>}
      </li>;
    })}</ul> : <p>No households have been added to this case yet.</p>}
    <p className="brace-households-note">Labels do not verify a resident’s unit or link it to a scan. Share each private link only with its intended household.</p>
  </section>;
}
