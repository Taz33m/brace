"""Search inside scans: ranking, directions and the coverage statement. No network, no keys, a made-up index."""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from PIL import Image

from backend.openproblems import search as S

PID = 7


def thing(name, quarter, category="fixture", where="in this room", detail=""):
    return {"name": name, "category": category, "quarter": quarter, "where": where, "detail": detail}


def pos(scan, sweep, room_id, room_type, things, light="daylight", heading=0.0, seen=(), description="", face1_yaw=90.0):
    return {"scan_id": scan, "scan_name": f"Unit {scan}", "sweep_id": sweep, "room_id": room_id, "room_label": None,
            "heading": heading, "face1_yaw": face1_yaw, "source": "vision", "survey_note": None, "room_type": room_type,
            "spaces_visible": list(seen), "light": light, "description": description, "things": things}


@pytest.fixture
def index(tmp_path, monkeypatch):
    monkeypatch.setattr(S, "OPEN_DIR", tmp_path)
    positions = [
        pos("A", "a1", "liv", "living room", [thing("sliding glass door", 2, "glazing", detail="opens to the balcony"),
                                              thing("sofa", 4, "on the floor")], heading=350.0),
        pos("A", "a2", "liv", "living room", [thing("sliding glass door", 3, "glazing")], heading=90.0),
        pos("A", "a3", "liv", "living room", [thing("sliding glass door", 1, "glazing")], heading=None, face1_yaw=None),
        pos("A", "a4", "kit", "kitchen", [thing("kitchen island", 3, detail="white counter"), thing("range", 1, "appliance"),
                                          thing("sliding glass door", 2, "glazing", where="through a doorway")],
            light="direct sun", seen=["living room"]),
        pos("A", "a5", "lau", "laundry", [thing("stacked washer and dryer", 4, "appliance"),
                                          thing("sliding closet door", 2, "door")]),
        pos("B", "b1", "liv", "living room", [thing("slider", 4, "glazing"), thing("windows", 1, "glazing"),
                                              thing("glass coffee table", 2, "on the floor")], heading=45.0),
        pos("B", "b2", "kit", "kitchen", [thing("kitchen island", 2), thing("stove", 1, "appliance")], light="artificial light"),
        pos("B", "b3", "bal", "balcony or patio", [thing("folding chair", 1, "on a balcony or patio"),
                                                   thing("potted plant", 2, "on a balcony or patio"),
                                                   thing("balcony railing", 3, "other")],
            description="A small balcony. There is no grill here."),
    ]
    data = {"property_id": PID, "total_positions": 20, "indexed_positions": 8, "indexed_share": 0.4,
            "scans": {"A": {"name": "Unit A", "positions": 12, "indexed": 5}, "B": {"name": "Unit B", "positions": 8, "indexed": 3}},
            "positions": positions}
    (tmp_path / f"{PID}.json").write_text(json.dumps(data))
    return data


def ids(results):
    return [r["sweep_id"] for r in results]


# --- wording --------------------------------------------------------------------------------------------------
def test_plurals_and_synonyms_fold_to_one_spelling():
    assert S.tokens("sliders") == S.tokens("sliding glass door") == S.tokens("Sliding glass doors")
    assert S.tokens("stoves") == S.tokens("range") and S.tokens("range hood") != S.tokens("range")
    assert S.tokens("hot water heaters") == S.tokens("water heater")
    assert S.tokens("windows") == {"window"} and S.tokens("glass") == {"glass"}
    assert S.tokens("show me every washing machine") == {"washer"}


def test_synonym_in_the_query_finds_the_plain_name(index):
    assert set(ids(S.search(PID, "show me the sliders", k=10))) == set(ids(S.search(PID, "sliding glass door", k=10)))
    assert ids(S.search(PID, "stove", k=10)) == ["a4", "b2"]          # indexed as "range" and as "stove"


