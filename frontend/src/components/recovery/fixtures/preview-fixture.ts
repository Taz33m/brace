/**
 * Synthetic UI fixture for the owner recovery workspace.
 *
 * Opt-in only: used by RecoveryPreview.tsx and tests. It is NEVER a fallback
 * when real calls fail. Every ID, name, address, price and image here is made
 * up and labelled as a fixture; nothing describes a real property.
 */
import type {
  Assessment,
  Assumption,
  CaseEvent,
  CaseMode,
  Comparable,
  Evidence,
  LocationRef,
  MediaRef,
  MoneyRange,
  Observation,
  OwnerCaseView,
  PublishedNotice,
  RecoveryCaseSummary,
  RecoveryTask,
  RepairLine,
  ResidentReport,
  SupportReceipt,
  ValuationResult,
  ValueBasis,
} from "../../../recovery/contracts";

export const FIXTURE_LABEL = "UI fixture — not a property assessment";

export type FixtureVariant = "full" | "conditional" | "insufficient" | "stale" | "empty";

export const FIXTURE_VARIANTS: readonly FixtureVariant[] = ["full", "conditional", "insufficient", "stale", "empty"];

const DEFAULT_CASE_ID = "fx-case-1";

/* ------------------------------------------------------------------ helpers */

function deepCopy<T>(value: T): T {
  return JSON.parse(JSON.stringify(value)) as T;
}

type RangeKind = MoneyRange["range_kind"];

function money(
  low: number | null,
  high: number | null,
  point: number | null,
  basis: ValueBasis,
  range_kind: RangeKind,
  method: string,
  source_ids: string[],
): MoneyRange {
  return { currency: "USD", low, high, point, basis, range_kind, method, source_ids, unavailable_reason: null };
}

function noMoney(basis: ValueBasis, range_kind: RangeKind, method: string, reason: string, source_ids: string[] = []): MoneyRange {
  return { currency: "USD", low: null, high: null, point: null, basis, range_kind, method, source_ids, unavailable_reason: reason };
}

/** Small inline SVG "image", always stamped SYNTHETIC FIXTURE. */
function svgUri(caption: string, body: string): string {
  const svg =
    "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 320 200' width='320' height='200'>" +
    "<rect width='320' height='200' fill='#d9d3c4'/>" +
    body +
    "<rect width='320' height='22' fill='#222' fill-opacity='.75'/>" +
    `<text x='8' y='15' font-family='sans-serif' font-size='11' fill='#fff'>${caption}</text>` +
    "<text x='160' y='190' font-family='sans-serif' font-size='13' font-weight='700' text-anchor='middle' fill='#b81f35'>SYNTHETIC FIXTURE</text>" +
    "</svg>";
  return "data:image/svg+xml," + encodeURIComponent(svg);
}

const ROOF_BASE =
  "<rect x='50' y='40' width='220' height='120' fill='#8a8577' stroke='#4a463d' stroke-width='2'/>" +
  "<line x1='50' y1='100' x2='270' y2='100' stroke='#4a463d' stroke-width='2'/>" +
  "<rect x='80' y='55' width='22' height='14' fill='#6d695e'/>" +
  "<rect x='80' y='125' width='22' height='14' fill='#6d695e'/>";

function media(media_id: string, caption: string, body: string, alt: string): MediaRef {
  return { media_id, url: svgUri(caption, body), alt: `${alt} (synthetic fixture image)`, mime_type: "image/svg+xml" };
}

const mediaRef = {
  roofBefore: () =>
    media("fx-media-roof-before", "Roof plan 2024-05-18 (before)", ROOF_BASE, "Roof plan before the incident, membrane intact"),
  roofAfter: () =>
    media(
      "fx-media-roof-after",
      "Roof plan 2024-07-11 (after)",
      ROOF_BASE +
        "<polygon points='170,44 262,46 264,98 176,96' fill='#3b3a36'/>" +
        "<rect x='182' y='52' width='72' height='38' fill='#1d5fbf' fill-opacity='.85' stroke='#fff' stroke-dasharray='4 3'/>" +
        "<text x='218' y='75' font-family='sans-serif' font-size='10' text-anchor='middle' fill='#fff'>TARP</text>",
      "Roof plan after the incident, east-wing membrane torn and covered by a tarp",
    ),
  interior2b: () =>
    media(
      "fx-media-mp-2b",
      "Interior scan, unit 2B living room",
      "<polygon points='40,40 280,40 250,80 70,80' fill='#efe9dc'/>" +
        "<rect x='70' y='80' width='180' height='90' fill='#c9c1ae'/>" +
        "<ellipse cx='175' cy='58' rx='34' ry='10' fill='#8b6f47' fill-opacity='.7'/>",
      "Interior scan of the unit 2B living room with a ceiling stain",
    ),
  layout3c: () =>
    media(
      "fx-media-mp-layout",
      "Representative layout (sister unit)",
      "<rect x='60' y='40' width='200' height='130' fill='#efe9dc' stroke='#4a463d' stroke-width='2'/>" +
        "<line x1='160' y1='40' x2='160' y2='170' stroke='#4a463d' stroke-width='2'/>" +
        "<rect x='70' y='50' width='60' height='18' fill='#9a917d'/>",
      "Floor plan of a sister unit used as a representative layout",
    ),
  residentCeiling: (media_id: string) =>
    media(
      media_id,
      "Resident photo, unit 2B ceiling",
      "<rect x='20' y='30' width='280' height='140' fill='#eee8da'/>" +
        "<ellipse cx='160' cy='95' rx='70' ry='34' fill='#8b6f47' fill-opacity='.6'/>" +
        "<circle cx='170' cy='100' r='5' fill='#5a4630'/>",
      "Resident photo of a water stain on the unit 2B ceiling",
    ),
  tarpInspection: () =>
    media(
      "fx-media-tarp-inspection",
      "Inspection photo, tarp secured",
      "<rect x='30' y='50' width='260' height='110' fill='#8a8577'/>" +
        "<rect x='70' y='65' width='180' height='80' fill='#1d5fbf' fill-opacity='.85'/>" +
        "<circle cx='75' cy='70' r='4' fill='#fff'/><circle cx='245' cy='70' r='4' fill='#fff'/>" +
        "<circle cx='75' cy='140' r='4' fill='#fff'/><circle cx='245' cy='140' r='4' fill='#fff'/>",
      "Inspection photo of the tarp secured over the east wing",
    ),
  gutter: () =>
    media(
      "fx-media-gutter-done",
      "Contractor photo, gutter rehung",
      "<rect x='20' y='60' width='280' height='16' fill='#6d695e'/>" +
        "<rect x='20' y='76' width='280' height='10' fill='#9a917d'/>" +
        "<rect x='250' y='86' width='10' height='70' fill='#9a917d'/>",
      "Contractor photo of the rehung gutter",
    ),
};

