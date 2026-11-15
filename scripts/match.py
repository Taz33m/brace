"""Find the products one item of a scanned home most likely is, each with a price its page bears out.

    python -m scripts.match 9519837 CaSLe7ZwnfF kitchen-1 refrigerator
    python -m scripts.match 9519837 CaSLe7ZwnfF kitchen-1 range --dry        # do not save

The item must be in the saved inventory of the scan. The match is saved beside it, under '<room_id>:<kind>'.
"""
from __future__ import annotations

import argparse

from backend import product_match


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("property", type=int)
    ap.add_argument("scan")
    ap.add_argument("room_id")
    ap.add_argument("kind", nargs="+", help="a kind of fit-out as the inventory names it, such as refrigerator or range hood")
    ap.add_argument("--dry", action="store_true", help="do not save")
    args = ap.parse_args()
    try:
        e = product_match.match(args.property, args.scan, args.room_id, " ".join(args.kind), save=not args.dry)
    except ValueError as err:
        raise SystemExit(f"no match was made: {err}")
    u = e["usage"]
    print(f"{e['stop']} in {e['seconds']} s, {u['searches']} searches, {u['pages_read']} pages read, {u['input_tokens']:,} tokens in, {u['output_tokens']:,} out")
    print(f"seen: {'; '.join(e['seen']) or 'nothing noted'}   brand read: {e['brand_read'] or 'none'}")
    for c in e["candidates"]:
        print(f"  kept     {c['make']} {c['model'] or ''}  ${c['price']:,.2f}  {c['store']}  {c['url']}\n           {c['name']}\n           {c['why']}")
    for d in e["dropped"]:
        print(f"  dropped  {d['make']} {d['model'] or ''}  ${d['price']:,.2f}  {d['store']}  [{d['why_dropped']}]  {d['url']}")
    for s in e["steps"]:
        print(f"  {s['t']:>6} s  {s['kind']:6} {s['text'][:150]}")
    print(f"the model's last words: {e['said']}")
    print(e["statement"])


if __name__ == "__main__":
    main()
