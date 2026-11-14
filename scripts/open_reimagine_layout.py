"""Make a staged room agree between two standpoints (open problem: furnish an empty room, consistently).

  python -m scripts.open_reimagine_layout layout      # find the pieces in the first staged photo, anchor them, draw the check (free after the first look)
  python -m scripts.open_reimagine_layout guide       # pick the second standpoint and draw the coloured blocks into its real photo (free)
  python -m scripts.open_reimagine_layout stage       # one paid call: turn the blocks into the furniture
  python -m scripts.open_reimagine_layout judge       # measure the result and make the side-by-side sheet

Everything written is an illustration or a working picture made from one. None of it is evidence about the building.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image

from backend import openings
from backend.config import BUILDINGS_DIR
from backend.openproblems import reimagine, reimagine_layout as rl, reimagine_view as rv

PROPERTY, SCAN, ROOM = "4303509", "9odpSsu2KYQ", "Living Room"
FIRST = "ztrt2e9utqiu7p2zdgyz365ua"
FIRST_FOLDER = reimagine.OUT / SCAN / f"{FIRST}_view25_listing_d8fecb7f"
FIRST_VIEW = rl.view_of(25, -12, 105)
NEIGHBOURS = ["twnzf6gk54kbpgm4bkhpbd7nd", "ha8gw4zi9b3na3eqg210iq2td"]
WORK = reimagine.OUT / SCAN / "two_standpoints"


def _scan() -> dict:
    bundle = json.loads((BUILDINGS_DIR / PROPERTY / "building.json").read_text())
    return next(s for s in bundle["scans"] if s["id"] == SCAN)


def _layout() -> dict:
    return json.loads((WORK / "layout.json").read_text())


def _second(layout: dict, cams: dict, sweep: str | None, hfov: float) -> tuple[str, dict, dict]:
    """The neighbour that sees the furniture best, and the view from it aimed at the middle of the layout."""
    seen = {}
    for s in ([sweep] if sweep else NEIGHBOURS):
        yaw, pitch = rl.aim(layout, cams[s])
        view = rl.view_of(yaw, pitch, hfov)
        seen[s] = (view, rl.in_view(layout, cams[s], view))
    # A camera standing on the rug or within half a metre of a piece gets a picture mostly of one block.
    best = max(seen, key=lambda s: (not seen[s][1]["stands_on_rug"], seen[s][1]["nearest_piece_m"] >= 0.5, seen[s][1]["corners_in_view"]))
    return best, seen[best][0], {s: v[1] for s, v in seen.items()}


def cmd_layout(a) -> int:
    WORK.mkdir(parents=True, exist_ok=True)
    scan = _scan()
    cams = rv.cameras(scan)
    found = rl.find_pieces(FIRST_FOLDER / "staged_view.jpg", WORK / "pieces_found.json")
    plan = openings.layout(scan, openings.fetch(SCAN))
    staged = np.asarray(Image.open(FIRST_FOLDER / "staged_view.jpg").convert("RGB"), dtype=np.float32)
    real = np.asarray(Image.open(FIRST_FOLDER / "real_view.jpg").convert("RGB"), dtype=np.float32)
    layout = rl.build_layout(found, cams[FIRST], FIRST_VIEW, plan, ROOM,
                             {"generated": True, "photo": str(FIRST_FOLDER / "staged_view.jpg"), "scan_id": SCAN, "sweep_id": FIRST},
                             changed_mask=rl.changed(real, staged))
    (WORK / "layout.json").write_text(json.dumps(layout, indent=1))
    rl.draw_outlines(staged, layout, cams[FIRST], FIRST_VIEW).save(WORK / "anchoring_check_A.jpg", quality=90)
    for p in layout["pieces"]:
        print(f"{p['name']:<22} {p['colour']['name']:<8} {p['width_m']:.2f} wide x {p['depth_m']:.2f} deep x {p['height_m']:.2f} high  at {p['footprint'][0]}  {json.dumps(p['check'])}")
    if layout["rug"]:
        print("rug", layout["rug"]["footprint"], "sides", layout["rug"]["sides_m"], json.dumps(layout["rug"].get("squared_up")), json.dumps(layout["rug"]["check"]))
    print("not anchored:", layout["not_anchored"], "| part of the building, left out:", json.dumps(layout["part_of_the_building"]))
    print("vision calls used:", rl.vision_calls())
    print("layout", WORK / "layout.json")
    print("check ", WORK / "anchoring_check_A.jpg")
    return 0


def cmd_guide(a) -> int:
    layout, cams = _layout(), rv.cameras(_scan())
    sweep, view, seen = _second(layout, cams, a.sweep, a.hfov)
    real = rv.wide_view(rv.load_cube(SCAN, sweep), view["yaw_deg"], view["pitch_deg"], view["hfov_deg"], view["width"], view["height"])
    out = WORK / f"guide_B_{sweep[:10]}{'_edges' if a.edges else ''}.jpg"
    rl.draw_guide(real, layout, cams[sweep], view, a.edges).save(out, quality=92)
    print("how each neighbour sees the layout:", json.dumps(seen))
    print("second standpoint", sweep, json.dumps(view))
    print("guide", out)
    return 0


def cmd_stage(a) -> int:
    layout, cams = _layout(), rv.cameras(_scan())
    sweep, view, _ = _second(layout, cams, a.sweep, a.hfov)
    extra = rl.camera_move(cams[FIRST], FIRST_VIEW, cams[sweep], view) + (a.extra.strip() + " " if a.extra.strip() else "")
    if a.dry:
        print(rl.instruction_for(layout, extra, a.edges))
        return 0
    out = rl.stage_second(SCAN, sweep, view, layout, cams[sweep], FIRST_FOLDER / "staged_view.jpg", extra=extra, attempt=a.attempt, hidden_edges=a.edges)
    if not out["ok"]:
        print("Nothing was generated:", json.dumps(out["reason"]), file=sys.stderr)
        return 1
    print(reimagine.LABEL)
    print("from cache" if out["cached"] else "new generation", "| budget", json.dumps(reimagine.budget()),
          "| used on the second standpoint:", rl.second_standpoint_generations())
    print("folder", out["folder"])
    return 0


def cmd_judge(a) -> int:
    layout, cams = _layout(), rv.cameras(_scan())
    folder = Path(a.folder)
    record = json.loads((folder / "record.json").read_text())
    sweep, src = record["source"]["sweep_id"], record["source"]["view"]
    view = rl.view_of(src["yaw_deg_clockwise_from_face_1"], src["pitch_deg"], src["horizontal_field_deg"])
    layout = record["layout"]
    verdict = rl.judge(folder, layout, cams[sweep], view)
    # For looking at: the boxes drawn over the result. Each piece should stand inside its own box.
    settled = np.asarray(Image.open(folder / "staged_view_settled.jpg").convert("RGB"), dtype=np.float32)
    rl.draw_outlines(settled, layout, cams[sweep], view).save(folder / "placement_check.jpg", quality=90)
    if a.look:
        result = Image.open(folder / "staged_view_settled.jpg").convert("RGB")
        names = [p["name"] for p in layout["pieces"]]
        seen = rl.find_boxes(result, names, f"boxes in {folder.name}")
        blocks = rl.regions(layout, cams[sweep], view, whole=True)    # a piece is as big as its whole block, hidden part included
        by_name = {s["name"]: s for s in seen["pieces"]}
        verdict["seen_by_vision_model"] = {
            "note": seen["note"],
            "pieces": {n: {"present": bool(by_name.get(n, {}).get("present")),
                           **rl.box_agreement(by_name[n]["box"] if by_name.get(n, {}).get("present") else None, blocks[n])} for n in names}}
    if a.stand:
        again = rl.find_pieces(folder / "staged_view_settled.jpg", folder / "pieces_found.json")
        verdict["where_it_stands"] = rl.where_it_stands(again, layout, cams[sweep], view)
    earlier = json.loads((folder / "verdict.json").read_text()) if (folder / "verdict.json").exists() else {}
    verdict = {**{k: v for k, v in earlier.items() if k in ("seen_by_vision_model", "where_it_stands", "looked_at")}, **verdict}
    (folder / "verdict.json").write_text(json.dumps(verdict, indent=1))
    sheet = rl.side_by_side(FIRST_FOLDER, folder, WORK / f"side_by_side_{folder.name[-8:]}.jpg")
    print(json.dumps(verdict, indent=1))
    print("sheet", sheet, "| vision calls used:", rl.vision_calls())
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="step", required=True)
    sub.add_parser("layout")
    for name in ("guide", "stage"):
        p = sub.add_parser(name)
        p.add_argument("--sweep", help="use this standpoint instead of picking the best neighbour")
        p.add_argument("--hfov", type=float, default=105.0)
        p.add_argument("--edges", action="store_true", help="also draw every block's edges, so a block behind another shows where it ends")
        if name == "stage":
            p.add_argument("--extra", default="", help="more words for the instruction")
            p.add_argument("--attempt", default="", help="a tag that makes this a new request rather than a cached one")
            p.add_argument("--dry", action="store_true", help="print the instruction and stop, without the paid call")
    p = sub.add_parser("judge")
    p.add_argument("folder")
    p.add_argument("--look", action="store_true", help="also ask the vision model where it sees each piece (one counted call)")
    p.add_argument("--stand", action="store_true", help="also find the pieces in the result and measure, in metres, where they stand (one counted call, kept)")
    a = ap.parse_args()
    return {"layout": cmd_layout, "guide": cmd_guide, "stage": cmd_stage, "judge": cmd_judge}[a.step](a)


if __name__ == "__main__":
    raise SystemExit(main())
