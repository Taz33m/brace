import L from "leaflet";
import "leaflet/dist/leaflet.css";
import { useEffect, useRef } from "react";
import type { Portfolio, ScenarioMap } from "../types";

const BAND_COLOR: Record<string, string> = {
  hurricane: "#c2223a",
  "strong tropical storm": "#e2702a",
  "tropical storm": "#d9a514",
  warning: "#c2223a",
};
const FIELD_COLOR: Record<number, string> = { 34: "#e6b422", 50: "#e2702a", 64: "#c2223a" };

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
    L.tileLayer("https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png", {
      maxZoom: 18, subdomains: "abcd",
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors &copy; <a href="https://carto.com/attributions">CARTO</a>',
    }).addTo(m);
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
      if (map.cone) geo(map.cone, { color: "#14202b", weight: 1, dashArray: "5 5", fillColor: "#14202b", fillOpacity: 0.05 });
      for (const f of [...(map.wind_fields ?? [])].sort((a, b) => a.kt - b.kt)) {
        geo(f.polygon, { color: FIELD_COLOR[f.kt] ?? "#888", weight: 1, fillColor: FIELD_COLOR[f.kt] ?? "#888", fillOpacity: 0.16 });
      }
      const track = map.track ?? [];
      if (track.length > 1) L.polyline(track.map((p) => [p.lat, p.lon] as [number, number]), { color: "#14202b", weight: 2 }).addTo(g);
      for (const p of track) {
        L.circleMarker([p.lat, p.lon], { radius: 4, color: "#14202b", weight: 1.5, fillColor: "#fff", fillOpacity: 1 })
          .bindTooltip(`${p.hours_from_issue <= 0 ? "Now" : `+${Math.round(p.hours_from_issue)} h`}: ${Math.round(p.wind_kt * 1.15078)} mph`).addTo(g);
      }
    } else {
      for (const w of map.warning_polygons ?? []) geo(w, { color: "#c2223a", weight: 1.5, fillColor: "#c2223a", fillOpacity: 0.1 });
      for (const f of map.fire_perimeters ?? []) {
        L.geoJSON({ type: "Feature", properties: {}, geometry: f.polygon } as GeoJSON.Feature,
          { style: () => ({ color: "#5a2a12", weight: 1, fillColor: "#5a2a12", fillOpacity: 0.35 }) })
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
        radius: rank <= 25 ? 6 : 4, color: "#fff", weight: 1, fillColor: BAND_COLOR[band] ?? "#6b7785", fillOpacity: 0.9,
      }).on("click", () => open.current(id)).addTo(g);
      markers.current.set(id, c);
    }
    const key = `${map?.name}:${points.length > 0}`;
    if (points.length && fitted.current !== key) {
      fitted.current = key;
      m.fitBounds(L.latLngBounds(points.map((p) => [p[1], p[2]] as [number, number])).pad(0.15));
    }
  }, [points, map?.name]);

  useEffect(() => {
    markers.current.forEach((c, id) => c.setStyle(id === highlight ? { radius: 10, weight: 3, color: "#14202b" } : { radius: 5, weight: 1, color: "#fff" }));
    if (highlight != null) markers.current.get(highlight)?.bringToFront();
  }, [highlight]);

  return <div className="threat-map" ref={el} aria-label="Map of the forecast and the buildings it touches" />;
}
