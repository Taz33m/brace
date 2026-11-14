import type { Evidence, LocationRef } from "../../../docs/recovery-handoffs/shared-contract";

export interface SpatialRoom {
  id: string;
  label?: string;
  type?: string;
  floor_id?: string | null;
  area_sqft?: number | null;
  polygon?: number[][] | null;
}
export interface SpatialScan {
  id: string;
  name?: string;
  rooms?: SpatialRoom[];
  sweeps?: { id: string; room_id?: string | null; floor_id?: string | null }[];
  captured_at?: string | null;
  model_created_at?: string | null;
}
export interface RecoverySpatial {
  case_id: string;
  analysis_revision: number;
  locations: LocationRef[];
  structures: { id: string; polygon?: number[][]; footprint_sqft?: number | null; [key: string]: unknown }[];
  scans: SpatialScan[];
  capture_pairs: Record<string, unknown>;
  source_status: Record<string, unknown>;
  limitations: string[];
  image_evidence_ids: string[];
}
export interface SpatialState {
  case_id: string | null;
  analysis_revision: number | null;
  state: "loading" | "ready" | "error";
  data: RecoverySpatial | null;
  error: string | null;
}
export const emptySpatial: SpatialState = { case_id: null, analysis_revision: null, state: "loading", data: null, error: null };

function validateSpatial(value: RecoverySpatial, caseId: string, revision: number): void {
  if (!value || value.case_id !== caseId || value.analysis_revision !== revision) {
    throw new Error("Spatial evidence changed. Reload the case before viewing its images.");
  }
  if (!Array.isArray(value.locations) || !Array.isArray(value.structures) || !Array.isArray(value.scans)
    || !Array.isArray(value.limitations) || !Array.isArray(value.image_evidence_ids)
    || value.image_evidence_ids.some(id => typeof id !== "string")) {
    throw new Error("The spatial evidence response could not be read.");
  }
}

/** A case/revision switch clears images immediately, aborts work and rejects late replies. */
export class SpatialCaseController {
  private generation = 0;
  private abort: AbortController | null = null;
  private disposed = false;
  private value: SpatialState = emptySpatial;

  constructor(private readonly transport: { get_spatial(case_id: string, signal?: AbortSignal): Promise<RecoverySpatial> },
    private readonly changed: (value: SpatialState) => void) {}

  get state(): SpatialState { return this.value; }

  async load(caseId: string, revision: number): Promise<void> {
    this.abort?.abort();
    const abort = new AbortController();
    this.abort = abort;
    this.disposed = false;
    const generation = ++this.generation;
    this.value = { case_id: caseId, analysis_revision: revision, state: "loading", data: null, error: null };
    this.changed(this.value);
    try {
      const result = await this.transport.get_spatial(caseId, abort.signal);
      if (this.disposed || generation !== this.generation || abort.signal.aborted) return;
      validateSpatial(result, caseId, revision);
      this.value = { ...this.value, state: "ready", data: result, error: null };
      this.changed(this.value);
    } catch (error) {
      if (this.disposed || generation !== this.generation || abort.signal.aborted) return;
      this.value = { ...this.value, state: "error", data: null,
        error: error instanceof Error ? error.message : "Spatial evidence could not be loaded." };
      this.changed(this.value);
    }
  }

  dispose(): void {
    this.disposed = true;
    this.generation++;
    this.abort?.abort();
    this.abort = null;
  }
}

export function currentSpatial(state: SpatialState, caseId: string | null, revision: number | null): RecoverySpatial | null {
  const data = state.data;
  return data && state.state === "ready" && data.case_id === caseId && data.analysis_revision === revision ? data : null;
}

export function permittedEvidenceImage(value: string | null | undefined, origin: string): string | null {
  if (!value) return null;
  try {
    const url = new URL(value, origin);
    if (url.origin !== origin || url.username || url.password) return null;
    if (!/^\/api\/recovery\/(?:media\/[^/]+|cases\/[^/]+\/evidence\/[^/]+\/image)$/.test(url.pathname)) return null;
    return `${url.pathname}${url.search}`;
  } catch { return null; }
}

export function evidenceImageUrl(evidence: Evidence | null, spatial: RecoverySpatial | null,
  caseId: string | null, revision: number | null, origin: string): string | null {
  if (!evidence || caseId === null || revision === null) return null;
  if (evidence.kind === "resident_photo") {
    const url = permittedEvidenceImage(evidence.media?.url, origin);
    return url?.startsWith("/api/recovery/media/") ? url : null;
  }
  if (!spatial || spatial.case_id !== caseId || spatial.analysis_revision !== revision
    || !spatial.image_evidence_ids.includes(evidence.evidence_id)
    || !["vexcel_image", "matterport_view"].includes(evidence.kind)) return null;
  return `/api/recovery/cases/${encodeURIComponent(caseId)}/evidence/${encodeURIComponent(evidence.evidence_id)}/image`;
}

export function preferredEvidence(evidence: Evidence[], selectedId: string | null, kinds: Evidence["kind"][],
  imageUrl: (evidence: Evidence) => string | null): Evidence | null {
  const rows = evidence.filter(row => kinds.includes(row.kind));
  return rows.find(row => row.evidence_id === selectedId) ?? rows.find(row => imageUrl(row) !== null) ?? rows[0] ?? null;
}
