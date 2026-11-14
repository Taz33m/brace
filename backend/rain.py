"""Observed rainfall from PARDIG, Google DeepMind's public precipitation dataset.

PARDIG estimates how hard rain was falling every 15 minutes on a 0.1 degree (about 10 km)
grid. It measures the past; it is not a forecast. In a replay it is therefore hindsight:
it is shown beside a plan as "what actually fell", and never feeds the ranking or the agent.
"""
from __future__ import annotations

import json
from typing import Callable

from .config import HAZARDS_DIR

BUCKET = "pardig_1"
PREFIX = "NRT/zarr_rechunked_as_timeseries/2016_to_2025/predictions.zarr"
CACHE = HAZARDS_DIR / "pardig"
STEP_HOURS = 0.25
RATE_CAP_MM_H = 75.0  # the dataset's deterministic rates are capped here, so intense bursts are understated


def summarise(rates_m_per_h: list[float], start: str, end: str, cell: tuple[float, float]) -> dict:
    """Totals for one grid cell from its 15-minute rain rates (metres per hour, as stored)."""
    mm_h = [max(0.0, float(r)) * 1000.0 for r in rates_m_per_h if r == r]  # drop NaN
    total = sum(mm_h) * STEP_HOURS
    peak = max(mm_h, default=0.0)
    return {
        "mm": round(total, 1), "inches": round(total / 25.4, 1), "peak_mm_per_h": round(peak, 1),
        "capped": peak >= RATE_CAP_MM_H - 0.5,
        "from": start, "to": end, "cell": [round(cell[0], 2), round(cell[1], 2)],
        "source": "PARDIG (Google DeepMind), about 10 km grid, observed",
    }


def _read(lat: float, lon: float, start: str, end: str) -> tuple[list[float], tuple[float, float]]:
    """One network read of a cell's time series. The bucket is public; no credentials are sent."""
    import obstore
    import xarray as xr
    import zarr

    store = obstore.store.GCSStore(bucket=BUCKET, prefix=PREFIX, skip_signature=True)
    ds = xr.open_zarr(zarr.storage.ObjectStore(store, read_only=True), chunks=None)
    pt = ds["precipitation"].sel(latitude=lat, longitude=lon % 360, method="nearest").sel(time=slice(start, end)).compute()
    return [float(v) for v in pt.values], (float(pt.latitude), float(pt.longitude) - 360 if float(pt.longitude) > 180 else float(pt.longitude))


def observed(lat: float, lon: float, start: str, end: str, read: Callable = _read) -> dict | None:
    """Rain that fell on the grid cell containing a point between two UTC times. Cached per cell; None if unreadable."""
    key = f"{round(lat, 1):.1f}_{round(lon, 1):.1f}_{start[:13]}_{end[:13]}".replace(":", "")
    path = CACHE / f"{key}.json"
    if path.exists():
        return json.loads(path.read_text())
    try:
        rates, cell = read(lat, lon, start, end)
    except Exception:  # an optional, hindsight-only extra must never break a page
        return None
    if not rates:
        return None
    out = summarise(rates, start, end, cell)
    CACHE.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out))
    return out


# Windows of observed rain to show beside a replay, by scenario id.
REPLAY_WINDOWS = {"beryl-2024": ("2024-07-07T12:00:00", "2024-07-09T00:00:00")}
