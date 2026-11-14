import { Component, Suspense, lazy, useEffect, useRef, useState } from "react";
import type { ComponentType, FormEvent, ReactNode } from "react";
import type {
  CommandResult, Evidence, LocationRef, OwnerCaseView, OwnerCommand, RecoveryCaseSummary, ResidentApi,
} from "../../../docs/recovery-handoffs/shared-contract";
import { createRecoveryClient, RecoveryApiError } from "./client";
import { OwnerCaseController } from "./owner-controller";
import type { OwnerCaseState } from "./owner-controller";
import { recoveryHash, residentHash } from "./routes";
import { SpatialCaseController, currentSpatial, emptySpatial, evidenceImageUrl, permittedEvidenceImage, preferredEvidence } from "./spatial";
import type { RecoverySpatial, SpatialState } from "./spatial";
import "./entry.css";
import { DraftNotices } from "./DraftNotices";

type Client = ReturnType<typeof createRecoveryClient>;
const client = createRecoveryClient();

interface WorkspaceProps {
  cases: RecoveryCaseSummary[];
  snapshot: OwnerCaseView | null;
  state: "loading" | "ready" | "error";
  error: string | null;
  busy: boolean;
  selected_evidence_id: string | null;
  map_slot: ReactNode;
  interior_slot: ReactNode;
  on_open_case: (case_id: string) => void;
  on_back_to_prepare: () => void;
  on_focus: (location: LocationRef) => void;
  on_select_evidence: (evidence_id: string) => void;
  on_command: (command: OwnerCommand) => Promise<void>;
}
interface ResidentProps { api: ResidentApi; on_session_expired: () => void }

const ownerModules = import.meta.glob<{ RecoveryWorkspace: ComponentType<WorkspaceProps> }>("../components/recovery/RecoveryWorkspace.tsx");
const residentModules = import.meta.glob<{ ResidentExperience: ComponentType<ResidentProps> }>("../components/resident/ResidentExperience.tsx");
const ownerLoader = ownerModules["../components/recovery/RecoveryWorkspace.tsx"];
const residentLoader = residentModules["../components/resident/ResidentExperience.tsx"];
const Workspace = ownerLoader ? lazy(async () => ({ default: (await ownerLoader()).RecoveryWorkspace })) : null;
const ResidentExperience = residentLoader ? lazy(async () => ({ default: (await residentLoader()).ResidentExperience })) : null;

const errorMessage = (error: unknown) => error instanceof Error ? error.message : "This request could not be completed. Try again.";
const authError = (error: unknown) => error instanceof RecoveryApiError && (error.status === 401 || error.status === 403);
const blankState: OwnerCaseState = { case_id: null, snapshot: null, state: "loading", error: null, busy: false, connection: "reconnecting" };

class EntryBoundary extends Component<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false };
  static getDerivedStateFromError() { return { failed: true }; }
  render() {
    return this.state.failed
      ? <EntryMessage title="This view could not be opened" message="Reload to try loading the view again." retry={() => window.location.reload()} />
      : this.props.children;
  }
}

function EntryMessage({ title, message, retry }: { title: string; message?: string; retry?: () => void }) {
  return <section className="brace-entry-message" aria-live="polite"><h1>{title}</h1>{message && <p>{message}</p>}
    {retry && <button type="button" onClick={retry}>Try again</button>}</section>;
}

export function OwnerSignIn({ on_signed_in, sign_in = client.owner_session }: {
  on_signed_in: () => void; sign_in?: (secret: string) => Promise<unknown>;
}) {
  const [secret, setSecret] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  async function submit(event: FormEvent) {
    event.preventDefault();
    if (busy || !secret.trim()) return;
    setBusy(true); setError(null);
    try { await sign_in(secret); setSecret(""); on_signed_in(); }
    catch (problem) { setError(errorMessage(problem)); }
    finally { setBusy(false); }
  }
  return <div className="brace-recovery-entry"><section className="brace-entry-message">
    <h1>Owner sign in</h1><p>Enter your owner access secret to open your assigned properties.</p>
    <form onSubmit={submit} className="brace-entry-form"><label htmlFor="brace-owner-secret">Access secret</label>
      <input id="brace-owner-secret" type="password" autoComplete="current-password" value={secret}
        onChange={event => setSecret(event.target.value)} disabled={busy} required />
      {error && <p role="alert">{error}</p>}<button type="submit" disabled={busy || !secret.trim()}>{busy ? "Signing in…" : "Sign in"}</button>
    </form></section></div>;
}

