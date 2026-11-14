import type { ReactNode } from "react";

const finite = (x: number | null | undefined): x is number => typeof x === "number" && Number.isFinite(x);

export type RangeTrackProps = {
  low: number | null;
  high: number | null;
  point: number | null;
  domain: [number, number];
  unavailable?: boolean;
  /** Extra: a thicker track for the headline figure. */
  emphasis?: boolean;
};

/**
 * The Standard Response range: a thin line spans low to high, a dot marks the point.
 * When unavailable (or the low/high pair is inconsistent and there is no point) the track is hatched and empty, with no dot.
 * Decorative: pair it with a text readout (RangeRow does).
 */
export function RangeTrack({ low, high, point, domain, unavailable = false, emphasis = false }: RangeTrackProps) {
  const [d0, d1] = domain;
  const span = d1 - d0;
  const at = (x: number) => {
    if (!Number.isFinite(span) || span <= 0) return 50;
    return Math.min(100, Math.max(0, ((x - d0) / span) * 100));
  };
  const hasSpan = finite(low) && finite(high) && low <= high;
  const hasPoint = finite(point);
  const empty = unavailable || (!hasSpan && !hasPoint);
  const classes = ["r-range-track", empty && "is-unavailable", emphasis && "is-emphasis"].filter(Boolean).join(" ");

  return (
    <span className={classes} aria-hidden="true">
      <span className="r-range-axis" />
      {empty ? (
        <span className="r-range-hatch" />
      ) : (
        <>
          {hasSpan && <span className="r-range-span" style={{ left: `${at(low)}%`, width: `${at(high) - at(low)}%` }} />}
          {hasPoint && <span className="r-range-dot" style={{ left: `${at(point)}%` }} />}
        </>
      )}
    </span>
  );
}

export type RangeRowProps = {
  label: ReactNode;
  /** Text equivalent of the track, e.g. "$1.2M to $1.5M" or "Not enough evidence". Always shown. */
  readout: string;
  low: number | null;
  high: number | null;
  point: number | null;
  domain: [number, number];
  emphasis?: boolean;
  unavailable?: boolean;
  /** Shown under the row, e.g. the range-kind label or unavailable_reason. */
  note?: ReactNode;
};

/** Label, track, readout in one grid row. Renders a <div>; wrap rows in RangeList (or any block). */
export function RangeRow({ label, readout, low, high, point, domain, emphasis = false, unavailable = false, note }: RangeRowProps) {
  const classes = ["r-range-row", emphasis && "is-emphasis", unavailable && "is-unavailable"].filter(Boolean).join(" ");
  return (
    <div className={classes}>
      <span className="r-range-label">{label}</span>
      <RangeTrack low={low} high={high} point={point} domain={domain} unavailable={unavailable} emphasis={emphasis} />
      <span className="r-range-readout">{readout}</span>
      {note != null && note !== false && <span className="r-range-note">{note}</span>}
    </div>
  );
}

/** Extra: a plain stack for RangeRows. */
export function RangeList({ children, className }: { children: ReactNode; className?: string }) {
  return <div className={["r-range-list", className].filter(Boolean).join(" ")}>{children}</div>;
}

/**
 * Extra: a shared domain for several tracks so they line up. Ignores null and non-finite values.
 * Pads by `pad` (fraction of the spread) on each side and never returns an empty domain.
 */
export function rangeDomain(values: readonly (number | null | undefined)[], pad = 0.08): [number, number] {
  const xs = values.filter(finite);
  if (xs.length === 0) return [0, 1];
  let lo = Math.min(...xs);
  let hi = Math.max(...xs);
  if (lo === hi) {
    const d = Math.abs(lo) * 0.1 || 1;
    return [lo - d, hi + d];
  }
  const d = (hi - lo) * pad;
  lo -= d;
  hi += d;
  return [lo, hi];
}
