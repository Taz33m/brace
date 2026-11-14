// Labels, allowed transitions, selectors and command keys for the owner workspace. Pure, no React.
import type {
  Assessment,
  AssessmentStatus,
  CaseMode,
  Evidence,
  LocationRef,
  Observation,
  ObservationStatus,
  OwnerCaseView,
  RecoveryTask,
  SourceDate,
  TaskStatus,
} from "../../recovery/contracts";
import type { ToneMark } from "../recovery-ui/StatusMark";

/* ---------- labels ---------- */

export const CASE_MODE_LABEL: Record<CaseMode, string> = {
  observed_recovery: "Observed recovery",
  historical_replay: "Historical replay",
  scenario_exercise: "Scenario exercise",
};

export const CASE_MODE_HELP: Record<CaseMode, string> = {
  observed_recovery: "Built from dated observations of this property after the event.",
  historical_replay: "Replays a past event using only what was known at its verified knowledge cutoff.",
  scenario_exercise: "A hypothetical exercise. Reports and assumptions are invented for practice and describe no real damage.",
};

export const OBSERVATION_STATUS_LABEL: Record<ObservationStatus, string> = {
  reported: "Reported",
  under_review: "Under review",
  verified: "Verified",
  dismissed: "Dismissed",
};

export const OBSERVATION_BASIS_LABEL: Record<Observation["basis"], string> = {
  reported: "Resident report",
  observed: "Seen in evidence",
  inferred: "Model suggestion (not verified)",
};

export const TASK_STATUS_LABEL: Record<TaskStatus, string> = {
  proposed: "Proposed, not approved",
  approved: "Approved, not yet accepted",
  accepted: "Accepted",
  in_progress: "In progress",
  completion_submitted: "Completion submitted, awaiting verification",
  verified: "Verified complete",
  cancelled: "Cancelled",
};

export const TASK_STATUS_ORDER: readonly TaskStatus[] = [
  "proposed",
  "approved",
  "accepted",
  "in_progress",
  "completion_submitted",
  "verified",
  "cancelled",
];

export const ASSESSMENT_STATUS_LABEL: Record<AssessmentStatus, string> = {
  running: "Running",
  draft: "Draft, not published",
  published: "Published",
  stale: "Stale: inputs changed",
  failed: "Failed",
};

export const EVIDENCE_KIND_LABEL: Record<Evidence["kind"], string> = {
  costar_record: "CoStar record",
  vexcel_image: "Vexcel aerial",
  matterport_view: "Matterport view",
  resident_photo: "Resident photo",
  inspection: "Inspection",
  cost_source: "Cost source",
  official_notice: "Official notice",
};

export const BINDING_LABEL: Record<LocationRef["binding"], string> = {
  verified_unit: "Verified unit",
  verified_space: "Verified space",
  representative_layout: "Representative layout, not this unit",
  unverified: "Location not verified",
  unmapped: "Not mapped to a space",
};

/* ---------- fallbacks for values this build does not recognise ---------- */
// The server may send a status, kind or binding newer than this screen. Nothing is dropped and nothing reads
// "undefined": an unknown value gets a readable label that says so, and a neutral look that is never "verified".

/** `map[raw]` when `raw` is one of the map's own keys; undefined otherwise (safe for "constructor" and friends). */
export function lookupKnown<V>(map: Readonly<Record<string, V>>, raw: unknown): V | undefined {
  return typeof raw === "string" && Object.prototype.hasOwnProperty.call(map, raw) ? map[raw] : undefined;
}

/** "drone_video" -> "Drone video". Readable text for a raw code; "" when there is nothing readable. */
export function humanizeCode(raw: unknown): string {
  if (typeof raw !== "string") return "";
  const words = raw.replace(/[._\-:/]+/g, " ").replace(/\s+/g, " ").trim().toLowerCase();
  if (words === "") return "";
  const text = words.length > 48 ? `${words.slice(0, 47)}…` : words;
  return text.charAt(0).toUpperCase() + text.slice(1);
}

function unrecognised(raw: unknown, what: string): string {
  const text = humanizeCode(raw);
  return text === "" ? `Unknown ${what}` : `${text} (unrecognised ${what})`;
}

/** A label from `map`, or "<Raw value> (unrecognised <what>)" for a value this screen does not know. */
export function labelOr(map: Readonly<Record<string, string>>, raw: unknown, what: string): string {
  return lookupKnown(map, raw) ?? unrecognised(raw, what);
}