function permittedImage(value: string | null | undefined): string | null {
  return typeof window === "undefined" ? null : permittedEvidenceImage(value, window.location.origin);
}

/** Source-pinned authorized imagery only; no latest-photo or placeholder fallback. */
export function EvidenceSlot({ title, evidence, image_url, location }: {
  title: string; evidence: Evidence | null; image_url?: string | null; location?: LocationRef | null;
}) {
  const url = permittedImage(image_url === undefined ? evidence?.media?.url : image_url);
  const [failed, setFailed] = useState(false);
  useEffect(() => setFailed(false), [url, evidence?.evidence_id]);
  const selectedLocation = evidence?.location ?? (evidence === null ? location : null);
  return <section className="brace-entry-evidence" aria-label={title}><h2>{title}</h2>
    {evidence ? <><p>{evidence.source_label}</p>
      <p>{evidence.captured_at ? `Captured ${evidence.captured_at}` : "Capture date unknown"}</p>
      {url && !failed ? <img src={url} alt={evidence.media?.alt ?? evidence.summary} onError={() => setFailed(true)} />
        : <p className="brace-entry-muted">{failed ? "This evidence image could not be loaded." : "No image is available for this evidence."}</p>}
      <p>{evidence.summary}</p>{evidence.limitations.length > 0 && <ul>{evidence.limitations.map((item, index) => <li key={index}>{item}</li>)}</ul>}
    </> : <p className="brace-entry-muted">No {title.toLowerCase()} is available for this case.</p>}
    {selectedLocation && <p>{selectedLocation.label} · {selectedLocation.binding.replace(/_/g, " ")}</p>}
    {location && evidence && location.location_id !== evidence.location?.location_id
      && <p className="brace-entry-muted">Selected location: {location.label}. Its association with this evidence is unverified.</p>}
  </section>;
}

function SpatialContext({ spatial, evidence }: { spatial: RecoverySpatial | null; evidence: Evidence | null }) {
  if (!spatial) return null;
  const scanId = evidence?.location?.scan_id;
  const scan = spatial.scans.find(item => item.id === scanId);
  const room = scan?.rooms?.find(item => item.id === evidence?.location?.room_id);
  return <aside className="brace-entry-spatial" aria-label="Registered spatial context">
    <h3>Registered spatial context</h3>
    <p>{spatial.structures.length} structures · {spatial.scans.length} scanned spaces</p>
    {scan && <><p>{scan.name ?? "Scanned space"} · {scan.rooms?.length ?? 0} rooms · {scan.sweeps?.length ?? 0} viewpoints</p>
      {room && <p>Referenced room: {room.label || room.type || room.id}</p>}
      <p>These scan coordinates do not establish a resident unit or verified damage.</p></>}
    {typeof spatial.capture_pairs.limitation === "string" && <p>{spatial.capture_pairs.limitation}</p>}
  </aside>;
}

export async function commandForCurrentCase(active: Pick<OwnerCaseController, "state" | "command"> | null,
  caseId: string | null, command: OwnerCommand): Promise<CommandResult> {
  if (!active || !caseId || active.state.case_id !== caseId) {
    throw new Error("The selected case changed. Load it before applying an update.");
  }
  return active.command(command);
}