def test_synonym_in_the_index_is_found_by_the_plain_name(index):
    assert "b1" in ids(S.search(PID, "sliding glass doors", k=10))    # indexed as "slider"
    assert ids(S.search(PID, "window")) == ["b1"]                     # indexed as "windows"


def test_words_must_come_from_one_thing_not_be_pieced_together(index):
    hits = ids(S.search(PID, "every sliding glass door", k=20))
    assert "a5" not in hits                                           # a sliding closet door is not a glass slider
    assert ids(S.search(PID, "sliding door", k=20)).count("a5") == 1  # but it is a sliding door


def test_every_part_of_the_query_is_required(index):
    hits = S.search(PID, "sunlit kitchen with an island")
    assert ids(hits) == ["a4"]                                        # b2 has an island but is not sunlit
    assert hits[0]["thing"] == "kitchen island" and hits[0]["quarter"] == 3
    assert "direct sun" in hits[0]["phrase"] and "kitchen island" in hits[0]["phrase"]
    assert ids(S.search(PID, "washer and dryer")) == ["a5"]


def test_generic_ask_matches_on_the_kind_of_thing(index):
    hits = S.search(PID, "things left on a balcony")
    assert ids(hits) == ["b3"]                                        # not the slider that "opens to the balcony"
    assert "folding chair" in hits[0]["phrase"] and "potted plant" in hits[0]["phrase"]
    assert "railing" not in hits[0]["phrase"]


def test_nothing_matching_returns_nothing(index):
    assert S.search(PID, "water heater") == []
    assert S.search(PID, "fireplace") == []
    assert S.search(PID, "grill") == []                               # "There is no grill here" is not a grill
    assert S.search(PID, "the of and") == []


# --- ranking --------------------------------------------------------------------------------------------------
def test_at_most_two_results_from_one_room_unless_all_are_asked_for(index):
    hits = S.search(PID, "sliding glass door", k=10)
    assert sum(1 for r in hits if (r["scan_id"], r["room_id"]) == ("A", "liv")) == 2
    every = S.search(PID, "show me every sliding glass door", k=10)
    assert sum(1 for r in every if (r["scan_id"], r["room_id"]) == ("A", "liv")) == 3
    assert len(S.search(PID, "every sliding glass door", k=2)) == 2   # k still caps the list


def test_a_thing_in_the_room_outranks_one_seen_through_a_doorway(index):
    hits = S.search(PID, "every sliding glass door", k=10)
    assert ids(hits)[-1] == "a4" and hits[0]["score"] > hits[-1]["score"]
    assert all(0 < r["score"] <= 1 for r in hits)


class Reranker:
    """Stands in for the model: answers the one re-rank call with a fixed order."""

    def __init__(self, order):
        self.order, self.calls = order, 0
        self.messages = SimpleNamespace(create=self.create)

    def create(self, **kw):
        self.calls += 1
        self.kw = kw
        return SimpleNamespace(stop_reason="end_turn", content=[SimpleNamespace(type="text", text=json.dumps({"order": self.order}))])


def test_model_rerank_is_one_call_and_can_drop_candidates(index):
    text_order = ids(S.search(PID, "every sliding glass door", k=10))
    client = Reranker([3, 1, 99])
    hits = S.search(PID, "every sliding glass door", k=10, client=client)
    assert client.calls == 1 and ids(hits) == [text_order[2], text_order[0]]
    assert S.calls_used()["search"] == 1
    assert "image" not in json.dumps(client.kw["messages"])            # descriptions only, no imagery


def test_rerank_failure_falls_back_to_text_order(index):
    def boom(**kw):
        raise RuntimeError("offline")
    client = SimpleNamespace(messages=SimpleNamespace(create=boom))
    assert ids(S.search(PID, "sliding glass door", client=client)) == ids(S.search(PID, "sliding glass door"))