/* --------------------------------------------------------------- locations */

function location(key: "roof" | "unit2b" | "layout3c" | "basement" | "stair"): LocationRef {
  switch (key) {
    case "roof":
      return {
        location_id: "fx-loc-roof-east",
        label: "Roof, east wing (fixture)",
        structure_id: "fx-struct-main",
        scan_id: null,
        sweep_id: null,
        room_id: null,
        unit_label: null,
        binding: "verified_space",
        longitude: 0.0012,
        latitude: 0.0008,
        bearing_degrees: 90,
      };
    case "unit2b":
      return {
        location_id: "fx-loc-unit-2b-living",
        label: "Unit 2B, living room (fixture)",
        structure_id: "fx-struct-main",
        scan_id: "fx-scan-unit-2b",
        sweep_id: "fx-sweep-2b-04",
        room_id: "fx-room-2b-living",
        unit_label: "2B",
        binding: "verified_unit",
        longitude: null,
        latitude: null,
        bearing_degrees: 210,
      };
    case "layout3c":
      return {
        location_id: "fx-loc-unit-3c-kitchen",
        label: "Unit 3C, kitchen (layout of a sister unit)",
        structure_id: "fx-struct-main",
        scan_id: "fx-scan-typical-a",
        sweep_id: "fx-sweep-typ-a-02",
        room_id: "fx-room-typ-a-kitchen",
        unit_label: "3C",
        binding: "representative_layout",
        longitude: null,
        latitude: null,
        bearing_degrees: null,
      };
    case "basement":
      return {
        location_id: "fx-loc-basement-storage",
        label: "Basement storage (not scanned)",
        structure_id: "fx-struct-main",
        scan_id: null,
        sweep_id: null,
        room_id: null,
        unit_label: null,
        binding: "unmapped",
        longitude: null,
        latitude: null,
        bearing_degrees: null,
      };
    case "stair":
      return {
        location_id: "fx-loc-stair-b",
        label: "Stairwell B landing (fixture)",
        structure_id: "fx-struct-main",
        scan_id: "fx-scan-common",
        sweep_id: "fx-sweep-common-07",
        room_id: null,
        unit_label: null,
        binding: "unverified",
        longitude: null,
        latitude: null,
        bearing_degrees: 0,
      };
  }
}

/* ------------------------------------------------------------------- cases */

type CaseSeed = Pick<
  RecoveryCaseSummary,
  "case_id" | "property_ref" | "property_name" | "address" | "city" | "incident_name" | "incident_at" | "assessment_as_of" | "mode" | "mode_label" | "next_action"
>;

const MODE_LABEL: Record<CaseMode, string> = {
  observed_recovery: "Observed recovery",
  historical_replay: "Historical replay",
  scenario_exercise: "Scenario exercise",
};

function caseSeeds(): CaseSeed[] {
  return [
    {
      case_id: "fx-case-1",
      property_ref: { dataset: "residential_property", id: "fx-prop-a" },
      property_name: "Sample Apartments A (fixture)",
      address: "100 Example Avenue (fixture)",
      city: "Sampleville, NJ",
      incident_name: "Synthetic storm cell (fixture incident)",
      incident_at: "2024-07-08",
      assessment_as_of: "2024-07-12",
      mode: "observed_recovery",
      mode_label: MODE_LABEL.observed_recovery,
      next_action: "Review the unit 2B ceiling report against the interior scan",
    },
    {
      case_id: "fx-case-2",
      property_ref: { dataset: "commercial_property", id: "fx-prop-b" },
      property_name: "Sample Office Building B (fixture)",
      address: "200 Placeholder Road (fixture)",
      city: "Testburg, NJ",
      incident_name: "Replayed windstorm (fixture incident)",
      incident_at: "2024-07-08T04:15:00-04:00",
      assessment_as_of: "2024-07",
      mode: "historical_replay",
      mode_label: MODE_LABEL.historical_replay,
      next_action: "Compare the replayed assessment with the knowledge cutoff",
    },
    {
      case_id: "fx-case-3",
      property_ref: { dataset: "residential_property", id: "fx-prop-c" },
      property_name: "Sample Townhomes C (fixture)",
      address: "300 Demo Lane (fixture)",
      city: "Mockton, NJ",
      incident_name: "Hypothetical roof failure drill (fixture exercise)",
      incident_at: "2024-07-08",
      assessment_as_of: "2024-07-12",
      mode: "scenario_exercise",
      mode_label: MODE_LABEL.scenario_exercise,
      next_action: "Walk through the exercise task list with the response team",
    },
  ];
}

/* ---------------------------------------------------------------- evidence */