export function RecoveryEntry({ case_id }: { case_id: string | null }) {
  const [cases, setCases] = useState<RecoveryCaseSummary[]>([]);
  const [listing, setListing] = useState(true);
  const [listError, setListError] = useState<string | null>(null);
  const [needsSignIn, setNeedsSignIn] = useState(false);
  const [reload, setReload] = useState(0);
  const [view, setView] = useState<OwnerCaseState>(blankState);
  const [spatialState, setSpatialState] = useState<SpatialState>(emptySpatial);
  const [selected, setSelected] = useState<string | null>(null);
  const [focused, setFocused] = useState<LocationRef | null>(null);
  const [invitation, setInvitation] = useState<{ case_id: string; url: string; expires: string | null } | null>(null);
  const controller = useRef<OwnerCaseController | null>(null);
  const openId = case_id ?? cases[0]?.case_id ?? null;
  // Route changes can render before effect cleanup. Do not display the previous
  // case snapshot, images or invitation during that intervening frame.
  const currentView = view.case_id === openId ? view : blankState;
  const snapshot = currentView.snapshot?.case.case_id === openId ? currentView.snapshot : null;
  const analysisRevision = snapshot?.case.analysis_revision ?? null;
  const spatial = currentSpatial(spatialState, openId, analysisRevision);

  useEffect(() => {
    let current = true;
    setListing(true); setListError(null);
    client.get_cases().then(result => { if (current) setCases(result.cases); }).catch(error => {
      if (!current) return;
      if (authError(error)) setNeedsSignIn(true); else setListError(errorMessage(error));
    }).finally(() => { if (current) setListing(false); });
    return () => { current = false; };
  }, [reload]);

  useEffect(() => {
    setSelected(null); setFocused(null); setInvitation(null);
    if (!openId || needsSignIn) { setView(blankState); return; }
    let current = true;
    const track = async <T,>(promise: Promise<T>): Promise<T> => {
      try { return await promise; }
      catch (error) { if (current && authError(error)) setNeedsSignIn(true); throw error; }
    };
    const active = new OwnerCaseController({
      get_case: id => track(client.get_case(id)),
      command: (id, command, key) => track(client.command(id, command, key)),
      subscribe_case: (id, args) => client.subscribe_case(id, { ...args, on_connection: state => {
        if (current && state === "expired") setNeedsSignIn(true);
        args.on_connection(state);
      } }),
    }, state => { if (current) setView(state); });
    controller.current = active;
    void active.open(openId);
    return () => { current = false; active.dispose(); if (controller.current === active) controller.current = null; };
  }, [openId, reload, needsSignIn]);

  useEffect(() => {
    if (!snapshot || needsSignIn) { setSpatialState(emptySpatial); return; }
    let current = true;
    const active = new SpatialCaseController({ get_spatial: async (id, signal) => {
      try { return await client.get_spatial(id, signal); }
      catch (error) { if (current && authError(error)) setNeedsSignIn(true); throw error; }
    } }, value => { if (current) setSpatialState(value); });
    void active.load(snapshot.case.case_id, snapshot.case.analysis_revision);
    return () => { current = false; active.dispose(); };
  }, [openId, analysisRevision, reload, needsSignIn]);

  const retry = () => setReload(value => value + 1);
  if (needsSignIn) return <OwnerSignIn on_signed_in={() => { setNeedsSignIn(false); retry(); }} />;

  async function command(value: OwnerCommand): Promise<void> {
    const active = controller.current;
    const receipt = await commandForCurrentCase(active, openId, value);
    if (!active) return;
    if (controller.current !== active) return;
    if (receipt.invitation_token) {
      setInvitation({ case_id: active.state.case_id!, url: `${window.location.origin}${window.location.pathname}${window.location.search}${residentHash(receipt.invitation_token)}`,
        expires: receipt.invitation_expires_at });
    }
  }
  const imageUrl = (evidence: Evidence | null) => evidenceImageUrl(evidence, spatial, openId, analysisRevision, window.location.origin);
  const aerial = preferredEvidence(snapshot?.evidence ?? [], selected, ["vexcel_image"], imageUrl);
  const interior = preferredEvidence(snapshot?.evidence ?? [], selected, ["matterport_view", "resident_photo"], imageUrl);
  const spatialLoading = snapshot && !spatial && spatialState.state !== "error";
  const spatialError = spatialState.case_id === openId && spatialState.analysis_revision === analysisRevision ? spatialState.error : null;
  const props: WorkspaceProps = {
    cases, snapshot, state: listError ? "error" : listing ? "loading" : !openId ? "ready" : currentView.state,
    error: listError ?? currentView.error, busy: currentView.busy, selected_evidence_id: snapshot ? selected : null,
    map_slot: <><EvidenceSlot key={`${openId}:${analysisRevision}:aerial`} title="Aerial evidence" evidence={aerial} image_url={imageUrl(aerial)} location={snapshot ? focused : null} />
      <SpatialContext spatial={spatial} evidence={aerial} /></>,
    interior_slot: <><EvidenceSlot key={`${openId}:${analysisRevision}:interior`} title="Interior evidence" evidence={interior} image_url={imageUrl(interior)} location={snapshot ? focused : null} />
      <SpatialContext spatial={spatial} evidence={interior} /></>,
    on_open_case: id => { window.location.hash = recoveryHash(id); },
    on_back_to_prepare: () => { window.location.hash = "#/"; },
    on_focus: location => {
      setFocused(location);
      const match = snapshot?.evidence.find(evidence => evidence.location?.location_id === location.location_id);
      if (match) setSelected(match.evidence_id);
    },
    on_select_evidence: id => { setSelected(id); setFocused(snapshot?.evidence.find(e => e.evidence_id === id)?.location ?? null); },
    on_command: command,
  };
  return <div className="brace-recovery-entry">
    {invitation && invitation.case_id === openId && <section className="brace-entry-invitation" aria-label="Resident invitation">
      <h2>Resident invitation</h2><p>Share this private link with the intended resident.</p>
      <input aria-label="Private resident invitation link" readOnly value={invitation.url} onFocus={event => event.target.select()} />
      {invitation.expires && <p>Expires {invitation.expires}</p>}<button type="button" onClick={() => setInvitation(null)}>Dismiss link</button>
    </section>}
    {(listError || currentView.error) && <div className="brace-entry-status" role="alert"><span>{listError ?? currentView.error}</span><button type="button" onClick={retry}>Reload case</button></div>}
    {spatialError && <div className="brace-entry-status" role="alert"><span>{spatialError}</span><button type="button" onClick={retry}>Reload evidence</button></div>}
    {spatialLoading && <p className="brace-entry-status" role="status">Loading registered spatial evidence…</p>}
    {currentView.connection === "reconnecting" && snapshot && <p className="brace-entry-status" role="status">Reconnecting to case updates…</p>}
    <EntryBoundary key={openId ?? "cases"}><Suspense fallback={<EntryMessage title="Opening recovery workspace…" />}>
      {Workspace ? <Workspace {...props} /> : <EntryMessage title="Recovery workspace unavailable" message="This view is not available in the current build. Your case data has not been changed." retry={retry} />}
    </Suspense></EntryBoundary>
    {snapshot && <DraftNotices key={snapshot.case.case_id} snapshot={snapshot} busy={currentView.busy}
      on_published={retry} on_session_expired={() => setNeedsSignIn(true)} />}
    {!Workspace && <p className="brace-entry-return"><a href="#/">Back to Prepare</a></p>}
  </div>;
}

