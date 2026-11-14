"""Checking a resident's report against the scan made before the storm: the verdict by code, the look made once."""
import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from backend import report_check as rc
from backend import server
from backend import site_model as sm
from backend.config import VISION_MODEL

READ = {"thing_in_view": True, "thing": "white framed window", "floor_covering": "grey carpet",
        "damage_already_visible": False, "damage_or_staining": "none visible"}


@pytest.fixture
def site(tmp_path, monkeypatch):
    """One building with two scanned homes and a search index, written the way the stages write them."""
    cache = tmp_path / "cache"
    monkeypatch.setattr(sm, "CACHE_DIR", cache)
    monkeypatch.setattr(sm, "OPEN", cache / "open")
    monkeypatch.setattr(sm, "MP_CACHE", cache / "matterport")
    monkeypatch.setattr(sm, "building_dir", lambda pid: cache / "buildings" / str(pid))

    def write(path, data):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data))

    write(cache / "buildings" / "7" / "building.json", {
        "record": {"id": 7, "name": "Test Court", "address": "1 Test St", "city": "Houston", "state": "TX", "type_label": "Apartments", "units": 40},
        "site": {}, "aerial": {}, "structures": [],
        "scans": [{"id": "scanA", "name": "1BR - A1", "kind": "unit", "sweeps": [{"id": "p1"}, {"id": "p2"}, {"id": "p3"}],
                   "rooms": [{"id": "r1", "type": "Bedroom"}, {"id": "r2", "type": "Kitchen"}, {"id": "r3", "type": "Patio"}]},
                  {"id": "scanB", "name": "2BR - B1", "kind": "unit", "sweeps": [{"id": "q1"}], "rooms": [{"id": "s1", "type": "Living Room"}]}]})

    def position(scan, name, sweep, room_id, label, heading, things):
        return {"scan_id": scan, "scan_name": name, "sweep_id": sweep, "room_id": room_id, "room_label": label, "room_type": label.lower(),
                "heading": heading, "things": [{"name": n, "quarter": q, "where": w, "detail": d} for n, q, w, d in things]}

    write(cache / "open" / "search" / "7.json", {"positions": [
        position("scanA", "1BR - A1", "p1", "r1", "Bedroom", 0.0, [("window", 2, "in this room", "white frame, blinds closed")]),
        position("scanA", "1BR - A1", "p2", "r2", "Kitchen", 90.0, [("refrigerator", 1, "in this room", "white, freezer on top")]),
        position("scanA", "1BR - A1", "p3", "r3", "Patio", None, [("sliding glass door", 4, "through a doorway", "")]),
        position("scanB", "2BR - B1", "q1", "s1", "Living Room", 10.0, [("fireplace", 3, "in this room", "brick surround")])]})
    return 7


class FakeClient:
    """Stands in for the vision model: counts the looks and answers each the same way."""

    def __init__(self, said=READ, stop="end_turn", fail=False):
        self.said, self.stop, self.fail, self.calls = said, stop, fail, []
        self.messages = SimpleNamespace(create=self.create)

    def create(self, **kw):
        self.calls.append(kw)
        if self.fail:
            raise RuntimeError("no connection")
        return SimpleNamespace(stop_reason=self.stop, content=[SimpleNamespace(type="text", text=json.dumps(self.said))])


@pytest.fixture
def picture(monkeypatch):
    """A stand-in for the scan's photograph, so no panorama is fetched."""
    monkeypatch.setattr(rc, "photograph", lambda pid, view: Image.new("RGB", (120, 90), (90, 90, 90)) if view and view.get("bearing_deg") is not None else None)


def report(site, text, scan="scanA"):
    return sm.add_report(site, text, scan)


def test_a_report_fits_when_the_thing_it_names_was_seen_in_the_room_it_names(site):
    found = rc.check(site, report(site, "The bedroom window is cracked and letting water in"))
    assert found["verdict"] == "fits" and found["before"] is None
    assert "bedroom" in found["says"] and "window" in found["says"]
    assert found["view"] == {"scan_id": "scanA", "position_id": "p1", "bearing_deg": 90.0}
    assert all(isinstance(f["value"], str) and f["src"] for f in found["because"])               # each fact names what it rests on
    seen = next(f for f in found["because"] if "window" in f["value"] and "recorded" in f["value"])
    assert "vision model" in seen["how"] and seen["src"] == ["matterport:scanA"]                   # what a model read is labelled as such


