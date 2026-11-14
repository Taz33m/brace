"""Furniture agreeing between two standpoints: no network and no keys. Rooms, cameras and boxes are made up,
so what the code should find is known exactly."""
from __future__ import annotations

import io
import json

import numpy as np
import pytest
from PIL import Image

from backend.openproblems import reimagine, reimagine_layout as rl, reimagine_view as rv

# A camera 1.4 m above the floor at the room's origin, looking north and a little down.
CAMERA = {"e": 0.0, "n": 0.0, "z": 1.4, "h": 0.0}
VIEW = rl.view_of(0, -15, 90, 1200, 800)


def seen_as(kind: str, footprint: list, height: float, name: str = "piece") -> dict:
    """What a perfect finder would report for a real box: its pixel box and the two ends of its front floor edge."""
    box = {"footprint": footprint, "height_m": height}
    px = rv.project(rl.corners(box), CAMERA, **VIEW)
    xs, ys = [p[0] for p in px], [p[1] for p in px]
    return {"name": name, "kind": kind, "look": "", "box": [min(xs), min(ys), max(xs), max(ys)],
            "floor_left": list(px[0]), "floor_right": list(px[1])}


def test_a_box_seen_in_a_photo_is_put_back_where_it_stands():
    # A sofa 1.6 m wide, 0.9 m deep and 0.8 m high, three metres in front of the camera, a little to the right.
    truth = [[-0.5, 3.0], [1.1, 3.0], [1.1, 3.9], [-0.5, 3.9]]
    box = rl.anchor(seen_as("sofa", truth, 0.8), CAMERA, VIEW)
    assert np.allclose(box["footprint"], truth, atol=0.02)      # the floor edge fixes the place; the depth is the assumed 0.9
    assert box["width_m"] == pytest.approx(1.6, abs=0.02) and box["depth_m"] == 0.9
    assert box["height_m"] == pytest.approx(0.8, abs=0.03)
    assert "0.90 m" in box["assumed"] and "sofa" in box["assumed"]  # the layout says what was not measured


def test_the_assumed_depth_is_the_only_thing_not_read_from_the_photo():
    # The same sofa, but really only 0.6 m deep: place, width and the assumed depth come out the same,
    # because depth cannot be seen from the front. The layout must not pretend otherwise.
    shallow = [[-0.5, 3.0], [1.1, 3.0], [1.1, 3.6], [-0.5, 3.6]]
    box = rl.anchor(seen_as("sofa", shallow, 0.8), CAMERA, VIEW)
    assert np.allclose(box["footprint"][:2], shallow[:2], atol=0.02) and box["depth_m"] == 0.9


def plant_seen(at_e: float) -> tuple[dict, dict]:
    """A pot 0.2 m wide under leaves 0.6 m wide and 1.2 m high, 2.5 m ahead: the finder gives the pot's floor
    edge and the pixel box around the whole plant."""
    leaves = [[at_e - 0.3, 2.5], [at_e + 0.3, 2.5], [at_e + 0.3, 2.5], [at_e - 0.3, 2.5]]    # a flat upright sheet
    found = seen_as("plant", leaves, 1.2)
    pot = rv.project([(at_e - 0.1, 2.5, 0.0), (at_e + 0.1, 2.5, 0.0)], CAMERA, **VIEW)
    found["floor_left"], found["floor_right"] = list(pot[0]), list(pot[1])
    return found, {"footprint": leaves, "height_m": 1.2}


def test_a_plant_is_anchored_by_the_middle_of_its_pot_and_holds_its_leaves():
    found, _ = plant_seen(0.0)                                          # straight ahead, where a photo does not lean
    box = rl.anchor(found, CAMERA, VIEW)
    assert np.allclose(np.mean(np.array(box["footprint"]), axis=0), [0.0, 2.5], atol=0.02)
    # A camera looking down sees the top of an upright thing wider than its foot, so the box that holds the
    # whole pixel box is a little generous: never narrower than the plant, here under 0.1 m wider.
    assert 0.6 <= box["width_m"] <= 0.7 and box["depth_m"] == box["width_m"]                     # as deep as wide, assumed
    assert box["height_m"] == pytest.approx(1.2, abs=0.03)
    assert "as deep as it is wide" in box["assumed"]