/** Promise identity survives StrictMode's effect setup/cleanup/setup sequence. */
export class ResidentBootstrap {
  private token: string | null | undefined;
  private pending: Promise<void> | undefined;

  start(invitation: string | null, transport: Pick<Client, "resident_session" | "resident_api">): Promise<void> {
    if (this.pending && (invitation === null || invitation === this.token)) return this.pending;
    this.token = invitation;
    this.pending = (invitation ? transport.resident_session(invitation) : transport.resident_api.get_home()).then(() => undefined);
    return this.pending;
  }
  forget_token(): void { this.token = null; }
  reset(): void { this.pending = undefined; this.token = undefined; }
}

export function ResidentEntry({ invitation_token, on_invitation_consumed }: {
  invitation_token: string | null; on_invitation_consumed: (invitation: string) => void;
}) {
  const bootstrap = useRef(new ResidentBootstrap());
  const [state, setState] = useState<"loading" | "ready" | "error" | "expired">("loading");
  const [error, setError] = useState<string | null>(null);
  const [retry, setRetry] = useState(0);
  useEffect(() => {
    let current = true;
    setState("loading"); setError(null);
    bootstrap.current.start(invitation_token, client).then(() => {
      if (!current) return;
      setState("ready");
      if (invitation_token) { bootstrap.current.forget_token(); on_invitation_consumed(invitation_token); }
    }).catch(problem => {
      if (!current) return;
      setState(authError(problem) ? "expired" : "error"); setError(errorMessage(problem));
    });
    return () => { current = false; };
  }, [invitation_token, retry, on_invitation_consumed]);

  const expired = () => { bootstrap.current.reset(); setState("expired"); setError("Open a new invitation from your property manager to continue."); };
  return <div className="brace-recovery-entry">
    {state === "loading" && <EntryMessage title="Opening your resident view…" />}
    {state === "expired" && <EntryMessage title="Resident session expired" message="Open a new invitation from your property manager to continue." />}
    {state === "error" && <EntryMessage title="The resident view could not be opened" message={error ?? undefined}
      retry={() => { bootstrap.current.reset(); setRetry(value => value + 1); }} />}
    {state === "ready" && <EntryBoundary><Suspense fallback={<EntryMessage title="Loading resident experience…" />}>
      {ResidentExperience ? <ResidentExperience api={client.resident_api} on_session_expired={expired} />
        : <EntryMessage title="Resident view unavailable" message="This view is not available in the current build. Please check again with your property manager." />}
    </Suspense></EntryBoundary>}
  </div>;
}