export const observationStatusLabel = (s: string): string => labelOr(OBSERVATION_STATUS_LABEL, s, "status");
export const taskStatusLabel = (s: string): string => labelOr(TASK_STATUS_LABEL, s, "status");
export const assessmentStatusLabel = (s: string): string => labelOr(ASSESSMENT_STATUS_LABEL, s, "status");
export const evidenceKindLabel = (kind: string): string => labelOr(EVIDENCE_KIND_LABEL, kind, "kind");

export const isKnownObservationStatus = (s: string): s is ObservationStatus => lookupKnown(OBSERVATION_STATUS_LABEL, s) !== undefined;
export const isKnownTaskStatus = (s: string): s is TaskStatus => lookupKnown(TASK_STATUS_LABEL, s) !== undefined;

/** Only these two bindings place something in an exact unit or space. Anything else, including unknown values, is unverified. */
export const isVerifiedBinding = (b: string): boolean => b === "verified_unit" || b === "verified_space";

/** The binding label; an unknown binding says so and is treated as unverified, never as an exact place. */
export function bindingLabel(b: string): string {
  const known = lookupKnown(BINDING_LABEL, b);
  if (known) return known;
  const text = humanizeCode(b);
  return text === "" ? "No location binding given, treated as unverified" : `Unrecognised binding “${text}”, treated as unverified`;
}

/* ---------- tones (for StatusMark) ---------- */

/** Used for any status this screen does not recognise: neutral and hollow, never the verified look. */
const UNKNOWN_TONE: ToneMark = { tone: "neutral", shape: "hollow" };

const TASK_TONE: Record<TaskStatus, ToneMark> = {
  proposed: { tone: "muted", shape: "hollow" },
  approved: { tone: "info", shape: "hollow" },
  accepted: { tone: "info", shape: "filled" },
  in_progress: { tone: "pending", shape: "filled" },
  completion_submitted: { tone: "pending", shape: "ring" },
  verified: { tone: "verified", shape: "filled" },
  cancelled: { tone: "muted", shape: "hatched" },
};

export function taskStatusTone(s: TaskStatus): ToneMark {
  return lookupKnown(TASK_TONE, s) ?? UNKNOWN_TONE;
}

const OBSERVATION_TONE: Record<ObservationStatus, ToneMark> = {
  reported: { tone: "neutral", shape: "hollow" },
  under_review: { tone: "pending", shape: "ring" },
  verified: { tone: "verified", shape: "filled" },
  dismissed: { tone: "muted", shape: "hatched" },
};

export function observationStatusTone(s: ObservationStatus): ToneMark {
  return lookupKnown(OBSERVATION_TONE, s) ?? UNKNOWN_TONE;
}

/** Extra: tone for an assessment status. Stale is hatched (no longer holds). */
const ASSESSMENT_TONE: Record<AssessmentStatus, ToneMark> = {
  running: { tone: "pending", shape: "ring" },
  draft: { tone: "neutral", shape: "hollow" },
  published: { tone: "info", shape: "filled" },
  stale: { tone: "pending", shape: "hatched" },
  failed: { tone: "danger", shape: "filled" },
};

export function assessmentStatusTone(s: AssessmentStatus): ToneMark {
  return lookupKnown(ASSESSMENT_TONE, s) ?? UNKNOWN_TONE;
}

/* ---------- transitions ---------- */

export const TASK_NEXT: Record<TaskStatus, TaskStatus[]> = {
  proposed: ["approved", "cancelled"],
  approved: ["accepted", "cancelled"],
  accepted: ["in_progress", "cancelled"],
  in_progress: ["completion_submitted", "cancelled"],
  completion_submitted: ["verified", "cancelled"],
  verified: [],
  cancelled: [],
};

/** Allowed next statuses; none for a status this screen does not recognise. */
export const taskNext = (s: string): readonly TaskStatus[] => lookupKnown(TASK_NEXT, s) ?? [];

export type TaskTransitionNeeds = { note: "required" | "optional"; confirmation_source: boolean; evidence: boolean };

/** What a move to `target` needs before it can be sent. The server still validates. */
export function taskTransitionNeeds(target: TaskStatus): TaskTransitionNeeds {
  return {
    note: target === "verified" || target === "cancelled" ? "required" : "optional",
    confirmation_source: target === "accepted",
    evidence: target === "completion_submitted",
  };
}

export const OBSERVATION_NEXT: Record<ObservationStatus, ObservationStatus[]> = {
  reported: ["under_review", "verified", "dismissed"],
  under_review: ["verified", "dismissed"],
  verified: [],
  dismissed: [],
};

/** Allowed review moves; none for a status this screen does not recognise. */
export const observationNext = (s: string): readonly ObservationStatus[] => lookupKnown(OBSERVATION_NEXT, s) ?? [];

export type ObservationTransitionNeeds = { note: "required" | "optional"; evidence: boolean; min_evidence: number };

