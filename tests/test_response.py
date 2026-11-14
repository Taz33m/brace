"""What a resident says becomes work, in a fixed order, and the homes a household could move to come from the listings."""
import json

from backend import portfolio, response


def test_people_come_first_then_things_to_inspect_then_calls():
    reports = [
        {"id": "a", "text": "water under the balcony door", "where": {"room": "Patio", "thing": "door", "scan_name": "A3"}, "check": {"verdict": "fits", "says": "Fits the scan."}},
        {"id": "b", "text": "Support request (access): I need help getting downstairs", "where": None, "check": {"verdict": "cannot_tell", "says": "x"}},
        {"id": "c", "text": "the stove is leaking in the bedroom", "where": {"room": "Bedroom"}, "check": {"verdict": "wrong_place", "says": "Not where the scan has it."}},
        {"id": "d", "text": "something smells", "where": None, "check": {"verdict": "cannot_tell", "says": "The scan cannot tell."}},
    ]
    got = response.from_residents(reports)
    assert [(g["id"], g["kind"], g["report_id"]) for g in got] == [("R1", "person", "b"), ("R2", "inspect", "a"), ("R3", "call", "c"), ("R4", "call", "d")]
    assert got[0]["title"] == "Reach the resident who asked for help with getting out" and got[0]["said"] == "I need help getting downstairs"
    assert got[1]["title"] == "Inspect the door in the patio, A3" and got[1]["because"] == "Fits the scan."
    assert got[2]["title"] == "Ask the resident which room they mean"
    assert all("cost" not in g for g in got)                       # the scan was made before the storm: nothing here is priced
    assert response.from_residents([]) == []


def test_homes_available_are_this_community_first_then_the_nearest(tmp_path, monkeypatch):
    (tmp_path / "data").mkdir()
    listing = lambda pid, name, lat, lon, free, low, high: {"propertyId": pid, "buildingName": name, "numUnitsAvailable": free, "minRent": low, "maxRent": high,
                                                            "address": {"latitude": lat, "longitude": lon}}
    (tmp_path / "data" / "apartment-listing.jsonl").write_text("\n".join(json.dumps(r) for r in [
        listing(2, "Near", 29.604, -95.2, 5, 900, 1300), listing(1, "Here", 29.6, -95.2, 49, 776, 1155), listing(3, "Far", 29.9, -95.2, 80, 700, 900),
        listing(4, "Full", 29.601, -95.2, 0, 800, 1000), {"propertyId": 5, "numUnitsAvailable": 3, "minRent": 800, "address": {}}]))
    monkeypatch.setattr(portfolio, "KIT_DIR", tmp_path)
    monkeypatch.setattr(portfolio, "building", lambda pid: {"lat": 29.6, "lon": -95.2} if pid == 1 else {})
    got = portfolio.homes_available_near(1)
    assert [(h["name"], h["same_community"], h["available"], h["low"], h["high"]) for h in got] == [("Here", True, 49, 776, 1155), ("Near", False, 5, 900, 1300)]
    assert got[1]["km"] == 0.4 and got[0]["source"] == "CoStar apartment listing"
    assert portfolio.homes_available_near(9) == []                 # no position: nothing is guessed