function evidenceList(): Evidence[] {
  const base = { model_created_at: null, limitations: [] as string[] };
  return [
    {
      ...base,
      evidence_id: "fx-ev-costar-subject",
      kind: "costar_record",
      source_id: "fx-src-costar-subject",
      source_label: "Synthetic property record (fixture)",
      captured_at: null,
      effective_at: "2024-03",
      available_at: "2024-03-15",
      received_at: "2024-07-08T14:20:00Z",
      location: null,
      media: null,
      summary: "48 units, built 1987, three storeys over a basement. Synthetic record for UI testing.",
      limitations: ["Unit count and year built are fixture values."],
    },
    {
      ...base,
      evidence_id: "fx-ev-costar-comps",
      kind: "costar_record",
      source_id: "fx-src-costar-comps",
      source_label: "Synthetic comparable sales extract (fixture)",
      captured_at: null,
      effective_at: "2024-06-30",
      available_at: "2024-07-01",
      received_at: "2024-07-08T18:05:00Z",
      location: null,
      media: null,
      summary: "Five synthetic multifamily sales within a made-up 36-month window.",
    },
    {
      ...base,
      evidence_id: "fx-ev-aerial-before",
      kind: "vexcel_image",
      source_id: "fx-src-vexcel-2024-05-18",
      source_label: "Synthetic aerial capture, nadir (fixture)",
      captured_at: "2024-05-18",
      effective_at: "2024-05-18",
      available_at: "2024-05-25",
      received_at: "2024-07-08T19:00:00Z",
      location: location("roof"),
      media: mediaRef.roofBefore(),
      summary: "Pre-incident roof plan. Membrane appears continuous over the east wing.",
    },
    {
      ...base,
      evidence_id: "fx-ev-aerial-after",
      kind: "vexcel_image",
      source_id: "fx-src-vexcel-2024-07-11",
      source_label: "Synthetic aerial capture, nadir (fixture)",
      captured_at: "2024-07-11T15:42:00Z",
      effective_at: "2024-07-11",
      available_at: "2024-07-12T08:00:00Z",
      received_at: "2024-07-12T09:10:00Z",
      location: location("roof"),
      media: mediaRef.roofAfter(),
      summary: "Post-incident roof plan. Torn membrane on the east wing, partly covered by a tarp.",
      limitations: ["Capture angle differs slightly from the May capture; edges are approximate."],
    },
    {
      ...base,
      evidence_id: "fx-ev-aerial-oblique",
      kind: "vexcel_image",
      source_id: "fx-src-vexcel-oblique-2024-07-11",
      source_label: "Synthetic aerial capture, east oblique (fixture)",
      captured_at: "2024-07-11",
      effective_at: null,
      available_at: null,
      received_at: "2024-07-12T09:10:00Z",
      location: location("roof"),
      media: null,
      summary: "Oblique capture is listed in the catalog but no image was delivered.",
      limitations: ["Image not delivered; nothing to compare."],
    },
    {
      ...base,
      evidence_id: "fx-ev-mp-2b",
      kind: "matterport_view",
      source_id: "fx-src-scan-unit-2b",
      source_label: "Synthetic interior scan, unit 2B (fixture)",
      captured_at: "2023-11-02",
      effective_at: null,
      available_at: "2023-11-03",
      received_at: "2024-07-09T10:00:00Z",
      model_created_at: "2023-11-02T16:30:00-05:00",
      location: location("unit2b"),
      media: mediaRef.interior2b(),
      summary: "Interior scan of the unit 2B living room, taken before the incident.",
      limitations: ["Scan predates the incident; it shows layout, not current condition."],
    },
    {
      ...base,
      evidence_id: "fx-ev-mp-layout-3c",
      kind: "matterport_view",
      source_id: "fx-src-scan-typical-a",
      source_label: "Synthetic interior scan, typical layout A (fixture)",
      captured_at: "2023-10",
      effective_at: null,
      available_at: null,
      received_at: "2024-07-09T10:00:00Z",
      model_created_at: "2023-10",
      location: location("layout3c"),
      media: mediaRef.layout3c(),
      summary: "Scan of a sister unit with the same floor plan as 3C.",
      limitations: ["Representative layout only. This is not unit 3C."],
    },
    {
      ...base,
      evidence_id: "fx-ev-mp-basement",
      kind: "matterport_view",
      source_id: "fx-src-scan-common",
      source_label: "Synthetic common-area scan (fixture)",
      captured_at: "2023-11-02",
      effective_at: null,
      available_at: "2023-11-03",
      received_at: "2024-07-09T10:00:00Z",
      model_created_at: null,
      location: location("basement"),
      media: null,
      summary: "Common-area scan. The basement storage room was not included.",
      limitations: ["Basement storage was not scanned, so reports there cannot be placed on the model."],
    },
    {
      ...base,
      evidence_id: "fx-ev-photo-2b",
      kind: "resident_photo",
      source_id: "fx-src-report-2b",
      source_label: "Resident upload, unit 2B (fixture)",
      captured_at: "2024-07-09T07:55:00-04:00",
      effective_at: null,
      available_at: null,
      received_at: "2024-07-09T12:02:00Z",
      location: location("unit2b"),
      media: mediaRef.residentCeiling("fx-media-ev-photo-2b"),
      summary: "Photo of a brown water stain on the living-room ceiling, about 1 m across.",
      limitations: ["Resident photo; scale is estimated."],
    },
    {
      ...base,
      evidence_id: "fx-ev-inspection-roof",
      kind: "inspection",
      source_id: "fx-src-inspection-roof",
      source_label: "Synthetic roof inspection (fixture)",
      captured_at: "2024-07-12T09:30:00-04:00",
      effective_at: "2024-07-12",
      available_at: "2024-07-12",
      received_at: "2024-07-12T15:00:00Z",
      location: location("roof"),
      media: null,
      summary: "About 340 sq ft of membrane torn or lifted on the east wing. Decking is wet but sound.",
    },
    {
      ...base,
      evidence_id: "fx-ev-inspection-tarp",
      kind: "inspection",
      source_id: "fx-src-inspection-tarp",
      source_label: "Synthetic tarp inspection (fixture)",
      captured_at: "2024-07-10T11:00:00Z",
      effective_at: "2024-07-10",
      available_at: "2024-07-10",
      received_at: "2024-07-10T12:30:00Z",
      location: location("roof"),
      media: mediaRef.tarpInspection(),
      summary: "Emergency tarp installed and ballasted at four corners.",
    },
    {
      ...base,
      evidence_id: "fx-ev-photo-gutter",
      kind: "inspection",
      source_id: "fx-src-contractor-gutter",
      source_label: "Synthetic contractor photo (fixture)",
      captured_at: "2024-07-13",
      effective_at: null,
      available_at: null,
      received_at: "2024-07-13T20:15:00Z",
      location: location("roof"),
      media: mediaRef.gutter(),
      summary: "Contractor photo submitted as completion evidence for the gutter task.",
      limitations: ["Submitted by the contractor; not yet reviewed."],
    },
    {
      ...base,
      evidence_id: "fx-ev-cost-roofing",
      kind: "cost_source",
      source_id: "fx-src-cost-table",
      source_label: "Synthetic regional cost table (fixture)",
      captured_at: null,
      effective_at: "2024-06",
      available_at: "2024-06-01",
      received_at: "2024-07-08T14:20:00Z",
      location: null,
      media: null,
      summary: "Made-up unit rates for membrane roofing, drywall and drying.",
      limitations: ["Rates are fixture values, not a market survey."],
    },
    {
      ...base,
      evidence_id: "fx-ev-notice-county",
      kind: "official_notice",
      source_id: "fx-src-county-notice",
      source_label: "Sample County emergency notice (fixture)",
      captured_at: null,
      effective_at: "2024-07-09",
      available_at: "2024-07-09T06:00:00-04:00",
      received_at: "2024-07-09T10:30:00Z",
      location: null,
      media: null,
      summary: "Synthetic notice: building permits for emergency roof repairs are expedited for 30 days.",
    },
  ];
}

