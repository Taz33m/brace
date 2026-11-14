/**
 * UI FIXTURE — synthetic resident snapshot. Not a CoStar property, not a real household,
 * not a property assessment. IDs are synthetic; nothing here comes from the sponsor kit.
 */
import type { LocationRef, ResidentHome } from "../contract";

export interface FixtureOptions {
  rooms: boolean;
  content: boolean;
  unit_confirmed: boolean;
}

const room = (id: string, label: string): LocationRef => ({
  location_id: id,
  label,
  structure_id: "fx-structure-1",
  scan_id: "fx-scan-unit-4b",
  sweep_id: null,
  room_id: id,
  unit_label: "4B",
  binding: "verified_unit",
  longitude: null,
  latitude: null,
  bearing_degrees: null,
});

export function buildHome(opts: FixtureOptions): ResidentHome {
  const now = Date.now();
  const iso = (minsAgo: number) => new Date(now - minsAgo * 60_000).toISOString();
  const locations: LocationRef[] = opts.rooms
    ? [
        room("fx-loc-living", "Living room"),
        room("fx-loc-kitchen", "Kitchen"),
        room("fx-loc-bed", "Bedroom"),
        room("fx-loc-bath", "Bathroom"),
        room("fx-loc-hall", "Hallway"),
        {
          ...room("fx-loc-model", "Two-bedroom model unit"),
          unit_label: null,
          scan_id: "fx-scan-model",
          binding: "representative_layout",
        },
      ]
    : [];
  return {
    case_id: "fx-case-001",
    case_revision: 7,
    property_name: "Harbor Point Apartments",
    address: "100 Example Way, Houston, TX",
    unit_label: "4B",
    unit_confirmed: opts.unit_confirmed,
    mode: "scenario_exercise",
    mode_label: "Hurricane exercise",
    incident_name: "Hurricane exercise (fixture)",
    updated_at: iso(6),
    selectable_locations: locations,
    reports: [],
    support_requests: [],
    tasks: opts.content
      ? [
          {
            task_id: "TSK-201",
            revision: 1,
            title: "Clear storm debris from the parking garage ramp",
            status: "in_progress",
            public_status_detail: "The crew has started work.",
            confirmed_schedule: iso(-90),
            updated_at: iso(40),
          },
        ]
      : [],
    notices: opts.content
      ? [
          {
            notice_id: "NTC-101",
            title: "Water off on floors 1–2 until 3 PM",
            body: "Plumbers are repairing a burst riser. Floors 3 and up are not affected. Bottled water is in the lobby.",
            published_at: iso(35),
            published_by: "Property management",
            source_ids: [],
          },
        ]
      : [],
    event_cursor: 42,
  };
}
