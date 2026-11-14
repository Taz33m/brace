import type { Evidence, OwnerCaseView } from "../../../docs/recovery-handoffs/shared-contract";
import type { RecoverySpatial } from "./spatial";

export interface CaptureSide {
  role: "before" | "after";
  collection: string | null;
  layer: string | null;
  window: string;
  evidence: Evidence | null;
  available: boolean;
  unavailable: string | null;
}

const text = (value: unknown): string | null => typeof value === "string" && value.trim() ? value : null;
function sourceDay(value: unknown): string | null {
  const raw = text(value);
  if (!raw || !/^\d{4}-\d{2}-\d{2}(?:T.*)?$/.test(raw)) return null;
  const day = raw.slice(0, 10), parsed = new Date(`${day}T00:00:00Z`);
  return Number.isFinite(parsed.getTime()) && parsed.toISOString().slice(0, 10) === day ? day : null;
}
export function captureDate(value: unknown): string {
  const day = sourceDay(value);
  return day ? new Date(`${day}T00:00:00Z`).toLocaleDateString("en-US", {
    month: "short", day: "numeric", year: "numeric", timeZone: "UTC",
  }) : "unknown";
}

/** A catalog end date alone never becomes a fabricated one-day capture window. */
export function captureWindow(value: Record<string, unknown>): string {
  const first = sourceDay(value.first_date), last = sourceDay(value.last_date) ?? sourceDay(value.date);
  if (first && last && first > last) return "Capture window needs review";
  if (first && last) return first === last ? `${captureDate(first)} (one-day window)`
    : `${captureDate(first)} – ${captureDate(last)}`;
  if (last) return `Start unknown – ${captureDate(last)}`;
  if (first) return `${captureDate(first)} – end unknown`;
  return "Capture window unknown";
}

export function captureComparison(spatial: RecoverySpatial | null, snapshot: OwnerCaseView | null) {
  if (!spatial || !snapshot || spatial.case_id !== snapshot.case.case_id
    || spatial.analysis_revision !== snapshot.case.analysis_revision) return null;
  const pair = spatial.capture_pairs;
  const side = (role: "before" | "after"): CaptureSide => {
    const raw = pair?.[role];
    const entry = raw && typeof raw === "object" && !Array.isArray(raw) ? raw as Record<string, unknown> : null;
    const collection = text(entry?.collection), evidenceId = text(entry?.evidence_id);
    const sourceId = collection ? `vexcel:collection:${collection}:${snapshot.case.property_ref.id}` : null;
    const matching = entry ? snapshot.evidence.filter(row => row.kind === "vexcel_image"
      && (evidenceId ? row.evidence_id === evidenceId : sourceId !== null && row.source_id === sourceId)) : [];
    const evidence = matching.length === 1 ? matching[0] : null;
    const available = entry?.image_available === true && evidence !== null
      && spatial.image_evidence_ids.includes(evidence.evidence_id);
    let unavailable: string | null = null;
    if (!entry) unavailable = `No eligible ${role}-incident capture is registered for this case.`;
    else if (!evidence) unavailable = "This capture is not linked to a unique source in the current case.";
    else if (!available) unavailable = text(entry.unavailable_reason) ?? "The dated image is not available in this case revision.";
    return { role, collection, layer: text(entry?.layer), window: captureWindow(entry ?? {}), evidence, available, unavailable };
  };
  return { before: side("before"), after: side("after"), limitation: text(pair?.limitation) };
}
