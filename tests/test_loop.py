"""The whole loop in one test: the owner approves, the notice reaches the resident, the resident answers,
and the answer lands on the owner's side against the room it names."""
import json

from fastapi import Request

from backend import site_model
from backend.recovery.site_activity import case_activity
from tests.test_preparation_approval import PATH, bridge  # noqa: F401  (bridge is a fixture)


def test_approval_reaches_the_resident_and_the_residents_answer_comes_back_placed(bridge, tmp_path, monkeypatch):
    app, owner, resident = bridge["app"], bridge["owner"], bridge["resident"]

    # What the scans of this building showed, as the search stage saved it.
    monkeypatch.setattr(site_model, "OPEN", tmp_path / "open")
    index = tmp_path / "open" / "search" / "7.json"
    index.parent.mkdir(parents=True)
    index.write_text(json.dumps({"positions": [
        {"scan_id": "scanA", "scan_name": "1BR - A1", "sweep_id": "p1", "room_id": "r1", "room_label": "Bedroom", "room_type": "bedroom", "heading": 0.0,
         "things": [{"name": "window", "quarter": 2, "where": "in this room"}]}]}))

    @app.get("/api/test/buildings/{building_id}/reports")
    def reports(building_id: int, request: Request):
        return site_model.place(building_id, case_activity(request, building_id))

    # 1. Nothing has reached the resident, and nothing has come back.
    assert resident.get("/api/resident/home").json()["notices"] == []
    assert owner.get("/api/test/buildings/7/reports").json() == []

    # 2. The owner approves the action the notice is linked to. The notice is published to this building's households.
    approved = owner.post(PATH, json={}).json()
    assert approved["ok"] and approved["delivery"] == "resident_feed" and "published" in approved["say"]

    # 3. The resident sees that notice, word for word.
    seen = resident.get("/api/resident/home").json()["notices"]
    assert len(seen) == 1 and seen[0]["body"] == app.state.plan["messages"][0]["body"]

    # 4. The resident answers twice: once naming a place, once not.
    assert resident.post("/api/resident/support", json={"category": "other", "description": "The bedroom window is letting water in"},
                         headers={"Idempotency-Key": "loop-test-0001"}).status_code == 200
    assert resident.post("/api/resident/support", json={"category": "access", "description": "I need help getting down"},
                         headers={"Idempotency-Key": "loop-test-0002"}).status_code == 200

    # 5. Both are on the owner's side. The first is placed in the bedroom, at the window, and marked as placed from the words.
    back = {row["text"].split(": ", 1)[1]: row for row in owner.get("/api/test/buildings/7/reports").json()}
    placed = back["The bedroom window is letting water in"]["where"]
    assert placed["room"] == "Bedroom" and placed["thing"] == "window" and placed["placed_by"] == "description"
    assert back["I need help getting down"]["where"] is None

    # 6. A resident of another building's case sees none of it, and a resident cannot read the owner's side.
    assert bridge["other"].get("/api/resident/home").json()["notices"] == []
    assert resident.get("/api/test/buildings/7/reports").status_code == 401
