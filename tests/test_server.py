import json

import pytest
from fastapi.testclient import TestClient

from backend import screen, server

SCENARIO = {"id": "test-storm", "kind": "hurricane", "name": "Hurricane Test", "city": "Houston", "live": False, "summary": "A test.",
            "steps": [{"id": "t48", "issued": "2024-07-06T09:00:00Z", "label": "48 hours before landfall"},
                      {"id": "t36", "issued": "2024-07-06T21:00:00Z", "label": "36 hours before landfall"}]}


SALES = {7: {"price": 18_000_000, "basis": "Confirmed", "portfolio": False, "date": "2014-09-19"},
         8: {"price": 30_000_000, "basis": "Allocated", "portfolio": True, "date": "2021-12-15"}}


def row(i, manager, kind="Office"):
    return {"last_sale": SALES.get(i), "id": i, "rank": i, "name": f"Building {i}", "address": "1 Test St", "city": "Houston", "lat": 29.7 + i / 100, "lon": -95.4,
            "type_label": kind, "units": 100 if kind != "Office" else None, "stories": 3, "year_built": 1990, "tenant_count": 4,
            "manager": manager, "owner": None, "photo": None, "scans": 1,
            "exposure": {"kind": "hurricane", "wind_band": "tropical storm", "peak_wind_mph": 45, "hours_until_tropical_storm_wind": 30.0},
            "hours_left": 30.0, "reasons": ["roof condition 2 of 5"]}


@pytest.fixture
def client(site, threat, monkeypatch):
    monkeypatch.setattr(server.hazards, "scenarios", lambda: [SCENARIO], raising=False)
    monkeypatch.setattr(server.hazards, "scenario", lambda sid, step=None: {"kind": "hurricane", "name": "Hurricane Test", "issued": "x", "track": []}, raising=False)
    monkeypatch.setattr(screen, "rank", lambda sid, step=None: [row(7, "Acme"), row(8, "Acme", "Apartment community"), row(9, "Other")])
    monkeypatch.setattr(screen, "threat_for", lambda sid, step, b: {**threat, "step_id": step})
    monkeypatch.setattr(screen, "site_facts", lambda: {})
    monkeypatch.setattr(server.rain, "REPLAY_WINDOWS", {"test-storm": ("2024-07-07T12:00:00", "2024-07-09T00:00:00")})
    monkeypatch.setattr(server.rain, "observed", lambda lat, lon, start, end: {"mm": 104.0, "inches": 4.1})
    monkeypatch.setattr(server.portfolio_data, "building", lambda pid: {"last_sale": {"price": 18_000_000, "basis": "Confirmed", "portfolio": False, "date": "2014-09-19"}})
    monkeypatch.setattr(server.Site, "load", classmethod(lambda cls, pid: site if pid == 7 else (_ for _ in ()).throw(server.BuildingError("unknown property"))))
    return TestClient(server.app)


def test_scenarios_and_unknown_ids(client):
    assert client.get("/api/scenarios").json()[0]["id"] == "test-storm"
    body = client.get("/api/scenarios/test-storm").json()
    assert body["step"] == "t36" and body["map"]["kind"] == "hurricane"       # defaults to the latest forecast step
    assert client.get("/api/scenarios/nope").status_code == 404
    assert client.get("/api/scenarios/test-storm?step=nope").status_code == 404


def test_portfolio_filters_and_counts(client):
    p = client.get("/api/portfolio?scenario=test-storm").json()
    assert p["touched"] == 3 and p["shown"] == 3 and p["homes"] == 100 and p["tenants"] == 12
    assert p["managers"][0] == {"name": "Acme", "buildings": 2} and len(p["points"]) == 3
    # Value exposed is the sum of last recorded sale prices, with how many buildings have one and how many are allocated shares.
    assert p["value"] == {"buildings_with_sale": 2, "last_sale_total": 48_000_000, "allocated_share": 1, "oldest_sale": "2014-09-19"}
    acme = client.get("/api/portfolio?scenario=test-storm&manager=Acme&kind=Office").json()
    assert acme["shown"] == 1 and acme["buildings"][0]["id"] == 7 and acme["buildings"][0]["plan"] is None
    assert acme["managers"][0]["buildings"] == 2                               # the filter list stays whole


