// Dated aerial comparison: a simple wipe between two Vexcel captures, with explicit missing states.
import { useId, useState } from "react";
import type { Evidence, MediaRef, SourceDate } from "../../recovery/contracts";
import { EmptyState, EvidenceBadge } from "../recovery-ui";
import { compareSourceDatesChronological, compareSourceDatesCoarse, formatSourceDate } from "./format";
import { evidenceKindLabel, hasImage } from "./model";

/** The capture's image, or null when it has none that can be shown (no media, or media that is not an image). */
const imageOf = (e: Evidence | null): MediaRef | null => (e != null && hasImage(e) ? e.media : null);

/** The user's explicit picks; null means "use the default for that side". */
export type AerialPairChoice = { before: string | null; after: string | null };
export const NO_AERIAL_CHOICE: AerialPairChoice = { before: null, after: null };

export const AERIAL_CAVEAT =
  "Captures can differ in angle, footprint and season. A visible difference is a candidate observation, not a determined cause.";
export const IMAGE_UNAVAILABLE = "Image not available for this capture";

/** vexcel_image evidence in capture order (chronological at each date's own precision, unknown dates last). */
export function aerialCaptures(evidence: Evidence[]): Evidence[] {
  return evidence.filter((e) => e.kind === "vexcel_image").sort((a, b) => compareSourceDatesChronological(a.captured_at, b.captured_at));
}

/**
 * Where a capture date sits relative to the incident: <0 before, 0 same, >0 after, compared at the coarser of
 * the two precisions with no time-zone shift (format.ts compareSourceDatesCoarse): "2024-07-08" vs
 * "2024-07-08T15:42Z" is the same day; two full timestamps compare as instants. null if either is unknown.
 */
export function compareToIncident(captured: SourceDate | null, incident: SourceDate | null): number | null {
  return compareSourceDatesCoarse(captured, incident);
}

/** Captures split by their relation to the incident, each list in capture order. */
export function aerialSides(captures: Evidence[], incident_at: SourceDate) {
  const pre: Evidence[] = [];
  const post: Evidence[] = [];
  const undated: Evidence[] = [];
  for (const c of captures) {
    const rel = compareToIncident(c.captured_at, incident_at);
    if (rel == null) undated.push(c);
    else if (rel <= 0) pre.push(c);
    else post.push(c);
  }
  return { pre, post, undated };
}

/**
 * The earliest (or latest) capture in `list` that has an image (model.ts hasImage); only if none has one, the
 * earliest (latest) capture at all.
 */
function preferImage(list: Evidence[], which: "earliest" | "latest", exclude: Evidence | null = null): Evidence | null {
  const candidates = list.filter((c) => c !== exclude);
  if (which === "latest") candidates.reverse();
  return candidates.find(hasImage) ?? candidates[0] ?? null;
}

/**
 * Default pair: the latest capture on or before the incident and the earliest one after it, preferring
 * captures that have an image on each side; a capture without an image is used only when that side has
 * nothing else. If one side has no capture at all, the two nearest captures on the other side are compared
 * (the UI flags the mismatch). `captures` must be in capture order (see aerialCaptures).
 */
export function defaultAerialPair(captures: Evidence[], incident_at: SourceDate): { before: Evidence | null; after: Evidence | null } {
  const { pre, post } = aerialSides(captures, incident_at);
  let before = preferImage(pre, "latest");
  let after = preferImage(post, "earliest");
  if (before && after) return { before, after };

  const dated = [...pre, ...post];
  const pool = dated.length >= 2 ? captures.filter((c) => dated.includes(c)) : captures;
  if (pool.length < 2) return { before, after };
  if (before == null && after == null) {
    // Nothing can be placed against the incident: compare the earliest and latest.
    before = preferImage(pool, "earliest");
    after = preferImage(pool, "latest", before);
  } else if (before == null) {
    // Every dated capture is after the incident: compare the two earliest.
    before = preferImage(pool, "earliest");
    after = preferImage(pool, "earliest", before);
  } else {
    // Every dated capture is on or before the incident: compare the two latest.
    after = preferImage(pool, "latest");
    before = preferImage(pool, "latest", after);
  }
  // Keep the pair in capture order.
  if (before && after && captures.indexOf(before) > captures.indexOf(after)) [before, after] = [after, before];
  return { before, after };
}

/** The pair actually shown: explicit picks that still exist, otherwise the defaults. */
export function resolveAerialPair(captures: Evidence[], incident_at: SourceDate, choice: AerialPairChoice) {
  const d = defaultAerialPair(captures, incident_at);
  const find = (id: string | null) => (id == null ? null : captures.find((c) => c.evidence_id === id) ?? null);
  return { before: find(choice.before) ?? d.before, after: find(choice.after) ?? d.after };
}

/**
 * The choice after `evidence_id` was selected elsewhere: it becomes the "after" side, or the "before"
 * side when it is pre-incident or earlier than the current "after" capture (at the coarser precision, so a
 * date-only capture on the same day as the "after" one replaces it rather than becoming "before").
 * A capture without an image is still shown; its side then reads "Image not available for this capture".
 * Returns null if it is not a capture.
 */
