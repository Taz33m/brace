import { useState } from "react";
import type { KeyboardEvent, ReactNode } from "react";
import type { LocationRef } from "../../../docs/recovery-handoffs/shared-contract";
import type { RecoverySpatial, SpatialScan } from "./spatial";
import { fitSource, geographicPoint, meanPoint, siteMetres, sourcePoint, sourceRing } from "./spatial-geometry";
import type { Point2 } from "./spatial-geometry";
import "./spatial-viewer.css";

export interface SpatialViewerProps {
  spatial: RecoverySpatial | null;
  selected_location: LocationRef | null;
  on_focus: (location: LocationRef) => void;
  mode: "site" | "interior";
}
type Sweep = NonNullable<SpatialScan["sweeps"]>[number] & {
  model_position?: { x?: number | null; y?: number | null; z?: number | null };
  lon?: number | null; lat?: number | null;
};
type Scan = SpatialScan & { origin?: number[] | null; floors?: { id: string; label?: string | null; sequence?: number }[] };
const dateLabel = (value: unknown): string => {
  if (typeof value !== "string" || !value) return "unknown";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "unknown" : date.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric", timeZone: "UTC" });
};
const rounded = (value: unknown) => typeof value === "number" && Number.isFinite(value) && value > 0 ? value.toLocaleString("en-US", { maximumFractionDigits: 0 }) : null;
const ringString = (points: Point2[]) => points.map(point => point.map(value => value.toFixed(2)).join(",")).join(" ");
function activate(event: KeyboardEvent<SVGElement>, callback: () => void) {
  if (event.key === "Enter" || event.key === " ") { event.preventDefault(); callback(); }
}
function fallbackLocation(id: string, label: string, values: Partial<LocationRef> = {}): LocationRef {
  return { location_id: id, label, structure_id: null, scan_id: null, sweep_id: null, room_id: null, unit_label: null,
    binding: "unverified", longitude: null, latitude: null, bearing_degrees: null, ...values };
}
function bindingLabel(location: LocationRef | null) {
  if (location?.binding === "verified_unit") return "Reviewed unit association";
  if (location?.binding === "verified_space") return "Reviewed space association";
  if (location?.binding === "representative_layout") return "Representative layout — exact unit not confirmed";
  return "Exact unit and structure association need review";
}

function Diagram({ title, children, focus, north, span }: { title: string; children: ReactNode; focus: Point2 | null; north?: boolean; span: number }) {
  const [zoom, setZoom] = useState(1);
  const width = 800 / zoom, height = 430 / zoom;
  const center = zoom > 1 && focus ? focus : [400, 215];
  const left = Math.max(0, Math.min(800 - width, center[0] - width / 2));
  const top = Math.max(0, Math.min(430 - height, center[1] - height / 2));
  return <div className="brace-spatial-canvas">
    <svg viewBox={`${left} ${top} ${width} ${height}`} aria-label={title} role="group" preserveAspectRatio="xMidYMid meet">
      <title>{title}</title>{children}
    </svg>
    {north && <span className="brace-spatial-north" aria-label="North is up">↑<b>N</b></span>}
    <div className="brace-spatial-zoom" aria-label="Diagram zoom">
      <button type="button" aria-label="Zoom in" disabled={zoom >= 4} onClick={() => setZoom(value => Math.min(4, value * 1.5))}>+</button>
      <button type="button" aria-label="Zoom out" disabled={zoom <= 1} onClick={() => setZoom(value => Math.max(1, value / 1.5))}>−</button>
      <button type="button" disabled={zoom === 1} onClick={() => setZoom(1)}>Fit</button>
    </div>
    <span className="brace-spatial-scale">{span > 0 ? `${(span / zoom).toLocaleString("en-US", { maximumFractionDigits: 1 })} m source span` : "One recorded position"}</span>
  </div>;
}

