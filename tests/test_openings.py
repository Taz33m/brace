"""Which measured windows and outside doors of a scanned space face a point on the site."""
import math

from backend import openings

LAT0, LON0 = 29.6, -95.2
KX = openings.M_PER_DEG * math.cos(math.radians(LAT0))


def vertex(x, y):
    return {"position": {"x": x, "y": y}}


def wall(a, b, *holes):
    return {"id": f"e{a}{b}", "type": "wall", "vertices": [vertex(*a), vertex(*b)], "openings": list(holes)}


def hole(oid, kind, width, where=0.5, height=1.5):
    return {"id": oid, "type": kind, "width": width, "height": height, "lowerElevation": 0.9, "relativeCenter": where, "label": kind}


def room(rid, label, corners, holes=None):
    """A room from its corners in order; `holes` maps a wall's index to the openings in it."""
    holes = holes or {}
    edges = [wall(corners[i], corners[(i + 1) % len(corners)], *holes.get(i, [])) for i in range(len(corners))]
    return {"id": rid, "label": "", "classifications": [{"label": label}], "boundary": {"edges": edges}}


def placed(x, y, turn_deg=0.0):
    """A viewpoint whose site position is its scan position turned clockwise by `turn_deg` (scan +y is north at 0)."""
    t = math.radians(turn_deg)
    east, north = x * math.cos(t) + y * math.sin(t), -x * math.sin(t) + y * math.cos(t)
    return {"id": f"w{x}{y}", "lon": LON0 + east / KX, "lat": LAT0 + north / openings.M_PER_DEG, "model_position": {"x": x, "y": y, "z": 1.4}}


def scan(turn_deg=0.0):
    return {"id": "SCAN", "name": "Unit 1", "sweeps": [placed(0, 0, turn_deg), placed(3, 0, turn_deg), placed(0, 3, turn_deg), placed(3, 3, turn_deg)]}


# A bedroom 4 m square with a window in its east wall and a door in its north wall into a hall,
# and a living room with a door onto a patio.
BEDROOM = room("bed", "Bedroom", [(0, 0), (4, 0), (4, 4), (0, 4)], {1: [hole("win", "window", 1.2)], 2: [hole("door", "doorway", 0.8, height=2.0)]})
HALL = room("hall", "Hallway", [(0, 4), (4, 4), (4, 6), (0, 6)], {0: [hole("door", "doorway", 0.8, height=2.0)]})
LIVING = room("liv", "Living Room", [(-5, 0), (0, 0), (0, 4), (-5, 4)], {3: [hole("slider", "doorway", 1.8, height=2.0)]})
PATIO = room("pat", "Patio", [(-7, 0), (-5, 0), (-5, 4), (-7, 4)], {1: [hole("slider", "doorway", 1.8, height=2.0)]})
ROOMS = [BEDROOM, HALL, LIVING, PATIO]


def by_id(plan):
    return {o["id"]: o for o in plan["openings"]}


def test_an_opening_gets_its_measured_size_a_place_and_the_way_it_faces():
    plan = openings.layout(scan(), ROOMS)
    win = by_id(plan)["win"]
    assert win["kind"] == "window" and win["room"] == "Bedroom" and win["width_m"] == 1.2 and win["height_m"] == 1.5
    assert win["at"] == [4.0, 2.0] and win["faces_deg"] == 90.0 and win["outside"] is True       # east wall, faces east
    assert plan["placement_error_m"] < 0.01 and len(plan["rooms"]) == 4


def test_a_door_between_two_rooms_is_inside_and_a_door_onto_a_patio_is_outside():
    found = by_id(openings.layout(scan(), ROOMS))
    assert found["door"]["outside"] is False
    slider = found["slider"]
    assert slider["outside"] is True and slider["room"] == "Living Room" and slider["faces_deg"] == 270.0   # seen from the room, facing out


def test_turning_the_scan_on_the_site_turns_what_its_openings_face():
    win = by_id(openings.layout(scan(turn_deg=30), ROOMS))["win"]
    assert abs(win["faces_deg"] - 120.0) < 0.2


def test_facing_lists_only_outside_openings_that_look_toward_the_point():
    plan = openings.layout(scan(), ROOMS)
    east = openings.facing(plan, LON0 + 30 / KX, LAT0 + 2 / openings.M_PER_DEG)          # 30 m east of the bedroom
    assert [f["id"] for f in east["facing"]] == ["win"] and round(east["facing"][0]["metres"]) == 26
    west = openings.facing(plan, LON0 - 30 / KX, LAT0 + 2 / openings.M_PER_DEG)
    assert [f["id"] for f in west["facing"]] == ["slider"]
    north = openings.facing(plan, LON0 + 2 / KX, LAT0 + 40 / openings.M_PER_DEG)         # the hall door looks that way but is inside
    assert north["facing"] == []


def test_the_sentence_speaks_for_the_scanned_space_only_and_says_when_nothing_faces():
    plan = openings.layout(scan(), ROOMS)
    hit = openings.facing(plan, LON0 + 30 / KX, LAT0 + 2 / openings.M_PER_DEG)["facing"]
    assert openings.sentence("Unit 1", hit) == "In Unit 1, the bedroom window, 1.2 m wide by 1.5 m, faces it from about 26 m."
    assert openings.sentence("Unit 1", []) == "No window or outside door in Unit 1 faces it."


def test_a_scan_that_cannot_be_placed_is_not_drawn():
    assert openings.layout({"id": "S", "sweeps": [placed(0, 0), placed(1, 0)]}, ROOMS) is None            # too few viewpoints
    assert openings.layout({"id": "S", "sweeps": [placed(0, 0), placed(1, 0), placed(2, 0)]}, ROOMS) is None  # all on one line
    stretched = scan()
    stretched["sweeps"][1]["lon"] = LON0 + 9 / KX                                                           # positions that do not fit the scan
    assert openings.layout(stretched, ROOMS) is None


def test_for_plan_uses_the_nearest_placed_scan_and_skips_inside_actions(monkeypatch):
    monkeypatch.setattr(openings, "fetch", lambda model_id, refresh=False: ROOMS)
    site = {"scans": [scan(), {"id": "FAR", "name": "Unplaced", "sweeps": [{"id": "x", "lon": None, "lat": None}]}]}
    plan = {"actions": [
        {"id": "A1", "site": {"lon": LON0 + 30 / KX, "lat": LAT0 + 2 / openings.M_PER_DEG}, "interior": None},
        {"id": "A2", "site": None, "interior": {"scan_id": "SCAN"}},
        {"id": "A3", "site": {"lon": LON0 + 500 / KX, "lat": LAT0}, "interior": None},                   # too far from any scan to say anything
    ]}
    got = openings.for_plan(site, plan)
    assert list(got["actions"]) == ["A1"] and list(got["plans"]) == ["SCAN"]
    assert got["actions"]["A1"]["scan_id"] == "SCAN" and got["actions"]["A1"]["line"].startswith("In Unit 1, the bedroom window")