def test_a_plant_off_to_the_side_is_still_wholly_inside_its_box():
    # Off to the side a wide photo leans upright things over, so the box has to be a little generous:
    # never narrower or lower than the plant, and not much wider.
    found, plant = plant_seen(1.2)
    box = rl.anchor(found, CAMERA, VIEW)
    assert np.allclose(np.mean(np.array(box["footprint"]), axis=0), [1.2, 2.5], atol=0.12)
    assert 0.6 <= box["width_m"] <= 0.9 and box["height_m"] >= 1.19
    mine, theirs = rv.project(rl.corners(box), CAMERA, **VIEW), rv.project(rl.corners(plant), CAMERA, **VIEW)
    assert min(p[0] for p in mine) <= min(p[0] for p in theirs) + 1 and max(p[0] for p in mine) >= max(p[0] for p in theirs) - 1
    assert min(p[1] for p in mine) <= min(p[1] for p in theirs) + 1


def test_a_floor_edge_above_the_horizon_is_not_anchored():
    found = {"name": "ghost", "kind": "sofa", "look": "", "box": [100, 50, 300, 120], "floor_left": [100, 120], "floor_right": [300, 120]}
    assert rl.anchor(found, CAMERA, VIEW) is None
    layout = rl.build_layout({"pieces": [found], "rug": []}, CAMERA, VIEW, None, "Living Room", {})
    assert layout["pieces"] == [] and layout["not_anchored"] == ["ghost"]     # said, not silently dropped


def test_rug_corners_go_to_the_floor_one_by_one_and_a_cut_corner_is_rebuilt():
    truth = [(-1.0, 2.0), (1.0, 2.0), (1.0, 4.0), (-1.0, 4.0)]
    px = rv.project([(e, n, 0.0) for e, n in truth], CAMERA, **VIEW)
    rug = rl.anchor_rug([list(p) for p in px], CAMERA, VIEW)
    assert np.allclose(rug["footprint"], truth, atol=0.01) and rug["corners_beyond_the_picture"] == []
    # A rug whose near-left corner is below the picture: the finder reports the two points where the
    # picture's bottom edge cuts its sides. The corner is rebuilt where those two sides meet.
    near = [(-1.0, 0.9), (1.0, 0.9), (1.0, 4.0), (-1.0, 4.0)]
    bottom = VIEW["height"] - 1
    cut_a = rv.floor_point((rv.project([(-1.0, 1.2, 0.0)], CAMERA, **VIEW)[0][0], bottom), CAMERA, **VIEW)
    px = rv.project([(e, n, 0.0) for e, n in near], CAMERA, **VIEW)
    assert px[0][1] > bottom                                             # the corner really is out of the picture
    # Points on the bottom row lying on the rug's left side and on its near side.
    left_cut = rl._meet((-1.0, 4.0), (-1.0, 0.9), cut_a, (cut_a[0] + 1, cut_a[1]))
    on_left = rv.project([(float(left_cut[0]), float(left_cut[1]), 0.0)], CAMERA, **VIEW)[0]
    row_right = rv.floor_point((VIEW["width"] / 2, bottom), CAMERA, **VIEW)   # the floor seen along the bottom row
    assert abs(on_left[1] - bottom) < 1.5
    # the near side (n = 0.9) is entirely below the bottom row here, so cut it with a slanted rug instead
    slanted = [(-0.2, 1.0), (1.5, 2.2), (0.6, 3.6), (-1.1, 2.4)]
    spx = rv.project([(e, n, 0.0) for e, n in slanted], CAMERA, **VIEW)
    assert spx[0][1] > bottom and all(p[1] < bottom for p in spx[1:])
    def cut(p, q):                                                          # where the side from p to q crosses the bottom row
        for t in np.linspace(0, 1, 20001):
            e, n = p[0] + (q[0] - p[0]) * t, p[1] + (q[1] - p[1]) * t
            at = rv.project([(e, n, 0.0)], CAMERA, **VIEW)[0]
            if at[1] <= bottom:
                return [at[0], float(bottom)]
    reported = [cut(slanted[0], slanted[3]), list(spx[3]), list(spx[2]), list(spx[1]), cut(slanted[0], slanted[1])]
    rug = rl.anchor_rug(reported, CAMERA, VIEW)
    assert len(rug["footprint"]) == 4 and len(rug["corners_beyond_the_picture"]) == 1
    assert np.allclose(rug["corners_beyond_the_picture"][0], slanted[0], atol=0.03)
    assert np.allclose(rug["footprint"][3], slanted[0], atol=0.03)       # it takes the place of the two cut points
    assert row_right is not None