function SiteView({ spatial, selected_location, on_focus }: Omit<SpatialViewerProps, "mode"> & { spatial: RecoverySpatial }) {
  const structures = spatial.structures.map(structure => ({ structure, ring: sourceRing(structure.polygon) }))
    .filter(item => item.ring.length >= 3 && item.ring.every(point => geographicPoint(point)));
  const scans = spatial.locations.filter(location => location.scan_id && !location.sweep_id && geographicPoint([location.longitude, location.latitude]));
  const coordinates = [...structures.flatMap(item => item.ring), ...scans.map(location => [location.longitude!, location.latitude!] as Point2)];
  const origin = meanPoint(coordinates);
  const fit = fitSource(coordinates.map(point => siteMetres(point, origin)));
  const selected = structures.find(item => item.structure.id === selected_location?.structure_id)?.structure;
  const focusedGeo = geographicPoint([selected_location?.longitude, selected_location?.latitude])
    ?? geographicPoint(selected?.centroid);
  const project = (point: Point2) => fit!.project(siteMetres(point, origin));
  return <div className="brace-spatial-view">
    <div className="brace-spatial-heading"><div><span>Vexcel · site geometry</span><h3>Choose a structure</h3></div>
      <p>{structures.length} footprints · {scans.length} scan registrations</p></div>
    {fit ? <Diagram key={`${spatial.case_id}:site`} title="Recorded building footprints and scan registration points; north up" north
      span={fit.spanX} focus={focusedGeo ? project(focusedGeo) : null}>
      {structures.map(({ structure, ring }) => {
        const sourceCenter = geographicPoint(structure.centroid) ?? meanPoint(ring);
        const center = project(sourceCenter);
        const location = spatial.locations.find(row => row.structure_id === structure.id && !row.scan_id)
          ?? fallbackLocation(`structure:${structure.id}`, `Structure ${structure.id}`, { structure_id: structure.id, longitude: sourceCenter[0], latitude: sourceCenter[1] });
        const active = selected_location?.structure_id === structure.id;
        return <g key={structure.id}>
          <polygon className={`brace-spatial-footprint${active ? " is-selected" : ""}`} points={ringString(ring.map(project))}
            tabIndex={0} role="button" aria-pressed={active} aria-label={`Select structure ${structure.id}`}
            onClick={() => on_focus(location)} onKeyDown={event => activate(event, () => on_focus(location))}>
            <title>{structure.id} · {rounded(structure.footprint_sqft) ?? "unknown"} sq ft footprint · analysis {dateLabel(structure.roof_analysis_date)}</title>
          </polygon>
          <text className="brace-spatial-building-label" x={center[0]} y={center[1]}>{structure.id}</text>
        </g>;
      })}
      {scans.map(location => {
        const point = project([location.longitude!, location.latitude!]);
        const active = location.scan_id === selected_location?.scan_id;
        return <circle className={`brace-spatial-scan-point${active ? " is-selected" : ""}`} key={location.location_id}
          cx={point[0]} cy={point[1]} r={active ? 6 : 4} tabIndex={0} role="button" aria-pressed={active}
          aria-label={`Open registered scan ${location.label}; alignment needs review`}
          onClick={() => on_focus(location)} onKeyDown={event => activate(event, () => on_focus(location))}>
          <title>{location.label} · {bindingLabel(location)}</title>
        </circle>;
      })}
    </Diagram> : <p className="brace-spatial-empty">No footprint or scan coordinates are available for this case.</p>}
    <div className="brace-spatial-legend"><span><i className="footprint" />Recorded footprint</span><span><i className="scan" />Scan GPS — alignment unverified</span></div>
    {selected && <div className="brace-spatial-selection"><strong>Structure {selected.id}</strong>
      <span>{typeof selected.roof_material === "string" ? selected.roof_material : "Roof material unknown"}{rounded(selected.footprint_sqft) ? ` · ${rounded(selected.footprint_sqft)} sq ft footprint` : ""}</span>
      <span>Attribute analysis {dateLabel(selected.roof_analysis_date)} · not an incident damage finding</span></div>}
    <p className="brace-spatial-note">Click a footprint or scan point to focus the source evidence. Geometry comes from the registered source record; a nearby scan does not prove an occupied unit match.</p>
  </div>;
}

