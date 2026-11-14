/** Time formatting for residents: local, short, and never inventing precision the source lacks. */

const DATE_ONLY = /^\d{4}-\d{2}-\d{2}$/;

export function parseWhen(value: string | null | undefined): Date | null {
  if (!value) return null;
  // Date-only source values stay date-only (contract: keep source precision).
  const d = DATE_ONLY.test(value) ? new Date(`${value}T12:00:00`) : new Date(value);
  return Number.isNaN(d.getTime()) ? null : d;
}

/** "3:42 PM" today, "Yesterday 3:42 PM", "Mon 12 Nov, 3:42 PM", date-only as "Mon 12 Nov". */
export function formatWhen(value: string | null | undefined, now: Date = new Date()): string {
  const d = parseWhen(value);
  if (!d || !value) return "Unknown";
  const dateOnly = DATE_ONLY.test(value);
  const time = d.toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" });
  const sameDay = d.toDateString() === now.toDateString();
  const yest = new Date(now);
  yest.setDate(now.getDate() - 1);
  if (!dateOnly && sameDay) return `Today ${time}`;
  if (!dateOnly && d.toDateString() === yest.toDateString()) return `Yesterday ${time}`;
  const day = d.toLocaleDateString(undefined, { weekday: "short", day: "numeric", month: "short" });
  return dateOnly ? day : `${day}, ${time}`;
}

/** "just now", "4 min ago", "2 h ago", else formatWhen. For "last updated" lines. */
export function formatAgo(value: string | null | undefined, now: Date = new Date()): string {
  const d = parseWhen(value);
  if (!d || !value) return "Unknown";
  // A date-only source has no time of day; "just now" / "4 min ago" would invent precision.
  if (DATE_ONLY.test(value)) return formatWhen(value, now);
  const s = Math.round((now.getTime() - d.getTime()) / 1000);
  if (s < 45) return "just now";
  if (s < 3600) return `${Math.round(s / 60)} min ago`;
  if (s < 6 * 3600) return `${Math.round(s / 3600)} h ago`;
  return formatWhen(value, now);
}

/** Value for <input type="datetime-local"> from a Date, in local time. */
export function toLocalInput(d: Date): string {
  const p = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}T${p(d.getHours())}:${p(d.getMinutes())}`;
}

/** datetime-local value (local wall time) to an ISO 8601 string with timezone, or null. */
export function localInputToIso(v: string): string | null {
  if (!v) return null;
  const d = new Date(v);
  return Number.isNaN(d.getTime()) ? null : d.toISOString();
}