def test_a_lopsided_rug_is_squared_up_and_the_measured_corners_are_kept():
    true_rug = {"name": "rug", "kind": "rug", "footprint": [[0.0, 0.0], [2.0, 0.0], [2.0, 3.0], [0.0, 3.0]]}
    same = rl.square_up(true_rug)
    assert np.allclose(same["footprint"], true_rug["footprint"], atol=1e-6) and same["squared_up"]["each_corner_moved_m"] == [0, 0, 0, 0]
    # One corner read 0.4 m out (it was hidden under a sofa): the long sides still agree, and set the direction.
    lopsided = {"name": "rug", "kind": "rug", "footprint": [[0.0, 0.0], [2.0, 0.0], [2.0, 3.0], [0.0, 3.4]]}
    square = rl.square_up(lopsided)
    c = np.array(square["footprint"])
    for i in range(4):
        assert abs(float((c[i] - c[i - 1]) @ (c[(i + 1) % 4] - c[i]))) < 1e-3                     # every corner is a right angle
    assert square["as_measured"] == lopsided["footprint"]                                        # nothing is hidden
    assert max(square["squared_up"]["each_corner_moved_m"]) <= 0.21 and square["sides_m"] == [2.0, 3.2, 2.0, 3.2]
    for i in range(4):                                                                             # corners keep their order
        assert np.linalg.norm(c[i] - np.array(lopsided["footprint"][i])) < 0.25


# ---- inside the room ---------------------------------------------------------------------------------------

PLAN = {"rooms": [{"name": "Living Room", "walls": [[[0, 0], [4, 0]], [[4, 0], [4, 4]], [[4, 4], [0, 4]], [[0, 4], [0, 0]]]}],
        "openings": [{"kind": "door", "room": "Living Room", "width_m": 0.9, "at": [2.0, 4.0], "ends": [[1.55, 4.0], [2.45, 4.0]]},
                     {"kind": "window", "room": "Living Room", "width_m": 1.0, "at": [4.0, 2.0], "ends": [[4.0, 1.5], [4.0, 2.5]]},
                     {"kind": "door", "room": "Kitchen", "width_m": 0.8, "at": [9.0, 9.0], "ends": [[8.6, 9.0], [9.4, 9.0]]}]}


def check(footprint):
    doors = [o for o in PLAN["openings"] if o["kind"] == "door" and o["room"] == "Living Room"]
    return rl.fits(footprint, rl.room_outline(PLAN, "Living Room"), doors)


def test_a_piece_inside_the_walls_and_clear_of_the_door_passes():
    got = check([[0.2, 0.2], [2.0, 0.2], [2.0, 1.1], [0.2, 1.1]])
    assert got["inside_room"] is True and got["outside_by_m"] == 0.0 and got["crosses_door"] == []
    assert got["nearest_door_m"] == pytest.approx(2.9, abs=0.01)


def test_a_piece_through_a_wall_is_reported_with_how_far():
    got = check([[3.0, 1.0], [4.3, 1.0], [4.3, 1.4], [3.0, 1.4]])
    assert got["inside_room"] is False and got["outside_by_m"] == pytest.approx(0.3, abs=0.01)
    assert got["share_outside"] == pytest.approx(0.3 / 1.3, abs=0.01)
    assert got["crosses_door"] == []                                 # in front of a window is allowed; a window is not a door


