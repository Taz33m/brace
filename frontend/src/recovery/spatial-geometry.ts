/** Source-coordinate transforms only; no guessed walls, routes or floor heights. */
export type Point2 = [number, number];
export function sourcePoint(value: unknown): Point2 | null {
  return Array.isArray(value) && value.length >= 2 && typeof value[0] === "number" && typeof value[1] === "number"
    && Number.isFinite(value[0]) && Number.isFinite(value[1]) ? [value[0], value[1]] : null;
}
export function sourceRing(value: unknown): Point2[] {
  if (!Array.isArray(value)) return [];
  const points = value.map(sourcePoint);
  return points.length >= 3 && points.every((point): point is Point2 => point !== null) ? points : [];
}
export function geographicPoint(value: unknown): Point2 | null {
  const point = sourcePoint(value);
  return point && Math.abs(point[0]) <= 180 && Math.abs(point[1]) <= 90 ? point : null;
}
export function meanPoint(points: Point2[]): Point2 {
  return points.length ? [points.reduce((sum, point) => sum + point[0], 0) / points.length,
    points.reduce((sum, point) => sum + point[1], 0) / points.length] : [0, 0];
}
export function siteMetres(point: Point2, origin: Point2): Point2 {
  return [(point[0] - origin[0]) * 111320 * Math.cos(origin[1] * Math.PI / 180), (point[1] - origin[1]) * 111320];
}
export function fitSource(points: Point2[], width = 800, height = 430, padding = 48) {
  if (!points.length) return null;
  const xs = points.map(point => point[0]), ys = points.map(point => point[1]);
  const minX = Math.min(...xs), maxX = Math.max(...xs), minY = Math.min(...ys), maxY = Math.max(...ys);
  const spanX = maxX - minX, spanY = maxY - minY;
  // A one-point source gets drawing padding, never an invented measured extent.
  const scale = Math.min((width - 2 * padding) / (spanX || 1), (height - 2 * padding) / (spanY || 1));
  const center: Point2 = [(minX + maxX) / 2, (minY + maxY) / 2];
  return { scale, width, height, spanX, spanY,
    project(point: Point2): Point2 { return [width / 2 + (point[0] - center[0]) * scale, height / 2 - (point[1] - center[1]) * scale]; } };
}
