// Presentation helpers for the recovery workspace. Pure functions, no React, no network.
import type { MoneyRange, SourceDate, ValueBasis } from "../../recovery/contracts";
import { humanizeCode } from "./model";

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

const USD = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0, minimumFractionDigits: 0 });

/** "$1,234,567". Rounds to whole dollars. Callers must handle null themselves (see describeMoneyRange). */
export function formatUsd(n: number): string {
  if (!Number.isFinite(n)) return "Amount unavailable";
  // Avoid "-$0" for tiny negatives.
  const r = Math.round(n);
  return USD.format(r === 0 ? 0 : r);
}

const trim = (s: string) => s.replace(/\.0$/, "");

/** "$1.2M", "$950K", "$12.5K", "$1,200". */
export function formatUsdCompact(n: number): string {
  if (!Number.isFinite(n)) return "Amount unavailable";
  const sign = n < 0 ? "-" : "";
  const a = Math.abs(n);
  if (a >= 1e9 || Math.round(a / 1e6) >= 1000) return `${sign}$${trim((a / 1e9).toFixed(1))}B`;
  if (a >= 1e6 || Math.round(a / 1e3) >= 1000) return `${sign}$${trim((a / 1e6).toFixed(1))}M`;
  if (a >= 1e5) return `${sign}$${Math.round(a / 1e3)}K`;
  if (a >= 1e4) return `${sign}$${trim((a / 1e3).toFixed(1))}K`;
  return formatUsd(n);
}

export type MoneyRangeState = "point" | "range" | "range_with_point" | "unavailable" | "invalid";
export type MoneyRangeDescription = { state: MoneyRangeState; text: string; detail: string | null };

export const NOT_ENOUGH_EVIDENCE = "Not enough evidence";
export const RANGE_INCONSISTENT = "Range unavailable (inconsistent data)";

/**
 * Text for a MoneyRange. Never produces "$0" for a null amount.
 * - all null: "unavailable", "Not enough evidence", detail = unavailable_reason
 * - one of low/high null, low > high, or a non-finite value: "invalid"
 */
export function describeMoneyRange(r: MoneyRange): MoneyRangeDescription {
  const { low, high, point } = r;
  const bad = [low, high, point].some((v) => v !== null && (typeof v !== "number" || !Number.isFinite(v)));
  if (bad) return { state: "invalid", text: RANGE_INCONSISTENT, detail: "The source supplied a value that is not a finite number." };
  if (low === null && high === null) {
    if (point === null) return { state: "unavailable", text: NOT_ENOUGH_EVIDENCE, detail: r.unavailable_reason };
    return { state: "point", text: formatUsd(point), detail: null };
  }
  if (low === null || high === null) {
    return { state: "invalid", text: RANGE_INCONSISTENT, detail: "Only one end of the range was supplied." };
  }
  if (low > high) {
    return { state: "invalid", text: RANGE_INCONSISTENT, detail: "The low end is above the high end." };
  }
  const span = low === high ? formatUsd(low) : `${formatUsd(low)} to ${formatUsd(high)}`;
  if (point === null) return { state: "range", text: span, detail: null };
  return { state: "range_with_point", text: `${formatUsd(point)} (range ${span})`, detail: null };
}

/** Compact variant of describeMoneyRange's text, for tight readouts. Same states and null rules. */
export function describeMoneyRangeCompact(r: MoneyRange): MoneyRangeDescription {
  const d = describeMoneyRange(r);
  if (d.state === "unavailable" || d.state === "invalid") return d;
  const { low, high, point } = r as { low: number | null; high: number | null; point: number | null };
  if (d.state === "point") return { ...d, text: formatUsdCompact(point as number) };
  const span = low === high ? formatUsdCompact(low as number) : `${formatUsdCompact(low as number)} to ${formatUsdCompact(high as number)}`;
  return { ...d, text: d.state === "range" ? span : `${formatUsdCompact(point as number)} (${span})` };
}

/**
 * What kind of range this is. Only calibrated_confidence is a confidence interval. A kind this build does not
 * recognise gets a readable label that says so and never claims to be a confidence interval.
 */
export function rangeKindLabel(kind: MoneyRange["range_kind"]): string {
  switch (kind) {
    case "calibrated_confidence":
      return "calibrated confidence interval";
    case "comparable_dispersion":
      return "spread of comparable sales, not a confidence interval";
    case "scenario":
      return "scenario range";
    case "source_range":
      return "range given by the source";
    default:
      return `${humanizeCode(kind) || "Unknown"} range (unrecognised kind), not a confidence interval`;
  }
}

export const VALUE_BASIS_LABEL: Record<ValueBasis, string> = {
  market_supported: "Market supported",
  conditional: "Conditional",
  insufficient_evidence: "Insufficient evidence",
};

