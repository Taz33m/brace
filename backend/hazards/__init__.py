"""Hazard data for Brace: forecast scenarios, exposure of a point, and public hazard zoning.

Public functions (coordinates are (lat, lon) floats in WGS84, times are ISO 8601 UTC strings):

    scenarios(include_live=True) -> list[dict]
    scenario(scenario_id, step_id=None) -> dict
    exposure(scenario_id, lat, lon, step_id=None) -> dict
    static_risk(lat, lon, cached_only=False) -> dict
    warm_static(points, log=print) -> int
    live_alerts(lat, lon) -> list[dict]

Extras: live_status() says in plain words what the live check found for each
metro, and refresh() downloads everything the package caches (run it once via
scripts/fetch_hazards.py so the demo works offline).

Everything fetched is cached under data/hazards. Network failures raise
HazardError or yield an "unknown" value; nothing hangs.
"""
from __future__ import annotations

from .alerts import live_alerts
from .errors import HazardError
from .registry import exposure, live_status, refresh, scenario, scenarios
from .static import static_risk, warm_static

__all__ = [
    "HazardError", "scenarios", "scenario", "exposure", "static_risk", "warm_static", "live_alerts",
    "live_status", "refresh",
]
