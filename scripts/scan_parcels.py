"""Fetch and cache the Vexcel parcel record for every building in the portfolio. Resumable.

Usage: python -m scripts.scan_parcels
"""
from __future__ import annotations

import time

from backend import portfolio, vexcel


def main() -> None:
    todo = portfolio.buildings()
    ok = miss = err = 0
    t0 = time.time()
    for i, b in enumerate(todo, 1):
        try:
            if vexcel.parcel(b["lat"], b["lon"]) is None:
                miss += 1
            else:
                ok += 1
        except Exception as e:  # keep going; the cache makes reruns cheap
            err += 1
            print(f"  {b['id']}: {e}", flush=True)
        if i % 100 == 0:
            print(f"{i}/{len(todo)} ok={ok} no-parcel={miss} errors={err} {time.time() - t0:.0f}s", flush=True)
    print(f"done ok={ok} no-parcel={miss} errors={err} {time.time() - t0:.0f}s", flush=True)


if __name__ == "__main__":
    main()
