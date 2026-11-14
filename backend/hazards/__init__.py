"""Hazard data for Brace: replays of real events, exposure of a point, and public hazard zoning.

Brace does not forecast or watch the weather. A scenario is a real event replayed from the warnings as
they were issued, saved under data/hazards.

Public functions (coordinates are (lat, lon) floats in WGS84, times are ISO 8601 UTC strings):

    scenarios() -> list[dict]
    scenario(scenario_id, step_id=None) -> dict
    exposure(scenario_id, lat, lon, step_id=None) -> dict
    static_risk(lat, lon, cached_only=False) -> dict
    warm_static(points, log=print) -> int

refresh() downloads everything the package caches (run it once via scripts/fetch_hazards.py so the app
works offline).

Everything fetched is cached under data/hazards. Network failures raise
HazardError or yield an "unknown" value; nothing hangs.
"""
from __future__ import annotations

from .errors import HazardError
from .registry import exposure, refresh, scenario, scenarios
from .static import static_risk, warm_static

__all__ = [
    "HazardError", "scenarios", "scenario", "exposure", "static_risk", "warm_static", "refresh",
]
