"""The forecast as data: one row per building per step, keyed by the CoStar property id, empty where the forecast is silent."""
import csv
import io

import pytest

from backend import forecast_export as fx
from backend import hazards, portfolio

BUILDINGS = [
    {"id": 101, "name": "Gulf Court", "address": "1 Gulf St", "city": "Houston", "state": "TX", "lat": 29.7, "lon": -95.4, "type_label": "Apartments", "units": 40, "tenant_count": 2, "year_built": 1980},
    {"id": 102, "name": "Far Court", "address": "2 Far St", "city": "Houston", "state": "TX", "lat": 30.4, "lon": -95.0, "type_label": "Office", "units": None, "tenant_count": 5, "year_built": 2001},
    {"id": 201, "name": "Elsewhere", "address": "3 West St", "city": "Los Angeles", "state": "CA", "lat": 34.0, "lon": -118.2, "type_label": "Retail"},
]


@pytest.fixture
def storm(monkeypatch):
    steps = {"s48": {"issued": "2024-07-06T09:00:00Z", "label": "48 hours before landfall", "advisory": "31"},
             "s12": {"issued": "2024-07-07T21:00:00Z", "label": "12 hours before landfall", "advisory": "37"}}
    monkeypatch.setattr(portfolio, "buildings", lambda: BUILDINGS)
    monkeypatch.setattr(hazards, "scenarios", lambda include_live=True: [{"id": "storm", "city": "Houston", "steps": [{"id": k} for k in steps]}])
    monkeypatch.setattr(hazards, "scenario", lambda sid, step=None: {"id": sid, "kind": "hurricane", "name": "Hurricane Test", "city": "Houston", **steps[step or "s12"]})
    monkeypatch.setattr(hazards, "static_risk", lambda lat, lon, cached_only=False: {"fema": {"zone": "AE", "high_risk": True}, "fire_zone": None, "km_to_past_fire": None})

    def exposure(sid, lat, lon, step=None):
        if lat > 30:      # too far north: the forecast says nothing about wind here
            return {"kind": "hurricane", "peak_wind_mph": None, "wind_band": None, "hours_until_tropical_storm_wind": None, "in_cone": False}
        return {"kind": "hurricane", "peak_wind_mph": 55, "wind_band": "tropical storm", "hours_until_tropical_storm_wind": 7.5 if step == "s12" else 43.5,
                "hours_until_peak_wind": 15.7, "closest_approach_km": 66.6, "track_side": "right", "in_cone": True, "wind_basis": "inside the forecast 34 kt wind radius"}
    monkeypatch.setattr(hazards, "exposure", exposure)


def test_one_row_per_building_in_the_metro_keyed_by_the_costar_id(storm):
    rows = fx.rows("storm", "s12")
    assert [r["costar_property_id"] for r in rows] == [101, 102]                 # the Los Angeles building is not in a Houston forecast
    near = rows[0]
    assert near["touched_by_forecast"] is True and near["peak_sustained_wind_mph"] == 55 and near["hours_until_conditions_arrive"] == 7.5
    assert near["conditions_arrive_utc"] == "2024-07-08T04:30Z"                   # issued 21:00 UTC plus 7.5 hours
    assert near["safe_crew_hours"] == 1.5                                         # less the six-hour stand-down, as the planner uses it
    assert near["forecast_source"] == "National Hurricane Center, forecast advisory 37" and near["fema_flood_zone"] == "AE"


def test_a_building_the_forecast_is_silent_about_keeps_its_row_with_empty_cells(storm):
    far = fx.rows("storm", "s12")[1]
    assert far["touched_by_forecast"] is False
    assert far["peak_sustained_wind_mph"] is None and far["conditions_arrive_utc"] is None and far["safe_crew_hours"] is None
    line = list(csv.DictReader(io.StringIO(fx.to_csv([far]))))[0]
    assert line["touched_by_forecast"] == "false" and line["peak_sustained_wind_mph"] == "" and line["homes"] == "" and line["inside_cone"] == "false"


def test_all_steps_stack_into_one_table_with_the_same_columns(storm):
    table = fx.table("storm", "all")
    assert [(r["costar_property_id"], r["forecast_step"]) for r in table] == [
        (101, "48 hours before landfall"), (102, "48 hours before landfall"), (101, "12 hours before landfall"), (102, "12 hours before landfall")]
    assert table[0]["safe_crew_hours"] == 37.5 and table[2]["safe_crew_hours"] == 1.5      # the same building, the clock running down
    header = fx.to_csv(table).splitlines()[0].split(",")
    assert header == fx.COLUMNS and header[0] == "costar_property_id"