/** verified and dismissed need a note; verified also needs at least one evidence id. */
export function observationTransitionNeeds(target: ObservationStatus): ObservationTransitionNeeds {
  const verified = target === "verified";
  return {
    note: verified || target === "dismissed" ? "required" : "optional",
    evidence: verified,
    min_evidence: verified ? 1 : 0,
  };
}

/* ---------- command keys ---------- */
// Every key names the case and the entity it acts on, so a pending or failed command can never surface on, or be
// retried against, another case or another record. Each part is URI-encoded so ids that contain ":" stay unambiguous.

const part = (s: string) => encodeURIComponent(s);

export const commandKey = {
  startAssessment: (case_id: string) => `assessment:start:${part(case_id)}`,
  publishAssessment: (case_id: string, assessment_id: string) => `assessment:publish:${part(case_id)}:${part(assessment_id)}`,
  reviewObservation: (case_id: string, observation_id: string, target: string) =>
    `obs:${part(case_id)}:${part(observation_id)}:${part(target)}`,
  transitionTask: (case_id: string, task_id: string, target: string) => `task:${part(case_id)}:${part(task_id)}:${part(target)}`,
  publishNotice: (case_id: string) => `notice:publish:${part(case_id)}`,
  createInvitation: (case_id: string, household_id: string) => `invite:${part(case_id)}:${part(household_id)}`,
} as const;

/* ---------- selectors ---------- */

export function currentAssessment(view: OwnerCaseView): Assessment | null {
  if (view.current_assessment_id == null) return null;
  return view.assessments.find((a) => a.assessment_id === view.current_assessment_id) ?? null;
}

const timeOf = (iso: string) => {
  const t = Date.parse(iso);
  return Number.isNaN(t) ? -Infinity : t;
};

/** Every assessment except the current one, newest first (by created_at). */
export function assessmentHistory(view: OwnerCaseView): Assessment[] {
  return view.assessments
    .filter((a) => a.assessment_id !== view.current_assessment_id)
    .slice()
    .sort((a, b) => timeOf(b.created_at) - timeOf(a.created_at));
}

/** Extra: a published assessment that is not the current one has been superseded. */
export function isSupersededAssessment(view: OwnerCaseView, a: Assessment): boolean {
  return a.status === "published" && a.assessment_id !== view.current_assessment_id;
}

/** Extra: the status label for an assessment in context ("Superseded" for an old published version). */
export function assessmentStateLabel(view: OwnerCaseView, a: Assessment): string {
  return isSupersededAssessment(view, a) ? "Superseded" : assessmentStatusLabel(a.status);
}

const isPublished = (a: Assessment) => a.status === "published" || (typeof a.published_at === "string" && a.published_at.trim() !== "");

/**
 * Why an assessment's figures may no longer hold, or null when it was built on the case's current inputs.
 * - "published": it was published (published_at set) and its inputs changed since. It must never be called unpublishable.
 * - "draft": a draft built on older inputs; it can't be published until it is re-run.
 * - "stale_run": status "stale", never published (a run that finished after its inputs changed); kept as history.
 * - "outdated": any other status built on older inputs (e.g. a failed or running record).
 */
export type AssessmentStaleness = "published" | "draft" | "stale_run" | "outdated";

export function assessmentStaleness(view: OwnerCaseView, a: Assessment): AssessmentStaleness | null {
  if (a.status !== "stale" && a.base_analysis_revision >= view.case.analysis_revision) return null;
  if (isPublished(a)) return "published";
  if (a.status === "draft") return "draft";
  if (a.status === "stale") return "stale_run";
  return "outdated";
}

const evidenceCache = new WeakMap<OwnerCaseView, Map<string, Evidence>>();

/** evidence_id -> Evidence. Cached per snapshot object. */
export function evidenceMap(view: OwnerCaseView): Map<string, Evidence> {
  let m = evidenceCache.get(view);
  if (!m) {
    m = new Map(view.evidence.map((e) => [e.evidence_id, e]));
    evidenceCache.set(view, m);
  }
  return m;
}

/** All evidence items whose source_id matches (MoneyRange.source_ids etc. refer to source ids). */
export function evidenceForSource(view: OwnerCaseView, source_id: string): Evidence[] {
  return view.evidence.filter((e) => e.source_id === source_id);
}

/** The unit label for a household, or null if unknown. */
export function householdUnit(view: OwnerCaseView, household_id: string): string | null {
  return view.household_labels.find((h) => h.household_id === household_id)?.unit_label ?? null;
}

