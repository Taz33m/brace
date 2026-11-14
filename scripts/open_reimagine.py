"""Stage one real panorama face as an illustration (open problem: furnish an empty room).

  python -m scripts.open_reimagine --model 9odpSsu2KYQ --sweep ztrt2e9utqiu7p2zdgyz365ua --face 1 --purpose listing
  python -m scripts.open_reimagine --model 9odpSsu2KYQ --sweep ztrt2e9utqiu7p2zdgyz365ua --face 2 --purpose listing --reference-face 1

A new picture is a paid call; a picture already made is read from the cache. The result is an illustration,
never a photo of the building.
"""
from __future__ import annotations

import argparse
import json
import sys

from backend.openproblems import reimagine


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--model", required=True, help="Matterport scan id")
    ap.add_argument("--sweep", required=True, help="scan position id")
    ap.add_argument("--face", required=True, type=int, choices=[1, 2, 3, 4], help="side face of the panorama")
    ap.add_argument("--purpose", required=True, choices=sorted(reimagine.INSTRUCTIONS))
    ap.add_argument("--reference-face", type=int, choices=[1, 2, 3, 4],
                    help="a neighbouring face already staged for the same purpose, sent as a furniture reference")
    ap.add_argument("--budget", action="store_true", help="print the generations used and stop")
    a = ap.parse_args()
    if a.budget:
        print(json.dumps(reimagine.budget()))
        return 0
    out = reimagine.stage(a.model, a.sweep, a.face, a.purpose, reference_face=a.reference_face)
    if not out["ok"]:
        print("Nothing was generated:", json.dumps(out["reason"]), file=sys.stderr)
        return 1
    rec = out["record"]
    print(reimagine.LABEL)
    print("from cache" if out["cached"] else "new generation", "| budget", json.dumps(reimagine.budget()))
    print("image   ", out["image"])
    print("labelled", out["labelled"])
    print("record  ", out["record_path"])
    print("change from the real view (0 to 255):", json.dumps(rec["pixel_change_from_real"]))
    if rec.get("seam_with_reference"):
        print("shared edge with the reference view:", json.dumps({k: v for k, v in rec["seam_with_reference"].items() if k != "note"}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
