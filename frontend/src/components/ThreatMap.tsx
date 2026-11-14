import L from "leaflet";
import "leaflet/dist/leaflet.css";
import { useEffect, useMemo, useRef } from "react";
import type { Portfolio, ScenarioMap } from "../types";

// The map at night: a dark ink base, the forecast drawn in light, and every building a point of colour.
const BAND_COLOR: Record<string, string> = {
  hurricane: "#ff4d5a",
  "strong tropical storm": "#ff9a3c",
  "tropical storm": "#ffd23f",
  warning: "#ff5a4d",
  watch: "#ffb347",
};
const BAND_LABEL: Record<string, string> = {
  hurricane: "Hurricane wind",
  "strong tropical storm": "Strong tropical storm wind",
  "tropical storm": "Tropical storm wind",
  warning: "Under the warning",
  watch: "Under the watch",
};
const BAND_ORDER = ["hurricane", "strong tropical storm", "tropical storm", "warning", "watch"];
const FIELD_COLOR: Record<number, string> = { 34: "#f0b429", 50: "#f2792b", 64: "#e5383b" };
const QUIET = "#8a8f98";

interface Props {
  map: ScenarioMap | null;
  points: Portfolio["points"];
  highlight: number | null;
  onOpen: (id: number) => void;
}

/** The forecast drawn over the metro: track, cone and wind fields (or warning areas), and every building it touches. */
export function ThreatMap({ map, points, highlight, onOpen }: Props) {
  const el = useRef<HTMLDivElement>(null);
  const lmap = useRef<L.Map | null>(null);
  const threat = useRef<L.LayerGroup | null>(null);
  const dots = useRef<L.LayerGroup | null>(null);
  const markers = useRef<Map<number, L.CircleMarker>>(new Map());
  const fitted = useRef<string | null>(null);
  const open = useRef(onOpen);
  open.current = onOpen;

  useEffect(() => {
    if (!el.current || lmap.current) return;
    const m = L.map(el.current, { zoomControl: true, preferCanvas: true, attributionControl: true }).setView([29.76, -95.37], 9);
    const esri = "https://server.arcgisonline.com/ArcGIS/rest/services/Canvas";
    L.tileLayer(`${esri}/World_Dark_Gray_Base/MapServer/tile/{z}/{y}/{x}`, { maxZoom: 16, attribution: "Tiles &copy; Esri" }).addTo(m);
    L.tileLayer(`${esri}/World_Dark_Gray_Reference/MapServer/tile/{z}/{y}/{x}`, { maxZoom: 16, opacity: 0.55 }).addTo(m);
    threat.current = L.layerGroup().addTo(m);
    dots.current = L.layerGroup().addTo(m);
    lmap.current = m;
    return () => { m.remove(); lmap.current = null; };
  }, []);

  useEffect(() => {
    const g = threat.current;
    if (!g) return;
    g.clearLayers();
    if (!map) return;
    const geo = (geometry: unknown, style: L.PathOptions) =>
      L.geoJSON({ type: "Feature", properties: {}, geometry } as GeoJSON.Feature, { style: () => style, interactive: false }).addTo(g);
    if (map.kind === "hurricane") {
      // The cone is the line the eye follows: white, like a boundary drawn on the map by hand.
      if (map.cone) geo(map.cone, { color: "#f4f1ea", weight: 2, fillColor: "#f4f1ea", fillOpacity: 0.035 });
      for (const f of [...(map.wind_fields ?? [])].sort((a, b) => a.kt - b.kt)) {
        geo(f.polygon, { color: FIELD_COLOR[f.kt] ?? QUIET, weight: 1.5, opacity: 0.9, fillColor: FIELD_COLOR[f.kt] ?? QUIET, fillOpacity: 0.2 });
      }
      const track = map.track ?? [];
      if (track.length > 1) L.polyline(track.map((p) => [p.lat, p.lon] as [number, number]), { color: "#f4f1ea", weight: 2, opacity: 0.85, dashArray: "2 7" }).addTo(g);
      for (const p of track) {
        L.circleMarker([p.lat, p.lon], { radius: 4, color: "#14110f", weight: 1.5, fillColor: "#f4f1ea", fillOpacity: 1 })
          .bindTooltip(`${p.hours_from_issue <= 0 ? "Now" : `+${Math.round(p.hours_from_issue)} h`}: ${Math.round(p.wind_kt * 1.15078)} mph`).addTo(g);
      }
    } else {
      for (const w of map.warning_polygons ?? []) geo(w, { color: "#f4f1ea", weight: 2, fillColor: "#ff5a4d", fillOpacity: 0.1 });
      for (const f of map.fire_perimeters ?? []) {
        L.geoJSON({ type: "Feature", properties: {}, geometry: f.polygon } as GeoJSON.Feature,
          { style: () => ({ color: "#ff8a3c", weight: 1.5, fillColor: "#f2601d", fillOpacity: 0.6 }) })
          .bindTooltip(`${f.name} (what burned afterwards)`).addTo(g);
      }
    }
  }, [map]);

  useEffect(() => {
    const g = dots.current, m = lmap.current;
    if (!g || !m) return;
    g.clearLayers();
    markers.current.clear();
    // Draw the least pressing first so the most pressing sit on top.
    for (const [id, lat, lon, band, rank] of [...points].sort((a, b) => b[4] - a[4])) {
      const c = L.circleMarker([lat, lon], {
        radius: rank <= 25 ? 5.5 : 3, stroke: rank <= 25, color: "#14110f", weight: 1, fillColor: BAND_COLOR[band] ?? QUIET, fillOpacity: rank <= 25 ? 1 : 0.85,
      }).on("click", () => open.current(id)).addTo(g);
      markers.current.set(id, c);
    }
    const key = `${map?.name}:${points.length > 0}`;
    if (points.length && fitted.current !== key) {
      fitted.current = key;
      m.fitBounds(L.latLngBounds(points.map((p) => [p[1], p[2]] as [number, number])).pad(0.45));
    }
  }, [points, map?.name]);

  useEffect(() => {
    const top = new Set(points.filter((p) => p[4] <= 25).map((p) => p[0]));
    markers.current.forEach((c, id) => c.setStyle(id === highlight
      ? { radius: 11, stroke: true, weight: 3, color: "#ffffff" }
      : { radius: top.has(id) ? 5.5 : 3, stroke: top.has(id), weight: 1, color: "#14110f" }));
    if (highlight != null) markers.current.get(highlight)?.bringToFront();
  }, [highlight, points]);

  // What the colours mean, counted from the buildings on the map.
  const tally = useMemo(() => {
    const count = new Map<string, number>();
    for (const p of points) count.set(p[3], (count.get(p[3]) ?? 0) + 1);
    return [...count.entries()].sort((a, b) => (BAND_ORDER.indexOf(a[0]) + 99) % 99 - (BAND_ORDER.indexOf(b[0]) + 99) % 99);
  }, [points]);

  return (
    <div className="threat-map">
      <div className="threat-canvas" ref={el} aria-label="Map of the forecast and the buildings it touches" />
      {tally.length > 0 && (
        <dl className="threat-tally" aria-label="Buildings by forecast">
          {tally.map(([band, n]) => (
            <div key={band}>
              <dt><i style={{ background: BAND_COLOR[band] ?? QUIET }} />{n.toLocaleString()}</dt>
              <dd>{BAND_LABEL[band] ?? band}</dd>
            </div>
          ))}
        </dl>
      )}
    </div>
  );
}
