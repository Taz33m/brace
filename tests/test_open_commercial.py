"""Room labelling for commercial scans, driven by a scripted stand-in for the vision model: no network, no keys."""
from __future__ import annotations

import json
import threading
from types import SimpleNamespace

import pytest
from PIL import Image

from backend import matterport
from backend.openproblems import commercial


def storm(seen=None):
    """The model's five seen / not seen answers; `seen` maps the kinds that were seen to what was seen."""
    seen = seen or {}
    return {field: {"seen": kind in seen, "what": seen.get(kind, "")} for field, kind in commercial.STORM_FIELDS.items()}


def body(room_type="open office", confidence="high", reason="Rows of desks with monitors", seen=None):
    return {"room_type": room_type, "confidence": confidence, "reason": reason, "storm": storm(seen)}


def reply(room_type="open office", confidence="high", reason="Rows of desks with monitors", seen=None, stop="end_turn"):
    return SimpleNamespace(stop_reason=stop, content=[SimpleNamespace(type="text", text=json.dumps(body(room_type, confidence, reason, seen)))])


def raw(text, stop="end_turn"):
    return SimpleNamespace(stop_reason=stop, content=[SimpleNamespace(type="text", text=text)])


class Script:
    """Hands out the scripted replies in order and keeps every request it was sent."""

    def __init__(self, replies):
        self.replies = list(replies)
        self.requests = []
        self._lock = threading.Lock()
        self.messages = SimpleNamespace(create=self._create)

    def _create(self, **kw):
        with self._lock:
            self.requests.append(kw)
            if not self.replies:
                raise AssertionError("the model was called more often than the script allows")
            return self.replies.pop(0)


def sweep(sid, room, x, y):
    return {"id": sid, "x": x, "y": y, "z": 0.0, "room_id": room, "floor_id": "f1", "has_pano": True}


def room(rid, kind="Other", label="", polygon=None, area=400.0):
    return {"id": rid, "type": kind, "label": label, "floor_id": "f1", "area_sqft": area, "polygon": polygon}


SQUARE = [[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]]


@pytest.fixture
def scan(tmp_path, monkeypatch):
    """Patches the scan source and the cache folder; call it with rooms and sweeps to set the scan up."""
    face = tmp_path / "face.jpg"
    Image.new("RGB", (64, 64), (180, 180, 170)).save(face)
    monkeypatch.setattr(commercial, "OUT_DIR", tmp_path / "open" / "commercial")
    monkeypatch.setattr(matterport, "face_image", lambda model, sw, f: face)
    monkeypatch.setattr(matterport, "download_faces", lambda model, sweeps, faces: 0)
    holder = {}
    monkeypatch.setattr(matterport, "fetch_model", lambda model_id, refresh=False: holder[model_id])

    def make(rooms, sweeps, model_id="SCAN1"):
        holder[model_id] = {"id": model_id, "name": "Test Suite", "floors": [{"id": "f1", "label": "Floor 1", "sequence": 0}],
                            "rooms": rooms, "sweeps": sweeps}
        return model_id

    return make


def test_normal_answer_sits_beside_matterports_label(scan):
    mid = scan([room("r1", "Other", polygon=SQUARE)], [sweep("s1", "r1", 5, 5)])
    script = Script([reply("server or IT room", "high", "Two racks of servers and a wall of patch panels",
                           {"electronics at floor level": "server racks standing on the floor"})])
    out = commercial.label_rooms(mid, client=script)
    r = out["rooms"][0]
    assert r["matterport"] == {"type": "Other", "label": "", "real_type": False, "named": False}
    assert r["ours"]["type"] == "server or IT room" and r["ours"]["confidence"] == "high"
    assert r["status"] == "labelled" and r["sweep_id"] == "s1" and "deepest inside" in r["chosen_by"]
    assert r["storm"] == [{"kind": "electronics at floor level", "seen": "server racks standing on the floor", "sweep_id": "s1", "views": 1}]
    s = out["summary"]
    assert (s["matterport_real_type"], s["ours_real_type"], s["type_counts"]) == (0, 1, {"server or IT room": 1})
    assert s["storm_rooms"][0]["room_id"] == "r1" and s["storm_rooms"][0]["score"] == 3
    assert out["calls"] == {"made_this_run": 1, "answers_from_cache": 0, "made_ever_all_scans": 1, "budget": commercial.BUDGET}
    req = script.requests[0]  # called the way backend/vision.py calls the model
    assert req["model"] == commercial.VISION_MODEL and req["output_config"]["format"]["type"] == "json_schema"
    assert [b["type"] for b in req["messages"][0]["content"]] == ["image", "text"]
    assert commercial.image_path(mid, "r1", "s1").exists()
    assert json.loads((commercial.OUT_DIR / f"{mid}.json").read_text())["rooms"][0]["ours"]["type"] == "server or IT room"


