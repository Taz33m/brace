"""Amenity inventory: the merging rule, the listed/found comparison and the paid-call budget.

Everything here is a scripted stand-in on the synthetic site from conftest: no network, no keys, no kit data.
"""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from shapely.geometry import box

from backend.openproblems import amenities as A

from .conftest import ll, rect

ENUMS = {"AttachmentType": {"4": "BuildingPhoto", "43": "Matterport3DScan"},
         "ParkingType": {"1": "Surface", "3": "Covered"}, "ResidentialParkingType": {"8": "Carport"}}


def det(label: str, x: float, y: float, w: float = 10, h: float = 6, score: float = 0.8) -> dict:
    """A detector row: a box w by h metres centred at local metres (x, y)."""
    (w0, s0), (e0, n0) = ll(x - w / 2, y - h / 2), ll(x + w / 2, y + h / 2)
    return {"label": label, "confidence": score, "bbox_wkt": box(w0, s0, e0, n0).wkt}


def box_sighting(kind: str, x: float, y: float, source: str = A.AERIAL_DETECTOR, w: float = 10, h: float = 6, conf: float = 0.8) -> dict:
    (w0, s0), (e0, n0) = ll(x - w / 2, y - h / 2), ll(x + w / 2, y + h / 2)
    lon, lat = ll(x, y)
    return A._sighting(kind, source, conf, "test", {"type": "site point", "lon": lon, "lat": lat, "cell": "A1",
                                                    "structure": None, "bbox": [w0, s0, e0, n0]}, "test box")


def scan_sighting(kind: str, scan_id: str, xy: tuple[float, float] | None, source: str = A.SCAN_NAME,
                  anchor: str = "at", storm: dict | None = None, sweep: str | None = None) -> dict:
    lon, lat = ll(*xy) if xy else (None, None)
    place = {"type": "scan", "scan_id": scan_id, "scan_name": scan_id, "structure": None, "lon": lon, "lat": lat, "cell": None}
    if sweep:
        place["sweep_id"] = sweep
    return A._sighting(kind, source, 0.9, "test", place, "test scan", anchor=anchor, storm=storm)


def parcel_sighting(kind: str) -> dict:
    lon, lat = ll(0, 0)
    return A._sighting(kind, A.AERIAL_ATTRIBUTE, 1.0, "test", {"type": "parcel", "lon": lon, "lat": lat}, "attribute", anchor="parcel")


def by_kind(amenities: list[dict]) -> dict[str, dict]:
    return {a["kind"]: a for a in amenities}


# --- merging: two sources, one amenity ----------------------------------------------

def test_four_sources_seeing_one_pool_count_once():
    storm = {"glass": "large windows", "exterior_doors": "glass doors", "loose_items": ["lounge chairs"], "equipment": []}
    pool = by_kind(A.merge([
        box_sighting("pool", 10, 10),
        parcel_sighting("pool"),                                       # parcel-wide: no point
        scan_sighting("pool", "POOLSCAN", (18, 12)),                   # a scan standing at the pool, 8 m away
        scan_sighting("pool", "CLUB", (40, 10), A.PANORAMA, anchor="from", storm=storm, sweep="p1"),  # seen from the clubhouse
    ]))["pool"]
    assert pool["count"] == 1
    assert pool["sources"] == sorted([A.AERIAL_ATTRIBUTE, A.AERIAL_DETECTOR, A.PANORAMA, A.SCAN_NAME])
    assert len(pool["instances"][0]["sightings"]) == 4 and not pool["unplaced_sightings"]
    assert pool["instances"][0]["place"]["bbox"]                       # the boxed place is the one reported
    assert pool["instances"][0]["before_a_storm"]["loose_items"] == ["lounge chairs"]
    assert pool["count_is_minimum"] is False