function InteriorView({ spatial, selected_location, on_focus }: Omit<SpatialViewerProps, "mode"> & { spatial: RecoverySpatial }) {
  const [chosen, setChosen] = useState<{ case_id: string; scan_id: string | null; floor_id: string | null }>({ case_id: spatial.case_id, scan_id: null, floor_id: null });
  const scans = spatial.scans as Scan[];
  const scan = scans.find(row => row.id === selected_location?.scan_id)
    ?? scans.find(row => chosen.case_id === spatial.case_id && row.id === chosen.scan_id) ?? scans[0];
  if (!scan) return <div className="brace-spatial-view"><div className="brace-spatial-heading"><div><span>Matterport · interior geometry</span><h3>Scanned spaces</h3></div></div>
    <p className="brace-spatial-empty">No eligible room or scan-position geometry is available. A resident can still describe a location in their report.</p></div>;
  const scanLocation = spatial.locations.find(row => row.scan_id === scan.id && !row.sweep_id)
    ?? fallbackLocation(`scan:${scan.id}`, scan.name || "Scanned space", { scan_id: scan.id });
  const allRooms = scan.rooms || [], allSweeps = (scan.sweeps || []) as Sweep[];
  const floorIds = [...new Set([...allRooms.map(room => room.floor_id ?? null), ...allSweeps.map(sweep => sweep.floor_id ?? null)])];
  if (floorIds.length === 0) floorIds.push(null);
  const selectedFloor = selected_location?.scan_id === scan.id
    ? allSweeps.find(row => row.id === selected_location.sweep_id)?.floor_id ?? allRooms.find(row => row.id === selected_location.room_id)?.floor_id : undefined;
  const chosenFloor = chosen.case_id === spatial.case_id && chosen.scan_id === scan.id ? chosen.floor_id : undefined;
  const floor = chosenFloor !== undefined && floorIds.includes(chosenFloor) ? chosenFloor
    : selectedFloor !== undefined && floorIds.includes(selectedFloor) ? selectedFloor : floorIds[0];
  const rooms = allRooms.filter(room => (room.floor_id ?? null) === floor).map(room => ({ room, ring: sourceRing(room.polygon) }));
  const outlinedRooms = rooms.filter(item => item.ring.length > 0);
  const sweeps = allSweeps.filter(sweep => (sweep.floor_id ?? null) === floor)
    .map(sweep => ({ sweep, point: sourcePoint([sweep.model_position?.x, sweep.model_position?.y]) }))
    .filter((item): item is { sweep: Sweep; point: Point2 } => item.point !== null);
  const fit = fitSource([...outlinedRooms.flatMap(item => item.ring), ...sweeps.map(item => item.point)]);
  const focused = sweeps.find(item => item.sweep.id === selected_location?.sweep_id)?.point
    ?? outlinedRooms.find(item => item.room.id === selected_location?.room_id)?.ring[0] ?? null;
  const roomLocation = (roomId: string, label: string) => spatial.locations.find(row => row.scan_id === scan.id && row.room_id === roomId)
    ?? { ...scanLocation, location_id: `scan:${scan.id}:room:${roomId}`, label, room_id: roomId, sweep_id: null,
      longitude: null, latitude: null };
  return <div className="brace-spatial-view">
    <div className="brace-spatial-heading"><div><span>Matterport · recorded model geometry</span><h3>Explore the scanned space</h3></div></div>
    <div className="brace-spatial-controls"><label>Scanned space<select value={scan.id} onChange={event => {
      const next = spatial.locations.find(row => row.scan_id === event.target.value && !row.sweep_id);
      setChosen({ case_id: spatial.case_id, scan_id: event.target.value, floor_id: null });
      if (next) on_focus(next);
    }}>{scans.map(row => <option key={row.id} value={row.id}>{row.name || row.id}</option>)}</select></label>
      {floorIds.length > 1 && <label>Scan level<select value={floor ?? ""} onChange={event => setChosen({ case_id: spatial.case_id, scan_id: scan.id, floor_id: event.target.value || null })}>
        {floorIds.map((id, index) => <option key={id ?? "unassigned"} value={id ?? ""}>{scan.floors?.find(row => row.id === id)?.label || (id === null ? "Unassigned level" : `Scan level ${index + 1}`)}</option>)}
      </select></label>}</div>
    {fit ? <Diagram key={`${spatial.case_id}:${scan.id}:${floor}`} title="Matterport room outlines and recorded scan viewpoints in model coordinates"
      span={fit.spanX} focus={focused ? fit.project(focused) : null}>
      {outlinedRooms.map(({ room, ring }) => {
        const label = room.label || (room.type && room.type !== "Unlabelled" ? room.type : "Unlabelled room");
        const center = fit.project(meanPoint(ring));
        const active = selected_location?.scan_id === scan.id && selected_location?.room_id === room.id;
        const location = roomLocation(room.id, label);
        return <g key={room.id}><polygon points={ringString(ring.map(fit.project))} className={`brace-spatial-room${active ? " is-selected" : ""}`}
          tabIndex={0} role="button" aria-label={`Focus ${label}`} aria-pressed={active}
          onClick={() => on_focus(location)} onKeyDown={event => activate(event, () => on_focus(location))}>
          <title>{label}{rounded(room.area_sqft) ? ` · ${rounded(room.area_sqft)} sq ft` : " · area unknown"}</title></polygon>
          <text className="brace-spatial-room-label" x={center[0]} y={center[1]}>{label}</text></g>;
      })}
      {sweeps.map(({ sweep, point }, index) => {
        const projected = fit.project(point);
        const location = spatial.locations.find(row => row.scan_id === scan.id && row.sweep_id === sweep.id)
          ?? { ...scanLocation, location_id: `scan:${scan.id}:sweep:${sweep.id}`, sweep_id: sweep.id, room_id: sweep.room_id ?? null,
            longitude: sweep.lon ?? null, latitude: sweep.lat ?? null };
        const active = selected_location?.scan_id === scan.id && selected_location?.sweep_id === sweep.id;
        return <g key={sweep.id}><circle cx={projected[0]} cy={projected[1]} r={active ? 7 : 5}
          className={`brace-spatial-viewpoint${active ? " is-selected" : ""}`} tabIndex={0} role="button" aria-pressed={active}
          aria-label={`Focus scan viewpoint ${index + 1}${location.label ? ` in ${location.label}` : ""}`}
          onClick={() => on_focus(location)} onKeyDown={event => activate(event, () => on_focus(location))}>
          <title>{location.label} · recorded viewpoint {index + 1}</title></circle>
          {active && <text className="brace-spatial-point-label" x={projected[0] + 12} y={projected[1] - 12}>View {index + 1}</text>}</g>;
      })}
    </Diagram> : <p className="brace-spatial-empty">This scan has no usable room outlines or model coordinates. Open its source imagery to inspect the space.</p>}
    <div className="brace-spatial-legend"><span><i className="footprint" />{outlinedRooms.length} recorded room outlines</span><span><i className="scan" />{sweeps.length} recorded viewpoints</span><span>Model x/y axes · metres</span></div>
    {!outlinedRooms.length && sweeps.length > 0 && <p className="brace-spatial-note">Room boundaries are unavailable for this scan. The dots show the actual capture positions; no walls or walkable routes have been inferred.</p>}
    <div className="brace-spatial-selection"><strong>{scan.name || "Scanned space"}</strong><span>{bindingLabel(scanLocation)}</span>
      <span>Capture {dateLabel(scan.captured_at)} · model created {dateLabel(scan.model_created_at)}</span></div>
  </div>;
}

export function SpatialViewer(props: SpatialViewerProps) {
  if (!props.spatial) return <div className="brace-spatial-view"><p className="brace-spatial-empty">Spatial sources are unavailable for this case revision.</p></div>;
  const scopedSelection = props.selected_location && props.spatial.locations.some(location => location.location_id === props.selected_location?.location_id
    || (location.scan_id && location.scan_id === props.selected_location?.scan_id)) ? props.selected_location : null;
  const common = { ...props, spatial: props.spatial, selected_location: scopedSelection };
  return props.mode === "site" ? <SiteView {...common} /> : <InteriorView {...common} />;
}