@pytest.mark.parametrize("bad", [
    raw("It looks like an office to me."),
    raw(json.dumps(body("bedroom"))),
    raw(json.dumps({**body("corridor"), "storm": {"piano": {"seen": True, "what": "a piano"}}})),
    raw(json.dumps({**body("corridor"), "confidence": 0.9})),
    raw(json.dumps(body("corridor", seen={"outside door": "  "}))),  # says seen, names nothing
    reply(stop="refusal"),
])
def test_unreadable_answer_is_no_label_and_is_not_paid_for_again(scan, bad):
    mid = scan([room("r1", polygon=SQUARE)], [sweep("s1", "r1", 5, 5)])
    out = commercial.label_rooms(mid, client=Script([bad]))
    r = out["rooms"][0]
    assert r["ours"] is None and r["status"] == "no answer" and r["why"]
    assert out["summary"]["ours_real_type"] == 0 and out["summary"]["ours_no_answer"] == 1 and out["summary"]["type_counts"] == {}
    assert out["summary"]["unlabelled"][0]["room_id"] == "r1"
    again = commercial.label_rooms(mid, client=Script([]))  # an empty script fails the test if it is called
    assert again["rooms"][0]["status"] == "no answer" and again["calls"]["made_this_run"] == 0
    retried = commercial.label_rooms(mid, client=Script([reply("corridor")]), retry_failed=True)
    assert retried["rooms"][0]["ours"]["type"] == "corridor" and commercial.calls_made()["total"] == 2


def test_cannot_tell_is_kept_and_not_counted_as_a_label(scan):
    mid = scan([room("r1", "Void", polygon=SQUARE)], [sweep("s1", "r1", 5, 5)])
    out = commercial.label_rooms(mid, client=Script([reply("cannot tell", "low", "View is a blank wall and a closed door")]))
    r = out["rooms"][0]
    assert r["ours"]["type"] == "cannot tell" and r["status"] == "cannot tell" and r["types_seen"] == {}
    s = out["summary"]
    assert (s["ours_real_type"], s["ours_cannot_tell"], s["type_counts"]) == (0, 1, {})
    assert s["unlabelled"] == [{"room_id": "r1", "status": "cannot tell", "why": "View is a blank wall and a closed door"}]


def test_cache_prevents_a_second_call(scan):
    mid = scan([room("r1", polygon=SQUARE), room("r2", "Hallway", polygon=[[20, 0], [24, 0], [24, 4], [20, 4], [20, 0]])],
               [sweep("s1", "r1", 5, 5), sweep("s2", "r2", 22, 2)])
    first = commercial.label_rooms(mid, client=Script([reply("corridor"), reply("corridor")]))
    assert first["calls"]["made_this_run"] == 2
    second = commercial.label_rooms(mid, client=Script([]))
    assert second["calls"]["made_this_run"] == 0 and second["calls"]["answers_from_cache"] == 2
    assert [r["ours"] for r in second["rooms"]] == [r["ours"] for r in first["rooms"]]
    assert commercial.calls_made() == {"total": 2, "by_model": {mid: 2}}
    assert second["summary"]["matterport_real_type"] == 1 and second["summary"]["ours_real_type"] == 2