# --- directions -----------------------------------------------------------------------------------------------
def test_direction_arithmetic():
    assert S.bearing(0.0, 1) == 0.0 and S.compass(0.0) == "north"
    assert S.bearing(350.0, 2) == 80.0 and S.compass(80.0) == "east"       # wraps past north
    assert S.bearing(90.0, 3) == 270.0 and S.compass(270.0) == "west"
    assert S.bearing(45.0, 4) == 315.0 and S.compass(315.0) == "northwest"
    assert S.compass(337.4) == "northwest" and S.compass(337.6) == "north" and S.compass(22.4) == "north"
    assert S.bearing(None, 2) is None and S.bearing(10.0, None) is None and S.compass(None) is None
    assert S.viewer_yaw(90.0, 1) == 0.0 and S.viewer_yaw(90.0, 2) == -90.0 and S.viewer_yaw(-170.0, 1) == 100.0
    assert S.viewer_yaw(None, 1) is None


def test_result_carries_the_direction_to_face(index):
    by = {r["sweep_id"]: r for r in S.search(PID, "every sliding glass door", k=10)}
    assert (by["a1"]["quarter"], by["a1"]["bearing_deg"], by["a1"]["direction"]) == (2, 80.0, "east")
    assert (by["a2"]["bearing_deg"], by["a2"]["direction"]) == (270.0, "west")
    assert (by["b1"]["bearing_deg"], by["b1"]["direction"]) == (315.0, "northwest")
    assert by["a3"]["quarter"] == 1 and by["a3"]["direction"] is None      # no compass fix: quarter only, no made-up bearing
    assert by["a1"]["scan_name"] == "Unit A" and by["a1"]["viewer_yaw"] == -90.0


# --- counting -------------------------------------------------------------------------------------------------
def test_count_states_coverage_beside_the_number(index):
    c = S.count(PID, "sliding glass door")
    assert (c["rooms"], c["scans"]) == (2, 2)                              # the kitchen only sees it through a doorway
    assert (c["indexed_positions"], c["total_positions"], c["indexed_share"], c["complete"]) == (8, 20, 0.4, False)
    assert "8 of 20 scan positions were indexed (40%)" in c["statement"] and "may be higher" in c["statement"]
    assert {e["scan_id"]: e["rooms"] for e in c["by_scan"]} == {"A": 1, "B": 1}


def test_count_of_nothing_still_states_coverage(index):
    c = S.count(PID, "fireplace")
    assert (c["rooms"], c["scans"], c["positions"]) == (0, 0, 0)
    assert c["statement"].startswith("Nothing indexed shows") and "8 of 20" in c["statement"]


def test_search_without_an_index_says_so(tmp_path, monkeypatch):
    monkeypatch.setattr(S, "OPEN_DIR", tmp_path)
    with pytest.raises(S.SearchError):
        S.search(PID, "window")


# --- building the index with a scripted model -----------------------------------------------------------------
class Describer:
    def __init__(self):
        self.calls = 0
        self.messages = SimpleNamespace(create=self.create)

    def create(self, **kw):
        self.calls += 1
        assert kw["model"] == S.VISION_MODEL and kw["output_config"]["format"]["type"] == "json_schema"
        body = {"room_type": "office", "spaces_visible": [], "light": "daylight", "description": "An office.",
                "things": [thing("window", 2, "glazing")]}
        return SimpleNamespace(stop_reason="end_turn", content=[SimpleNamespace(type="text", text=json.dumps(body))])