def test_overlapping_boxes_are_one_place_and_separate_boxes_are_two():
    one = by_kind(A.merge([box_sighting("pool", 0, 0), box_sighting("pool", 2, 1, conf=0.5)]))["pool"]
    assert one["count"] == 1 and one["confidence"] == 0.8
    two = by_kind(A.merge([box_sighting("pool", 0, 0), box_sighting("pool", 60, 0)]))["pool"]
    assert two["count"] == 2 and [i["n"] for i in two["instances"]] == [1, 2]


def test_a_sighting_without_a_point_confirms_but_never_adds():
    pool = by_kind(A.merge([box_sighting("pool", 0, 0), box_sighting("pool", 60, 0),
                            parcel_sighting("pool"), scan_sighting("pool", "NOGPS", None)]))["pool"]
    assert pool["count"] == 2                                          # not 3 and not 4
    assert {s["source"] for s in pool["unplaced_sightings"]} == {A.AERIAL_ATTRIBUTE, A.SCAN_NAME}
    assert pool["count_is_minimum"] is False                           # the boxes cover the whole parcel


def test_only_unplaced_sightings_make_exactly_one_and_say_it_is_a_floor():
    court = by_kind(A.merge([parcel_sighting("sport court")]))["sport court"]
    assert court["count"] == 1 and court["count_is_minimum"] is True
    gyms = by_kind(A.merge([scan_sighting("fitness room", "GYM_A", None), scan_sighting("fitness room", "GYM_B", None)]))["fitness room"]
    assert gyms["count"] == 1 and gyms["count_is_minimum"] is True     # two scans, no fixes: at least one


def test_a_scan_far_from_every_box_is_its_own_place_and_a_distant_view_is_not():
    far = by_kind(A.merge([box_sighting("pool", 0, 0), scan_sighting("pool", "OTHER", (70, 0))]))["pool"]
    assert far["count"] == 2
    distant = scan_sighting("pool", "FAR", (200, 0), A.PANORAMA, anchor="from")
    view = by_kind(A.merge([box_sighting("pool", 0, 0), box_sighting("pool", 60, 0), distant]))["pool"]
    assert view["count"] == 2 and len(view["unplaced_sightings"]) == 1   # too far to say which pool it saw
    only = by_kind(A.merge([box_sighting("pool", 0, 0), distant]))["pool"]
    assert only["count"] == 1 and not only["unplaced_sightings"]         # one pool on site: it saw that one


def test_a_footprint_and_a_detector_box_on_it_are_one_carport_but_two_footprints_stay_two():
    foot_a = box_sighting("covered parking", 0, 0, A.AERIAL_ATTRIBUTE, w=30, h=6, conf=0.7)
    foot_a["place"]["footprint"] = rect(-15, -3, 15, 3)
    foot_b = box_sighting("covered parking", 0, 5, A.AERIAL_ATTRIBUTE, w=30, h=6, conf=0.7)   # touching row beside it
    foot_b["place"]["footprint"] = rect(-15, 2, 15, 8)
    seen = box_sighting("covered parking", 1, 0, w=28, h=6, conf=0.65)
    lot = by_kind(A.merge([foot_a, foot_b, seen]))["covered parking"]
    assert lot["count"] == 2
    assert sorted(len(i["sightings"]) for i in lot["instances"]) == [1, 2]


def test_a_scan_without_gps_borrows_a_point_but_cannot_add_a_place():
    sightings = [box_sighting("pool", 0, 0),
                 scan_sighting("clubhouse or lounge", "CLUB", (20, 0)),
                 scan_sighting("pool", "POOLSCAN", None),
                 scan_sighting("clubhouse or lounge", "POOLSCAN", None, A.PANORAMA, anchor="from")]
    A.borrow_positions(sightings)
    got = by_kind(A.merge(sightings))
    assert got["pool"]["count"] == 1 and not got["pool"]["unplaced_sightings"]
    assert got["clubhouse or lounge"]["count"] == 1
    assert "borrowed" in sightings[2]["place"]["position_basis"]


# --- CoStar: what the listing names ---------------------------------------------------