def test_run_limit_is_respected_and_first_looks_come_first(scan):
    rooms = [room(f"r{i}", polygon=[[30 * i, 0], [30 * i + 20, 0], [30 * i + 20, 20], [30 * i, 20], [30 * i, 0]]) for i in range(3)]
    sweeps = [sweep(f"s{i}{k}", f"r{i}", 30 * i + 2 + 8 * k, 10) for i in range(3) for k in range(3)]
    mid = scan(rooms, sweeps)
    script = Script([reply("warehouse floor")] * 3)
    out = commercial.label_rooms(mid, client=script, limit=3)
    assert len(script.requests) == 3 and out["calls"]["made_this_run"] == 3
    assert [r["status"] for r in out["rooms"]] == ["labelled"] * 3  # every room got its first look before any second look
    assert all(v["status"] == "not looked at" and "limit" in v["why"] for r in out["rooms"] for v in r["other_views"])
    tight = commercial.label_rooms(mid, client=Script([]), limit=0)
    assert tight["calls"]["made_this_run"] == 0 and tight["summary"]["ours_real_type"] == 3


def test_limit_leaves_rooms_unlabelled_rather_than_guessed(scan):
    mid = scan([room("r1", polygon=SQUARE), room("r2", polygon=[[20, 0], [24, 0], [24, 4], [20, 4], [20, 0]])],
               [sweep("s1", "r1", 5, 5), sweep("s2", "r2", 22, 2)])
    out = commercial.label_rooms(mid, client=Script([reply("gym")]), limit=1)
    assert [r["status"] for r in out["rooms"]] == ["labelled", "not looked at"]
    assert out["rooms"][1]["ours"] is None and out["summary"]["ours_not_looked_at"] == 1


def test_overall_budget_is_a_hard_stop(scan, monkeypatch):
    monkeypatch.setattr(commercial, "BUDGET", 2)
    rooms = [room(f"r{i}", polygon=[[30 * i, 0], [30 * i + 4, 0], [30 * i + 4, 4], [30 * i, 4], [30 * i, 0]]) for i in range(4)]
    mid = scan(rooms, [sweep(f"s{i}", f"r{i}", 30 * i + 2, 2) for i in range(4)])
    script = Script([reply("storage")] * 2)
    out = commercial.label_rooms(mid, client=script)
    assert len(script.requests) == 2 and commercial.calls_made()["total"] == 2
    assert [r["status"] for r in out["rooms"]] == ["labelled", "labelled", "not looked at", "not looked at"]
    assert "budget" in out["rooms"][3]["why"]
    assert commercial.label_rooms(mid, client=Script([]))["calls"]["made_this_run"] == 0  # still nothing more is sent


def test_room_without_a_scan_position_is_listed_and_never_asked_about(scan):
    mid = scan([room("r1", polygon=SQUARE), room("empty", "Void", polygon=[[20, 0], [24, 0], [24, 4], [20, 4], [20, 0]])],
               [sweep("s1", "r1", 5, 5)])
    script = Script([reply("meeting room")])
    out = commercial.label_rooms(mid, client=script)
    assert len(script.requests) == 1
    assert out["rooms"][1]["status"] == "no scan position" and out["rooms"][1]["ours"] is None
    s = out["summary"]
    assert (s["rooms"], s["rooms_with_a_scan_position"], s["rooms_without_a_scan_position"]) == (2, 1, 1)


def test_further_looks_never_change_the_rooms_label(scan):
    mid = scan([room("hall", "Hallway", polygon=[[0, 0], [40, 0], [40, 10], [0, 10], [0, 0]], area=4000)],
               [sweep("mid", "hall", 20, 5), sweep("west", "hall", 2, 5), sweep("east", "hall", 38, 5)])
    script = Script([reply("corridor", "high", "Long passage with doors both sides"),
                     reply("loading dock", "medium", "Raised platform and a roll-up door", {"dock or roll-up door": "roll-up door on the far wall"}),
                     reply("cannot tell", "low", "Camera faces a blank wall")])
    out = commercial.label_rooms(mid, client=script, limit=1)  # the first look alone, so the order of replies is fixed
    assert out["rooms"][0]["sweep_id"] == "mid" and out["rooms"][0]["ours"]["type"] == "corridor"
    out = commercial.label_rooms(mid, client=script, max_views=3)
    r = out["rooms"][0]
    assert r["ours"]["type"] == "corridor" and r["mixed"] and r["types_seen"] == {"corridor": 1, "loading dock": 1}
    assert sorted(v["type"] for v in r["other_views"]) == ["cannot tell", "loading dock"]
    assert r["storm"][0]["kind"] == "dock or roll-up door" and r["storm_score"] == 3
    s = out["summary"]
    assert s["matterport_real_type"] == 1 and s["ours_real_type"] == 1 and s["mixed_rooms"] == 1
    assert s["looks"] == 3 and s["looks_cannot_tell"] == 1 and s["look_type_counts"] == {"corridor": 1, "loading dock": 1}


