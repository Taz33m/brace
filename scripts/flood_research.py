"""Run the flood test's research agent once: it finds flood fixes and their prices on the web, and each price is checked against its page.

    python -m scripts.flood_research            # run and save
    python -m scripts.flood_research --dry      # run, print, do not save
    python -m scripts.flood_research --prices 4303509 39JTmBzqWxr      # price the lines of one home's file for an insurer
"""
from __future__ import annotations

import argparse

from backend import flood, flood_agent


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true", help="do not save what was found")
    ap.add_argument("--prices", nargs=2, metavar=("PROPERTY", "SCAN"), help="price the lines of one home's file instead: building work and the furniture its scan saw")
    args = ap.parse_args()
    if args.prices:
        from backend import insurer_file
        items = insurer_file.price_list(int(args.prices[0]), args.prices[1])
        run = flood_agent.price(items, save_to=None if args.dry else insurer_file.PRICES)
        print(f"{run['stop']} in {run['seconds']} s, {sum(1 for s in run['steps'] if s['kind'] == 'search')} searches, {run['usage']['input_tokens']:,} tokens in, {run['usage']['output_tokens']:,} out")
        for r in run["prices"]:
            print(f"  {'ok ' if r['checked'] else 'no '} {r['item']:22} ${r['price']:,.2f}{' to $' + format(r['price_high'], ',.2f') if r['price_high'] else ''} {r['unit']}  [{r['check_note']}]\n       {r['source']['url']}")
        return
    run = flood_agent.research(save=not args.dry)
    print(f"{run['stop']} in {run['seconds']} s, {sum(1 for s in run['steps'] if s['kind'] == 'search')} searches, {run['usage']['input_tokens']:,} tokens in, {run['usage']['output_tokens']:,} out")
    for f in run["fixes"]:
        print(f"  {'ok ' if f['checked'] else 'no '} {f['type']:9} {f['name']}: ${f['price']:,.2f} {f['price_unit']}"
              f"{', holds ' + format(f['holds_ft'], 'g') + ' ft' if f['holds_ft'] else ''}{', ' + format(f['weeks'], 'g') + ' weeks' if f['weeks'] else ''}  [{f['check_note']}]\n       {f['source']['url']}")
    if not args.dry and run["fixes"]:
        cat = flood.catalogue()
        print(f"saved to {flood.RESEARCH}. The plan can now choose from: {', '.join(m['name'] for m in cat['measures'] if m['type'] == 'quick')}")


if __name__ == "__main__":
    main()
