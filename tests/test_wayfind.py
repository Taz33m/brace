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
             "sweeps": [pos("u1", 0, 0, 5, "up", "f2", ["u2"]), pos("u2", 10, 0, 5, "up", "f2", ["u1", "stair"]), pos("stair", 14, 0, 5, "up", "f2", ["u2", "door"]),
                        pos("door", 14, 4, 1.4, "big", "f1", ["stair", "mid"]), pos("mid", 15, 10, 1.4, "big", "f1", ["door", "far"]), pos("far", 28, 18, 1.4, "big", "f1", ["mid"])]}
    monkeypatch.setattr(wayfind.matterport, "fetch_model", lambda model_id: model)
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
    assert [(lv["label"], lv["positions"]) for lv in where["levels"]] == [("Level 1", 3), ("Level 2", 3)]     # the empty floor has no positions and no level
    assert [(r["type"], r["typed_by"], r["area_sqft"]) for r in where["rooms"]] == [("atrium", "Brace", 6444), ("meeting room", "Brace", 2469)]
    first = where["positions"][0]
    assert first["lon"] == pytest.approx(-74.6555, abs=1e-5) and first["heading"] is not None and first["sees"] == ["u2"]


def test_the_schedule_names_the_place_and_the_room_types_find_the_room(hall):
    got = wayfind.find(hall, "Where is the git push up challenge?", "u1")
    assert got["found"] and got["event"] == "Git Push-Up Challenge" and got["place"] == "JRR Forum"
    assert got["room"]["type"] == "atrium" and got["room"]["typed_by"] == "Brace" and got["room"]["level"] == "Level 1"
    assert got["say"].startswith("Git Push-Up Challenge is at JRR Forum. That is the atrium on Level 1")
    assert got["schedule_source"] == "told to the team by the organisers"


def test_the_way_is_the_shortest_walk_and_ends_in_the_middle_of_the_room(hall):
    way = wayfind.find(hall, "the push-up challenge", "u1")["route"]
    assert way["positions"] == ["u1", "u2", "stair", "door", "mid"]                     # in at the door, then on to the middle; never to the far corner
    assert way["levels_changed"] == 1 and [g["level_change"] for g in way["legs"]] == [0, 0, -1, 0]
    assert way["metres"] == pytest.approx(10 + 4 + (4 ** 2 + 3.6 ** 2) ** 0.5 + (1 + 36) ** 0.5, abs=0.2)
    assert "down one level" in way["says"] and all(g["bearing"] is not None for g in way["legs"])


def test_a_kind_of_room_can_be_asked_for_directly_and_an_unknown_place_is_said_to_be_unknown(hall):
    room = wayfind.find(hall, "where is the conference room", "door")
    assert room["found"] and room["event"] is None and room["room"]["type"] == "meeting room" and room["route"]["positions"][-1] in ("u1", "u2", "stair")
    nowhere = wayfind.find(hall, "where is the swimming pool", "u1")
    assert nowhere["found"] is False and "no room in this scan matches" in nowhere["say"]
    assert wayfind.find(hall, "the forum")["route"] is None                               # no starting position, so a place but no way
