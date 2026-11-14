"""Find, place and count a property's amenities, and check them against CoStar's listing.

    python -m scripts.open_amenities --building 4303509              # detector + amenity looks (paid, cached, counted)
    python -m scripts.open_amenities --building 4303509 --offline    # only what is already cached, no calls
    python -m scripts.open_amenities --building 4303509 --no-vision  # detector only

Writes data/cache/open/amenities/<property_id>.json.
"""
from __future__ import annotations

import argparse
import sys

from backend.openproblems import amenities as A


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--building", type=int, required=True)
    ap.add_argument("--offline", action="store_true", help="make no detector or vision call; use what is cached")
    ap.add_argument("--no-vision", action="store_true", help="make no vision call")
    a = ap.parse_args()

    client = None
    if not a.offline and not a.no_vision:
        import anthropic
        client = anthropic.Anthropic()
    kwargs = {"detector": None} if a.offline else {}
    try:
        r = A.inventory(a.building, client=client, **kwargs)
    except (A.BuildingError, KeyError) as e:
        print(f"cannot inventory {a.building}: {e}")
        return 1
    path = A.save(r)

    print(f"{r['name']} ({r['property_id']}), {r['units']} homes")
    for name, s in r["sources"].items():
        print(f"  source {name:17s} {s['status']:14s} {s.get('detail', '')}")
    print("  found:")
    for am in r["amenities"]:
        more = " (at least)" if am["count_is_minimum"] else ""
        flag = "" if am["confirmed"] else "  UNCONFIRMED"
        print(f"    {am['count']}{more} x {am['kind']}  confidence {am['confidence']}  from {', '.join(am['sources'])}{flag}")
        for inst in am["instances"]:
            p = inst["place"]
            where = p.get("cell") or p.get("scan_name") or p["type"]
            if p.get("scan_name") and p.get("cell"):
                where = f"{p['scan_name']} at {p['cell']}"
            storm = inst["before_a_storm"]
            seen = ""
            if storm:
                bits = storm["loose_items"][:4] + storm["equipment"][:3]
                if storm.get("aerial_loose_items"):
                    bits.append(f"from the air: {storm['aerial_loose_items']}")
                seen = f" | glass: {storm['glass']} | {'; '.join(str(b) for b in bits)}"
            print(f"      #{inst['n']} {where} [{', '.join(inst['sources'])}]{seen}")
    c = r["comparison"]
    print(f"  CoStar lists {c['counts']['listed']} kinds; {r['costar']['amenity_ids_note']}")
    print(f"  listed and found ({len(c['listed_and_found'])}): "
          + ", ".join(f"{x['kind']} (listed {x['listed_count'] or 'n/a'}, found {x['found_count']})" for x in c["listed_and_found"]))
    print(f"  listed, not found ({len(c['listed_not_found'])}): "
          + ", ".join(f"{x['kind']} [{x['status']}]" for x in c["listed_not_found"]))
    print(f"  found, not listed ({len(c['found_not_listed'])}): " + ", ".join(x["kind"] for x in c["found_not_listed"]))
    if c["found_not_listed_unconfirmed"]:
        print(f"  unconfirmed, not listed ({len(c['found_not_listed_unconfirmed'])}): "
              + ", ".join(f"{x['kind']} ({x['confidence']})" for x in c["found_not_listed_unconfirmed"]))
    print(f"  coverage: {r['site_coverage']['note']}")
    print(f"  calls: {r['calls']}")
    print(f"  wrote {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