def test_choose_views_picks_the_position_deepest_inside_then_spreads_out():
    r = room("r1", polygon=[[0, 0], [30, 0], [30, 10], [0, 10], [0, 0]])
    sweeps = [sweep("door", "r1", 0.5, 5), sweep("centre", "r1", 15, 5), sweep("near", "r1", 16, 5), sweep("far", "r1", 28, 5)]
    views, how = commercial.choose_views(r, sweeps)
    assert views[0]["id"] == "centre" and "deepest inside" in how
    assert [v["id"] for v in views] == ["centre", "door", "far"]  # "near" is within the minimum spacing and is skipped
    assert [v["id"] for v in commercial.choose_views(r, sweeps, max_views=1)[0]] == ["centre"]
    views, how = commercial.choose_views(room("r2"), [sweep("a", "r2", 0, 0), sweep("b", "r2", 1, 0), sweep("c", "r2", 9, 0)])
    assert views[0]["id"] == "b" and "no usable outline" in how
    assert commercial.choose_views(r, []) == ([], "no scan position inside this room")


def test_parse_answer_cuts_an_overlong_reason_and_says_so():
    long = " ".join(["word"] * 20)
    a = commercial.parse_answer(json.dumps(body("atrium", "medium", long)))
    assert len(a["reason"].split()) == commercial.MAX_REASON_WORDS and a["reason_cut"] is True and a["storm_items"] == []
    assert commercial.parse_answer("") is None and commercial.parse_answer("[]") is None


def test_no_client_is_needed_when_everything_is_cached(scan, monkeypatch):
    mid = scan([room("r1", polygon=SQUARE)], [sweep("s1", "r1", 5, 5)])
    commercial.label_rooms(mid, client=Script([reply("restroom")]))
    monkeypatch.setattr(commercial.anthropic, "Anthropic", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no client should be made")))
    assert commercial.label_rooms(mid)["rooms"][0]["ours"]["type"] == "restroom"


def test_a_storm_item_marked_not_seen_is_never_listed(scan):
    mid = scan([room("r1", polygon=SQUARE)], [sweep("s1", "r1", 5, 5)])
    b = body("private office", seen={"large glass": "window wall on the left"})
    b["storm"]["outside_door"] = {"seen": False, "what": "no exterior door visible"}  # a remark on something absent
    out = commercial.label_rooms(mid, client=Script([raw(json.dumps(b))]))
    assert [s["kind"] for s in out["rooms"][0]["storm"]] == ["large glass"]
    assert out["rooms"][0]["ours"]["storm_items"] == [{"kind": "large glass", "seen": "window wall on the left"}]


def test_an_answer_to_an_older_wording_is_not_reused(scan, monkeypatch):
    mid = scan([room("r1", polygon=SQUARE)], [sweep("s1", "r1", 5, 5)])
    commercial.label_rooms(mid, client=Script([reply("storage")]))
    monkeypatch.setattr(commercial, "PROMPT_VERSION", commercial.PROMPT_VERSION + 1)
    out = commercial.label_rooms(mid, client=Script([reply("corridor")]))
    assert out["rooms"][0]["ours"]["type"] == "corridor" and commercial.calls_made()["total"] == 2


def test_vacant_rooms_are_counted_apart_from_rooms_whose_use_was_named(scan):
    mid = scan([room("r1", polygon=SQUARE)], [sweep("s1", "r1", 5, 5)])
    s = commercial.label_rooms(mid, client=Script([reply(commercial.VACANT, "medium", "Empty carpeted room, nothing shows its use")]))["summary"]
    assert (s["ours_real_type"], s["ours_use_named"], s["ours_vacant"]) == (1, 0, 1)
