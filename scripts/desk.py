"""Run the storm desk for one forecast step: every building with a saved plan, one agent, one crew schedule.

    python -m scripts.desk --scenario beryl-2024 --step adv33
    python -m scripts.desk --scenario beryl-2024 --step adv33 --crews "tree crew=2"     # the owner has two tree crews
    python -m scripts.desk --scenario beryl-2024 --step adv33 --schedule-only          # the crew rule alone, no agent, no cost
"""
from __future__ import annotations

import argparse

from backend import desk


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--scenario", required=True)
    ap.add_argument("--step")
    ap.add_argument("--crews", action="append", default=[], help='how many crews of a trade the owner has, as "tree crew=2"')
    ap.add_argument("--schedule-only", action="store_true")
    args = ap.parse_args()
    crews = {k.strip(): int(v) for k, v in (c.split("=", 1) for c in args.crews)}
    if args.schedule_only:
        got = desk.schedule(args.scenario, args.step, crews=crews)
        for t in got["trades"]:
            print(f"{t['trade']}: {t['crews']} crew(s), {t['hours_asked']:g} hours asked, {t['people_covered']} people covered")
            for j in t["scheduled"]:
                print(f"  crew {j['crew']}  {j.get('start_local') or j['start_h']} to {j.get('end_local') or j['end_h']}  {j['building']}  {j['job_id']}  {j['hours']:g} h")
            for j in t["deferred"]:
                print(f"  after the storm  {j['building']}  {j['job_id']}  {j['hours']:g} h. {j['reason']}")
        return 0
    from backend import desk_agent
    record = desk_agent.run_desk(args.scenario, args.step, crews)
    print(record["statement"])
    print(f"\n{record['stop']} in {record['seconds']} s; {len(record['for_the_owner']['questions'])} questions and "
          f"{len(record['for_the_owner']['approvals'])} approvals for the owner")
    return 0 if record["stop"] == "finished" else 1


if __name__ == "__main__":
    raise SystemExit(main())
