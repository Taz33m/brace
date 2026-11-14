/**
 * Reading a nod or a shake from where the head has been pointing, and deciding whether one may be acted on.
 *
 * Nothing here touches the camera, the browser or a library, so all of it can be tested with made-up numbers.
 * The owner rehearses a deliberate nod and shake, so every doubt is settled as "nothing happened":
 * a missed faint gesture costs a second try, a false one answers a question nobody answered.
 */
export type Gesture = "nod" | "shake";
/** Where the head points at one moment: yaw is left-right, pitch is up-down, both in degrees. */
export interface HeadSample { t: number; yaw: number; pitch: number }

/** Only the last this-many milliseconds are looked at, so a gesture has to be finished inside it. */
export const WINDOW_MS = 1600;
/** Each stroke (down, up, left or right) must travel at least this many degrees from one end to the other. */
export const MIN_SWING_DEG = 8;
/** The head must change direction at least this many times: down-up-down, not one glance and back. */
export const MIN_REVERSALS = 2;
/** A stroke quicker than this is the tracker jumping for a frame, not a head moving. */
export const MIN_SWING_MS = 90;
/** The gesture's own axis must move this many times further than the other, so a diagonal wobble is nothing. */
export const DOMINANCE = 1.5;
/** A hole this long between samples (the face was lost) breaks the movement; only what follows it counts. */
export const MAX_GAP_MS = 350;
/** Fewer samples than this cannot show two reversals. */
export const MIN_SAMPLES = 6;
/** How long a recognised gesture waits before it is delivered, so that speech starting in that time wins. */
export const SPEECH_WINS_MS = 500;

interface Point { t: number; v: number }
interface Stroke { start: number; end: number }

/** The newest samples: inside the window, and with no hole in them. */
function recent(samples: readonly HeadSample[]): HeadSample[] {
  const last = samples[samples.length - 1];
  let from = samples.length - 1;
  while (from > 0 && last.t - samples[from - 1].t <= WINDOW_MS && samples[from].t - samples[from - 1].t <= MAX_GAP_MS) from--;
  return samples.slice(from);
}

/**
 * Split one axis into strokes: runs in one direction that each cover MIN_SWING_DEG or more.
 * A new stroke begins only once the head has come back that far, so small tremors along the way are ignored.
 */
function strokes(points: Point[]): Stroke[] {
  const out: Stroke[] = [];
  let lo = points[0], hi = points[0];   // the extremes seen before any stroke has begun
  let from = points[0], far = points[0];
  let dir = 0;
  for (const p of points) {
    if (dir === 0) {
      if (p.v < lo.v) lo = p;
      if (p.v > hi.v) hi = p;
      if (p.v - lo.v >= MIN_SWING_DEG) { dir = 1; from = lo; far = p; }
      else if (hi.v - p.v >= MIN_SWING_DEG) { dir = -1; from = hi; far = p; }
    } else if ((p.v - far.v) * dir > 0) {
      far = p;
    } else if ((far.v - p.v) * dir >= MIN_SWING_DEG) {
      out.push({ start: from.t, end: far.t });
      from = far; far = p; dir = -dir;
    }
  }
  if (dir !== 0) out.push({ start: from.t, end: far.t });
  return out;
}

const spread = (values: number[]) => Math.max(...values) - Math.min(...values);

/** True when `axis` swung back and forth enough, and moved clearly more than `other` while it did. */
function swung(samples: HeadSample[], axis: "yaw" | "pitch", other: "yaw" | "pitch"): boolean {
  const needed = MIN_REVERSALS + 1;
  let run: Stroke[] = [], found: Stroke[] | null = null;
  for (const s of strokes(samples.map((p) => ({ t: p.t, v: p[axis] })))) {
    run = s.end - s.start >= MIN_SWING_MS ? [...run, s] : [];
    if (run.length >= needed) found = run.slice(-needed);
  }
  if (!found) return false;
  const start = found[0].start, end = found[needed - 1].end;
  const during = samples.filter((p) => p.t >= start && p.t <= end);
  return spread(during.map((p) => p[axis])) >= DOMINANCE * spread(during.map((p) => p[other]));
}

/**
 * Yaw and pitch from the head matrix the face tracker reports: sixteen numbers, column by column.
 * The third column is the way the nose points as the camera sees it, which is all a nod or a shake needs;
 * it is divided by its own length because the matrix also carries the size of the face.
 * Yaw is positive towards the camera's right and pitch is positive looking up. Null when the matrix is unusable.
 */
export function headAngles(matrix: ArrayLike<number>): { yaw: number; pitch: number } | null {
  const x = matrix[8], y = matrix[9], z = matrix[10];
  const length = Math.hypot(x, y, z);
  if (!(length > 0)) return null;
  const degrees = 180 / Math.PI;
  return { yaw: Math.atan2(x, z) * degrees, pitch: Math.asin(y / length) * degrees };
}

/** A nod, a shake, or nothing. `samples` are in time order, oldest first. */
export function classify(samples: readonly HeadSample[]): Gesture | null {
  if (samples.length < MIN_SAMPLES) return null;
  const now = recent(samples);
  if (now.length < MIN_SAMPLES) return null;
  const nod = swung(now, "pitch", "yaw"), shake = swung(now, "yaw", "pitch");
  // Both at once is a head doing something else; say nothing rather than guess.
  return nod === shake ? null : nod ? "nod" : "shake";
}

/**
 * Why a gesture may not be acted on now, or null when it may.
 * A gesture counts only while Brace is simply listening: never while Brace is speaking or thinking,
 * and never while the owner is being heard, because speech always wins over the camera.
 */
export function refusal(c: { on: boolean; voice: string; presence: string }): string | null {
  if (!c.on) return "no conversation";
  if (c.voice !== "live") return `voice is ${c.voice}`;
  if (c.presence !== "listening") return c.presence;
  return null;
}
