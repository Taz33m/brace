"""Tighter prices for the schedule, each one a price a page states for a more specific thing and confirmed on that page.

    python -m scripts.tighten fitting                         # the labour to fit one of each kind of product
    python -m scripts.tighten fitting --first CaSLe7ZwnfF     # the same, with the kinds in that scan's inventory first
    python -m scripts.tighten specific 9519837 CaSLe7ZwnfF    # built work, priced as the reader described it
    python -m scripts.tighten finishes 9519837 CaSLe7ZwnfF    # one look at the scan: floors, doors, walls, baseboards
    python -m scripts.tighten work 9519837 CaSLe7ZwnfF        # prices for the finishes that were read
    python -m scripts.tighten report 9519837                  # the schedule before and after, and every line that changed
    python -m scripts.tighten reject specific "hallway-1:wall cabinet" "why" --scan CaSLe7ZwnfF     # a reviewer sets a confirmed price aside

A run looks up only what has no confirmed price yet and adds to what is saved, so running one again is the retry.
"""
from __future__ import annotations

import argparse

from backend import inventory_agent, tighten


def _show(run: dict) -> None:
    print(f"{run['stop']} in {run['seconds']} s, {sum(1 for s in run['steps'] if s['kind'] == 'search')} searches, {sum(1 for s in run['steps'] if s['kind'] == 'read')} pages read, "
          f"{run['usage']['input_tokens']:,} tokens in, {run['usage']['output_tokens']:,} out; asked for {len(run['items'])}, confirmed {len({r['item'] for r in run['prices'] if r['checked']})}")
    for r in run["prices"]:
        print(f"  {'ok ' if r['checked'] else 'no '} {r['item']:40} ${r['price']:,.2f}{' to $' + format(r['price_high'], ',.2f') if r['price_high'] else ''} {r['unit']}  {r.get('place') or ''}  [{r['check_note']}]\n"
              f"       {r['source']['url']}\n       \"{r['source']['quote'][:200]}\"")
    left = [i["id"] for i in run["items"] if i["id"] not in {r["item"] for r in run["prices"] if r["checked"]}]
    if left:
        print("  no confirmed price: " + ", ".join(left))


def _money(low, high) -> str:
    f = lambda v: f"${v:,.0f}" if v == int(v) else f"${v:,.2f}"
    return "no price" if low is None else f(low) if low == high else f"{f(low)} to {f(high)}"


def report(property_id: int) -> None:
    from backend import schedule
    with tighten.set_aside():
        before = schedule.schedule(property_id)
    after = schedule.schedule(property_id)
    lines = lambda s: [(room["name"], l) for b in s["buildings"] for u in b["units"] for room in u["rooms"] for l in room["items"]]
    for name, s in (("before", before), ("after", after)):
        home, total = s["home"]["total"], s["total"]
        print(f"{name:7} one home {_money(home['low'], home['high'])} (width ${home['high'] - home['low']:,.0f}), property {_money(total['low'], total['high'])}, {home['lines_priced']} of {home['lines']} lines priced")
    print(f"\n{'room':20} {'line':38} {'qty':>5}  {'price of one, before':24} {'price of one, after':24} {'line, after':22} basis")
    for (room, old), (_, new) in zip(lines(before), lines(after)):
        if (old["price_low"], old["price_high"]) != (new["price_low"], new["price_high"]):
            wider = " WIDER" if None not in (old["price_low"], new["price_low"]) and new["price_high"] - new["price_low"] > old["price_high"] - old["price_low"] else ""
            print(f"{room:20} {new['what'][:38]:38} {new['quantity']:>5}  {_money(old['price_low'], old['price_high']):24} {_money(new['price_low'], new['price_high']):24} {_money(new['low'], new['high']):22} {new['price_basis']}{wider}"
                  + (f" [{new['finish']}]" if new.get("finish") else ""))
    print("\nfinishes read, on lines whose price did not change: " + ("; ".join(sorted({f"{l['what']}: {l['finish']}" for _, l in lines(after) if l.get("finish")})) or "none"))


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="what", required=True)
    fit = sub.add_parser("fitting")
    fit.add_argument("--first", metavar="SCAN", help="put the kinds in this scan's inventory at the head of the list")
    for name in ("specific", "finishes", "work"):
        p = sub.add_parser(name)
        p.add_argument("property", type=int)
        p.add_argument("scan")
    sub.add_parser("report").add_argument("property", type=int)
    no = sub.add_parser("reject")
    no.add_argument("file", choices=["fitting", "specific", "work"])
    no.add_argument("item", help="the row's item, such as fitting:toilet, door:panelled or hallway-1:wall cabinet")
    no.add_argument("why")
    no.add_argument("--scan", help="the scan, for a specific price")
    for p in sub.choices.values():
        p.add_argument("--dry", action="store_true", help="do not save")
    args = ap.parse_args()
    try:
        if args.what == "report":
            report(args.property)
        elif args.what == "reject":
            if args.file == "specific" and not args.scan:
                raise ValueError("a specific price belongs to a scan: give --scan")
            path = {"fitting": tighten.fitting_path, "work": tighten.work_path}[args.file]() if args.file != "specific" else tighten.specific_path(args.scan)
            n = 0 if args.dry else tighten.set_row_aside(path, args.item, args.why)
            print(f"{n} confirmed row{'' if n == 1 else 's'} for {args.item} set aside" if n else f"no confirmed row for {args.item} to set aside")
        elif args.what == "fitting":
            inv = inventory_agent.saved(args.first) if args.first else None
            _show(tighten.price_fitting([i["kind"] for i in (inv or {}).get("items") or []], save=not args.dry))
        elif args.what == "specific":
            _show(tighten.price_specific(args.scan, save=not args.dry))
        elif args.what == "work":
            _show(tighten.price_work(args.scan, save=not args.dry))
        else:
            f = tighten.read_finishes(args.property, args.scan, save=not args.dry)
            print(f"{f['stop']} in {f['seconds']} s, {len(f['pictures'])} pictures, {f['usage']['input_tokens']:,} tokens in, {f['usage']['output_tokens']:,} out")
            for room, said in f["rooms"].items():
                print(f"  {room:14} floor      {said['finish']:28} {said['seen']}")
            for what, said in f["home"].items():
                print(f"  {'home':14} {what:10} {(said or {}).get('finish') or 'no answer':28} {(said or {}).get('seen') or ''}")
    except ValueError as err:
        raise SystemExit(f"nothing was done: {err}")


if __name__ == "__main__":
    main()