export const VALUE_BASIS_HELP: Record<ValueBasis, string> = {
  market_supported: "Backed by dated market evidence for this property and comparable sales.",
  conditional: "Depends on the assumptions listed below. It changes if they turn out wrong.",
  insufficient_evidence: "There is not enough evidence to state a value. No amount is shown in place of one.",
};

const DATE_ONLY = /^(\d{4})-(\d{2})-(\d{2})$/;
const MONTH_ONLY = /^(\d{4})-(\d{2})$/;
const YEAR_ONLY = /^(\d{4})$/;

const monthName = (mm: string) => {
  const m = Number(mm);
  return m >= 1 && m <= 12 ? MONTHS[m - 1] : null;
};

/**
 * A source date at its own precision, with no timezone conversion for date-only values.
 * "2024-07-08" -> "8 Jul 2024", "2024-07" -> "Jul 2024", "2024" -> "2024",
 * a timestamp -> "8 Jul 2024, 14:05 UTC", null -> "Date unknown". Unparseable strings are shown as given.
 */
export function formatSourceDate(d: SourceDate | null): string {
  if (d == null) return "Date unknown";
  const s = d.trim();
  if (s === "") return "Date unknown";
  let m = DATE_ONLY.exec(s);
  if (m) {
    const mon = monthName(m[2]);
    const day = Number(m[3]);
    return mon && day >= 1 && day <= 31 ? `${day} ${mon} ${m[1]}` : s;
  }
  m = MONTH_ONLY.exec(s);
  if (m) {
    const mon = monthName(m[2]);
    return mon ? `${mon} ${m[1]}` : s;
  }
  if (YEAR_ONLY.test(s)) return s;
  return formatTimestamp(s);
}

const pad2 = (n: number) => String(n).padStart(2, "0");

// An ISO 8601 date-time: date, "T" (or a space), hh:mm, optional :ss and fraction, optional zone.
const TIMESTAMP = /^(\d{4})-(\d{2})-(\d{2})[Tt ](\d{2}):(\d{2})(?::(\d{2})(?:[.,](\d+))?)?\s*([Zz]|[+-]\d{2}(?::?\d{2})?)?$/;

/** Days in a 1-based month: day 0 of the following month is the last day of this one. */
function daysInMonth(year: number, month: number): number {
  const d = new Date(0);
  d.setUTCFullYear(year, month, 0);
  return d.getUTCDate();
}

/**
 * Milliseconds since the epoch for an ISO 8601 timestamp, or null when `iso` is not one.
 * A timestamp written without a zone ("2024-07-08T04:15:00") is read as UTC, never in the viewer's zone.
 * Date-only, month and year values are not timestamps and return null.
 */
export function timestampMs(iso: string): number | null {
  const m = TIMESTAMP.exec(iso.trim());
  if (!m) return null;
  const year = Number(m[1]);
  const month = Number(m[2]);
  const day = Number(m[3]);
  const hour = Number(m[4]);
  const minute = Number(m[5]);
  const second = m[6] ? Number(m[6]) : 0;
  const ms = m[7] ? Math.floor(Number(`0.${m[7]}`) * 1000) : 0;
  if (month < 1 || month > 12 || day < 1 || day > daysInMonth(year, month)) return null;
  if (hour > 23 || minute > 59 || second > 60) return null;
  let offsetMinutes = 0;
  const zone = m[8];
  if (zone && zone !== "Z" && zone !== "z") {
    const digits = zone.slice(1).replace(":", "");
    const oh = Number(digits.slice(0, 2));
    const om = digits.length > 2 ? Number(digits.slice(2)) : 0;
    if (oh > 23 || om > 59) return null;
    offsetMinutes = (zone[0] === "-" ? -1 : 1) * (oh * 60 + om);
  }
  // setUTCFullYear avoids Date.UTC's 0-99 => 1900s mapping.
  const d = new Date(0);
  d.setUTCFullYear(year, month - 1, day);
  d.setUTCHours(hour, minute, second, ms);
  const t = d.getTime() - offsetMinutes * 60_000;
  return Number.isFinite(t) ? t : null;
}

/**
 * "8 Jul 2024, 14:05 UTC"; null -> "Time unknown". A date-only value is shown as a date, never as midnight UTC.
 * A timestamp without a zone is read as UTC (never shifted by the viewer's zone). Anything that is not an ISO
 * date or timestamp is shown as given rather than guessed.
 */
