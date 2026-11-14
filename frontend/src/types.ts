export type LonLat = [number, number];
export type Direction = "up" | "down" | "north" | "east" | "south" | "west";
export type Timing = "before_arrival" | "after_event" | "capital";

export interface Step { id: string; issued: string; label: string }
export interface Scenario {
  id: string;
  kind: "hurricane" | "wildfire";
  name: string;
  city: string;
  live: boolean;
  summary: string;
  steps: Step[];
}

/** GeoJSON geometry as the hazard feeds return it. */
export interface Geometry { type: string; coordinates: unknown }

export interface ScenarioMap {
  kind: "hurricane" | "wildfire";
  name: string;
  issued: string;
  center?: [number, number];
  max_wind_kt?: number;
  track?: { time: string; lat: number; lon: number; wind_kt: number; hours_from_issue: number }[];
  cone?: Geometry | null;
  wind_fields?: { kt: number; polygon: Geometry }[];
  landfall?: { time: string; lat: number; lon: number } | null;
  warning_polygons?: Geometry[];
  warning_text?: string;
  wind?: { gust_mph?: number; direction?: string } | null;
  fire_perimeters?: { name: string; polygon: Geometry }[];
}

export interface Exposure {
  kind: "hurricane" | "wildfire";
  peak_wind_mph?: number;
  wind_band?: string;
  hours_until_tropical_storm_wind?: number | null;
  closest_approach_km?: number;
  in_cone?: boolean;
  in_warning?: boolean;
  hours_until_warning?: number | null;
  warning_hours?: number | null;
}

export interface Row {
  id: number;
  rank: number;
  name: string;
  address: string;
  city: string;
  lat: number;
  lon: number;
  type_label: string;
  units: number | null;
  stories: number | null;
  year_built: number | null;
  tenant_count: number | null;
  manager: string | null;
  owner: string | null;
  photo: string | null;
  scans: number;
  exposure: Exposure;
  hours_left: number | null;
  reasons: string[];
  plan: { actions: number; headline: string | null } | null;
}

export interface Portfolio {
  scenario: string;
  step: string | null;
  touched: number;
  shown: number;
  homes: number;
  tenants: number;
  managers: { name: string; buildings: number }[];
  types: { name: string; buildings: number }[];
  buildings: Row[];
  /** [id, lat, lon, band, rank] for every touched building. */
  points: [number, number, number, string, number][];
}

export interface Structure {
  id: string;
  primary: boolean;
  footprint_sqft: number;
  roof_material: string | null;
  roof_condition: number | null;
  roof_defects: string[];
  roof_objects: Record<string, number>;
  polygon: LonLat[];
  centroid: LonLat;
}

export interface Scan {
  id: string;
  name: string;
  kind: string;
  level: number | null;
  structure: string | null;
  area_sqft: number | null;
  scanned: string;
  origin: LonLat | null;
  sdk_yaw_offset: number | null;
  sweeps: { id: string; lon: number | null; lat: number | null; heading: number | null }[];
}

export interface Threat {
  scenario_id: string;
  step_id: string | null;
  kind: "hurricane" | "wildfire";
  name: string;
  label: string | null;
  forecast_issued: string | null;
  replay: boolean;
  at_this_site: Exposure;
  hours_left: number | null;
  standing_risk: {
    fema: { zone: string; subtype: string | null; high_risk: boolean; floodway: boolean } | null;
    fire_zone: string | null;
    km_to_past_fire: number | null;
  };
}

export interface Lead {
  id: string;
  title: string;
  hazard: "wind" | "flood" | "fire" | "general";
  why: string;
  status: "open" | "actions" | "not_a_concern" | "cannot_check";
  note?: string;
  action_ids: string[];
}

export interface Action {
  id: string;
  lead_id: string;
  title: string;
  hazard: "wind" | "flood" | "fire" | "general";
  timing: Timing;
  hours_of_work: number;
  crew: string;
  cost_low: number;
  cost_high: number;
  why: string;
  basis: "seen" | "record";
  structure: string | null;
  site: null | { lon: number; lat: number; cell: string | null; image?: string; oblique_view?: string; oblique_image?: string };
  interior: null | { scan_id: string; scan_name: string; sweep_id: string; direction: Direction; image: string; lon: number | null; lat: number | null };
}

export interface Message { id: string; kind: "notice" | "work_order"; to: string; subject: string; body: string; action_ids: string[] }

export interface Plan {
  building_id: number;
  threat: Threat;
  stop: string;
  complete: boolean;
  seconds: number;
  headline: string | null;
  summary: string | null;
  actions: Action[];
  totals: Record<Timing, { count: number; cost_low: number; cost_high: number; hours: number }>;
  messages: Message[];
  leads: Lead[];
}

export interface Focus {
  lon?: number | null;
  lat?: number | null;
  cell?: string;
  structure?: string;
  scan_id?: string;
  sweep_id?: string;
  direction?: Direction;
}

export type AgentEvent =
  | { type: "status"; t: number; label: string }
  | { type: "thinking"; t: number; text: string }
  | { type: "note"; t: number; text: string }
  | { type: "step"; t: number; tool: string; label: string; image: string | null; focus: Focus | null }
  | { type: "lead"; t: number; lead: Lead }
  | { type: "lead_closed"; t: number; lead: Lead }
  | { type: "action"; t: number; action: Action }
  | { type: "message"; t: number; message: Message }
  | { type: "error"; t: number; message: string }
  | { type: "done"; t: number; stop: string; plan: Plan | null };

export interface Building {
  id: number;
  record: {
    name: string; address: string; city: string; state: string; zip: string; type_label: string; style: string | null;
    year_built: number | null; stories: number | null; gba_sqft: number | null; units: number | null;
    construction: string | null; contacts: Record<string, string>; tenant_count: number;
  };
  tenants: { name: string; employees: number | null; suite: string | null }[];
  site: { tree_cover_percent: number | null; roof_analysis_date: string | null; structure_count: number };
  structures: Structure[];
  aerial: { bounds: [number, number, number, number]; width: number; height: number; captured: string | null; obliques: string[] };
  scans: Scan[];
  threat: Threat;
  reasons: string[];
  plan: (Plan & { events: AgentEvent[] }) | null;
}

/** A place the user or the agent is pointing at on the site, and the scan view that goes with it when there is one. */
export interface Selection {
  lon: number;
  lat: number;
  label: string;
  structure: string | null;
  scanId: string | null;
  sweepId: string | null;
  direction: Direction;
}
