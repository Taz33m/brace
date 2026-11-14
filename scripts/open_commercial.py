"""Label the rooms of commercial scans (Matterport open problem: understand commercial spaces).

    python -m scripts.open_commercial --model P3S6VUTP3qB              # one Matterport scan, by model id
    python -m scripts.open_commercial --building 23347                 # every scan attached to a cached building
    python -m scripts.open_commercial --model P3S6VUTP3qB --limit 10   # at most 10 paid looks in this run
    python -m scripts.open_commercial --calls                          # paid looks made so far

Answers are cached under data/cache/open/commercial/, so a second run costs nothing.
"""
from __future__ import annotations

import argparse

from backend.openproblems import commercial


def show(model_id: str, name: str | None, rooms: list[dict], s: dict) -> None:
    print(f"\n{model_id}  {name or ''}")
    print(f"  rooms {s['rooms']}, with a scan position {s['rooms_with_a_scan_position']}  |  Matterport real type: {s['matterport_real_type']} "
          f"{s['matterport_labels']}  |  ours: {s['ours_use_named']} use named, {s['ours_vacant']} vacant, {s['ours_cannot_tell']} cannot tell, "
          f"{s['ours_no_answer']} no answer, {s['ours_not_looked_at']} not looked at")
    print(f"  types: {s['type_counts']}")
    if s["looks"] > s["ours_real_type"]:
        print(f"  all {s['looks']} looks: {s['look_type_counts']} ({s['looks_cannot_tell']} cannot tell)")
    for r in rooms:
        if not r["positions"]:
            continue
        o = r["ours"]
        mp = r["matterport"]["type"] + (f" / {r['matterport']['label']}" if r["matterport"]["label"] else "")
        line = f"{o['type']} ({o['confidence']}): {o['reason']}" if o else f"{r['status']}: {r.get('why')}"
        print(f"   {r['room_id'][:10]:10} {r['floor'] or '':8} {r['area_sqft'] or 0:>7} sqft  Matterport: {mp:12}  ours: {line}")
        if r["mixed"]:
            print(f"   {'':10} also seen in this room: {r['types_seen']}")
        for st in r["storm"]:
            print(f"   {'':10} storm: {st['kind']}: {st['seen']}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--model", action="append", default=[], help="Matterport model id (repeatable)")
    ap.add_argument("--building", action="append", default=[], type=int, help="CoStar property id of a cached building (repeatable)")
    ap.add_argument("--limit", type=int, default=None, help="most paid looks in this run")
    ap.add_argument("--views", type=int, default=commercial.MAX_VIEWS, help="looks per room, counting the first")
    ap.add_argument("--calls", action="store_true", help="print the paid-look count and exit")
    args = ap.parse_args()
    if args.calls or not (args.model or args.building):
        led = commercial.calls_made()
        print(f"paid looks so far: {led['total']} of {commercial.BUDGET}  {led['by_model']}")
        return 0
    left = args.limit
    for mid in args.model:
        res = commercial.label_rooms(mid, limit=left, max_views=args.views)
        if left is not None:
            left = max(0, left - res["calls"]["made_this_run"])
        show(mid, res["name"], res["rooms"], res["summary"])
        print(f"  paid looks this run: {res['calls']['made_this_run']}, from cache: {res['calls']['answers_from_cache']}  ->  {commercial.OUT_DIR / (mid + '.json')}")
    for pid in args.building:
        before = commercial.calls_made()["total"]
        res = commercial.label_building(pid, limit=left, max_views=args.views)
        used = commercial.calls_made()["total"] - before
        if left is not None:
            left = max(0, left - used)
        s = res["summary"]
        print(f"\n== {pid}  {res['name']}: {len(res['scans'])} scans, rooms with a scan position {s['rooms_with_a_scan_position']}, "
              f"Matterport real type {s['matterport_real_type']}, ours {s['ours_use_named']} use named + {s['ours_vacant']} vacant  {s['type_counts']}")
        for r in s["storm_rooms"][:8]:
            print(f"   storm: {r['model_id']} {r['room_id'][:10]} {r['type']} (score {r['score']}): {'; '.join(r['seen'])}")
        print(f"  paid looks this run: {used}  ->  {commercial.OUT_DIR / f'building_{pid}.json'}")
    led = commercial.calls_made()
    print(f"\npaid looks so far: {led['total']} of {commercial.BUDGET}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
