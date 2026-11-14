"""Run the "better geolocation" open problem on cached buildings.

    python -m scripts.open_geolocation --building 4303509        one building, plus its proof picture
    python -m scripts.open_geolocation --all                     every cached building and the summary

Reads only what is already cached; no network. Writes data/cache/open/geolocation/<property_id>.json,
<property_id>_proof.png and summary.json.
"""
from __future__ import annotations

import argparse
import json

from backend.openproblems import geolocation


def _print_building(res: dict) -> None:
    n = res["summary"]
    print(f"\n{res['property_id']}  {res['name']}: {n['scans']} scans, {n['aligned']} aligned, "
          f"{n['raw_gps_only']} raw GPS only, {n['not_placed']} not placed")
    for s in res["scans"]:
        c = s["correction"]
        move = f"{c['shift_m']:5.2f} m {c['rotation_deg']:+.1f} deg" if c else " " * 16
        under = f"{s['raw']['inside']:.0%} -> {s['fitted']['inside']:.0%}" if s["fitted"] and s["raw"] else ""
        print(f"  {s['id']}  {s['status_label']:<13} {move}  {under:<12} {s['name']}")
        print(f"      {s['why']}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--building", type=int, action="append", help="property id (repeatable)")
    ap.add_argument("--all", action="store_true", help="every cached building, then the summary")
    ap.add_argument("--no-picture", action="store_true", help="skip the proof picture")
    args = ap.parse_args()
    if not args.all and not args.building:
        ap.error("give --building <property_id> or --all")

    ids = geolocation.cached_property_ids() if args.all else args.building
    for pid in ids:
        _print_building(geolocation.alignment(pid, refresh=True))  # always recompute: this is the run command
        print(f"  wrote {geolocation.OUT_DIR / f'{pid}.json'}")
        if not args.no_picture:
            print(f"  wrote {geolocation.render_proof(pid)}")
    if args.all:
        s = geolocation.summary(ids)
        print("\nAll cached buildings")
        print(json.dumps({k: v for k, v in s.items() if k != "by_building"}, indent=1))
        print(f"wrote {geolocation.OUT_DIR / 'summary.json'}")


if __name__ == "__main__":
    main()