def test_building_bundle_plan_and_files(client, site):
    b = client.get("/api/buildings/7?scenario=test-storm&step=t48").json()
    assert b["record"]["name"] == "Test Plaza" and b["threat"]["step_id"] == "t48" and b["plan"] is None
    assert b["last_sale"]["price"] == 18_000_000 and b["last_sale"]["basis"] == "Confirmed"
    assert b["observed_rain"] is None                                   # an earlier forecast step: no hindsight shown
    assert client.get("/api/buildings/7?scenario=test-storm&step=t36").json()["observed_rain"]["mm"] == 104.0
    assert "in a high-risk flood zone (AE)" in b["reasons"]
    assert client.get("/api/buildings/999?scenario=test-storm").status_code == 404
    assert client.get("/api/buildings/7/aerial.jpg").headers["content-type"] == "image/jpeg"
    assert client.get("/api/buildings/7/oblique/from-south.jpg").status_code == 404
    assert client.get("/api/buildings/7/file/building.json").status_code == 404   # only images are served
    assert client.get("/api/buildings/7/file/..%2F..%2F.env").status_code == 404


def test_replay_streams_saved_plan_for_the_right_step(client, site):
    assert client.get("/api/buildings/7/plan/stream?scenario=test-storm&replay=true").status_code == 404
    plan = {"building_id": 7, "stop": "finished", "complete": True, "headline": "Two jobs.", "summary": "s", "actions": [], "totals": {},
            "messages": [], "leads": [], "events": [{"type": "status", "t": 0, "label": "Preparing"}]}
    (site.dir / "plans").mkdir(exist_ok=True)
    (site.dir / "plans" / "test-storm__t36.json").write_text(json.dumps(plan))
    text = client.get("/api/buildings/7/plan/stream?scenario=test-storm&replay=true&speed=50").text
    events = [json.loads(line[5:]) for line in text.splitlines() if line.startswith("data:")]
    assert [e["type"] for e in events] == ["status", "done"] and events[-1]["plan"]["headline"] == "Two jobs."
    # A plan belongs to one forecast step: nothing is saved for the earlier step.
    assert client.get("/api/buildings/7/plan/stream?scenario=test-storm&step=t48&replay=true").status_code == 404
    assert client.get("/api/buildings/7?scenario=test-storm").json()["plan"]["headline"] == "Two jobs."
    assert client.get("/api/portfolio?scenario=test-storm").json()["buildings"][0]["plan"] == {"actions": 0, "headline": "Two jobs."}


def test_headset_link_round_trip(client):
    assert client.get("/api/vr/target").json()["rev"] >= 0
    start = client.get("/api/vr/target").json()["rev"]
    sent = client.post("/api/vr/target", json={"building": 7, "scan_id": "SCAN1", "sweep_id": "w1", "bearing": 90, "junk": "x"}).json()
    assert sent["rev"] == start + 1 and sent["sweep_id"] == "w1" and "junk" not in sent
    client.post("/api/vr/pose", json={"building": 7, "scan_id": "SCAN1", "sweep_id": "w2", "bearing": 182.5})
    pose = client.get("/api/vr/pose").json()
    assert pose["sweep_id"] == "w2" and pose["age"] < 5
    assert "ip" in client.get("/api/lan").json()


def test_pano_face_validates_scan_sweep_and_face(client, site, monkeypatch, tmp_path):
    from PIL import Image
    face = tmp_path / "f.jpg"
    Image.new("RGB", (512, 512), (10, 20, 30)).save(face)
    monkeypatch.setattr(server.matterport, "face_image", lambda scan, sweep, f: face)
    ok = client.get("/api/buildings/7/pano/SCAN1/w1/0.jpg?size=256")
    assert ok.status_code == 200 and ok.headers["content-type"] == "image/jpeg"
    assert client.get("/api/buildings/7/pano/SCAN1/nope/0.jpg").status_code == 404
    assert client.get("/api/buildings/7/pano/OTHER/w1/0.jpg").status_code == 404
    assert client.get("/api/buildings/7/pano/SCAN1/w1/6.jpg").status_code == 404


