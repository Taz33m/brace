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