RECORD = {
    "id": 7, "buildingName": "Test Plaza", "amenities": [1, 2, 3],
    "contacts": [{"email": "nobody@example.com"}],
    "attachments": [
        {"caption": "Pool #1", "attachmentType": 4, "videoExternalReferenceType": 0},
        {"caption": "Pool #1", "attachmentType": 4, "videoExternalReferenceType": 0},
        {"caption": "Pool #3", "attachmentType": 4, "videoExternalReferenceType": 0},
        {"caption": "Laundry Room", "attachmentType": 4, "videoExternalReferenceType": 0},
        {"caption": "Playground", "attachmentType": 4, "videoExternalReferenceType": 0},
        {"caption": "Dog Park", "attachmentType": 4, "videoExternalReferenceType": 0},
        {"caption": "Fitness Center", "attachmentType": 43, "videoExternalReferenceType": 36, "videoKey": "GYM"},
        {"caption": "2 BR, 1 BA - Kitchen", "attachmentType": 4, "videoExternalReferenceType": 0},
        {"caption": "1BR, 1BA - Laundry", "attachmentType": 4, "videoExternalReferenceType": 0},
    ],
    "parking": [{"parkingType": 1}, {"parkingType": 3}],
    "propertyApartment": {"sitePhoneNumber": "5550000000", "residentialProfile": {"parkingPolicies": [{"parkingType": 8}]}},
}


def test_listing_reads_captions_and_parking_and_nothing_personal():
    facts = A.listed_from_record(RECORD, ENUMS, True)
    listed = by_kind(facts["listed"])
    assert set(listed) == {"pool", "laundry room", "playground", "dog park", "fitness room", "covered parking"}
    assert listed["pool"]["count"] == 3                      # "Pool #3" says three
    assert listed["laundry room"]["count"] is None
    assert len(listed["laundry room"]["evidence"]) == 1      # the unit photo's laundry is not a shared laundry room
    assert listed["fitness room"]["tour_caption_only"] is True
    assert len(listed["covered parking"]["evidence"]) == 2   # the parking type and the parking policy
    assert facts["amenity_ids"] == [1, 2, 3] and "not compared" in facts["amenity_ids_note"]
    text = json.dumps(facts)
    assert "example.com" not in text and "5550000000" not in text


# --- comparison -------------------------------------------------------------------------

ALL_CHECKED = {s: {"status": "checked"} for s in (A.AERIAL_ATTRIBUTE, A.AERIAL_DETECTOR, A.SCAN_NAME, A.ROOM_LABEL, A.PANORAMA)}


def test_comparison_separates_checked_from_not_visible_from_not_checked():
    listed = A.listed_from_record(RECORD, ENUMS)["listed"]
    found = A.merge([box_sighting("pool", 0, 0), box_sighting("pool", 60, 0),
                     scan_sighting("fitness room", "GYM", (5, 5)), parcel_sighting("sport court")])
    c = A.compare(listed, found, ALL_CHECKED)

    both = by_kind(c["listed_and_found"])
    assert set(both) == {"pool", "fitness room"}
    assert both["pool"]["listed_count"] == 3 and both["pool"]["found_count"] == 2 and both["pool"]["counts_agree"] is False
    assert both["fitness room"]["independent"] is False      # the listing's only evidence is the tour we looked at

    missing = by_kind(c["listed_not_found"])
    assert missing["playground"]["status"] == "checked, not seen"          # both aerial sources ran over the parcel
    assert missing["covered parking"]["status"] == "checked, not seen"
    assert missing["laundry room"]["status"] == "not visible to our sources"  # indoor, and no scan is of one
    assert missing["dog park"]["status"] == "not checked"                  # no source of ours looks for it
    assert [x["kind"] for x in c["found_not_listed"]] == ["sport court"]
    assert c["counts"] == {"listed": 6, "found": 3, "listed_and_found": 2, "listed_not_found": 4,
                           "listed_not_found_by_status": {"checked, not seen": 2, "not visible to our sources": 1, "not checked": 1},
                           "found_not_listed": 1, "found_not_listed_unconfirmed": 0}


