import type { Exposure, Threat, Timing } from "./types";

export const usd = (n: number) => n.toLocaleString("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 });
export const num = (n: number | null | undefined) => (n == null ? "–" : n.toLocaleString("en-US"));

export function costRange(low: number, high: number): string {
  if (low === 0 && high === 0) return "No outside cost";
  return low === high ? usd(low) : `${usd(low)} to ${usd(high)}`;
}

export function hours(h: number | null | undefined): string {
  if (h == null) return "timing unknown";
  if (h <= 0) return "now";
  if (h < 48) return `${Math.round(h)} hours`;
  return `${Math.round(h / 24)} days`;
}

/** "Sat 6 Jul 2024, 21:00 UTC" */
export function when(iso: string | null | undefined): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (isNaN(d.getTime())) return iso;
  return d.toLocaleString("en-GB", { weekday: "short", day: "numeric", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit", timeZone: "UTC" }) + " UTC";
}

export function monthYear(s: string | null | undefined): string {
  if (!s) return "date unknown";
  const d = new Date(s.includes("UTC") ? s.replace(" UTC", "") + " UTC" : s);
  if (isNaN(d.getTime())) return s;
  return d.toLocaleString("en-US", { month: "long", year: "numeric", timeZone: "UTC" });
}

export const TIMING: Record<Timing, string> = {
  before_arrival: "Do before it arrives",
  after_event: "Do after this event",
  capital: "Plan and budget",
};

export const HAZARD: Record<string, string> = { wind: "Wind", flood: "Flood", fire: "Fire", general: "General" };

export function exposureLine(e: Exposure): string {
  if (e.kind === "hurricane") {
    const wind = e.peak_wind_mph != null ? `Peak wind about ${Math.round(e.peak_wind_mph)} mph` : "Wind forecast unavailable";
    return `${wind} (${e.wind_band ?? "unknown"})`;
  }
  return e.in_warning ? "Inside the Red Flag Warning area" : "Outside the warning area";
}

export function standingLine(t: Threat): string | null {
  const f = t.standing_risk.fema;
  if (t.kind === "hurricane") {
    if (!f) return null;
    if (f.floodway) return "In the regulatory floodway";
    if (f.high_risk) return `High-risk flood zone ${f.zone}`;
    if ((f.subtype ?? "").includes("0.2")) return "500-year flood zone";
    return `Flood zone ${f.zone} (minimal risk)`;
  }
  return t.standing_risk.fire_zone ? `${t.standing_risk.fire_zone} fire hazard severity zone` : "Outside the mapped fire hazard zones";
}