/* ------------------------------------------------------------ observations */

function observationList(): Observation[] {
  return [
    {
      observation_id: "fx-obs-roof-membrane",
      title: "Roof membrane torn on the east wing",
      description: "About 340 sq ft of membrane torn or lifted. Visible in the July aerial and confirmed on site.",
      basis: "observed",
      status: "verified",
      evidence_ids: ["fx-ev-aerial-before", "fx-ev-aerial-after", "fx-ev-inspection-roof"],
      location: location("roof"),
      observed_at: "2024-07-11T15:42:00Z",
      updated_at: "2024-07-12T16:00:00Z",
      verification_note: "Matches the on-site inspection of 12 Jul (fixture).",
      verified_by: "Fixture reviewer",
    },
    {
      observation_id: "fx-obs-ceiling-2b",
      title: "Water stain on the unit 2B living-room ceiling",
      description: "Resident reports a spreading stain under the east-wing roof section.",
      basis: "reported",
      status: "under_review",
      evidence_ids: ["fx-ev-photo-2b", "fx-ev-mp-2b"],
      location: location("unit2b"),
      observed_at: "2024-07-09",
      updated_at: "2024-07-10T09:00:00Z",
      verification_note: null,
      verified_by: null,
    },
    {
      observation_id: "fx-obs-model-3c",
      title: "Possible water path toward the unit 3C kitchen",
      description:
        "Model suggestion: the 3C kitchen sits below the torn membrane on a representative layout. Nobody has looked inside 3C.",
      basis: "inferred",
      status: "reported",
      evidence_ids: ["fx-ev-aerial-after", "fx-ev-mp-layout-3c"],
      location: location("layout3c"),
      observed_at: null,
      updated_at: "2024-07-12T16:20:00Z",
      verification_note: null,
      verified_by: null,
    },
    {
      observation_id: "fx-obs-basement-damp",
      title: "Damp smell in basement storage",
      description: "A resident describes a damp smell near the boiler room. The area has not been scanned.",
      basis: "reported",
      status: "reported",
      evidence_ids: ["fx-ev-mp-basement"],
      location: location("basement"),
      observed_at: "2024-07",
      updated_at: "2024-07-11T08:00:00Z",
      verification_note: null,
      verified_by: null,
    },
    {
      observation_id: "fx-obs-stair-debris",
      title: "Debris on the stairwell B landing",
      description: "Branches reported on the landing after the storm.",
      basis: "observed",
      status: "dismissed",
      evidence_ids: ["fx-ev-inspection-tarp"],
      location: location("stair"),
      observed_at: "2024-07-08",
      updated_at: "2024-07-10T13:00:00Z",
      verification_note: "Cleared before the inspection; no damage found (fixture).",
      verified_by: "Fixture reviewer",
    },
  ];
}

/* ----------------------------------------------------------------- tasks */

function taskList(): RecoveryTask[] {
  const base = { completion_evidence_ids: [] as string[], superseded_scope: null };
  return [
    {
      ...base,
      task_id: "fx-task-dry-3c",
      revision: 1,
      title: "Moisture check in unit 3C kitchen",
      scope: "Moisture-meter readings at the kitchen ceiling and the wall below the east-wing roof line.",
      status: "proposed",
      location: location("layout3c"),
      evidence_ids: ["fx-ev-mp-layout-3c"],
      household_ids: ["fx-hh-3c"],
      assignee_label: null,
      confirmation_source: null,
      confirmed_schedule: null,
      updated_at: "2024-07-12T16:30:00Z",
    },
    {
      ...base,
      task_id: "fx-task-membrane",
      revision: 3,
      title: "Replace east-wing roof membrane",
      scope: "Replace about 340 sq ft of membrane on the east wing and re-flash two curbs.",
      superseded_scope: "Patch about 120 sq ft of membrane on the east wing.",
      status: "approved",
      location: location("roof"),
      evidence_ids: ["fx-ev-inspection-roof", "fx-ev-aerial-after"],
      household_ids: [],
      assignee_label: "Sample Roofing Co. (fixture)",
      confirmation_source: null,
      confirmed_schedule: null,
      updated_at: "2024-07-12T17:30:00Z",
    },
    {
      ...base,
      task_id: "fx-task-ceiling-2b",
      revision: 2,
      title: "Open and dry the unit 2B ceiling",
      scope: "Cut out about 16 sq ft of wet drywall, dry the cavity, and leave it open for inspection.",
      status: "accepted",
      location: location("unit2b"),
      evidence_ids: ["fx-ev-photo-2b"],
      household_ids: ["fx-hh-2b"],
      assignee_label: "Sample Drywall LLC (fixture)",
      confirmation_source: "Signed work order WO-FX-0012 (fixture)",
      confirmed_schedule: "2024-07-16T13:00:00Z",
      updated_at: "2024-07-12T18:00:00Z",
    },
    {
      ...base,
      task_id: "fx-task-dehumidify",
      revision: 2,
      title: "Run dehumidifiers in unit 2B",
      scope: "Two dehumidifiers in the living room for 72 hours, with daily readings.",
      status: "in_progress",
      location: location("unit2b"),
      evidence_ids: ["fx-ev-photo-2b"],
      household_ids: ["fx-hh-2b"],
      assignee_label: "Sample Restoration (fixture)",
      confirmation_source: "Phone confirmation logged by owner (fixture)",
      confirmed_schedule: "2024-07-11",
      updated_at: "2024-07-12T08:00:00Z",
    },
    {
      ...base,
      task_id: "fx-task-gutter",
      revision: 3,
      title: "Rehang east gutter",
      scope: "Rehang 30 ft of gutter and reconnect the downspout.",
      status: "completion_submitted",
      location: location("roof"),
      evidence_ids: ["fx-ev-aerial-after"],
      household_ids: [],
      assignee_label: "Sample Roofing Co. (fixture)",
      confirmation_source: "Signed work order WO-FX-0009 (fixture)",
      confirmed_schedule: "2024-07-13T14:00:00Z",
      completion_evidence_ids: ["fx-ev-photo-gutter"],
      updated_at: "2024-07-13T20:15:00Z",
    },
    {
      ...base,
      task_id: "fx-task-tarp",
      revision: 4,
      title: "Emergency tarp over east wing",
      scope: "Cover the torn membrane with a ballasted tarp until replacement.",
      status: "verified",
      location: location("roof"),
      evidence_ids: ["fx-ev-aerial-after"],
      household_ids: [],
      assignee_label: "Sample Roofing Co. (fixture)",
      confirmation_source: "Signed work order WO-FX-0007 (fixture)",
      confirmed_schedule: "2024-07-10T08:00:00-04:00",
      completion_evidence_ids: ["fx-ev-inspection-tarp"],
      updated_at: "2024-07-10T13:00:00Z",
    },
    {
      ...base,
      task_id: "fx-task-stair",
      revision: 2,
      title: "Clear stairwell B debris",
      scope: "Remove branches from the stairwell B landing.",
      status: "cancelled",
      location: location("stair"),
      evidence_ids: [],
      household_ids: [],
      assignee_label: null,
      confirmation_source: null,
      confirmed_schedule: null,
      updated_at: "2024-07-10T13:05:00Z",
    },
  ];
}

