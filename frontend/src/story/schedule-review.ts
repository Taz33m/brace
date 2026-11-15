import type { Schedule } from "./ScheduleTree";
export function reviewQuestions(data: Schedule): string[] {
  const questions: string[] = [];
  if (data.property.homes !== data.property.homes_on_record) questions.push(`Which unit count should we use? The listing rollup describes ${data.property.homes} homes; the property record gives ${data.property.homes_on_record}. Reconcile the difference before using the property total.`);
  questions.push("Which units share this scan's floor plan and renovation package? Confirm their counts; floor-area scaling does not establish identical appliances or finishes.");
  questions.push(data.property.scan_date ? `What has changed since the scan dated ${data.property.scan_date}? Confirm renovations, replacements, and additions.` : "When was this home scanned, and what has changed since then? The scan date is unavailable.");
  const missing = (data.total.lines ?? 0) - (data.total.lines_priced ?? 0);
  if (missing > 0) questions.push(`Obtain prices for ${missing} unpriced inventory lines. They are excluded from the displayed range, not assumed to cost zero.`);
  const units = [...new Map(data.buildings.flatMap(b => b.units).map(u => [u.scan_id, u])).values()];
  for (const unit of units) for (const room of unit.rooms) {
    if (!room.read) questions.push(`Review ${unit.name} / ${room.name}: the room was not read by the inventory agent.`);
    for (const doubt of room.doubts ?? []) questions.push(`${unit.name} / ${room.name}: ${doubt.doubt}`);
  }
  questions.push("Confirm quantities, local labor, finish grade, installation scope, and price validity with an estimator. A checked source page is not a contractor quote.");
  questions.push("Confirm landlord ownership and whether excluded structure, ceilings, common areas, or tenant possessions need a separate schedule.");
  questions.push("Confirm actual units per building. Roof-area allocation is an estimate, not a verified occupancy map.");
  return questions;
}
export function reviewMoney(value: { low: number | null; high: number | null }, fractionDigits = 0): string {
  const dollar = (n: number) => new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", minimumFractionDigits: fractionDigits, maximumFractionDigits: fractionDigits }).format(n);
  return value.low == null || value.high == null ? "Unpriced / unavailable" : value.low === value.high ? dollar(value.low) : `${dollar(value.low)}–${dollar(value.high)}`;
}
export function sourceLink(value: string | null): string | undefined {
  try { const url = new URL(value ?? ""); return ["http:", "https:"].includes(url.protocol) ? url.href : undefined; } catch { return undefined; }
}