def test_headset_target_carries_outside_points_and_a_line_to_say(client):
    sent = client.post("/api/vr/target", json={"building": 7, "lon": -95.4, "lat": 29.7, "label": "Looking at S1 from the west",
                                               "image": "plans/x/view_001.jpg", "kind": "step", "junk": "x"}).json()
    assert sent["scan_id"] is None and sent["lon"] == -95.4 and sent["label"].startswith("Looking") and "junk" not in sent


def test_headset_approval_needs_an_action_from_the_saved_plan(client, site):
    plans = server.building_dir(7) / "plans"
    plans.mkdir(parents=True, exist_ok=True)
    (plans / "test-storm__t36.json").write_text(json.dumps({"actions": [{"id": "A1"}], "events": [], "stop": "finished", "headline": "x"}))
    client.post("/api/vr/reset")
    ask = {"building": 7, "scenario": "test-storm", "step": "t36"}
    refused = client.post("/api/vr/approve", json={**ask, "action_id": "A9"}).json()
    assert refused["ok"] is False and client.get("/api/vr/approvals?building=7").json() == {"action_ids": []}
    done = client.post("/api/vr/approve", json={**ask, "action_id": "A1"}).json()
    assert done["ok"] is True and "Nothing has been sent yet" in done["say"]
    client.post("/api/vr/approve", json={**ask, "action_id": "A1"})   # approving twice records it once
    assert client.get("/api/vr/approvals?building=7").json() == {"action_ids": ["A1"]}
    assert client.get("/api/vr/approvals?building=8").json() == {"action_ids": []}
    client.post("/api/vr/reset")
    assert client.get("/api/vr/approvals?building=7").json() == {"action_ids": []}


