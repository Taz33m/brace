/**
 * Resident-facing wording for every server state. One place, so screens never improvise copy.
 *
 * Rules from the contract that this file enforces:
 * - A proposed task is never shown as booked or scheduled.
 * - "Accepted", "finished" and "checked" are different facts; none of them means it is safe to return.
 * - A schedule appears only when the server supplies `confirmed_schedule`.
 */
import type { ObservationStatus, ReportInput, ResidentTask, SupportInput, SupportReceipt, TaskStatus } from "../contract";

export type Tone = "neutral" | "info" | "ok" | "warn" | "bad";

export interface StatusCopy {
  label: string;
  tone: Tone;
}

export const REPORT_CATEGORIES: { value: ReportInput["category"]; label: string; hint: string }[] = [
  { value: "water", label: "Water or flooding", hint: "Leaks, standing water, wet walls or ceilings" },
  { value: "roof", label: "Roof, ceiling or windows", hint: "Holes, sagging, broken glass, wind damage" },
  { value: "smoke_or_fire", label: "Smoke or fire", hint: "Smoke smell, soot, scorch marks" },
  { value: "power_or_access", label: "Power or getting in", hint: "No power, doors, locks, lifts, stairs" },
  { value: "other", label: "Something else", hint: "Anything that doesn't fit above" },
];

export const SUPPORT_CATEGORIES: { value: SupportInput["category"]; label: string; hint: string }[] = [
  { value: "housing", label: "Somewhere to stay", hint: "You can't stay in your home right now" },
  { value: "access", label: "Getting in or around", hint: "Keys, locks, mobility, blocked routes" },
  { value: "communication", label: "Help understanding updates", hint: "Language, hearing, vision or reading help" },
  { value: "other", label: "Something else", hint: "Tell the property team what you need" },
];

export function categoryLabel(category: ReportInput["category"]): string {
  return REPORT_CATEGORIES.find((c) => c.value === category)?.label ?? "Report";
}

export function supportLabel(category: SupportInput["category"]): string {
  return SUPPORT_CATEGORIES.find((c) => c.value === category)?.label ?? "Support request";
}

const REPORT_STATUS: Record<ObservationStatus, StatusCopy> = {
  reported: { label: "Reported — awaiting review", tone: "neutral" },
  under_review: { label: "Being reviewed", tone: "info" },
  verified: { label: "Confirmed by property team", tone: "ok" },
  dismissed: { label: "Closed by property team", tone: "neutral" },
};

export function reportStatus(status: ObservationStatus): StatusCopy {
  return REPORT_STATUS[status];
}

const SUPPORT_STATUS: Record<SupportReceipt["status"], StatusCopy> = {
  received: { label: "Request received", tone: "neutral" },
  under_review: { label: "Being reviewed", tone: "info" },
  responded: { label: "Property team responded", tone: "ok" },
  closed: { label: "Closed", tone: "neutral" },
};

export function supportStatus(status: SupportReceipt["status"]): StatusCopy {
  return SUPPORT_STATUS[status];
}

const TASK_STATUS: Record<TaskStatus, StatusCopy> = {
  proposed: { label: "Being planned", tone: "neutral" },
  approved: { label: "Approved — not booked yet", tone: "info" },
  accepted: { label: "Accepted by the crew", tone: "info" },
  in_progress: { label: "Work in progress", tone: "info" },
  completion_submitted: { label: "Reported finished — awaiting check", tone: "warn" },
  verified: { label: "Repair checked", tone: "ok" },
  cancelled: { label: "Cancelled", tone: "neutral" },
};

export function taskStatus(task: Pick<ResidentTask, "status" | "confirmed_schedule">): StatusCopy {
  if (task.status === "accepted" && task.confirmed_schedule) return { label: "Scheduled", tone: "info" };
  return TASK_STATUS[task.status];
}

/** Ordered steps for the task timeline. `proposed` is the start; `cancelled` is shown separately. */
export const TASK_STEPS: { status: Exclude<TaskStatus, "cancelled">; label: string }[] = [
  { status: "proposed", label: "Planned" },
  { status: "approved", label: "Approved by property team" },
  { status: "accepted", label: "Crew accepted the job" },
  { status: "in_progress", label: "Work started" },
  { status: "completion_submitted", label: "Crew reported it finished" },
  { status: "verified", label: "Property team checked the repair" },
];

export type StepState = "done" | "current" | "todo";

export function taskStepStates(status: TaskStatus): StepState[] {
  if (status === "cancelled") return TASK_STEPS.map(() => "todo");
  const at = TASK_STEPS.findIndex((s) => s.status === status);
  return TASK_STEPS.map((_, i) => (i < at ? "done" : i === at ? (status === "verified" ? "done" : "current") : "todo"));
}

/** Always shown next to a checked repair: a finished repair is not permission to move back in. */
export const NOT_OCCUPANCY_CLEARANCE =
  "A checked repair doesn't mean it's safe to move back in. Wait for the property team to tell you that directly.";