def test_a_piece_against_a_door_is_reported_and_only_this_rooms_doors_count():
    got = check([[1.8, 3.2], [2.6, 3.2], [2.6, 3.98], [1.8, 3.98]])
    assert got["inside_room"] is True and len(got["crosses_door"]) == 1 and "0.9 m door" in got["crosses_door"][0]


def test_a_failed_check_stays_in_the_layout_and_the_piece_is_not_moved():
    camera = {"e": 2.0, "n": 0.5, "z": 1.4, "h": 0.0}
    truth = [[1.6, 3.5], [2.4, 3.5], [2.4, 4.4], [1.6, 4.4]]        # a sofa pushed through the wall, right at the door
    box = {"footprint": truth, "height_m": 0.8}
    px = rv.project(rl.corners(box), camera, **VIEW)
    found = {"name": "sofa", "kind": "sofa", "look": "grey", "floor_left": list(px[0]), "floor_right": list(px[1]),
             "box": [min(p[0] for p in px), min(p[1] for p in px), max(p[0] for p in px), max(p[1] for p in px)]}
    layout = rl.build_layout({"pieces": [found], "rug": []}, camera, VIEW, PLAN, "Living Room", {})
    piece = layout["pieces"][0]
    assert np.allclose(piece["footprint"], truth, atol=0.03)         # where it was seen, not where it would fit
    assert piece["check"]["inside_room"] is False and piece["check"]["outside_by_m"] == pytest.approx(0.4, abs=0.03)
    assert piece["check"]["crosses_door"]
    assert layout["generated"] is True and "Not a photo of the building" in layout["label"]


def test_something_the_staging_did_not_change_is_part_of_the_building_not_furniture():
    sofa = seen_as("sofa", [[-0.5, 3.0], [1.1, 3.0], [1.1, 3.9], [-0.5, 3.9]], 0.8, "sofa")
    door = seen_as("other", [[-2.0, 4.0], [-1.1, 4.0], [-1.1, 4.1], [-2.0, 4.1]], 2.0, "front door")
    mask = np.zeros((VIEW["height"], VIEW["width"]), dtype=bool)
    x0, y0, x1, y1 = (int(v) for v in sofa["box"])
    mask[y0:y1, x0:x1] = True                                        # only the sofa's pixels differ from the real photo
    layout = rl.build_layout({"pieces": [door, sofa], "rug": []}, CAMERA, VIEW, None, "Living Room", {}, changed_mask=mask)
    assert [p["name"] for p in layout["pieces"]] == ["sofa"]
    assert layout["part_of_the_building"] == [{"name": "front door", "changed_share_of_its_box": 0.0}]


# ---- drawing the blocks ------------------------------------------------------------------------------------

def two_blocks():
    near = {"name": "near", "kind": "coffee_table", "footprint": [[-0.4, 2.0], [0.4, 2.0], [0.4, 2.6], [-0.4, 2.6]], "height_m": 0.5,
            "colour": {"name": "red", "rgb": [225, 35, 35]}}
    far = {"name": "far", "kind": "sofa", "footprint": [[-1.0, 3.5], [1.0, 3.5], [1.0, 4.4], [-1.0, 4.4]], "height_m": 0.9,
           "colour": {"name": "blue", "rgb": [35, 80, 225]}}
    rug = {"name": "rug", "kind": "rug", "footprint": [[-1.2, 1.6], [1.2, 1.6], [1.2, 4.0], [-1.2, 4.0]], "colour": {"name": "orange", "rgb": [245, 140, 20]}}
    return {"pieces": [near, far], "rug": rug}


def test_blocks_are_painted_farthest_first_whatever_order_they_are_listed_in():
    layout = two_blocks()
    assert [p["name"] for p in rl.draw_order(layout["pieces"], CAMERA)] == ["far", "near"]
    assert [p["name"] for p in rl.draw_order(layout["pieces"][::-1], CAMERA)] == ["far", "near"]
    behind = {"e": 0.0, "n": 7.0, "z": 1.4, "h": 180.0}              # from the other side of the room the order turns round
    assert [p["name"] for p in rl.draw_order(layout["pieces"], behind)] == ["near", "far"]


