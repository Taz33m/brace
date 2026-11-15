/**
 * The headset tour: which standpoints to stand at, in what order, and which schedule lines to pin there.
 *
 * Pure functions over the schedule served at GET /api/schedule/{property_id}. Every tag is a line the
 * inventory agent recorded with an `at`: the panorama (sweep) it was seen best from, the compass turn
 * (yaw, clockwise, in the same frame as the sweep's heading) and the tilt (pitch, up is positive) to the
 * thing itself. Same frame and formula as the home page's inside beat (frontend/src/story/Loop.tsx), so a
 * tag sits on the same object in both.
 */

export interface Total {
  low: number | null;
  high: number | null;
  lines: number;
  lines_priced: number;
}

export interface At {
  sweep_id: string;
  standpoint?: string;
  direction?: string;
  yaw_deg: number;
  pitch_deg: number;
  heading_deg?: number | null;
}

export interface ScheduleItem {
  what: string;
  quantity: number | null;
  unit: string;
  low: number | null;
  high: number | null;
  seen: string | null;
  source_title?: string | null;
  at: At | null;
}

export interface ScheduleRoom {
  name: string;
  area_sqft: number | null;
  read: boolean;
  total: Total;
  items: ScheduleItem[];
}

export interface ScheduleUnit {
  scan_id: string;
  name: string;
  scan_date?: string | null;
  rooms: ScheduleRoom[];
  total: Total;
}

export interface Schedule {
  property: { id: number; name: string; address?: string; homes?: number; scan_date?: string | null };
  home: { name: string; total: Total; multiplied_by: number };
  buildings: { units?: ScheduleUnit[] }[];
}

export interface Tag {
  what: string;
  quantity: number | null;
  unit: string;
  low: number | null;
  high: number | null;
  seen: string | null;
  yaw: number;
  pitch: number;
}

export interface Stop {
  room: string;
  roomTotal: Total;
  sweepId: string;
  /** Compass heading of the panorama's first side face, needed to turn the cube faces into place. */
  heading: number;
  tags: Tag[];
  /** Compass yaw to face when arriving: the middle of this stop's tags. */
  facing: number;
}

/** The rooms worth opening with: most of the fit-out an owner insures is in these two. */
const LEAD_ROOMS = ["Kitchen", "Bathroom"];

/** The unit whose scan this is, or else the first unit with any located line. */
export function scannedUnit(s: Schedule, scanId: string): ScheduleUnit | null {
  const units = s.buildings.flatMap((b) => b.units ?? []);
  const located = (u: ScheduleUnit) => u.rooms.some((r) => r.items.some((i) => i.at));
  return units.find((u) => u.scan_id === scanId && located(u)) ?? units.find(located) ?? null;
}

/** Mean of compass angles, so 350 and 10 give 0, not 180. */
export function circularMeanDeg(degs: number[]): number {
  if (!degs.length) return 0;
  let x = 0, y = 0;
  for (const d of degs) {
    x += Math.cos((d * Math.PI) / 180);
    y += Math.sin((d * Math.PI) / 180);
  }
  const m = (Math.atan2(y, x) * 180) / Math.PI;
  return ((m % 360) + 360) % 360;
}

/**
 * Stops in tour order: lead rooms first, then the rest by how much there is to see; inside a room, the
 * standpoint with the most tags first. A standpoint whose panorama heading is unknown is skipped, because
 * its pictures could not be turned into place. Rooms with nothing located are skipped (they still count in
 * the totals). `headings` fills in a heading the schedule does not carry, by sweep id.
 */
export function buildTour(s: Schedule, scanId: string, headings: Record<string, number> = {}): Stop[] {
  const unit = scannedUnit(s, scanId);
  if (!unit) return [];
  const rooms = unit.rooms
    .map((room) => {
      const bySweep = new Map<string, { heading: number | null; tags: Tag[] }>();
      for (const i of room.items) {
        if (!i.at) continue;
        const entry = bySweep.get(i.at.sweep_id) ?? { heading: i.at.heading_deg ?? headings[i.at.sweep_id] ?? null, tags: [] };
        entry.tags.push({ what: i.what, quantity: i.quantity, unit: i.unit, low: i.low, high: i.high, seen: i.seen, yaw: i.at.yaw_deg, pitch: i.at.pitch_deg });
        bySweep.set(i.at.sweep_id, entry);
      }
      const stops: Stop[] = [...bySweep.entries()]
        .filter(([, e]) => e.heading != null)
        .map(([sweepId, e]) => ({
          room: room.name,
          roomTotal: room.total,
          sweepId,
          heading: e.heading as number,
          tags: e.tags,
          facing: circularMeanDeg(e.tags.map((t) => t.yaw)),
        }))
        .sort((a, b) => b.tags.length - a.tags.length);
      return { name: room.name, count: stops.reduce((n, st) => n + st.tags.length, 0), stops };
    })
    .filter((r) => r.stops.length);
  rooms.sort((a, b) => {
    const la = LEAD_ROOMS.indexOf(a.name), lb = LEAD_ROOMS.indexOf(b.name);
    if (la !== lb) return (la === -1 ? 99 : la) - (lb === -1 ? 99 : lb);
    return b.count - a.count;
  });
  return rooms.flatMap((r) => r.stops);
}

/**
 * Unit vector toward a compass yaw and pitch, in the viewer's frame: -z is yaw 0, yaw turns clockwise
 * seen from above (toward +x), pitch up is +y. The frame the cube faces are turned into.
 */
export function direction(yawDeg: number, pitchDeg: number): [number, number, number] {
  const t = (yawDeg * Math.PI) / 180, p = (pitchDeg * Math.PI) / 180;
  return [Math.cos(p) * Math.sin(t), Math.sin(p), -Math.cos(p) * Math.cos(t)];
}

export function money(n: number): string {
  return "$" + Math.round(n).toLocaleString("en-US");
}

/** A figure as the schedule states it. A line without a confirmed price shows no figure. */
export function range(low: number | null, high: number | null): string {
  if (low == null || high == null) return "no confirmed price";
  return low === high ? money(low) : `${money(low)}–${money(high)}`;
}

/** "Base cabinet ×2", or the bare name for a single item. */
export function label(t: Pick<Tag, "what" | "quantity" | "unit">): string {
  return t.quantity && t.quantity > 1 && t.unit === "each" ? `${t.what} ×${t.quantity}` : t.what;
}
