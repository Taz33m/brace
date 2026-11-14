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

/** The most recent priced sale CoStar records for a building. `basis` is how the price was established. */
export interface Sale { price: number; date: string; basis: string; portfolio: boolean }

export interface Row {
  last_sale: Sale | null;
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
  value: { buildings_with_sale: number; last_sale_total: number; allocated_share: number; oldest_sale: string | null };
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
  captured_at?: string | null;
  model_created_at?: string | null;
  association_basis?: string;
  rooms?: { id: string; label: string; type: string; floor_id: string | null; area_sqft: number; polygon: number[][] | null }[];
  floors?: { id: string; label: string | null; sequence: number; area_with_walls_sqft: number }[];
  origin: LonLat | null;
  sdk_yaw_offset: number | null;
  sweeps: { id: string; lon: number | null; lat: number | null; heading: number | null; room_id?: string | null; floor_id?: string | null; model_position?: {x: number | null; y: number | null; z: number | null} }[];
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
  interior: null | { scan_id: string; scan_name: string; sweep_id: string; direction: Direction; bearing: number | null; image: string; lon: number | null; lat: number | null };
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
  rent?: Rent | null;
  /** Which structures stand on the lowest ground, from the terrain model. */
  ground?: null | { lowest: { id: string; elevation_m: number; below_highest_m: number }[]; highest: { id: string; elevation_m: number }; spread_m: number; structures: number; source: string };
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
  last_sale: Sale | null;
  /** Rain that actually fell on this building's 10 km cell. Hindsight; shown only at the replay's final step. */
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

/** A window or door of a scanned space, placed in metres east and north of the scan's first viewpoint. */
export interface PlacedOpening {
  id: string; kind: "window" | "door"; room: string | null; width_m: number; height_m: number | null; sill_m: number | null;
  at: [number, number]; ends: [[number, number], [number, number]]; faces_deg: number;
  /** True when the opening is in an outer wall, or is a door onto a patio or balcony. */
  outside: boolean;
}

/** A scanned space as a plan drawn from its own wall measurements. */
export interface ScanPlan {
  scan_id: string; scan_name: string | null; placement_error_m: number;
  rooms: { id: string; name: string | null; walls: [[number, number], [number, number]][]; outdoor: boolean }[];
  openings: PlacedOpening[];
}

/** What in the nearest scanned space faces one outside action of the plan. */
export interface FacingHit {
  scan_id: string; metres: number; bearing_deg: number; line: string; target: { east: number; north: number };
  facing: { id: string; kind: string; room: string | null; width_m: number; height_m: number | null; metres: number; off_deg: number }[];
}

export interface Facing { plans: Record<string, ScanPlan>; actions: Record<string, FacingHit> }

/** One job in a saved plan, in the few fields needed to compare plans. */
export interface JobBrief { id: string; title: string; timing: Timing; crew: string; hours_of_work: number; cost_low: number; cost_high: number }

/** What became of each job between the plans saved for two forecast steps. A comparison of saved plans, not a new run. */
export interface ClockChange {
  replay: true;
  note: string;
  from: { step: string | null; label: string | null; hours_left: number | null; before_arrival: { count: number; cost_low: number; cost_high: number } };
  to: { step: string | null; label: string | null; hours_left: number | null; safe_working_hours: number | null; before_arrival: { count: number; cost_low: number; cost_high: number } };
  rows: { change: "deferred" | "still_fits" | "new" | "dropped" | "brought_forward"; before: JobBrief | null; after: JobBrief | null; reason: string | null }[];
  notice: { subject: string; action_ids: string[] } | null;
}

/** A forecast step that has a saved plan for a building. */
export interface SavedStep { step: string; label: string; hours_left: number | null; headline: string | null }

/** One source a fact rests on: whose data, which capture or scan, and when. */
export interface FactSource { id: string; provider?: string; what?: string; captured?: string; collection?: string; model?: string; name?: string; note?: string }
/** A measurement or finding with where it came from. */
export interface Measured { label: string; text: string; src: string[]; sources: FactSource[]; how?: string; limits?: string }
export type StageKey = "join" | "classify" | "inventory" | "expose" | "surface" | "search";
export interface Stage { key: StageKey; problem: string; job: string; state: "ready" | "partial" | "not_run"; number: number; unit: string; headline: string; limits?: string }
export interface SiteFact extends Measured { stage: StageKey; scan_id?: string; structure?: string; report?: boolean }
export interface ReportPlace { scan_id: string; scan_name: string; room: string | null; thing: string | null; position_id: string | null; bearing_deg?: number | null; matched_on?: string[]; placed_by?: string }
/** A resident's report checked against the scan, which was made before the storm. The verdict is decided by code from what the scan holds. */
export interface ReportCheck {
  verdict: "fits" | "wrong_place" | "cannot_tell"; says: string;
  because: { text?: string; value?: string; src?: string[] }[];
  view: { scan_id: string; position_id: string; bearing_deg: number } | null;
  before: (Record<string, unknown> & { basis?: string }) | null;
}
export interface ResidentReport { id: string; at: string; text: string; scan_id: string | null; where: ReportPlace | null; status: string; check?: ReportCheck | null }
export interface SiteModel {
  property_id: number; name: string; address: string; assembled_at: string;
  stages: Stage[]; facts: SiteFact[]; reports: ResidentReport[];
  scans: { id: string; name: string }[]; structures: { id: string }[];
  sources: Record<string, Omit<FactSource, "id">>;
}
export interface BoardStage { key: StageKey; problem: string; job: string; sites_ready: number; number: number; of: number; median_move_m?: number; largest_move_m?: number }
export interface Board {
  sites: number; stages: BoardStage[];
  rows: { property_id: number; name: string; address: string; scans: number; structures: number; stages: Record<StageKey, { state: Stage["state"]; number: number; headline: string }> }[];
}
export interface FindHit { scan_id: string; scan_name: string; room: string | null; thing: string | null; where: string; direction: string | null; phrase: string }

/** What came of approving an action. `delivery` is "resident_feed" when a notice was published to the building's households. */
export interface Approval { ok: boolean; say: string; delivery?: string | null; household_count?: number; already_published?: boolean; photon_queued?: number | null }

/** The site in three dimensions: a half-metre height grid with the aerial photo to drape over it. */
export interface SiteScene {
  property_id: number; name: string; homes: number | null;
  bounds: [number, number, number, number]; rows: number; cols: number; cell_m: [number, number];
  heights_url: string; texture_url: string; decode: { unit_m: number; what: string };
  sources: { heights: string; photo: string };
  structures: { id: string; polygon: [number, number][] | null; roof_height_m: number | null;
                tallest: null | { height_m: number; from_wall_m: number; above_roof_m: number; lon: number; lat: number; what: string | null } }[];
  positions: Record<string, { lon: number; lat: number; scan_id: string; scan_name: string | null }>;
  /** Each fitted scan: its floor plan where its own GPS put it, and where it sits once fitted under a roof. */
  fits: { scan_id: string; name: string | null; roof: string | null; moved_m: number; under_roof_before: number; under_roof_after: number;
          raw: [number, number][]; fitted: [number, number][] }[];
}

/** A scanned building as a place to find your way in. */
export interface PlacePosition { id: string; x: number; y: number; z: number; room_id: string | null; level: number | null; lon: number | null; lat: number | null; heading: number | null; sees: string[] }
export interface PlaceRoom { id: string; level: number | null; type: string | null; typed_by: string | null; confidence: string | null; area_sqft: number; positions: number; polygon: [number, number][] | null }
export interface Place { model_id: string; name: string; levels: { level: number; label: string; positions: number }[]; rooms: PlaceRoom[]; positions: PlacePosition[]; placed_by: string | null }
export interface PlaceAnswer {
  found: boolean; asked: string; event: string | null; say: string; place?: string; schedule_source?: string | null;
  room?: { id: string; type: string; typed_by: string | null; confidence: string | null; area_sqft: number; level: string | null; position_id: string; lon: number | null; lat: number | null };
  mover?: "walking" | "wheelchair"; chair_width_in?: number | null; no_way?: boolean; lifts_found?: number;
  /** For a wheelchair: what the walking way used that the chair cannot. */
  changed?: null | { instead_of: string; walking_metres: number; wheelchair_metres: number; walking_positions: string[]; flights_avoided: number; rise_avoided_m: number };
  route?: null | { mover: string; positions: string[]; metres: number; says?: string; levels_changed?: number; arrived: boolean; lift: boolean;
                   stairs: null | { flights: number; rise_m: number }; doorways: number; narrowest_doorway_in: number | null; narrowest_passage_m: number | null;
                   legs: { from: string; to: string; kind: "level" | "slope" | "step" | "stairs" | "lift"; metres: number; rise_m: number; level_change: number; bearing: number | null }[] };
}
/** What the headset last reported, for a second screen. */
export interface PlaceLive { rev: number; position?: string | null; yaw?: number | null; pitch?: number | null; mover?: "walking" | "wheelchair" | null; chair_in?: number | null; answer?: PlaceAnswer | null }

/** One room in three states: as scanned, cleared, and furnished again with generated models. */
export interface FurnishPiece { name: string; look: string | null; width_m: number; depth_m: number; height_m: number; stands_on_m: number; east_m: number; north_m: number; faces_deg: number; prompt: string; model: string | null }
export interface FurnishScene {
  scan_id: string; sweep_id: string; room: string | null; standpoint: { e: number; n: number; z: number; h: number }; view: { yaw_deg: number };
  pieces: FurnishPiece[]; contents: number; models_made: number; can_generate: boolean; service: string;
  labels: { as_it_was: string; cleared: string; furnished: string }; making: null | { running: boolean; made: string[]; stopped: string | null };
}

/** What a building's homes are advertised at, from its CoStar apartment listing. */
export interface Rent { low: number; high: number; currency: string; homes_listed: number | null; available: number | null; floor_plans: number; source: string }
export interface DeskJob { building_id: number; building: string; job_id: string; title: string; trade: string; hours: number; cost_low: number; cost_high: number; people: number;
  safe_until_h: number; crew?: number; start_h?: number; end_h?: number; start_local?: string; end_local?: string; reason?: string }
export interface DeskTrade { trade: string; crews: number; jobs: number; scheduled: DeskJob[]; deferred: DeskJob[]; people_covered: number; cost_low: number; cost_high: number }
export interface DeskSchedule { rule: string; trades: DeskTrade[]; forecast_issued_local: string; crews?: Record<string, number> }
export interface DeskBuilding { building_id: number; name: string; type: string; homes: number; tenants: number; hours_left: number; safe_crew_hours: number; lat: number | null; lon: number | null; rent: Rent | null }
/** What the storm desk decided for every building with a plan at one forecast step. */
export interface Desk {
  scenario: string; step: string; schedule: DeskSchedule; buildings: DeskBuilding[];
  run: null | { seconds: number; model: string; buildings_touched: number; what_more_crews_buy: DeskSchedule[]; statement: string; events: { kind: string }[] };
}