def test_a_thing_named_in_the_wrong_room_is_said_so_with_where_it_is(site):
    found = rc.check(site, report(site, "The refrigerator in the bedroom is leaking"))
    assert found["verdict"] == "wrong_place"
    assert "no refrigerator was seen in this home's bedroom" in found["says"] and "kitchen" in found["says"]
    assert found["view"] == {"scan_id": "scanA", "position_id": "p2", "bearing_deg": 90.0}         # look at where it is


def test_a_thing_this_home_does_not_have_is_wrong_place_with_nowhere_to_point(site):
    found = rc.check(site, report(site, "The fireplace in the bedroom is full of water"))       # only the other home has one
    assert found["verdict"] == "wrong_place" and "anywhere else in its scan" in found["says"]


def test_cannot_tell_is_the_answer_when_the_scan_holds_nothing_to_go_on(site):
    unplaced = rc.check(site, report(site, "Everything is ruined"))
    room_only = rc.check(site, report(site, "The bedroom is soaked"))
    doorway = rc.check(site, report(site, "The sliding glass door on the patio leaks"))
    not_scanned = rc.check(site, {"id": "x", "text": "The kitchen is flooded", "scan_id": "nope", "where": None})
    no_index = rc.check(8, {"id": "y", "text": "The bedroom window is cracked", "scan_id": None, "where": None})
    for found in (unplaced, room_only, doorway, not_scanned, no_index):
        assert found["verdict"] == "cannot_tell" and found["says"].startswith("The scan cannot tell") and found["before"] is None
    assert unplaced["view"] is None and "bedroom" in room_only["says"]
    assert "through a doorway" in doorway["says"] and "no scan of this home" in not_scanned["says"]


def test_no_verdict_judges_how_bad_the_damage_is(site):
    for text in ("The bedroom window is shattered, total loss", "The refrigerator in the bedroom is destroyed", "Everything is ruined"):
        assert rc.check(site, report(site, text))["verdict"] in ("fits", "wrong_place", "cannot_tell")


def test_the_look_is_made_once_and_kept(site, picture):
    r, client = report(site, "The bedroom window is cracked"), FakeClient()
    first = rc.checked(site, r, client)
    again = rc.checked(site, r, client)
    assert len(client.calls) == 1 and first == again
    assert first["before"] == {**READ, "basis": "read from the scan's photograph by a vision model; the scan was made before the storm"}
    assert first["verdict"] == "fits"                                                              # the look does not change the verdict
    sent = client.calls[0]
    assert sent["model"] == VISION_MODEL and sent["messages"][0]["content"][0]["type"] == "image"
    schema = json.dumps(sent["output_config"]["format"]["schema"])
    assert "minimum" not in schema and "maximum" not in schema
    kept = json.loads((sm.OPEN / "report_checks" / "7.json").read_text())
    assert kept[r["id"]]["before"]["floor_covering"] == "grey carpet" and kept[r["id"]]["view"] == first["view"]


def test_reading_without_looking_pays_for_nothing_but_shows_a_look_already_made(site, picture):
    r, client = report(site, "The bedroom window is cracked"), FakeClient()
    assert rc.checked(site, r, client, look=False)["before"] is None and client.calls == []
    rc.checked(site, r, client)
    assert rc.checked(site, r, FakeClient(fail=True), look=False)["before"]["thing"] == "white framed window"


def test_a_failed_look_leaves_before_empty_and_the_verdict_standing(site, picture):
    r = report(site, "The bedroom window is cracked")
    failed = rc.checked(site, r, FakeClient(fail=True))
    assert failed["verdict"] == "fits" and failed["before"] is None
    assert not (sm.OPEN / "report_checks" / "7.json").exists()                                     # nothing was read, so it may be tried again
    assert rc.checked(site, r, FakeClient())["before"]["floor_covering"] == "grey carpet"