def test_build_index_caches_counts_and_reports_share(site, tmp_path, monkeypatch):
    monkeypatch.setattr(S, "OPEN_DIR", tmp_path / "open")
    monkeypatch.setattr(S.matterport, "MP_CACHE", tmp_path / "mp")
    monkeypatch.setattr(S.matterport, "download_faces", lambda *a, **k: 0)
    monkeypatch.setattr(S, "fetch_fallback_faces", lambda *a, **k: 0)
    monkeypatch.setattr(S, "wide_image", lambda scan_id, sweep_id, side=512: Image.new("RGB", (64, 16)))
    (site.dir / "surveys").mkdir()
    (site.dir / "surveys" / "SCAN1.json").write_text(json.dumps([
        {"sweep_id": "w2", "glass": "large windows", "level": "ground", "floor_level_items": ["server rack"],
         "exterior_doors": "glass doors", "note": "An office suite."}]))
    client = Describer()

    first = S.build_index(site.id, client=client, limit=1)
    assert client.calls == 1 and (first["indexed_positions"], first["total_positions"], first["indexed_share"]) == (1, 2, 0.5)
    assert first["survey_only_positions"] == 1                             # w2 is known from the survey, without a direction
    hit = S.search(site.id, "server rack")[0]
    assert hit["sweep_id"] == "w2" and hit["quarter"] is None and hit["direction"] is None and hit["source"] == "survey"
    assert "1 of 2 scan positions were indexed (50%)" in S.count(site.id, "window")["statement"]

    second = S.build_index(site.id, client=client)
    assert client.calls == 2 and second["indexed_share"] == 1.0 and S.calls_used()["index"] == 2
    S.build_index(site.id, client=client)
    assert client.calls == 2                                               # everything cached: nothing paid for twice
    hit = S.search(site.id, "windows")[0]
    assert (hit["sweep_id"], hit["bearing_deg"], hit["direction"]) == ("w1", 180.0, "south")   # heading 90, quarter 2
    assert S.count(site.id, "window")["complete"] is True

    offline = S.build_index(site.id)                                       # no client: assembled from the cache, no calls
    assert offline["indexed_positions"] == 2 and client.calls == 2


def test_index_call_limit_is_enforced(site, tmp_path, monkeypatch):
    monkeypatch.setattr(S, "OPEN_DIR", tmp_path / "open")
    monkeypatch.setattr(S, "MAX_INDEX_CALLS", 1)
    monkeypatch.setattr(S.matterport, "MP_CACHE", tmp_path / "mp")
    monkeypatch.setattr(S.matterport, "download_faces", lambda *a, **k: 0)
    monkeypatch.setattr(S, "fetch_fallback_faces", lambda *a, **k: 0)
    monkeypatch.setattr(S, "wide_image", lambda scan_id, sweep_id, side=512: Image.new("RGB", (64, 16)))
    client = Describer()
    idx = S.build_index(site.id, client=client)
    assert client.calls == 1 and idx["indexed_positions"] == 1
    S.build_index(site.id, client=client)
    assert client.calls == 1


def test_island_is_only_an_island_when_the_check_says_so(site, tmp_path, monkeypatch):
    monkeypatch.setattr(S, "OPEN_DIR", tmp_path / "open")
    monkeypatch.setattr(S.matterport, "MP_CACHE", tmp_path / "mp")
    monkeypatch.setattr(S.matterport, "download_faces", lambda *a, **k: 0)
    monkeypatch.setattr(S, "fetch_fallback_faces", lambda *a, **k: 0)
    monkeypatch.setattr(S, "wide_image", lambda scan_id, sweep_id, side=512: Image.new("RGB", (64, 16)))
    calls = []

    def create(**kw):
        schema = kw["output_config"]["format"]["schema"]
        calls.append("check" if schema is S.ISLAND_SCHEMA else "describe")
        body = {"counter": "peninsula"} if schema is S.ISLAND_SCHEMA else {
            "room_type": "kitchen", "spaces_visible": [], "light": "daylight", "description": "A kitchen.",
            "things": [thing("kitchen island", 3, detail="white counter")]}
        return SimpleNamespace(stop_reason="end_turn", content=[SimpleNamespace(type="text", text=json.dumps(body))])

    client = SimpleNamespace(messages=SimpleNamespace(create=create))
    S.build_index(site.id, client=client)
    S.build_index(site.id, client=client)
    assert calls.count("describe") == 2 and calls.count("check") == 1      # one check per scan, cached
    assert S.search(site.id, "kitchen with an island") == []
    hits = S.search(site.id, "kitchen with a breakfast bar")
    assert len(hits) == 2 and hits[0]["thing"] == "kitchen peninsula" and hits[0]["quarter"] == 3