/* ------------------------------------------------- resident-facing records */

function householdLabels(): OwnerCaseView["household_labels"] {
  return [
    { household_id: "fx-hh-2b", unit_label: "2B" },
    { household_id: "fx-hh-3c", unit_label: "3C" },
    { household_id: "fx-hh-unconfirmed", unit_label: null },
  ];
}

function reportList(scenario: boolean): ResidentReport[] {
  const prefix = scenario ? "Exercise input (hypothetical): " : "";
  return [
    {
      report_id: "fx-rep-2b",
      household_id: "fx-hh-2b",
      category: "water",
      text: `${prefix}Brown stain on the living-room ceiling, getting bigger since last night.`,
      location: location("unit2b"),
      location_description: null,
      observed_at: "2024-07-09T07:55:00-04:00",
      received_at: "2024-07-09T12:02:00Z",
      status: "under_review",
      media: [mediaRef.residentCeiling("fx-media-report-2b")],
      public_status_detail: "Your report is being reviewed against the building scan.",
    },
    {
      report_id: "fx-rep-basement",
      household_id: "fx-hh-unconfirmed",
      category: "other",
      text: `${prefix}Damp smell in the storage cages downstairs.`,
      location: null,
      location_description: "Storage cage near the boiler room, not sure of the number",
      observed_at: "2024-07",
      received_at: "2024-07-11T07:40:00Z",
      status: "reported",
      media: [],
      public_status_detail: "Received. Nobody has reviewed it yet.",
    },
    {
      report_id: "fx-rep-3c-noise",
      household_id: "fx-hh-3c",
      category: "roof",
      text: `${prefix}Flapping noise above the kitchen during the storm.`,
      location: location("layout3c"),
      location_description: "Kitchen, near the window",
      observed_at: "2024-07-08",
      received_at: "2024-07-08T23:10:00Z",
      status: "verified",
      media: [],
      public_status_detail: "Confirmed: loose roof membrane above your unit. A tarp is in place.",
    },
  ];
}

function newerReport(scenario: boolean): ResidentReport {
  return {
    report_id: "fx-rep-2b-followup",
    household_id: "fx-hh-2b",
    category: "water",
    text: `${scenario ? "Exercise input (hypothetical): " : ""}Water is now dripping from the ceiling light fixture.`,
    location: location("unit2b"),
    location_description: "Ceiling light in the living room",
    observed_at: "2024-07-13T06:30:00-04:00",
    received_at: "2024-07-13T10:45:00Z",
    status: "reported",
    media: [mediaRef.residentCeiling("fx-media-report-2b-followup")],
    public_status_detail: "Received after the latest assessment. Nobody has reviewed it yet.",
  };
}

function supportList(): SupportReceipt[] {
  return [
    {
      request_id: "fx-sup-2b-housing",
      household_id: "fx-hh-2b",
      category: "housing",
      description: "Need somewhere to stay while the ceiling is opened.",
      status: "under_review",
      received_at: "2024-07-10T15:00:00Z",
      public_status_detail: "The owner is reviewing temporary housing options.",
      duplicate: false,
    },
    {
      request_id: "fx-sup-3c-communication",
      household_id: "fx-hh-3c",
      category: "communication",
      description: "Please send updates by text, not email.",
      status: "responded",
      received_at: "2024-07-09T09:00:00Z",
      public_status_detail: "Noted. Updates appear here and in the building notice board.",
      duplicate: false,
    },
  ];
}

function noticeList(): PublishedNotice[] {
  return [
    {
      notice_id: "fx-notice-tarp",
      title: "Temporary roof cover in place",
      body: "A tarp now covers the damaged section of the east-wing roof. Permanent repairs are not yet scheduled.",
      published_at: "2024-07-10T14:00:00Z",
      published_by: "Fixture owner",
      source_ids: ["fx-src-inspection-tarp"],
    },
    {
      notice_id: "fx-notice-permits",
      title: "Roof repair permits",
      body: "The county is expediting emergency roof permits. We will post a repair date once a contractor confirms one.",
      published_at: "2024-07-11T09:30:00-04:00",
      published_by: "Fixture owner",
      source_ids: ["fx-src-county-notice"],
    },
  ];
}

/* -------------------------------------------------------------- valuation */

