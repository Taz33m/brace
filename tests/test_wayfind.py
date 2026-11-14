"""Finding a place in a scanned building: the schedule says what is where, the room types say which room, the scan gives the way."""
import json

import pytest

from backend import wayfind


@pytest.fixture
def hall(tmp_path, monkeypatch):
    """Two levels. Upstairs is a meeting room; downstairs a big unlabelled space Brace typed as an atrium. One stair joins them."""
    def pos(pid, x, y, z, room, floor, sees):
        return {"id": pid, "x": x, "y": y, "z": z, "room_id": room, "floor_id": floor, "has_pano": True, "neighbors": sees,
                "rotation": {"x": 0, "y": 0, "z": 0, "w": 1}}
    model = {"id": "HALL", "name": "Test Hall", "created": "2026-11-10T00:00:00Z", "modified": None, "area_indoor_sqft": 8900, "area_with_walls_sqft": 9100, "geo": {"origin": [-74.6555, 40.3491], "ex10": [-74.65538, 40.3491], "ey10": [-74.6555, 40.34919]},
             "floors": [{"id": "f0", "label": "Floor 1", "sequence": 0}, {"id": "f1", "label": "Floor 2", "sequence": 1}, {"id": "f2", "label": "Floor 3", "sequence": 2}],
             "rooms": [{"id": "big", "type": "Hallway", "label": "", "floor_id": "f1", "area_sqft": 6444.5, "polygon": [[0, 0], [30, 0], [30, 20], [0, 20]]},
                       {"id": "up", "type": "Hallway", "label": "", "floor_id": "f2", "area_sqft": 2468.6, "polygon": [[0, 0], [20, 0], [20, 10], [0, 10]]},
                       {"id": "empty", "type": "Void", "label": "", "floor_id": "f0", "area_sqft": 0, "polygon": None}],
             # u1 also sees the hall floor across the void: a line of sight, not a way.
             "sweeps": [pos("u1", 0, 0, 5, "up", "f2", ["u2", "mid"]), pos("u2", 10, 0, 5, "up", "f2", ["u1", "stair"]), pos("stair", 14, 0, 5, "up", "f2", ["u2", "land"]),
                        pos("land", 14, 3, 3.2, "up", "f2", ["stair", "door"]), pos("door", 14, 6, 1.4, "big", "f1", ["land", "mid"]),
                        pos("mid", 15, 10, 1.4, "big", "f1", ["door", "far", "u1"]), pos("far", 28, 18, 1.4, "big", "f1", ["mid"])]}
    monkeypatch.setattr(wayfind.matterport, "fetch_model", lambda model_id: model)
    monkeypatch.setattr(wayfind, "walls", lambda model_id, refresh=False: [])
    from backend import wayfind_look
    monkeypatch.setattr(wayfind_look, "OUT", tmp_path / "looks")
    types = tmp_path / "types"
    types.mkdir()
    (types / "HALL.json").write_text(json.dumps({"rooms": [{"room_id": "big", "ours": {"type": "atrium", "confidence": "high"}},
                                                           {"room_id": "up", "ours": {"type": "meeting room", "confidence": "medium"}}]}))
    monkeypatch.setattr(wayfind, "ROOM_TYPES", types)
    schedule = tmp_path / "events.json"
    schedule.write_text(json.dumps([{"event": "Git Push-Up Challenge", "also_called": ["push-up challenge"], "place": "JRR Forum", "model_id": "HALL",
                                     "source": "told to the team by the organisers"}]))
    monkeypatch.setattr(wayfind, "EVENTS_FILE", schedule)
    return "HALL"


def test_a_place_has_levels_typed_rooms_and_positions_on_the_map(hall):
    where = wayfind.place(hall)
    assert [(lv["label"], lv["positions"]) for lv in where["levels"]] == [("Level 1", 3), ("Level 2", 4)]     # the empty floor has no positions and no level
    assert [(r["type"], r["typed_by"], r["area_sqft"]) for r in where["rooms"]] == [("atrium", "Brace", 6444), ("meeting room", "Brace", 2469)]
    first = where["positions"][0]
    assert first["lon"] == pytest.approx(-74.6555, abs=1e-5) and first["heading"] is not None and first["sees"] == ["u2", "mid"]


def test_the_schedule_names_the_place_and_the_room_types_find_the_room(hall):
    got = wayfind.find(hall, "Where is the git push up challenge?", "u1")
    assert got["found"] and got["event"] == "Git Push-Up Challenge" and got["place"] == "JRR Forum"
    assert got["room"]["type"] == "atrium" and got["room"]["typed_by"] == "Brace" and got["room"]["level"] == "Level 1"
    assert got["say"].startswith("Git Push-Up Challenge is at JRR Forum. That is the atrium on Level 1")
    assert got["schedule_source"] == "told to the team by the organisers"