def test_a_nearer_block_hides_the_farther_one_and_both_hide_the_rug():
    layout = two_blocks()
    photo = np.full((VIEW["height"], VIEW["width"], 3), 128, dtype=np.float32)
    guide = np.asarray(rl.draw_guide(photo, layout, CAMERA, VIEW)).astype(int)
    blocks = rl.regions(layout, CAMERA, VIEW)
    # The near block's top back edge stands in front of the far block's base: that pixel must be the near block's.
    x, y = rv.project([(0.0, 2.55, 0.5)], CAMERA, **VIEW)[0]
    fx, fy = rv.project([(0.0, 3.5, 0.02)], CAMERA, **VIEW)[0]
    assert abs(fx - x) < 2 and fy > rv.project([(0.0, 2.6, 0.5)], CAMERA, **VIEW)[0][1]   # the far base is hidden behind it
    assert blocks["near"][int(fy), int(fx)] and not blocks["far"][int(fy), int(fx)]
    assert tuple(guide[int(fy), int(fx)]) == (225, 35, 35)           # red top face, not blue
    # With hidden edges drawn, the far block's base line shows through the near block as a dark line of its own colour.
    lined = np.asarray(rl.draw_guide(photo, layout, CAMERA, VIEW, hidden_edges=True)).astype(int)
    assert tuple(lined[int(round(fy + 0.6)), int(fx)]) in {(14, 32, 90)} or (np.abs(lined[int(fy) - 2:int(fy) + 4, int(fx)] - np.array([14, 32, 90])).sum(axis=-1) < 12).any()
    # No pixel belongs to two pieces, and what the guide paints is exactly what the regions say.
    assert not (blocks["near"] & blocks["far"]).any() and not (blocks["rug"] & (blocks["near"] | blocks["far"])).any()
    whole = rl.regions(layout, CAMERA, VIEW, whole=True)                # the far block's full outline, hidden part included
    assert whole["far"].sum() > blocks["far"].sum() and (whole["far"] & blocks["near"]).any() and (whole["near"] == blocks["near"]).all()
    assert blocks["far"].sum() > 0 and blocks["rug"].sum() > 0
    painted = np.abs(guide - 128).max(axis=-1) > 0
    assert (painted == (blocks["near"] | blocks["far"] | blocks["rug"])).mean() > 0.999
    # The top is the lightest face, so the block reads as a solid and not as a flat shape.
    shades = {tuple(c) for c in guide[blocks["far"]][::50]}
    assert (35, 80, 225) in shades and len(shades) >= 2
    # Outside every block the real photo is untouched.
    assert (guide[~painted] == 128).all()


def test_a_standpoint_that_stands_in_the_furniture_is_told_apart_from_one_that_sees_it():
    layout = two_blocks()
    good = rl.in_view(layout, CAMERA, VIEW)
    assert good == {"corners_in_view": 1.0, "nearest_piece_m": 2.0, "stands_on_rug": False}
    on_it = {"e": 0.0, "n": 3.0, "z": 1.4, "h": 0.0}
    bad = rl.in_view(layout, on_it, VIEW)
    assert bad["stands_on_rug"] and bad["corners_in_view"] < 1.0 and bad["nearest_piece_m"] < 0.5
    yaw, pitch = rl.aim(layout, {"e": 3.0, "n": 3.2, "z": 1.4, "h": 90.0})   # furniture due west of a camera whose face 1 looks east
    assert yaw == pytest.approx(180, abs=3) and -35 <= pitch < 0


# ---- judging -----------------------------------------------------------------------------------------------

