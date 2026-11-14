"""Prepare buildings from the command line, so demo plans exist ahead of time.

    python -m scripts.plan --scenario <id> [--step <id>] 23347 9012     # specific buildings
    python -m scripts.plan --scenario <id> --top 4                       # the most pressing buildings with scans
    python -m scripts.plan --list                                        # show scenarios and their steps
"""
from __future__ import annotations

import argparse
import sys

from backend import hazards, screen
from backend.agent import Planner
from backend.building import BuildingError, Site, building_dir


def show(e: dict) -> None:
    t = e["type"]
    if t in ("status", "step"):
        print(f"  [{e['t']:6.1f}s] {e['label']}")
    elif t == "lead":
        print(f"  [{e['t']:6.1f}s] LEAD {e['lead']['id']} ({e['lead']['hazard']}): {e['lead']['title']}")
    elif t == "action":
        a = e["action"]
        print(f"  [{e['t']:6.1f}s] ACTION {a['id']} [{a['timing']}, {a['hours_of_work']}h, ${a['cost_low']:,}-${a['cost_high']:,}, {a['basis']}]: {a['title']}")
    elif t == "lead_closed" and e["lead"]["status"] != "actions":
        print(f"  [{e['t']:6.1f}s] {e['lead']['id']} -> {e['lead']['status']}")
    elif t == "message":
        print(f"  [{e['t']:6.1f}s] DRAFT {e['message']['kind']} to {e['message']['to']}: {e['message']['subject']}")
    elif t == "error":
        print(f"  ERROR: {e['message']}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("buildings", nargs="*", type=int)
    ap.add_argument("--scenario")
    ap.add_argument("--step")
    ap.add_argument("--top", type=int, default=0)
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--redo", action="store_true")
    args = ap.parse_args()
    if args.list or not args.scenario:
        for sc in hazards.scenarios():
            print(f"{sc['id']}  [{sc['kind']}, {sc['city']}{', live' if sc['live'] else ''}]  {sc['name']}")
            for st in sc["steps"]:
                print(f"    {st['id']}  {st['issued']}  {st['label']}")
        return 0
    sc = next(s for s in hazards.scenarios() if s["id"] == args.scenario)
    step = args.step or (sc["steps"][-1]["id"] if sc["steps"] else None)
    key = f"{args.scenario}__{step or 'now'}"
    ids = args.buildings
    if not ids:
        for r in screen.rank(args.scenario, step):
            if len(ids) >= args.top:
                break
            if r["scans"] and (args.redo or not (building_dir(r["id"]) / "plans" / f"{key}.json").exists()):
                ids.append(r["id"])
    if not ids:
        ap.error("give building ids or --top N")
    failed = 0
    for pid in ids:
        try:
            site = Site.load(pid)
        except BuildingError as e:
            print(f"{pid}: cannot prepare this building: {e}")
            failed += 1
            continue
        threat = screen.threat_for(args.scenario, step, site.d["record"])
        print(f"\n{pid}  {site.d['record']['name']} ({site.d['record']['type_label']}), {site.d['record']['city']}  |  {threat['name']}, {threat['label']}")
        plan = Planner(site, threat, emit=show).run()
        if plan["stop"] == "error":
            failed += 1
            continue
        t = plan["totals"]["before_arrival"]
        print(f"  => {len(plan['actions'])} actions ({t['count']} before arrival, ${t['cost_low']:,}-${t['cost_high']:,}), "
              f"{len(plan['messages'])} messages, {plan['seconds']}s: {plan['headline']}")
        u = plan["usage"]
        print(f"     tokens: {u['cache_creation_input_tokens']:,} cache writes, {u['cache_read_input_tokens']:,} cache reads, {u['output_tokens']:,} output")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