def test_a_look_the_model_declines_is_not_asked_again(site, picture):
    r, client = report(site, "The bedroom window is cracked"), FakeClient(stop="refusal")
    assert rc.checked(site, r, client)["before"] is None
    assert rc.checked(site, r, client)["before"] is None and len(client.calls) == 1


def test_no_photograph_means_no_paid_look(site, monkeypatch):
    monkeypatch.setattr(rc, "photograph", lambda pid, view: None)
    client = FakeClient()
    assert rc.checked(site, report(site, "The bedroom window is cracked"), client)["before"] is None and client.calls == []


def test_a_report_in_the_wrong_place_is_not_looked_at(site, picture):
    client = FakeClient()
    assert rc.checked(site, report(site, "The refrigerator in the bedroom is leaking"), client)["before"] is None and client.calls == []


def test_paid_looks_stop_at_the_cap_for_a_building(site, picture, monkeypatch):
    monkeypatch.setattr(rc, "MAX_LOOKS", 2)
    client = FakeClient()
    found = [rc.checked(site, report(site, "The bedroom window is cracked"), client) for _ in range(3)]
    assert len(client.calls) == 2
    assert [bool(f["before"]) for f in found] == [True, True, False] and found[2]["verdict"] == "fits"


def test_the_photograph_faces_the_reports_bearing(site, monkeypatch, tmp_path):
    colours = {0: (0, 0, 250), 1: (250, 0, 0), 2: (0, 250, 0), 3: (250, 250, 0), 4: (0, 250, 250), 5: (250, 0, 250)}

    def face(scan_id, sweep_id, n):
        path = tmp_path / f"{n}.png"
        Image.new("RGB", (64, 64), colours[n]).save(path)
        return path

    monkeypatch.setattr(rc.matterport, "face_image", face)
    # p1 faces north (heading 0) along its first side view, so a bearing of 90 is one quarter clockwise: the second side view.
    image = rc.photograph(site, {"scan_id": "scanA", "position_id": "p1", "bearing_deg": 90.0})
    assert image.size == (rc.WIDTH, rc.HEIGHT) and image.getpixel((rc.WIDTH // 2, rc.HEIGHT // 3)) == colours[2]
    assert rc.photograph(site, {"scan_id": "scanA", "position_id": "p3", "bearing_deg": 90.0}) is None   # no heading: the direction is not known
    assert rc.photograph(site, {"scan_id": "scanA", "position_id": "p1", "bearing_deg": None}) is None


def test_the_endpoints_return_the_check_the_photograph_and_the_site_model_with_checks(site, picture, monkeypatch):
    fake = FakeClient()
    monkeypatch.setattr(rc, "_client", lambda: fake)
    placed, unplaced = report(site, "The bedroom window is cracked"), report(site, "Everything is ruined")
    client = TestClient(server.app)

    listed = {r["id"]: r["check"] for r in client.get("/api/buildings/7/site-model").json()["reports"]}
    assert listed[placed["id"]]["verdict"] == "fits" and listed[placed["id"]]["before"] is None
    assert listed[unplaced["id"]]["verdict"] == "cannot_tell" and fake.calls == []                  # reading the site model pays for nothing

    body = client.get(f"/api/buildings/7/reports/{placed['id']}/check").json()
    assert set(body) == {"verdict", "says", "because", "view", "before"}
    assert body["verdict"] == "fits" and body["before"]["floor_covering"] == "grey carpet" and len(fake.calls) == 1
    assert client.get(f"/api/buildings/7/reports/{placed['id']}/check").json() == body and len(fake.calls) == 1
    assert client.get("/api/buildings/7/site-model").json()["reports"][0]["check"] == body          # the kept look now shows there too

    picture_of = client.get(f"/api/buildings/7/reports/{placed['id']}/before.jpg")
    assert picture_of.status_code == 200 and picture_of.headers["content-type"] == "image/jpeg"
    assert client.get(f"/api/buildings/7/reports/{unplaced['id']}/before.jpg").status_code == 404   # no view to show
    assert client.get("/api/buildings/7/reports/nope/check").status_code == 404
    assert client.get("/api/buildings/7/reports/nope/before.jpg").status_code == 404
    assert client.get(f"/api/buildings/99/reports/{placed['id']}/check").status_code == 404