def test_a_source_that_did_not_run_is_not_checked_rather_than_not_found():
    listed = A.listed_from_record(RECORD, ENUMS)["listed"]
    status = {**ALL_CHECKED, A.AERIAL_DETECTOR: {"status": "not checked"}, A.AERIAL_ATTRIBUTE: {"status": "not checked"}}
    missing = by_kind(A.compare(listed, [], status)["listed_not_found"])
    assert missing["playground"]["status"] == "not checked"
    assert missing["playground"]["sources_not_checked"] == [A.AERIAL_ATTRIBUTE, A.AERIAL_DETECTOR]
    assert missing["pool"]["status"] == "not checked"
    assert missing["laundry room"]["status"] == "not visible to our sources"
    nothing_ran = {s: {"status": "not checked"} for s in ALL_CHECKED}
    assert by_kind(A.compare(listed, [], nothing_ran)["listed_not_found"])["laundry room"]["status"] == "not checked"


def test_part_of_the_site_weakens_not_seen_and_low_confidence_finds_are_kept_apart():
    listed = A.listed_from_record(RECORD, ENUMS)["listed"]
    weak = scan_sighting("courtyard", "GYM", (5, 5), A.PANORAMA, anchor="from")
    weak["confidence"] = 0.5
    c = A.compare(listed, A.merge([weak]), ALL_CHECKED, whole_site=False)
    assert by_kind(c["listed_not_found"])["pool"]["status"] == "checked on part of the site, not seen"
    assert c["found_not_listed"] == [] and [x["kind"] for x in c["found_not_listed_unconfirmed"]] == ["courtyard"]


# --- the inventory, with a scripted detector and a scripted model -------------------------

class ScriptedDetector:
    def __init__(self):
        self.calls = []

    def __call__(self, area_wkt, labels):
        self.calls.append(sorted(labels))
        if "swimming pool" in labels:
            return [det("swimming pool", 40, 40, score=0.9), det("swimming pool", 500, 500)]   # the second is off the parcel
        if "long white shed roof" in labels:
            return [det("long white shed roof", 0, -45, w=30, h=6, score=0.7),                 # a carport row
                    det("long white shed roof", 0, 45, w=30, h=6, score=0.4)]                  # too weak to keep
        return [det("lounge chair", 42, 41, w=2, h=1, score=0.5)]


class ScriptedModel:
    def __init__(self):
        self.calls = 0
        self.messages = self

    def create(self, **kw):
        self.calls += 1
        assert kw["model"] == A.VISION_MODEL and kw["output_config"]["format"]["type"] == "json_schema"
        answer = {"here": ["fitness room"], "visible_nearby": ["pool"], "loose_items": ["dumbbells"],
                  "equipment": ["treadmill"], "glass": "large windows", "sure": "high", "note": "A fitness room."}
        return SimpleNamespace(stop_reason="end_turn", content=[SimpleNamespace(type="text", text=json.dumps(answer))])


@pytest.fixture
def community(site, monkeypatch):
    lon, lat = ll(30, 30)
    site.d["scans"].append({"id": "GYM", "name": "Fitness Center", "kind": "shared space", "structure": "S2", "origin": [lon, lat],
                            "rooms": [], "sweeps": [{"id": f"g{i}", "lon": lon, "lat": lat} for i in range(3)]})
    site.d["record"]["num_buildings"] = 2
    monkeypatch.setattr(A, "_pano_image", lambda scan_id, sweep_id: {"type": "text", "text": "stand-in image"})
    return site


def run(site, tmp_path, **kw):
    kw.setdefault("attributes", {"pool.detected": True, "pool.score": 1.0, "structures": []})
    kw.setdefault("listing_facts", A.listed_from_record(RECORD, ENUMS))
    return A.inventory(7, site=site, cache_dir=tmp_path / "amenities", **kw)