/** True if the current assessment is stale, or was built on an older analysis revision than the case's. */
export function isCurrentAssessmentStale(view: OwnerCaseView): boolean {
  const a = currentAssessment(view);
  if (!a) return false;
  return a.status === "stale" || a.base_analysis_revision < view.case.analysis_revision;
}

/* ---------- capture dates and the evidence a finding or task is shown with ---------- */

const YEAR = /^(\d{4})$/;
const MONTH = /^(\d{4})-(\d{2})$/;
const DAY = /^(\d{4})-(\d{2})-(\d{2})$/;
const TIMESTAMP = /^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}/;
const HAS_ZONE = /(?:Z|[+-]\d{2}(?::?\d{2})?)$/i;

/**
 * An ordering key for a SourceDate: [UTC milliseconds at the start of its period, precision 0-3], or null when the
 * date is unknown or unreadable. Date-only, month and year values are read as calendar dates (Date.UTC), never in the
 * viewer's timezone; a timestamp with an offset is its exact instant; one without an offset is read as UTC.
 */
export function sourceDateKey(d: SourceDate | null | undefined): [number, number] | null {
  if (typeof d !== "string") return null;
  const s = d.trim();
  let m = DAY.exec(s);
  if (m) {
    const month = Number(m[2]);
    const day = Number(m[3]);
    return month >= 1 && month <= 12 && day >= 1 && day <= 31 ? [Date.UTC(Number(m[1]), month - 1, day), 2] : null;
  }
  m = MONTH.exec(s);
  if (m) {
    const month = Number(m[2]);
    return month >= 1 && month <= 12 ? [Date.UTC(Number(m[1]), month - 1, 1), 1] : null;
  }
  m = YEAR.exec(s);
  if (m) return [Date.UTC(Number(m[1]), 0, 1), 0];
  if (TIMESTAMP.test(s)) {
    const iso = s.replace(" ", "T");
    const t = Date.parse(HAS_ZONE.test(iso) ? iso : `${iso}Z`);
    return Number.isNaN(t) ? null : [t, 3];
  }
  return null;
}

/** True when key `a` is strictly newer than `b`. Unknown dates are older than any known date; a more precise date wins a tie. */
function newer(a: [number, number] | null, b: [number, number] | null): boolean {
  if (a === null) return false;
  if (b === null) return true;
  return a[0] !== b[0] ? a[0] > b[0] : a[1] > b[1];
}

/** The latest-captured item by captured_at. Unknown dates count as oldest; ties keep the earlier item in the list. */
export function latestCaptured<T extends Pick<Evidence, "captured_at">>(items: readonly T[]): T | null {
  let best: T | null = null;
  let bestKey: [number, number] | null = null;
  for (const item of items) {
    const key = sourceDateKey(item.captured_at);
    if (best === null || newer(key, bestKey)) {
      best = item;
      bestKey = key;
    }
  }
  return best;
}

/** True when the evidence carries an image that can be shown as a thumbnail. */
export function hasImage(e: Evidence): boolean {
  const m = e.media;
  return (
    m != null &&
    typeof m.url === "string" &&
    m.url.trim() !== "" &&
    typeof m.mime_type === "string" &&
    m.mime_type.toLowerCase().startsWith("image/")
  );
}

export type FindingEvidence = {
  /** Cited evidence present in this snapshot, in citation order, without duplicates. */
  cited: Evidence[];
  /** How many cited ids are not in this snapshot. */
  missing: number;
  /** The supporting image: the latest-captured cited item that has an image. */
  supporting: Evidence | null;
  /** What clicking the finding selects: the supporting item, else the latest-captured cited item with any media, else the latest-captured cited item. */
  primary: Evidence | null;
};

/** The evidence a finding (observation) is shown with. A post-incident capture wins over an older one. */
export function findingEvidence(view: OwnerCaseView, o: Pick<Observation, "evidence_ids">): FindingEvidence {
  const map = evidenceMap(view);
  const ids = [...new Set(o.evidence_ids)];
  const cited = ids.map((id) => map.get(id)).filter((e): e is Evidence => e != null);
  const supporting = latestCaptured(cited.filter(hasImage));
  const primary = supporting ?? latestCaptured(cited.filter((e) => e.media != null)) ?? latestCaptured(cited);
  return { cited, missing: ids.length - cited.length, supporting, primary };
}

/** What "Show on site" for a task focuses and selects: its location, and its first cited evidence that is in this snapshot. */
export function taskSiteTarget(
  view: OwnerCaseView,
  task: Pick<RecoveryTask, "location" | "evidence_ids">,
): { location: LocationRef | null; evidence_id: string | null } {
  const map = evidenceMap(view);
  return { location: task.location ?? null, evidence_id: task.evidence_ids.find((id) => map.has(id)) ?? null };
}