export function formatTimestamp(iso: string | null): string {
  if (iso == null) return "Time unknown";
  const s = iso.trim();
  if (s === "") return "Time unknown";
  if (DATE_ONLY.test(s) || MONTH_ONLY.test(s) || YEAR_ONLY.test(s)) return formatSourceDate(s);
  const t = timestampMs(s);
  if (t == null) return s;
  const d = new Date(t);
  return `${d.getUTCDate()} ${MONTHS[d.getUTCMonth()]} ${d.getUTCFullYear()}, ${pad2(d.getUTCHours())}:${pad2(d.getUTCMinutes())} UTC`;
}

/** Ascending lexicographic ISO comparison, nulls last. Use with Array.prototype.sort. */
export function compareSourceDates(a: SourceDate | null, b: SourceDate | null): number {
  if (a == null && b == null) return 0;
  if (a == null) return 1;
  if (b == null) return -1;
  return a < b ? -1 : a > b ? 1 : 0;
}

export type SourceDatePrecision = "year" | "month" | "day" | "time";
const PRECISION_RANK: Record<SourceDatePrecision, number> = { year: 0, month: 1, day: 2, time: 3 };

type SourceDateParts = { precision: SourceDatePrecision; year: number; month: number; day: number; ms: number | null };

/** The calendar parts of a SourceDate as written (no time-zone conversion), or null if unknown or unparseable. */
function sourceDateParts(d: SourceDate | null): SourceDateParts | null {
  if (d == null) return null;
  const s = d.trim();
  let m = DATE_ONLY.exec(s);
  if (m) {
    const [year, month, day] = [Number(m[1]), Number(m[2]), Number(m[3])];
    if (month < 1 || month > 12 || day < 1 || day > daysInMonth(year, month)) return null;
    return { precision: "day", year, month, day, ms: null };
  }
  m = MONTH_ONLY.exec(s);
  if (m) {
    const [year, month] = [Number(m[1]), Number(m[2])];
    return month >= 1 && month <= 12 ? { precision: "month", year, month, day: 0, ms: null } : null;
  }
  if (YEAR_ONLY.test(s)) return { precision: "year", year: Number(s), month: 0, day: 0, ms: null };
  m = TIMESTAMP.exec(s);
  if (m) {
    const ms = timestampMs(s);
    if (ms == null) return null;
    return { precision: "time", year: Number(m[1]), month: Number(m[2]), day: Number(m[3]), ms };
  }
  return null;
}

/** The precision a SourceDate is written at, or null if it is unknown or unparseable. */
export function sourceDatePrecision(d: SourceDate | null): SourceDatePrecision | null {
  return sourceDateParts(d)?.precision ?? null;
}

const cmp = (a: number, b: number) => (a < b ? -1 : a > b ? 1 : 0);

/**
 * Compares two source dates at the coarser of their two precisions, with no time-zone shift:
 * - two full timestamps compare as instants (a timestamp without a zone is read as UTC);
 * - otherwise the calendar parts are compared exactly as written, cut to the coarser precision, so
 *   "2024-07-11" equals "2024-07-11T15:42:00Z", "2024-07" equals "2024-07-31", and
 *   "2024-07-08T23:30:00-04:00" is on 8 Jul (its own calendar day), not shifted to 9 Jul UTC.
 * Returns -1, 0 or 1, or null when either date is null or unparseable.
 */
export function compareSourceDatesCoarse(a: SourceDate | null, b: SourceDate | null): number | null {
  const pa = sourceDateParts(a);
  const pb = sourceDateParts(b);
  if (!pa || !pb) return null;
  if (pa.ms != null && pb.ms != null) return cmp(pa.ms, pb.ms);
  const rank = Math.min(PRECISION_RANK[pa.precision], PRECISION_RANK[pb.precision]);
  if (pa.year !== pb.year) return cmp(pa.year, pb.year);
  if (rank >= 1 && pa.month !== pb.month) return cmp(pa.month, pb.month);
  if (rank >= 2 && pa.day !== pb.day) return cmp(pa.day, pb.day);
  return 0;
}

/**
 * A total chronological order for sorting (use with Array.prototype.sort): by the calendar parts as written,
 * a coarser value before a finer one in the same period ("2024-07" before "2024-07-11" before
 * "2024-07-11T15:42:00Z"), two timestamps on the same written day by instant. Null and unparseable last.
 */
export function compareSourceDatesChronological(a: SourceDate | null, b: SourceDate | null): number {
  const pa = sourceDateParts(a);
  const pb = sourceDateParts(b);
  if (!pa || !pb) return pa ? -1 : pb ? 1 : 0;
  return (
    cmp(pa.year, pb.year) ||
    cmp(pa.month, pb.month) ||
    cmp(pa.day, pb.day) ||
    cmp(PRECISION_RANK[pa.precision], PRECISION_RANK[pb.precision]) ||
    cmp(pa.ms ?? 0, pb.ms ?? 0)
  );
}