def test_voice_session_is_refused_without_a_key(client, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert client.post("/api/voice/session?building=7&scenario=test-storm").status_code == 503
    assert client.get("/api/config").json()["voice_ready"] is False


def test_voice_session_grounds_the_voice_in_the_saved_plan(client, site, monkeypatch):
    plans = server.building_dir(7) / "plans"
    plans.mkdir(parents=True, exist_ok=True)
    plan = {"headline": "Trim the courtyard tree.", "stop": "finished", "events": [],
            "totals": {"before_arrival": {"count": 1, "cost_low": 1200, "cost_high": 4000, "hours": 6}},
            "actions": [{"id": "A1", "title": "Cut back limbs over the roof", "timing": "before_arrival", "why": "Limbs hang over the roof.",
                         "crew": "tree crew", "hours_of_work": 6, "cost_low": 1200, "cost_high": 4000, "structure": "S1",
                         "site": {"lon": -95.4, "lat": 29.7}, "interior": None}],
            "leads": [{"id": "L2", "title": "Tarp on the roof", "status": "not_a_concern", "note": "The flag predates the photo."}],
            "messages": [{"kind": "notice", "to": "Residents", "subject": "Bring in balcony items", "body": "secret body text"}]}
    (plans / "test-storm__t36.json").write_text(json.dumps(plan))
    seen = {}
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(server.voice, "mint", lambda body: seen.setdefault("body", body) and {"value": "ek_test", "model": body["session"]["model"]})
    got = client.post("/api/voice/session?building=7&scenario=test-storm&step=t36").json()
    assert got["value"] == "ek_test" and "test-key" not in json.dumps(got)
    session = seen["body"]["session"]
    notes = session["instructions"]
    assert "A1 | before it arrives | outside, on S1 | Cut back limbs over the roof" in notes and "$1,200 to $4,000" in notes
    assert "Tarp on the roof: not a concern" in notes and "Resident notice to Residents: Bring in balcony items" in notes
    assert "secret body text" not in notes and "Never say a crew is coming" in notes
    assert {t["name"] for t in session["tools"]} == {"go_to_action", "next_finding", "approve_action", "where_am_i", "set_hours_left", "hold_approval"}
    assert "wearing a headset" in notes and "large screen" not in notes
    # The big screen gets the same plan with a different account of what the owner can see, and no key is needed to read it.
    on_screen = client.get("/api/voice/notes?building=7&scenario=test-storm&step=t36&view=screen").json()["instructions"]
    assert "large screen" in on_screen and "wearing a headset" not in on_screen and "A1 | before it arrives" in on_screen
    # Only the big screen can see a nod or a shake, so only its voice is told what one means; approval still has to be asked for.
    assert "A message starting [gesture] is the owner answering by moving their head: a nod means yes and a shake means no." in on_screen
    assert "ask one short yes-or-no question. The owner may answer aloud or with a nod or a shake." in on_screen
    assert 'A nod in answer to "Shall I approve it?" counts as clearly asking.' in on_screen
    assert on_screen.index("[gesture]") < on_screen.index("Those bracketed tags are stage directions")   # so the tag is never said aloud
    assert "Approve an action only when the owner clearly asks you to approve it." in on_screen and "Approve an action only when the owner clearly asks" in notes
    assert "[gesture]" not in notes and "a nod or a shake" not in notes
    earlier = client.get("/api/voice/notes?building=7&scenario=test-storm&step=t48").json()["instructions"]
    assert "No inspection has been saved" in earlier                       # a step with no saved plan says so


def test_saved_plans_lists_only_the_steps_that_have_one(client, site):
    plans = server.building_dir(7) / "plans"
    plans.mkdir(parents=True, exist_ok=True)
    (plans / "test-storm__t36.json").write_text(json.dumps({
        "headline": "Trim the tree.", "threat": {"hours_left": 30.0}, "events": [], "stop": "finished",
        "totals": {"before_arrival": {"count": 1, "cost_low": 1200, "cost_high": 4000, "hours": 6}},
        "actions": [{"id": "A1", "title": "Cut back limbs", "timing": "before_arrival", "hours_of_work": 6,
                     "cost_low": 1200, "cost_high": 4000, "why": "not needed in the list"}]}))
    got = client.get("/api/buildings/7/plans?scenario=test-storm").json()["plans"]
    assert [p["step"] for p in got] == ["t36"] and got[0]["label"] == "36 hours before landfall" and got[0]["hours_left"] == 30.0
    assert got[0]["actions"] == [{"id": "A1", "title": "Cut back limbs", "timing": "before_arrival", "hours_of_work": 6,
                                  "cost_low": 1200, "cost_high": 4000}]
    assert client.get("/api/buildings/7/plans?scenario=nope").status_code == 404


def test_descent_lists_real_aerials_widest_first_centred_on_the_site(client, site, monkeypatch, tmp_path):
    asked = []
    photo = tmp_path / "wide.jpg"
    photo.write_bytes((server.building_dir(7) / "aerial.jpg").read_bytes())

    def ortho(area_wkt, buffer_m=8, **kwargs):
        asked.append((area_wkt, buffer_m, kwargs.get("max_px")))
        return photo, {"bounds": [-95.5, 29.6, -95.3, 29.8], "first_capture": "2026-01-02", "last_capture": "2026-02-12"}

    monkeypatch.setattr(server.vexcel, "ortho", ortho)
    got = client.get("/api/buildings/7/descent").json()
    west, south, east, north = site.d["aerial"]["bounds"]
    assert got["focus"] == {"lon": (west + east) / 2, "lat": (south + north) / 2}
    assert [b for _, b, _ in asked] == [10_000, 2_560, 640, 160] and all(px == (1600, 1600) for _, _, px in asked)
    assert [l["url"] for l in got["levels"]] == [f"/api/buildings/7/descent/{i}.jpg" for i in range(4)]
    assert got["levels"][0]["last_capture"] == "2026-02-12" and got["site"]["url"] == "/api/buildings/7/aerial.jpg"
    assert client.get("/api/buildings/7/descent/2.jpg").headers["content-type"] == "image/jpeg"
    assert client.get("/api/buildings/7/descent/9.jpg").status_code == 404
