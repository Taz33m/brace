"""Shared helpers for platform tests (no tests here). Synthetic labels only, no real data."""
from __future__ import annotations

from backend.recovery.platform.auth import Actor
from backend.recovery.platform.models import CaseInput, LocationRef, ReportInput

OWNER = Actor(role="owner", actor_id="owner:local")
OTHER_OWNER = Actor(role="owner", actor_id="owner:someone-else")


def location(location_id: str, label: str, unit_label: str | None = None) -> LocationRef:
    return LocationRef(location_id=location_id, label=label, structure_id=None, scan_id=None,
                       sweep_id=None, room_id=None, unit_label=unit_label, binding="unverified",
                       longitude=None, latitude=None, bearing_degrees=None)


def case_input(case_id: str = "case_test") -> CaseInput:
    return CaseInput(case_id=case_id,
                     property_ref={"dataset": "commercial_property", "id": "synthetic-1"},
                     property_name="Synthetic Apartments", address="1 Test Way", city="Houston",
                     incident_name="Test exercise", incident_at="2024-07-08",
                     assessment_as_of="2026-11-14", mode="scenario_exercise",
                     locations=[location("loc_kitchen_a", "Unit A kitchen", "A"),
                                location("loc_kitchen_b", "Unit B kitchen", "B"),
                                location("loc_lobby", "Lobby")])


def report(text: str = "Water on the kitchen floor", **kw) -> ReportInput:
    base = dict(category="water", text=text, selected_location_id=None, location_description=None,
                observed_at=None, upload_ids=[])
    base.update(kw)
    return ReportInput(**base)


def seeded(store, case_id: str = "case_test"):
    """A case with two households, A and B, each with a resident actor."""
    store.create_case(OWNER, case_input(case_id))
    ha = store.add_household(OWNER, case_id, "A", location_ids=["loc_kitchen_a", "loc_lobby"])
    hb = store.add_household(OWNER, case_id, "B", location_ids=["loc_kitchen_b", "loc_lobby"])
    res_a = Actor(role="resident", actor_id="resident:" + ha, case_id=case_id, household_id=ha)
    res_b = Actor(role="resident", actor_id="resident:" + hb, case_id=case_id, household_id=hb)
    return ha, hb, res_a, res_b
