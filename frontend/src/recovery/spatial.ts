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

export type EvidenceAssociation = "source" | "exact_viewpoint" | "same_room" | "same_scan" | "exact_location" | "verified_structure" | "site_overview" | "unassociated";

/** Source identifiers establish view membership; proximity never establishes a unit match. */
export function evidenceAssociation(evidence: Evidence, focus: LocationRef | null): EvidenceAssociation {
  if (!focus) return "source";
  const location = evidence.location;
  if (focus.scan_id && location?.scan_id === focus.scan_id) {
    if (focus.sweep_id && location.sweep_id === focus.sweep_id) return "exact_viewpoint";
    if (focus.room_id && location.room_id === focus.room_id) return "same_room";
    return "same_scan";
  }
  if (focus.structure_id && !focus.scan_id && location?.structure_id === focus.structure_id) {
    if (location.scan_id && !["verified_unit", "verified_space"].includes(location.binding)) return "unassociated";
    return location.scan_id ? "verified_structure" : "exact_location";
  }
  if (location?.location_id === focus.location_id && !focus.scan_id) return "exact_location";
  return evidence.kind === "vexcel_image" ? "site_overview" : "unassociated";
}

export function preferredEvidence(evidence: Evidence[], selectedId: string | null, kinds: Evidence["kind"][],
  imageUrl: (evidence: Evidence) => string | null, focus: LocationRef | null = null): Evidence | null {
  const rows = evidence.filter(row => kinds.includes(row.kind));
  if (focus) {
    const rank: Record<EvidenceAssociation, number> = { exact_viewpoint: 0, exact_location: 0, same_room: 1,
      verified_structure: 1, same_scan: 2, site_overview: 3, source: 4, unassociated: 5 };
    const associated = rows.filter(row => evidenceAssociation(row, focus) !== "unassociated")
      .sort((a, b) => rank[evidenceAssociation(a, focus)] - rank[evidenceAssociation(b, focus)]);
    // An explicit evidence-list selection can still inspect metadata. Map focus
    // passes no selected ID, preferring actual image bytes within this source scope.
    return associated.find(row => row.evidence_id === selectedId)
      ?? associated.find(row => imageUrl(row) !== null) ?? associated[0] ?? null;
  }
  return rows.find(row => row.evidence_id === selectedId) ?? rows.find(row => imageUrl(row) !== null) ?? rows[0] ?? null;
}

export interface InteriorChoice { case_id: string; scan_id: string | null; floor_id: string | null; focus_key: string }
export const spatialFocusKey = (location: LocationRef | null) => JSON.stringify([
  location?.location_id, location?.scan_id, location?.sweep_id, location?.room_id,
]);

export function interiorFloor(scan: SpatialScan, focus: LocationRef | null, choice: InteriorChoice, caseId: string): string | null {
  const floorIds = [...new Set([...(scan.rooms ?? []).map(room => room.floor_id ?? null),
    ...(scan.sweeps ?? []).map(sweep => sweep.floor_id ?? null)])];
  // Manual floor browsing lasts only while the external selection is unchanged.
  if (choice.case_id === caseId && choice.scan_id === scan.id && choice.focus_key === spatialFocusKey(focus)
    && floorIds.includes(choice.floor_id)) return choice.floor_id;
  if (focus?.scan_id === scan.id) {
    const selected = scan.sweeps?.find(row => row.id === focus.sweep_id)
      ?? scan.rooms?.find(row => row.id === focus.room_id);
    if (selected) return selected.floor_id ?? null;
  }
  return floorIds[0] ?? null;
}