function comparables(): Comparable[] {
  const src = ["fx-src-costar-comps"];
  return [
    {
      comp_id: "fx-comp-1",
      property_ref: { dataset: "residential_property", id: "fx-prop-comp-1" },
      label: "Sample Comparable 1 (fixture), 52 units",
      transaction_date: "2024-02-14",
      date_basis: "closed",
      price_usd: 18_900_000,
      price_status: "Disclosed price",
      allocated: false,
      included: true,
      reason: "Similar size and vintage, sold within 6 months.",
      source_ids: src,
    },
    {
      comp_id: "fx-comp-2",
      property_ref: { dataset: "residential_property", id: "fx-prop-comp-2" },
      label: "Sample Comparable 2 (fixture), 44 units",
      transaction_date: "2023-11",
      date_basis: "deed_recorded",
      price_usd: 16_750_000,
      price_status: "Disclosed price",
      allocated: false,
      included: true,
      reason: "Same submarket; deed month only.",
      source_ids: src,
    },
    {
      comp_id: "fx-comp-3",
      property_ref: { dataset: "residential_property", id: "fx-prop-comp-3" },
      label: "Sample Comparable 3 (fixture), 40 units",
      transaction_date: "2024-05-03T00:00:00Z",
      date_basis: "closed",
      price_usd: 6_100_000,
      price_status: "Allocated share of a portfolio sale",
      allocated: true,
      included: false,
      reason: "Allocated portfolio share, not a single-asset price.",
      source_ids: src,
    },
    {
      comp_id: "fx-comp-4",
      property_ref: { dataset: "residential_property", id: "fx-prop-comp-4" },
      label: "Sample Comparable 4 (fixture), 50 units",
      transaction_date: null,
      date_basis: "unknown",
      price_usd: null,
      price_status: "Price not disclosed",
      allocated: false,
      included: false,
      reason: "No disclosed price and no transaction date.",
      source_ids: src,
    },
    {
      comp_id: "fx-comp-5",
      property_ref: { dataset: "residential_property", id: "fx-prop-comp-5" },
      label: "Sample Comparable 5 (fixture), 47 units",
      transaction_date: "2024-04",
      date_basis: "deed_recorded",
      price_usd: 17_400_000,
      price_status: "Disclosed price",
      allocated: false,
      included: true,
      reason: "Similar size; recorded within the window.",
      source_ids: src,
    },
  ];
}

function repairLines(): RepairLine[] {
  return [
    {
      line_id: "fx-line-membrane",
      description: "Replace roof membrane, east wing",
      location: location("roof"),
      quantity: 340,
      quantity_unit: "sq ft",
      quantity_basis: "Measured on site 12 Jul (fixture)",
      rate_low_usd: 14,
      rate_high_usd: 22,
      total: money(4_760, 7_480, null, "market_supported", "source_range", "Quantity × rate range from cost table", [
        "fx-src-inspection-roof",
        "fx-src-cost-table",
      ]),
      source_ids: ["fx-src-inspection-roof", "fx-src-cost-table"],
    },
    {
      line_id: "fx-line-drywall-2b",
      description: "Open, dry and replace ceiling drywall, unit 2B",
      location: location("unit2b"),
      quantity: 16,
      quantity_unit: "sq ft",
      quantity_basis: "Estimated from resident photo",
      rate_low_usd: 45,
      rate_high_usd: 80,
      total: money(720, 1_280, 950, "conditional", "scenario", "Estimated area × rate; conditional on opening the ceiling", [
        "fx-src-report-2b",
        "fx-src-cost-table",
      ]),
      source_ids: ["fx-src-report-2b", "fx-src-cost-table"],
    },
    {
      line_id: "fx-line-3c-interior",
      description: "Interior repairs, unit 3C (if any)",
      location: location("layout3c"),
      quantity: null,
      quantity_unit: "sq ft",
      quantity_basis: "Not inspected",
      rate_low_usd: null,
      rate_high_usd: null,
      total: noMoney("insufficient_evidence", "scenario", "Not estimated", "Unit 3C has not been inspected; the only scan is a representative layout."),
      source_ids: [],
    },
  ];
}

function assumptions(scenario: boolean): Assumption[] {
  const list: Assumption[] = [
    {
      assumption_id: "fx-asm-units",
      label: "Unit count",
      value: "48 units",
      basis: "source",
      source_ids: ["fx-src-costar-subject"],
    },
    {
      assumption_id: "fx-asm-downtime",
      label: "Units offline during repair",
      value: "2 units for 3 to 6 weeks",
      basis: "user_supplied",
      source_ids: [],
    },
    {
      assumption_id: "fx-asm-rent",
      label: "Monthly rent per offline unit",
      value: "$2,100 to $2,400",
      basis: "scenario",
      source_ids: [],
    },
  ];
  if (scenario) {
    list.push({
      assumption_id: "fx-asm-exercise",
      label: "Exercise premise",
      value: "Damage is hypothetical; the roof failure did not happen.",
      basis: "scenario",
      source_ids: [],
    });
  }
  return list;
}

const BENCHMARK_SOURCES = ["fx-src-costar-subject", "fx-src-costar-comps"];

function marketValuation(scenario: boolean, effective_at: string, calibrated: boolean): ValuationResult {
  return {
    basis: "market_supported",
    effective_at,
    benchmark: money(16_750_000, 18_900_000, 17_400_000, "market_supported", "comparable_dispersion", "Median of included comparable sales", BENCHMARK_SOURCES),
    current_condition: calibrated
      ? money(16_600_000, 17_150_000, 16_880_000, "market_supported", "calibrated_confidence", "Benchmark less repair, downtime and a disclosed-damage discount; 80% interval from backtest (fixture)", [
          ...BENCHMARK_SOURCES,
          "fx-src-inspection-roof",
        ])
      : money(16_500_000, 17_200_000, 16_850_000, "market_supported", "scenario", "Benchmark less repair, downtime and a disclosed-damage discount (fixture)", [...BENCHMARK_SOURCES, "fx-src-inspection-roof"]),
    after_repair: money(17_100_000, 17_600_000, 17_350_000, "conditional", "scenario", "Benchmark assuming the accepted scope is completed", BENCHMARK_SOURCES),
    repair_cost: money(5_480, 8_760, null, "market_supported", "source_range", "Sum of repair lines with estimates", ["fx-src-cost-table", "fx-src-inspection-roof"]),
    downtime_cost: money(3_150, 7_200, 4_950, "conditional", "scenario", "Offline units × monthly rent × months offline", []),
    comparables: comparables(),
    repair_lines: repairLines(),
    assumptions: assumptions(scenario),
    limitations: [
      "Synthetic fixture values only.",
      "Unit 3C interior has not been inspected and is excluded from the repair total.",
    ],
  };
}

function conditionalValuation(scenario: boolean): ValuationResult {
  return {
    basis: "conditional",
    effective_at: "2024-07-12",
    benchmark: money(16_750_000, 18_900_000, 17_400_000, "market_supported", "comparable_dispersion", "Median of included comparable sales", BENCHMARK_SOURCES),
    current_condition: noMoney(
      "conditional",
      "scenario",
      "Cost to cure",
      "Interior condition of units 2B and 3C is unverified, so the current-condition value is withheld.",
    ),
    after_repair: money(17_000_000, 17_700_000, null, "conditional", "scenario", "Benchmark assuming the accepted scope is completed", BENCHMARK_SOURCES),
    repair_cost: money(5_480, 12_000, 7_900, "conditional", "source_range", "Cost to cure from repair lines and cost table", ["fx-src-cost-table"]),
    downtime_cost: money(3_150, 7_200, null, "conditional", "scenario", "Offline units × monthly rent × months offline", []),
    comparables: comparables().filter((c) => c.comp_id !== "fx-comp-3"),
    repair_lines: repairLines(),
    assumptions: assumptions(scenario),
    limitations: ["Conditional on interior inspection of 2B and 3C.", "Synthetic fixture values only."],
  };
}