def test_overlap_tells_a_piece_in_its_block_from_one_that_moved():
    blocks = {"sofa": np.zeros((200, 300), dtype=bool), "lamp": np.zeros((200, 300), dtype=bool)}
    blocks["sofa"][100:160, 40:140] = True
    blocks["lamp"][40:160, 200:230] = True
    changed_mask = np.zeros((200, 300), dtype=bool)
    changed_mask[100:160, 40:140] = True                              # the sofa exactly fills its block
    changed_mask[40:160, 250:280] = True                              # the lamp was drawn 50 pixels to the right of its block
    got = rl.overlap(changed_mask, blocks, ring=40)
    assert got["pieces"]["sofa"]["filled"] == 1.0 and got["pieces"]["sofa"]["around"] < 0.05
    assert got["pieces"]["lamp"]["filled"] == 0.0 and got["pieces"]["lamp"]["around"] > 0.1
    assert got["outside_all"] == pytest.approx(3600 / 9600, abs=0.001)
    assert got["pieces"]["sofa"]["block_px"] == 6000
    # a block nothing shows of (hidden or out of the picture) has no score rather than a made-up one
    blocks["hidden"] = np.zeros((200, 300), dtype=bool)
    assert rl.overlap(changed_mask, blocks)["pieces"]["hidden"] == {"block_px": 0, "filled": None, "around": None}


def test_box_agreement_between_what_was_seen_and_the_block():
    block = np.zeros((200, 300), dtype=bool)
    block[50:151, 100:201] = True
    same = rl.box_agreement([100, 50, 200, 150], block)
    assert same["overlap"] == 1.0 and same["centre_off_px"] == 0
    moved = rl.box_agreement([150, 50, 250, 150], block)
    assert moved["overlap"] == pytest.approx(1 / 3, abs=0.01) and moved["centre_off_px"] == 50
    assert rl.box_agreement(None, block) == {"overlap": None, "centre_off_px": None}


def test_left_over_block_colour_is_counted():
    layout = two_blocks()
    picture = np.full((100, 100, 3), 128, dtype=np.float32)
    assert rl.colour_leak(picture, layout) == {"near": 0, "far": 0, "rug": 0}
    picture[10:20, 10:20] = (35, 80, 225)                             # a patch of the far block's blue left behind
    picture[30:35, 30:40] = np.array((225, 35, 35)) * rl.SHADES[2]    # and some of the near block's darkest side
    assert rl.colour_leak(picture, layout) == {"near": 50, "far": 100, "rug": 0}


def test_the_room_away_from_the_furniture_is_measured_apart_from_the_furniture():
    real = np.full((200, 300, 3), 100, dtype=np.float32)
    result = real.copy()
    blocks = {"sofa": np.zeros((200, 300), dtype=bool)}
    blocks["sofa"][120:180, 100:200] = True
    result[120:180, 100:200] = 220                                    # furniture where the block was: expected
    kept = rl.structure_kept(real, result, blocks, margin=10)
    assert kept["away_from_furniture"] == 0.0 and kept["at_furniture"] > 50
    result[0:20] = 160                                                # the ceiling redrawn: the room did not survive
    assert rl.structure_kept(real, result, blocks, margin=10)["away_from_furniture"] > 5


# ---- the paid step, with a stand-in ------------------------------------------------------------------------

@pytest.fixture
def out(tmp_path, monkeypatch):
    monkeypatch.setattr(reimagine, "OUT", tmp_path / "out")
    monkeypatch.setattr(rv, "load_cube", lambda model_id, sweep_id, side=64: {f: np.full((64, 64, 3), 90 + 20 * f, dtype=np.float32) for f in range(6)})
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    first = tmp_path / "first_staged.jpg"
    Image.new("RGB", (384, 256), (150, 150, 150)).save(first)
    return tmp_path, first


class Scripted:
    def __init__(self):
        self.calls = []

    def __call__(self, images, instruction):
        self.calls.append((images, instruction))
        buf = io.BytesIO()
        Image.new("RGB", (384, 256), (200, 180, 160)).save(buf, "PNG")
        return {"image": buf.getvalue(), "provider": "scripted", "model": "stand-in", "quality": "none", "size": "384x256", "usage": None}