def test_seeing_across_a_void_is_not_a_way_and_the_walk_goes_down_the_stairs(hall):
    way = wayfind.find(hall, "the push-up challenge", "u1")["route"]
    assert way["positions"] == ["u1", "u2", "stair", "land", "door", "mid"]             # never u1 straight to the hall floor it can see
    assert [g["kind"] for g in way["legs"]] == ["level", "level", "stairs", "stairs", "level"]
    assert way["stairs"] == {"flights": 2, "rise_m": 3.6} and way["lift"] is False and "down 2 flights of stairs" in way["says"]
    assert all(g["bearing"] is not None for g in way["legs"])


def test_a_wheelchair_cannot_take_the_stairs_and_is_told_so_when_there_is_no_other_way(hall):
    got = wayfind.find(hall, "the push-up challenge", "u1", mover="wheelchair")
    assert got["found"] and got["route"] is None and got["no_way"] is True
    assert "cannot find a step-free way" in got["say"] and "2 flights of stairs" in got["say"]


def test_a_lift_seen_on_both_levels_is_the_wheelchairs_way_and_the_change_is_spelled_out(hall):
    where = wayfind.place(hall)
    lift = [{"levels": [1, 2], "basis": "lift doors seen on both levels", "ends": [
        {"level": 1, "position_id": "far", "metres_from_position": 1.5, "x": 28.0, "y": 19.0},
        {"level": 2, "position_id": "u1", "metres_from_position": 1.0, "x": 0.0, "y": 1.0}]}]
    chair = wayfind.route(where, "u2", "big", "wheelchair", 27.0, lift)
    assert [g["kind"] for g in chair["legs"]] == ["level", "lift", "level"] and chair["positions"] == ["u2", "u1", "far", "mid"]
    assert chair["lift"] and chair["stairs"] is None and "No steps on the way" in chair["says"] and "seen from the scan, not ridden" in chair["says"]
    on_foot = wayfind.route(where, "u2", "big", "walking", 27.0, lift)
    assert on_foot["stairs"]["flights"] == 2 and on_foot["metres"] < chair["metres"]      # walking still takes the stairs: they are shorter


def test_a_doorway_narrower_than_the_chair_bars_the_way_and_a_wall_bars_everyone():
    def at(pid, x, y):
        return {"id": pid, "x": x, "y": y, "z": 1.4, "level": 1}
    wall = {"a": (5.0, -3.0), "b": (5.0, 3.0), "doors": [{"t0": 0.4, "t1": 0.6, "width_m": 0.75}]}     # a 29.5 inch doorway in the middle
    through = wayfind.link(at("a", 0, 0), at("b", 10, 0), [wall])
    assert through["kind"] == "level" and through["doors"] == [{"width_in": 29.5, "clear_in": 27.6}]
    assert wayfind._allowed(through, "walking", 27.0) and not wayfind._allowed(through, "wheelchair", 27.0)    # 27.6 clear is less than 27 plus 2 to spare
    assert wayfind._allowed(through, "wheelchair", 25.0)
    assert wayfind.link(at("a", 0, 2.5), at("b", 10, 2.5), [wall]) is None                 # the same wall where there is no doorway


def test_the_narrowest_point_between_walls_is_measured_across_the_walk():
    left = {"a": (0.0, 1.0), "b": (10.0, 1.0), "doors": []}
    right = {"a": (0.0, -0.8), "b": (10.0, -0.8), "doors": []}
    a, b = {"x": 1.0, "y": 0.0}, {"x": 9.0, "y": 0.0}
    assert wayfind.passage(a, b, [left, right]) == 1.8
    assert wayfind.passage(a, b, [left]) is None                                           # open on one side: nothing to squeeze through


def test_a_kind_of_room_can_be_asked_for_directly_and_an_unknown_place_is_said_to_be_unknown(hall):
    room = wayfind.find(hall, "where is the conference room", "door")
    assert room["found"] and room["event"] is None and room["room"]["type"] == "meeting room" and room["route"]["positions"][-1] in ("u1", "u2", "stair", "land")
    nowhere = wayfind.find(hall, "where is the swimming pool", "u1")
    assert nowhere["found"] is False and "no room in this scan matches" in nowhere["say"]
    assert wayfind.find(hall, "the forum")["route"] is None                               # no starting position, so a place but no way