function insufficientValuation(scenario: boolean, effective_at: string): ValuationResult {
  const basis: ValueBasis = "insufficient_evidence";
  return {
    basis,
    effective_at,
    benchmark: noMoney(basis, "comparable_dispersion", "Median of included comparable sales", "No comparable sale has both a disclosed price and a date."),
    current_condition: noMoney(basis, "scenario", "Cost to cure", "Benchmark is unavailable."),
    after_repair: noMoney(basis, "scenario", "Benchmark after repair", "Benchmark is unavailable."),
    repair_cost: noMoney(basis, "source_range", "Sum of repair lines", "No inspected quantities yet."),
    downtime_cost: noMoney(basis, "scenario", "Offline units × monthly rent × months offline", "Number of offline units is unknown."),
    comparables: comparables().filter((c) => c.price_usd === null),
    repair_lines: repairLines().filter((l) => l.total.low === null),
    assumptions: assumptions(scenario).filter((a) => a.basis === "source" || a.basis === "scenario"),
    limitations: ["Not enough evidence to estimate any amount.", "Synthetic fixture values only."],
  };
}

/* ------------------------------------------------------------- assessments */

const ALL_OBSERVATION_IDS = ["fx-obs-roof-membrane", "fx-obs-ceiling-2b", "fx-obs-model-3c", "fx-obs-basement-damp"];

function previousAssessment(variant: FixtureVariant, scenario: boolean): Assessment {
  return {
    assessment_id: "fx-asmt-previous",
    run_id: "fx-run-previous",
    base_analysis_revision: 3,
    status: "published",
    headline: "Initial view: roof damage likely, interior unknown",
    summary: "Superseded first assessment, made before the post-incident aerial arrived.",
    created_at: "2024-07-09T08:10:00Z",
    published_at: "2024-07-09T09:00:00Z",
    valuation:
      variant === "insufficient"
        ? insufficientValuation(scenario, "2024-07-09")
        : {
            ...marketValuation(scenario, "2024-07-09", false),
            repair_cost: money(2_000, 9_000, null, "market_supported", "source_range", "Patch scope from cost table", ["fx-src-cost-table"]),
            repair_lines: [],
          },
    observation_ids: [],
    unresolved_questions: ["Is the roof membrane damaged?"],
    failure_reason: null,
  };
}

function assessmentsFor(variant: FixtureVariant, scenario: boolean): Assessment[] {
  const prev = previousAssessment(variant, scenario);
  switch (variant) {
    case "empty":
      return [];
    case "full":
      return [
        {
          assessment_id: "fx-asmt-current",
          run_id: "fx-run-current",
          base_analysis_revision: 6,
          status: "published",
          headline: "Roof membrane damage confirmed; interior partly verified",
          summary: "Market-supported estimate from three included comparables, with repair and downtime shown separately.",
          created_at: "2024-07-12T16:20:00Z",
          published_at: "2024-07-12T17:05:00Z",
          valuation: marketValuation(scenario, "2024-07-12", true),
          observation_ids: ALL_OBSERVATION_IDS,
          unresolved_questions: ["Did water reach unit 3C?", "Is the basement affected?"],
          failure_reason: null,
        },
        {
          assessment_id: "fx-asmt-failed",
          run_id: "fx-run-failed",
          base_analysis_revision: 6,
          status: "failed",
          headline: "Run failed",
          summary: "The worker restarted during the run.",
          created_at: "2024-07-12T15:50:00Z",
          published_at: null,
          valuation: null,
          observation_ids: [],
          unresolved_questions: [],
          failure_reason: "Worker restarted during the run; retry is safe (fixture).",
        },
        prev,
      ];
    case "conditional":
      return [
        {
          assessment_id: "fx-asmt-current",
          run_id: "fx-run-current",
          base_analysis_revision: 6,
          status: "published",
          headline: "Cost to cure only: interior condition unverified",
          summary: "Current-condition value is withheld until units 2B and 3C are inspected.",
          created_at: "2024-07-12T16:20:00Z",
          published_at: "2024-07-12T17:05:00Z",
          valuation: conditionalValuation(scenario),
          observation_ids: ALL_OBSERVATION_IDS,
          unresolved_questions: ["What is the interior condition of 2B and 3C?"],
          failure_reason: null,
        },
        {
          assessment_id: "fx-asmt-draft",
          run_id: "fx-run-draft",
          base_analysis_revision: 6,
          status: "draft",
          headline: "Draft: same inputs, revised downtime assumption",
          summary: "Draft awaiting owner review. Not published.",
          created_at: "2024-07-12T19:00:00Z",
          published_at: null,
          valuation: { ...conditionalValuation(scenario), downtime_cost: money(4_200, 7_200, 5_600, "conditional", "scenario", "Offline units × monthly rent × months offline", []) },
          observation_ids: ALL_OBSERVATION_IDS,
          unresolved_questions: ["What is the interior condition of 2B and 3C?"],
          failure_reason: null,
        },
        prev,
      ];
    case "insufficient":
      return [
        {
          assessment_id: "fx-asmt-current",
          run_id: "fx-run-current",
          base_analysis_revision: 6,
          status: "published",
          headline: "Not enough evidence to estimate value or cost",
          summary: "No usable comparable sale and no inspected quantities.",
          created_at: "2024-07-12T16:20:00Z",
          published_at: "2024-07-12T17:05:00Z",
          valuation: insufficientValuation(scenario, "2024-07-12"),
          observation_ids: ALL_OBSERVATION_IDS,
          unresolved_questions: ["Is there a comparable sale with a disclosed price?", "How large is the damaged area?"],
          failure_reason: null,
        },
        {
          assessment_id: "fx-asmt-running",
          run_id: "fx-run-running",
          base_analysis_revision: 6,
          status: "running",
          headline: "Assessment running",
          summary: "A new run is in progress on the current inputs.",
          created_at: "2024-07-12T20:00:00Z",
          published_at: null,
          valuation: null,
          observation_ids: [],
          unresolved_questions: [],
          failure_reason: null,
        },
        prev,
      ];
    case "stale":
      return [
        {
          assessment_id: "fx-asmt-current",
          run_id: "fx-run-current",
          base_analysis_revision: 6,
          status: "stale",
          headline: "Roof membrane damage confirmed; interior partly verified",
          summary: "Published before the latest resident report; its inputs are out of date.",
          created_at: "2024-07-12T16:20:00Z",
          published_at: "2024-07-12T17:05:00Z",
          valuation: marketValuation(scenario, "2024-07-12", false),
          observation_ids: ALL_OBSERVATION_IDS,
          unresolved_questions: ["Did water reach unit 3C?"],
          failure_reason: null,
        },
        prev,
      ];
  }
}

