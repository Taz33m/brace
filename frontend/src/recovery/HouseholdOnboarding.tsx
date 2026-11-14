import { useEffect, useRef, useState } from "react";
import type { FormEvent } from "react";
import type { OwnerCaseView, OwnerCommand } from "../../../docs/recovery-handoffs/shared-contract";
import { createRecoveryClient, RecoveryApiError } from "./client";
import type { HouseholdInput, HouseholdReceipt } from "./client";
import "./household-onboarding.css";

const client = createRecoveryClient();
type Attempt = { input: HouseholdInput; key: string };

/** Mount with the case ID as key: private household state never crosses cases. */
export function HouseholdOnboarding({ snapshot, busy, on_command, on_session_expired }: {
  snapshot: OwnerCaseView;
  busy: boolean;
  on_command: (command: OwnerCommand) => Promise<void>;
  on_session_expired: () => void;
}) {
  const [label, setLabel] = useState("");
  const [saving, setSaving] = useState(false);
  const [pendingRetry, setPendingRetry] = useState(false);
  const [created, setCreated] = useState<HouseholdReceipt | null>(null);
  const [inviting, setInviting] = useState<string | null>(null);
  const [inviteRetry, setInviteRetry] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const attempt = useRef<Attempt | null>(null);
  const invitation = useRef<OwnerCommand | null>(null);
  const active = useRef(true);
  const inFlight = useRef(false);
  useEffect(() => { active.current = true; return () => { active.current = false; }; }, []);

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
      expected_revision: Math.max(snapshot.case.case_revision, created?.case_revision ?? 0) }, key: crypto.randomUUID() };
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
      expected_revision: Math.max(snapshot.case.case_revision, created?.case_revision ?? 0) };
    invitation.current = request;
    try {
      await on_command(request);
      if (!active.current) return;
      invitation.current = null; setInviteRetry(null);
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

  const households = [...snapshot.household_labels];
  if (created && !households.some(row => row.household_id === created.household.household_id)) households.push(created.household);
  const disabled = busy || saving || inviting !== null;
  return <section className="brace-households" aria-labelledby="brace-households-title">
    <header><p>Resident access</p><h2 id="brace-households-title">Add a household</h2></header>
    <p>Create a private resident space for this property. An owner-supplied label does not verify a unit or link it to a scan.</p>
    <form onSubmit={event => void add(event)}>
      <label htmlFor="brace-household-label">Household or unit label <span>(optional)</span></label>
      <div className="brace-households-form-row"><input id="brace-household-label" value={label} maxLength={120}
        placeholder="For example, Unit 204" autoComplete="off" disabled={disabled || pendingRetry || inviteRetry !== null}
        onChange={event => setLabel(event.target.value)} />
        <button disabled={disabled || inviteRetry !== null} type="submit">{saving ? "Adding…" : pendingRetry ? "Retry household addition" : "Add household"}</button></div>
    </form>
    {pendingRetry && <p role="status">The result is not confirmed. Retry this same addition to check it without creating a duplicate.</p>}
    {created && <p className="brace-households-success" role="status">Added {created.household.unit_label || "a household"}. Generate its private invitation below.</p>}
    {error && <p className="brace-households-error" role="alert">{error}</p>}
    {households.length > 0 ? <ul>{households.map(row => <li key={row.household_id}>
      <div><strong>{row.unit_label || "Unlabelled household"}</strong><small>{row.household_id}</small></div>
      <button type="button" disabled={disabled || pendingRetry || (inviteRetry !== null && inviteRetry !== row.household_id)}
        onClick={() => void invite(row.household_id)}>{inviting === row.household_id ? "Creating link…"
          : inviteRetry === row.household_id ? "Retry invitation" : "Generate private invitation"}</button>
    </li>)}</ul> : <p>No households have been added to this case yet.</p>}
    <p className="brace-households-note">Share each link only with its intended household. Creating a link does not send a message.</p>
  </section>;
}