export function choiceForSelected(captures: Evidence[], incident_at: SourceDate, choice: AerialPairChoice, evidence_id: string): AerialPairChoice | null {
  const sel = captures.find((c) => c.evidence_id === evidence_id);
  if (!sel) return null;
  const pair = resolveAerialPair(captures, incident_at, choice);
  if (pair.before?.evidence_id === evidence_id || pair.after?.evidence_id === evidence_id) return choice;
  const rel = compareToIncident(sel.captured_at, incident_at);
  const earlierThanAfter = pair.after != null && (compareSourceDatesCoarse(sel.captured_at, pair.after.captured_at) ?? 0) < 0;
  const asBefore = (rel != null && rel <= 0) || earlierThanAfter;
  const next: AerialPairChoice = {
    before: pair.before?.evidence_id ?? null,
    after: pair.after?.evidence_id ?? null,
  };
  if (asBefore) next.before = evidence_id;
  else next.after = evidence_id;
  return next;
}

export type AerialCompareProps = {
  captures: Evidence[];
  incident_at: SourceDate;
  choice: AerialPairChoice;
  onChoice: (c: AerialPairChoice) => void;
  selected_evidence_id: string | null;
  on_select_evidence: (evidence_id: string) => void;
};

function captureOptionLabel(e: Evidence): string {
  return `${formatSourceDate(e.captured_at)} · ${e.source_label}${hasImage(e) ? "" : " (no image)"}`;
}

/** Which sides of the incident have any capture at all (with or without an image). */
export type Availability = { pre: boolean; post: boolean };

/**
 * The note under a side's label when the capture does not sit where that side implies. Computed from the
 * captures in this case: it only says no other capture exists when none does.
 */
export function aerialRelationNote(side: "Before" | "After", e: Evidence, incident_at: SourceDate, available: Availability): string | null {
  const rel = compareToIncident(e.captured_at, incident_at);
  if (rel == null) {
    return e.captured_at == null
      ? "Capture date unknown, so its order relative to the incident is unknown."
      : "This capture date cannot be placed against the incident date, so its order relative to the incident is unknown.";
  }
  if (side === "Before") {
    if (rel > 0) {
      return available.pre
        ? "Taken after the incident date. A capture from on or before the incident date is available under Before capture."
        : "Taken after the incident date; no capture from on or before the incident date is available.";
    }
    return rel === 0 ? "Taken on the incident date, so it may already show the incident." : null;
  }
  if (rel > 0) return null;
  const when = rel === 0 ? "Taken on the incident date, so it may not show the incident's effects" : "Taken before the incident date";
  return available.post
    ? `${when}. A capture from after the incident date is available under After capture.`
    : `${when}; no capture from after the incident date is available.`;
}

function Limitations({ items }: { items: string[] }) {
  if (items.length === 0) return null;
  return (
    <ul className="ra-limits">
      {items.map((l, i) => (
        <li key={i}>{l}</li>
      ))}
    </ul>
  );
}

function MissingImage() {
  return (
    <div className="ra-missing" role="img" aria-label={IMAGE_UNAVAILABLE}>
      <span>{IMAGE_UNAVAILABLE}</span>
    </div>
  );
}

function CaptureLabel({
  side,
  e,
  incident_at,
  available,
  selected,
  onSelect,
}: {
  side: "Before" | "After";
  e: Evidence;
  incident_at: SourceDate;
  available: Availability;
  selected: boolean;
  onSelect: () => void;
}) {
  const mismatch = aerialRelationNote(side, e, incident_at, available);
  return (
    <div className={`ra-side ra-side--${side.toLowerCase()}`}>
      <p className="ra-side-head">
        <span className="ra-side-name">{side}</span>
        <span className="ra-side-date">{formatSourceDate(e.captured_at)}</span>
      </p>
      <EvidenceBadge label={e.source_label} kindLabel={evidenceKindLabel(e.kind)} selected={selected} onClick={onSelect} title="Show this capture in the evidence inspector" />
      {mismatch && <p className="ra-mismatch">{mismatch}</p>}
    </div>
  );
}

