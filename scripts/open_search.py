"""Search a building's scans by what is in them.

    python -m scripts.open_search --building 4303509 --index [--limit 40]     # describe positions (paid, cached, counted)
    python -m scripts.open_search --building 4303509 --query "water heater"   # search the saved index (free)
    python -m scripts.open_search --building 4303509 --query "fireplace" --rerank   # one paid call to re-rank
"""
from __future__ import annotations

import argparse
import sys

from backend.openproblems import search as S


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--building", type=int, required=True)
    ap.add_argument("--index", action="store_true", help="describe scan positions with the vision model and save the index")
    ap.add_argument("--limit", type=int, default=None, help="most new paid calls in this run")
    ap.add_argument("--offline", action="store_true", help="with --index: rebuild from what is cached, no calls")
    ap.add_argument("--query")
    ap.add_argument("-k", type=int, default=5)
    ap.add_argument("--rerank", action="store_true", help="let the model re-rank the top text matches (one paid call)")
    a = ap.parse_args()
    if not a.index and not a.query:
        ap.error("give --index or --query")

    client = None
    if (a.index and not a.offline) or a.rerank:
        import anthropic
        client = anthropic.Anthropic()

    if a.index:
        idx = S.build_index(a.building, client=client, limit=a.limit)
        print(f"indexed {idx['indexed_positions']} of {idx['total_positions']} positions ({idx['indexed_share']:.0%}); "
              f"{idx['new_calls_this_run']} new calls this run; calls used so far: {idx['calls_used']}")
        for sid, s in idx["scans"].items():
            print(f"  {sid}  {s['indexed']:3d}/{s['positions']:3d}  {s['name']}")
        for f in idx["failed_this_run"]:
            print(f"  FAILED {f}")

    if a.query:
        try:
            hits = S.search(a.building, a.query, k=a.k, client=client if a.rerank else None)
            c = S.count(a.building, a.query)
        except S.SearchError as e:
            print(e)
            return 1
        print(c["statement"])
        for i, h in enumerate(hits, 1):
            face = f"face {h['direction']} ({h['bearing_deg']:.0f} deg)" if h["direction"] else \
                (f"quarter {h['quarter']} of the view (no compass fix for this scan)" if h["quarter"] else "no direction recorded")
            print(f"{i}. [{h['score']:.2f}] {h['scan_name']} ({h['scan_id']}) / {h['room'] or 'room'} / position {h['sweep_id']}: "
                  f"{face}; viewer yaw {h['viewer_yaw']}\n     {h['phrase']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