/* ----------------------------------------------------------------- events */

type EventSeed = [type: string, entity_id: string | null, analysis_revision: number, public_summary: string | null];

function commonEventSeeds(case_id: string): EventSeed[] {
  return [
    ["case.opened", case_id, 0, "Recovery case opened"],
    ["evidence.added", "fx-ev-costar-subject", 1, null],
    ["evidence.added", "fx-ev-aerial-before", 2, null],
    ["evidence.added", "fx-ev-costar-comps", 3, null],
    ["assessment.started", "fx-asmt-previous", 3, null],
    ["assessment.published", "fx-asmt-previous", 3, null],
    ["report.received", "fx-rep-2b", 4, "A resident report was received"],
    ["evidence.added", "fx-ev-aerial-after", 5, null],
    ["task.updated", "fx-task-tarp", 5, "Emergency roof tarp verified complete"],
    ["notice.published", "fx-notice-tarp", 5, "Notice published: Temporary roof cover in place"],
    ["observation.reviewed", "fx-obs-roof-membrane", 6, null],
    ["task.updated", "fx-task-membrane", 6, "Roof membrane scope changed; awaiting renewed acceptance"],
  ];
}

function tailEventSeeds(variant: FixtureVariant): EventSeed[] {
  switch (variant) {
    case "empty":
      return [];
    case "full":
      return [
        ["assessment.failed", "fx-asmt-failed", 6, null],
        ["assessment.started", "fx-asmt-current", 6, null],
        ["assessment.published", "fx-asmt-current", 6, null],
      ];
    case "conditional":
      return [
        ["assessment.started", "fx-asmt-current", 6, null],
        ["assessment.published", "fx-asmt-current", 6, null],
        ["assessment.drafted", "fx-asmt-draft", 6, null],
      ];
    case "insufficient":
      return [
        ["assessment.started", "fx-asmt-current", 6, null],
        ["assessment.published", "fx-asmt-current", 6, null],
        ["assessment.started", "fx-asmt-running", 6, null],
      ];
    case "stale":
      return [
        ["assessment.started", "fx-asmt-current", 6, null],
        ["assessment.published", "fx-asmt-current", 6, null],
        ["report.received", "fx-rep-2b-followup", 7, "A resident report was received"],
        ["assessment.stale", "fx-asmt-current", 7, null],
      ];
  }
}

function buildEvents(case_id: string, variant: FixtureVariant): CaseEvent[] {
  if (variant === "empty") return [];
  const seeds = [...commonEventSeeds(case_id), ...tailEventSeeds(variant)];
  const start = Date.UTC(2024, 6, 8, 14, 0, 0);
  return seeds.map(([type, entity_id, analysis_revision, public_summary], i) => ({
    event_id: 1001 + i,
    case_id,
    case_revision: i + 1,
    analysis_revision,
    type,
    at: new Date(start + i * 4 * 3600 * 1000).toISOString(),
    entity_id,
    public_summary,
  }));
}

/* ----------------------------------------------------------------- public */

function countPending(view: Pick<OwnerCaseView, "reports" | "tasks">): { pending_reports: number; pending_tasks: number } {
  return {
    pending_reports: view.reports.filter((r) => r.status === "reported" || r.status === "under_review").length,
    pending_tasks: view.tasks.filter((t) => t.status !== "verified" && t.status !== "cancelled").length,
  };
}

function buildSnapshot(seed: CaseSeed, variant: FixtureVariant): OwnerCaseView {
  const scenario = seed.mode === "scenario_exercise";
  const events = buildEvents(seed.case_id, variant);
  const last = events[events.length - 1];

  if (variant === "empty") {
    return {
      case: {
        ...seed,
        case_revision: 1,
        analysis_revision: 0,
        pending_reports: 0,
        pending_tasks: 0,
        next_action: "Attach the first evidence to start this case (fixture)",
      },
      evidence: [],
      observations: [],
      assessments: [],
      current_assessment_id: null,
      tasks: [],
      reports: [],
      support_requests: [],
      notices: [],
      household_labels: [],
      events: [],
      event_cursor: 0,
    };
  }

  const reports = reportList(scenario);
  if (variant === "stale") reports.unshift(newerReport(scenario));
  const tasks = taskList();
  const next_action = variant === "stale" ? "Re-run the assessment: a newer resident report arrived" : seed.next_action;

  return {
    case: {
      ...seed,
      case_revision: last.case_revision,
      analysis_revision: last.analysis_revision,
      ...countPending({ reports, tasks }),
      next_action,
    },
    evidence: evidenceList(),
    observations: observationList(),
    assessments: assessmentsFor(variant, scenario),
    current_assessment_id: "fx-asmt-current",
    tasks,
    reports,
    support_requests: supportList(),
    notices: noticeList(),
    household_labels: householdLabels(),
    events,
    event_cursor: last.event_id,
  };
}

/** Case list in "server order". Fresh copy on every call. */
export function fixtureCases(): RecoveryCaseSummary[] {
  return deepCopy(caseSeeds().map((seed) => buildSnapshot(seed, "full").case));
}

/** Owner snapshot for one fixture case. Fresh deep copy on every call. Throws on an unknown case_id. */
export function fixtureSnapshot(variant: FixtureVariant, case_id: string = DEFAULT_CASE_ID): OwnerCaseView {
  const seed = caseSeeds().find((s) => s.case_id === case_id);
  if (!seed) throw new Error(`Unknown fixture case_id "${case_id}"`);
  return deepCopy(buildSnapshot(seed, variant));
}