export function AerialCompare({ captures, incident_at, choice, onChoice, selected_evidence_id, on_select_evidence }: AerialCompareProps) {
  const id = useId();
  const [wipe, setWipe] = useState(50);
  const sides = aerialSides(captures, incident_at);
  const available: Availability = { pre: sides.pre.length > 0, post: sides.post.length > 0 };

  if (captures.length === 0) {
    return (
      <div className="ra-root">
        <EmptyState title="No aerial captures for this case">
          No dated Vexcel capture is attached to this case yet, so there is nothing to compare.
        </EmptyState>
        <p className="ra-caveat">{AERIAL_CAVEAT}</p>
      </div>
    );
  }

  if (captures.length === 1) {
    const only = captures[0];
    const onlyImg = imageOf(only);
    const rel = compareToIncident(only.captured_at, incident_at);
    return (
      <div className="ra-root">
        <p className="ra-notice" role="note">
          Only one aerial capture ({formatSourceDate(only.captured_at)}). A comparison needs a second dated capture.
        </p>
        <div className="ra-stage">{onlyImg ? <img className="ra-img" src={onlyImg.url} alt={onlyImg.alt} /> : <MissingImage />}</div>
        <div className="ra-sides">
          <CaptureLabel
            side={rel != null && rel <= 0 ? "Before" : "After"}
            e={only}
            incident_at={incident_at}
            available={available}
            selected={selected_evidence_id === only.evidence_id}
            onSelect={() => on_select_evidence(only.evidence_id)}
          />
        </div>
        <Limitations items={only.limitations} />
        <p className="ra-caveat">{AERIAL_CAVEAT}</p>
      </div>
    );
  }

  const { before, after } = resolveAerialPair(captures, incident_at, choice);
  const pick = (side: "before" | "after", evidence_id: string) => {
    onChoice({
      before: side === "before" ? evidence_id : (before?.evidence_id ?? null),
      after: side === "after" ? evidence_id : (after?.evidence_id ?? null),
    });
  };
  const same = before != null && after != null && before.evidence_id === after.evidence_id;
  const beforeImg = imageOf(before);
  const afterImg = imageOf(after);

  return (
    <div className="ra-root">
      <div className="ra-pickers">
        <label className="ra-picker" htmlFor={`${id}-before`}>
          <span>Before capture</span>
          <select id={`${id}-before`} className="ra-select" value={before?.evidence_id ?? ""} onChange={(e) => pick("before", e.target.value)}>
            {captures.map((c) => (
              <option key={c.evidence_id} value={c.evidence_id}>
                {captureOptionLabel(c)}
              </option>
            ))}
          </select>
        </label>
        <label className="ra-picker" htmlFor={`${id}-after`}>
          <span>After capture</span>
          <select id={`${id}-after`} className="ra-select" value={after?.evidence_id ?? ""} onChange={(e) => pick("after", e.target.value)}>
            {captures.map((c) => (
              <option key={c.evidence_id} value={c.evidence_id}>
                {captureOptionLabel(c)}
              </option>
            ))}
          </select>
        </label>
      </div>

      {same && (
        <p className="ra-notice" role="note">
          Both sides show the same capture. Pick a different capture to compare.
        </p>
      )}

      {!same && before && after && beforeImg && afterImg ? (
        <div className="ra-wipe">
          <div className="ra-stage">
            <img className="ra-img" src={beforeImg.url} alt={`Before, ${formatSourceDate(before.captured_at)}: ${beforeImg.alt}`} />
            <img
              className="ra-img ra-img--after"
              src={afterImg.url}
              alt={`After, ${formatSourceDate(after.captured_at)}: ${afterImg.alt}`}
              style={{ clipPath: `inset(0 0 0 ${wipe}%)` }}
            />
            <span className="ra-line" style={{ left: `${wipe}%` }} aria-hidden="true" />
            <span className="ra-tag ra-tag--before" aria-hidden="true">
              Before · {formatSourceDate(before.captured_at)}
            </span>
            <span className="ra-tag ra-tag--after" aria-hidden="true">
              After · {formatSourceDate(after.captured_at)}
            </span>
          </div>
          <label className="ra-range" htmlFor={`${id}-wipe`}>
            <span className="ra-range-label">Wipe: before on the left, after on the right</span>
            <input
              id={`${id}-wipe`}
              type="range"
              min={0}
              max={100}
              step={1}
              value={wipe}
              aria-valuetext={`${wipe}% before, ${100 - wipe}% after`}
              onChange={(e) => setWipe(Number(e.target.value))}
            />
          </label>
        </div>
      ) : (
        !same && (
          <div className="ra-split">
            <div className="ra-stage">{beforeImg ? <img className="ra-img" src={beforeImg.url} alt={beforeImg.alt} /> : <MissingImage />}</div>
            <div className="ra-stage">{afterImg ? <img className="ra-img" src={afterImg.url} alt={afterImg.alt} /> : <MissingImage />}</div>
          </div>
        )
      )}

      <div className="ra-sides">
        {before && (
          <div>
            <CaptureLabel
              side="Before"
              e={before}
              incident_at={incident_at}
              available={available}
              selected={selected_evidence_id === before.evidence_id}
              onSelect={() => on_select_evidence(before.evidence_id)}
            />
            <Limitations items={before.limitations} />
          </div>
        )}
        {after && (
          <div>
            <CaptureLabel
              side="After"
              e={after}
              incident_at={incident_at}
              available={available}
              selected={selected_evidence_id === after.evidence_id}
              onSelect={() => on_select_evidence(after.evidence_id)}
            />
            {!same && <Limitations items={after.limitations} />}
          </div>
        )}
      </div>
      <p className="ra-caveat">{AERIAL_CAVEAT}</p>
    </div>
  );
}
