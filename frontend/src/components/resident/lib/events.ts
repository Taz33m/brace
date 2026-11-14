/**
 * Event gate for the resident subscription.
 *
 * Events are replayable and may repeat after a reconnect (contract: "Duplicate event IDs are
 * harmless"). The gate accepts each event ID once, ignores anything at or below the cursor the
 * snapshot already reflects, and tracks the highest cursor seen so a resubscribe resumes there.
 */
import type { CaseEvent } from "../contract";

export const RESIDENT_EVENT_TYPES = new Set([
  "report.updated",
  "support.updated",
  "task.updated",
  "notice.published",
  "session.revoked",
  "case.updated",
]);

export type EventAction = "ignore" | "refresh" | "expire";

export interface EventGate {
  /** Decide what to do with an incoming event. Each event_id is acted on at most once. */
  accept(event: CaseEvent): EventAction;
  /** Highest event cursor seen (from events or snapshots). */
  cursor(): number;
  /** A fresh snapshot reflects everything up to its event_cursor. */
  advance(snapshot_cursor: number): void;
}

export function createEventGate(after: number): EventGate {
  let cursor = after;
  const seen = new Set<number>();
  return {
    accept(event) {
      if (!Number.isFinite(event.event_id)) return "ignore";
      if (seen.has(event.event_id)) return "ignore";
      seen.add(event.event_id);
      if (event.type === "session.revoked") return "expire";
      if (event.event_id <= cursor) return "ignore";
      cursor = event.event_id;
      return RESIDENT_EVENT_TYPES.has(event.type) ? "refresh" : "ignore";
    },
    cursor: () => cursor,
    advance(snapshot_cursor) {
      if (snapshot_cursor > cursor) cursor = snapshot_cursor;
    },
  };
}

/**
 * Snapshot ordering: a slower, older response must never replace a newer one.
 * Returns true when `incoming` should replace `current`.
 */
export function isNewerSnapshot(
  current: { case_revision: number; event_cursor: number } | null,
  incoming: { case_revision: number; event_cursor: number },
): boolean {
  if (!current) return true;
  if (incoming.case_revision !== current.case_revision) return incoming.case_revision > current.case_revision;
  return incoming.event_cursor >= current.event_cursor;
}
