import type { Building, LonLat, Scan, Structure } from "./types";

const M_PER_DEG = 111_320;

/** Position on the site photo as fractions (0 to 1) of its width and height. */
export function toFrac(b: Building, lon: number, lat: number): [number, number] {
  const [w, s, e, n] = b.aerial.bounds;
  return [(lon - w) / (e - w), (n - lat) / (n - s)];
}

export function fromFrac(b: Building, fx: number, fy: number): LonLat {
  const [w, s, e, n] = b.aerial.bounds;
  return [w + fx * (e - w), n - fy * (n - s)];
}

export function metres(a: LonLat, b: LonLat): number {
  const kx = M_PER_DEG * Math.cos((a[1] * Math.PI) / 180);
  return Math.hypot((a[0] - b[0]) * kx, (a[1] - b[1]) * M_PER_DEG);
}

function inside(poly: LonLat[], p: LonLat): boolean {
  let hit = false;
  for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) {
    const [xi, yi] = poly[i];
    const [xj, yj] = poly[j];
    if (yi > p[1] !== yj > p[1] && p[0] < ((xj - xi) * (p[1] - yi)) / (yj - yi) + xi) hit = !hit;
  }
  return hit;
}

export function structureAt(b: Building, p: LonLat): Structure | null {
  return b.structures.find((s) => inside(s.polygon, p)) ?? null;
}

/** The scan position closest to a point on the site, across every scan that has a GPS fix. */
export function nearestScanView(b: Building, p: LonLat, withinM = 60): { scan: Scan; sweepId: string; distance: number } | null {
  let best: { scan: Scan; sweepId: string; distance: number } | null = null;
  for (const scan of b.scans) {
    for (const s of scan.sweeps) {
      if (s.lon == null || s.lat == null) continue;
      const d = metres(p, [s.lon, s.lat]);
      if (!best || d < best.distance) best = { scan, sweepId: s.id, distance: d };
    }
  }
  return best && best.distance <= withinM ? best : null;
}

export const BEARING = { north: 0, east: 90, south: 180, west: 270 } as const;