def small_layout():
    layout = two_blocks()
    for p in layout["pieces"]:
        p["look"] = "grey"
    return layout


def test_staging_sends_the_guide_first_then_the_first_standpoint_and_labels_everything(out):
    tmp, first = out
    service, view = Scripted(), rl.view_of(0, -15, 90, 384, 256)
    got = rl.stage_second("M", "sw", view, small_layout(), CAMERA, first, service=service)
    assert got["ok"] and not got["cached"]
    images, instruction = service.calls[0]
    assert len(images) == 2 and images[1] == first.read_bytes()
    guide = np.asarray(Image.open(io.BytesIO(images[0])).convert("RGB")).astype(int)
    assert (np.abs(guide - np.array([225, 35, 35])).sum(axis=-1) < 60).any()        # the blocks are in what was sent
    assert "the red block is the near (grey)" in instruction and "the blue block is the far (grey)" in instruction
    assert "flat orange patch on the floor is the rug" in instruction and "remove every trace" in instruction
    record = json.loads((tmp / "out" / "M").glob("*/record.json").__next__().read_text())
    assert record["generated"] is True and record["kind"] == "illustration" and "Not a photo of the building" in record["label"]
    assert record["source"]["real"] is True and record["reference"]["generated"] is True and record["guide"]["generated"] is True
    assert record["layout"]["pieces"][0]["name"] == "near" and "image" not in record["service"]
    assert set(record["output"]["faces"]) == {"0", "1", "2", "3", "4", "5"}
    assert all(reimagine.is_generated(p) for p in (record["output"]["photo"], record["guide"]["path"], *record["output"]["faces"].values()))
    # The same request again is read back, not paid for; and the ledger says which method spent it.
    again = rl.stage_second("M", "sw", view, small_layout(), CAMERA, first, service=service)
    assert again["cached"] and len(service.calls) == 1
    assert reimagine.budget()["used"] == 1 and rl.second_standpoint_generations() == 1
    verdict = rl.judge(got["folder"], small_layout(), CAMERA, view)
    assert set(verdict) == {"overlap", "block_colour_px", "structure"} and set(verdict["overlap"]["pieces"]) == {"near", "far", "rug"}


def test_the_cap_on_second_standpoint_generations_holds_and_no_key_is_a_refusal(out):
    tmp, first = out
    service, view = Scripted(), rl.view_of(0, -15, 90, 384, 256)
    for n in range(rl.SECOND_STANDPOINT_GENERATIONS_ALLOWED):
        assert rl.stage_second("M", "sw", view, small_layout(), CAMERA, first, attempt=str(n), service=service)["ok"]
    fifth = rl.stage_second("M", "sw", view, small_layout(), CAMERA, first, attempt="one more", service=service)
    assert fifth["ok"] is False and fifth["reason"]["kind"] == "budget" and len(service.calls) == rl.SECOND_STANDPOINT_GENERATIONS_ALLOWED
    monkeypatch_free = rl.stage_second("M2", "sw", view, small_layout(), CAMERA, first, attempt="other scan")
    assert monkeypatch_free["ok"] is False                           # still the cap, never a real call


def test_without_a_key_the_real_service_refuses_and_nothing_is_written(out):
    tmp, first = out
    got = rl.stage_second("M", "sw", rl.view_of(0, -15, 90, 384, 256), small_layout(), CAMERA, first)
    assert got["ok"] is False and got["reason"]["code"] == "no_key"
    assert not (tmp / "out" / "M").exists() and reimagine.budget()["used"] == 0


def test_the_camera_move_is_put_into_words_from_the_two_standpoints():
    first, second = {"e": 0.0, "n": 0.0, "z": 1.4, "h": 0.0}, {"e": -2.0, "n": 0.5, "z": 1.4, "h": 0.0}
    words = rl.camera_move(first, rl.view_of(0, -10, 100), second, rl.view_of(30, -10, 100))
    assert "2.0 m to the left" in words and "0.5 m in front of" in words and "30 degrees to the right" in words
