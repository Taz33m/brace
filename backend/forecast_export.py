"""The forecast as data: one row per building per forecast step, keyed by the CoStar property id.

A hurricane advisory or a Red Flag Warning is a bulletin about a region. This writes out what Brace
makes of it for each building: whether it is touched, when conditions arrive, how strong, and how
many working hours a crew has left. A value the forecast does not give is left empty, never filled in.
"""
from __future__ import annotations

import csv
import io
from datetime import datetime, timedelta

from . import hazards, portfolio, screen
from .clock import CREW_STANDDOWN_HOURS

COLUMNS = [
    "costar_property_id", "name", "address", "city", "state", "lat", "lon", "property_type", "homes", "tenants_on_record", "year_built",
    "event", "event_kind", "forecast_step", "forecast_issued_utc", "forecast_source",
    "touched_by_forecast", "hours_until_conditions_arrive", "conditions_arrive_utc", "safe_crew_hours",
    # hurricane
    "peak_sustained_wind_mph", "wind_band", "hours_until_peak_wind", "closest_approach_km", "side_of_track", "inside_cone", "wind_basis",
    # wildfire
    "in_red_flag_warning", "in_fire_weather_watch", "warning_lasts_hours", "nws_zone", "nws_zone_name", "forecast_gust_mph", "particularly_dangerous_situation",
    # standing, as known when the forecast was issued
    "fema_flood_zone", "fema_high_risk", "ca_fire_hazard_zone", "km_to_past_fire",
]


def _source(sc: dict) -> str:
    src = sc.get("source") or {}
    name = src.get("name") or src.get("agency") or ("National Hurricane Center" if sc["kind"] == "hurricane" else "National Weather Service")
    what = f"forecast advisory {sc['advisory']}" if sc.get("advisory") else "Red Flag Warning products" if sc["kind"] == "wildfire" else "forecast"
    return f"{name}, {what}"


def step_ids(scenario_id: str) -> list[str | None]:
    sc = next(s for s in hazards.scenarios() if s["id"] == scenario_id)
    return [s["id"] for s in sc["steps"]] or [None]


def rows(scenario_id: str, step_id: str | None) -> list[dict]:
    """Every building in the scenario's metro at one forecast step, touched or not."""
    sc = hazards.scenario(scenario_id, step_id)
    issued = datetime.fromisoformat(sc["issued"].replace("Z", "+00:00")) if sc.get("issued") else None
    out = []
    for b in portfolio.buildings():
        if b["state"] != screen.STATE.get(sc["city"]):
            continue
        e = hazards.exposure(scenario_id, b["lat"], b["lon"], step_id)
        left = screen.hours_left(e)
        static = screen.as_of(sc, hazards.static_risk(b["lat"], b["lon"], cached_only=True)) or {}
        fema = static.get("fema") or {}
        storm = e["kind"] == "hurricane"
        touched = (e.get("wind_band") not in (None, "none", "below tropical storm")) if storm else bool(e.get("in_warning") or e.get("in_watch"))
        out.append({
            "costar_property_id": b["id"], "name": b["name"], "address": b["address"], "city": b["city"], "state": b["state"], "lat": b["lat"], "lon": b["lon"],
            "property_type": b.get("type_label"), "homes": b.get("units"), "tenants_on_record": b.get("tenant_count"), "year_built": b.get("year_built"),
            "event": sc["name"], "event_kind": sc["kind"], "forecast_step": sc.get("label"), "forecast_issued_utc": sc.get("issued"), "forecast_source": _source(sc),
            "touched_by_forecast": touched, "hours_until_conditions_arrive": left,
            "conditions_arrive_utc": (issued + timedelta(hours=left)).strftime("%Y-%m-%dT%H:%MZ") if issued and left is not None else None,
            "safe_crew_hours": None if left is None else max(0.0, round(left - CREW_STANDDOWN_HOURS, 1)),
            "peak_sustained_wind_mph": e.get("peak_wind_mph"), "wind_band": e.get("wind_band"), "hours_until_peak_wind": e.get("hours_until_peak_wind"),
            "closest_approach_km": e.get("closest_approach_km"), "side_of_track": e.get("track_side"), "inside_cone": e.get("in_cone"), "wind_basis": e.get("wind_basis"),
            "in_red_flag_warning": e.get("in_warning"), "in_fire_weather_watch": e.get("in_watch"), "warning_lasts_hours": e.get("warning_hours"),
            "nws_zone": e.get("zone"), "nws_zone_name": e.get("zone_name"), "forecast_gust_mph": e.get("gust_mph") if not storm else None,
            "particularly_dangerous_situation": e.get("pds"),
            "fema_flood_zone": fema.get("zone"), "fema_high_risk": fema.get("high_risk"), "ca_fire_hazard_zone": static.get("fire_zone"),
            "km_to_past_fire": static.get("km_to_past_fire"),
        })
    return out


def table(scenario_id: str, step: str | None) -> list[dict]:
    """One step, or every step of the scenario when `step` is "all"."""
    steps = step_ids(scenario_id) if step == "all" else [step]
    return [row for s in steps for row in rows(scenario_id, s)]


def to_csv(table_rows: list[dict]) -> str:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=COLUMNS, extrasaction="ignore")
    w.writeheader()
    for row in table_rows:
        # One building is one line: a name or address that carries a line break is written on one line.
        w.writerow({k: ("" if v is None else str(v).lower() if isinstance(v, bool) else " ".join(v.split()) if isinstance(v, str) else v)
                    for k, v in row.items()})
    return buf.getvalue()