def test_inventory_counts_once_places_each_and_pays_once(community, tmp_path):
    detector, model = ScriptedDetector(), ScriptedModel()
    r = run(community, tmp_path, client=model, detector=detector)
    got = by_kind(r["amenities"])
    assert got["pool"]["count"] == 1                                    # attribute + box + three views from the gym
    assert got["pool"]["sources"] == sorted([A.AERIAL_ATTRIBUTE, A.AERIAL_DETECTOR, A.PANORAMA])
    assert got["pool"]["instances"][0]["before_a_storm"]["aerial_loose_items"]["lounge chair"] == 1
    assert got["fitness room"]["count"] == 1 and got["fitness room"]["instances"][0]["place"]["scan_id"] == "GYM"
    assert got["fitness room"]["instances"][0]["before_a_storm"]["equipment"] == ["treadmill"]
    assert got["covered parking"]["count"] == 1
    assert r["sources"][A.AERIAL_DETECTOR]["boxes_dropped"] == {"outside_parcel": 1, "is_a_building": 0, "low_score": 1}
    for a in r["amenities"]:
        for inst in a["instances"]:
            assert inst["place"]["type"] in ("site point", "scan", "parcel") and inst["sources"] and 0 < inst["confidence"] <= 1
    assert r["calls"]["this_run"] == {"detector": 3, "vision": 3}       # two frame calls, one pool window, three looks

    again = run(community, tmp_path, client=model, detector=detector)   # everything is cached now
    assert again["calls"]["this_run"] == {"detector": 0, "vision": 0}
    assert len(detector.calls) == 3 and model.calls == 3
    assert by_kind(again["amenities"])["pool"]["count"] == 1
    assert again["calls"]["detector_calls_used"] == 3 and again["calls"]["vision_calls_used"] == 3


def test_without_a_detector_or_a_client_sources_say_not_checked(community, tmp_path):
    r = run(community, tmp_path, client=None, detector=None, attributes=None)
    assert r["sources"][A.AERIAL_DETECTOR]["status"] == "not checked"
    assert r["sources"][A.AERIAL_ATTRIBUTE]["status"] == "not checked"
    assert r["sources"][A.PANORAMA]["status"] == "not checked"
    assert r["calls"]["this_run"] == {"detector": 0, "vision": 0}
    missing = by_kind(r["comparison"]["listed_not_found"])
    assert missing["pool"]["status"] == "not checked" and missing["playground"]["status"] == "not checked"
    assert by_kind(r["amenities"])["fitness room"]["sources"] == [A.SCAN_NAME]


def test_budget_stops_paid_calls_at_the_limit(community, tmp_path):
    detector, model = ScriptedDetector(), ScriptedModel()
    budget = A.Budget(tmp_path / "ledger.json", detector_limit=1, vision_limit=2)
    r = run(community, tmp_path, client=model, detector=detector, budget=budget)
    assert len(detector.calls) == 1 and model.calls == 2                # never one more than allowed
    assert r["sources"][A.AERIAL_DETECTOR]["status"] == "partly checked"
    assert "budget" in r["sources"][A.PANORAMA]["stopped"]
    assert r["calls"]["detector_calls_used"] == 1 and r["calls"]["vision_calls_used"] == 2
    missing = by_kind(r["comparison"]["listed_not_found"])
    assert missing["covered parking"]["status"] == "checked, not seen"  # the footprints ran; the carport label did not
    assert "ran only in part" in missing["covered parking"]["why"]

    reloaded = A.Budget(tmp_path / "ledger.json", detector_limit=1, vision_limit=2)   # the ledger survives a restart
    assert reloaded.left("detector") == 0 and reloaded.left("vision") == 0
    with pytest.raises(A.BudgetExceeded):
        reloaded.charge("vision")
    assert A.DETECTOR_LIMIT == 30 and A.VISION_LIMIT == 60
