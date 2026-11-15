"""The portfolio list: scanned apartment communities inside a mapped fire zone, ranked. What is not known is null."""
import pytest

from backend import schedule


def _rec(id, type="Multifamily", scans=1, lon=2.0, city="Los Angeles"):
    return {"id": id, "name": f"Community {id}", "address": f"{id} Hill Rd", "city": city, "type": type, "lat": 34.0, "lon": lon, "model_ids": ["m"] * scans}


ZONES = {1.0: None, 2.0: "High", 3.0: "Very High"}     # the stand-in fire map goes by longitude


@pytest.fixture
def kit(monkeypatch):
    state = {"records": [], "plans": {}, "totals": {}}
    monkeypatch.setattr(schedule.portfolio, "buildings", lambda: state["records"])
    monkeypatch.setattr(schedule.portfolio, "floor_plans", lambda pid: state["plans"].get(pid, []))
    monkeypatch.setattr(schedule.exposure, "zone_at", lambda lat, lon: (ZONES[lon], True))

    def built(pid, scan=None):
        if pid not in state["totals"]:
            raise schedule.ScheduleError("no scan at this property has been read yet")
        return {"total": state["totals"][pid]}
    monkeypatch.setattr(schedule, "schedule", built)
    return state


def test_only_scanned_apartment_communities_in_a_mapped_zone_are_listed(kit):
    kit["records"] = [_rec(1), _rec(2, lon=1.0), _rec(3, scans=0), _rec(4, type="Office"), _rec(5, city="Houston"), _rec(6, city="LOS ANGELES", lon=3.0)]
    out = schedule.communities()
    assert [c["id"] for c in out["communities"]] == [1, 6]
    assert out["counted"] == {"scanned": 3, "in_zone": 2} and out["communities"][1]["fire_zone"] == "Very High"         # 1, 2 and 6 are scanned apartment communities in the city


def test_a_community_with_a_read_scan_ranks_first_then_by_rent_and_missing_rent_is_null(kit):
    kit["records"] = [_rec(1), _rec(2), _rec(3), _rec(4)]
    kit["plans"] = {2: [{"homes": 10, "rent_low": 2000, "rent_high": 3000}], 3: [{"homes": 40, "rent_low": 2000, "rent_high": 2500}, {"homes": 5, "rent_low": None, "rent_high": None}],
                    4: [{"homes": 8, "rent_low": 1000, "rent_high": 1000}]}
    kit["totals"] = {4: {"low": 100, "high": 200, "lines": 5, "lines_priced": 4}}
    rows = schedule.communities()["communities"]
    assert [(c["id"], c["rank"]) for c in rows] == [(4, 1), (3, 2), (2, 3), (1, 4)]
    assert rows[0]["total"] == {"low": 100, "high": 200} and rows[1]["total"] is None
    assert rows[1]["homes"] == 45 and rows[1]["rent_per_month"] == {"low": 80_000, "high": 100_000}                       # the five homes with no asking rent add no rent
    assert rows[3]["homes"] is None and rows[3]["rent_per_month"] is None and rows[3]["scans"] == 1                       # no listing: not known, and not zero


def test_a_community_whose_schedule_cannot_be_built_still_lists_with_a_null_total(kit):
    kit["records"] = [_rec(1)]
    assert schedule.communities()["communities"][0]["total"] is None
