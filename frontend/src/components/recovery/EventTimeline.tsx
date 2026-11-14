// Compact case event log, newest first. Older entries are muted and never animated; the entry at the
// current case revision is marked so nobody mistakes history for the present state, and an assessment
// publication that a later one replaced is labelled superseded.
import { useId, useMemo, useState } from "react";
import type { CaseEvent } from "../../recovery/contracts";
import { EmptyState, StatusMark } from "../recovery-ui";
import { formatTimestamp } from "./format";
import "./recovery-tab.css";

export type EventTimelineProps = { events: CaseEvent[]; case_revision: number; analysis_revision: number };

const COLLAPSED_COUNT = 6;

const KNOWN_TYPES: Record<string, string> = {
  "case.opened": "Case opened",
  "case.updated": "Case updated",
  "evidence.added": "Evidence added",
  "assessment.started": "Assessment started",
  "assessment.drafted": "Assessment drafted",
  "assessment.published": "Assessment published",
  "assessment.stale": "Assessment went stale",
  "assessment.failed": "Assessment failed",
  "observation.reviewed": "Observation reviewed",
  "report.received": "Resident report received",
  "report.updated": "Resident report updated",
  "support.updated": "Support request updated",
  "task.updated": "Task updated",
  "notice.published": "Notice published",
  "invitation.created": "Invitation created",
  "session.revoked": "Resident session revoked",
};

/** "assessment.published" -> "Assessment published"; unknown types are prettified the same way. */
export function humanizeEventType(type: string): string {
  const known = KNOWN_TYPES[type];
  if (known) return known;
  const words = type.replace(/[._\-:/]+/g, " ").replace(/\s+/g, " ").trim().toLowerCase();
  if (words === "") return "Event";
  return words.charAt(0).toUpperCase() + words.slice(1);
}

/** Keeps short ids whole; long ones show their tail, which is the distinctive part. */
function shortId(id: string): string {
  return id.length <= 16 ? id : `…${id.slice(-12)}`;
}

const PUBLISHED = "assessment.published";
export const SUPERSEDED_PUBLICATION_LABEL = "Superseded by a later publication";

/**
 * Newest first by event_id (the persisted, ordered cursor, so "newest" never depends on clocks). Duplicate deliveries of
 * the same event_id are harmless by contract: the first one received is kept and the rest are dropped.
 */
export function orderEvents(events: readonly CaseEvent[]): CaseEvent[] {
  const seen = new Set<number>();
  const unique: CaseEvent[] = [];
  for (const ev of events) {
    if (seen.has(ev.event_id)) continue;
    seen.add(ev.event_id);
    unique.push(ev);
  }
  return unique.sort((a, b) => b.event_id - a.event_id);
}

export function EventTimeline({ events, case_revision, analysis_revision }: EventTimelineProps) {
  const listId = useId();
  const [expanded, setExpanded] = useState(false);

  const ordered = useMemo(() => orderEvents(events), [events]);
  // The newest publication stands; every earlier "assessment.published" event was superseded by a later one.
  const latestPublication = ordered.find((ev) => ev.type === PUBLISHED)?.event_id ?? null;
  const shown = expanded ? ordered : ordered.slice(0, COLLAPSED_COUNT);
  const hidden = ordered.length - shown.length;

  return (
    <section className="rt-timeline" aria-labelledby={`${listId}-title`}>
      <header className="rt-head">
        <h3 id={`${listId}-title`} className="rt-title">
          Case events
        </h3>
        <span className="rt-revs">
          Case rev {case_revision} · Analysis rev {analysis_revision}
        </span>
      </header>

      {ordered.length === 0 ? (
        <EmptyState title="No events yet">Changes to this case will be listed here as the server records them.</EmptyState>
      ) : (
        <>
          <ol id={`${listId}-list`} className="rt-list">
            {shown.map((ev) => {
              const current = ev.case_revision === case_revision;
              const superseded = ev.type === PUBLISHED && latestPublication != null && ev.event_id < latestPublication;
              const classes = ["rt-event", current ? "rt-event--current" : "rt-event--old", superseded && "rt-event--superseded"];
              return (
                <li key={ev.event_id} className={classes.filter(Boolean).join(" ")}>
                  <span className="rt-dot" aria-hidden="true" />
                  <div className="rt-body">
                    <p className="rt-line">
                      <span className="rt-type">{humanizeEventType(ev.type)}</span>
                      {current && <span className="rt-current">Current revision</span>}
                      {superseded && <StatusMark tone="muted" shape="hatched" label={SUPERSEDED_PUBLICATION_LABEL} className="rt-superseded" />}
                    </p>
                    <p className="rt-meta">
                      <time dateTime={ev.at}>{formatTimestamp(ev.at)}</time>
                      <span aria-hidden="true"> · </span>
                      <span>rev {ev.case_revision}</span>
                      {ev.entity_id != null && (
                        <>
                          <span aria-hidden="true"> · </span>
                          <code className="rt-entity" title={ev.entity_id}>
                            {shortId(ev.entity_id)}
                          </code>
                        </>
                      )}
                    </p>
                    {ev.public_summary != null && ev.public_summary.trim() !== "" && (
                      <p className="rt-summary">{ev.public_summary}</p>
                    )}
                  </div>
                </li>
              );
            })}
          </ol>
          {ordered.length > COLLAPSED_COUNT && (
            <button
              type="button"
              className="rt-toggle"
              aria-expanded={expanded}
              aria-controls={`${listId}-list`}
              onClick={() => setExpanded((x) => !x)}
            >
              {expanded ? `Show latest ${COLLAPSED_COUNT}` : `Show all (${ordered.length})`}
            </button>
          )}
          {!expanded && hidden > 0 && <span className="r-sr-only">{hidden} older events hidden.</span>}
        </>
      )}
    </section>
  );
}
