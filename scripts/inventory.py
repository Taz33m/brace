"""Read one scanned home with the inventory agent: what the owner would have to replace, room by room.

    python -m scripts.inventory 9519837 CaSLe7ZwnfF                 # read every room and save
    python -m scripts.inventory 9519837 CaSLe7ZwnfF --only kitchen-1 --dry
    python -m scripts.inventory 9519837 CaSLe7ZwnfF --prices        # then price each kind of fit-out it named
"""
from __future__ import annotations

import argparse

from backend import inventory_agent


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("property", type=int)
    ap.add_argument("scan")
    ap.add_argument("--only", nargs="*", help="room ids or names to read, for a short run")
    ap.add_argument("--dry", action="store_true", help="do not save")
    ap.add_argument("--prices", action="store_true", help="find a price for each kind of line in the saved inventory, instead of reading the scan")
    args = ap.parse_args()
    if args.prices:
        from backend import flood_agent, schedule
        import json
        try:
            kept = json.loads(schedule.PRICES.read_text())
        except (OSError, ValueError):
            kept = {"prices": [], "steps": [], "seconds": 0}
        have = {r["item"] for r in kept.get("prices") or [] if r.get("checked")}
        # Only what has no confirmed price yet is looked up, and it is added to what is already saved: a price that is in use does not change under the schedule.
        items = [i for i in schedule.price_list(args.scan) if i["id"].startswith("fit:") and i["id"] not in have]
        if not items:
            print("every kind of fit-out in this inventory already has a confirmed price")
            return
        run = flood_agent.price(items, save_to=None)
        if not args.dry and run["prices"] and not run["stop"].startswith("error"):
            merged = {**run, "prices": (kept.get("prices") or []) + run["prices"], "steps": (kept.get("steps") or []) + run["steps"], "seconds": round((kept.get("seconds") or 0) + run["seconds"], 1)}
            schedule.PRICES.parent.mkdir(parents=True, exist_ok=True)
            schedule.PRICES.write_text(json.dumps(merged, indent=1))
        print(f"{run['stop']} in {run['seconds']} s, {sum(1 for s in run['steps'] if s['kind'] == 'search')} searches, {run['usage']['input_tokens']:,} tokens in")
        for r in run["prices"]:
            print(f"  {'ok ' if r['checked'] else 'no '} {r['item']:26} ${r['price']:,.2f}{' to $' + format(r['price_high'], ',.2f') if r['price_high'] else ''}  [{r['check_note']}]  {r['source']['url']}")
        return
    r = inventory_agent.run_inventory(args.property, args.scan, only=args.only, save=not args.dry)
    n = r["numbers"]
    print(f"{r['stop']} in {r['seconds']} s: {n['rooms_read']} rooms, {n['views_looked_at']} views, {n['lines']} lines, {n['items_named']} items; lead tokens {r['usage']}")
    for i in r["items"]:
        print(f"  {i['room']:12} {i['quantity']:>2} x {i['what']:36} {i['seen'][:60]}  [{i['at']['standpoint']} {i['at']['direction']}]")
    for m in r["merges"]:
        print(f"  merged {m['drop']} into {m['keep']}: {m['why']}")
    print(r["statement"])


if __name__ == "__main__":
    main()
