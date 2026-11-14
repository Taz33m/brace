"""The height model's arithmetic, on small made-up arrays. No network, no keys, no sponsor data."""
from __future__ import annotations

import json
import math
import struct
import zlib

import numpy as np
import pytest

from backend.openproblems import reconstruct as R
from tests.conftest import KX, LAT0, LON0, M, ll, rect


# --- helpers: a made-up Vexcel height file -------------------------------------------------------

def lonlat_to_mercator(lon: float, lat: float) -> tuple[float, float]:
    return (math.radians(lon) * R.EARTH_RADIUS_M,
            math.log(math.tan(math.pi / 4 + math.radians(lat) / 2)) * R.EARTH_RADIUS_M)


def geotiff(arr: np.ndarray, bounds: list[float], tile: tuple[int, int] = (16, 16), collection: str = "test-2026",
            last: str = "Fri Jan 02 18:43:55 UTC 2026") -> bytes:
    """The same kind of file the API returns: big-endian, tiled, deflate, float32, Web Mercator, with Vexcel's notes."""
    h, w = arr.shape
    tw, th = tile
    x0, y0 = lonlat_to_mercator(bounds[0], bounds[1])
    x1, y1 = lonlat_to_mercator(bounds[2], bounds[3])
    tiles = []
    for ty in range(0, h, th):
        for tx in range(0, w, tw):
            block = np.full((th, tw), -9999, dtype=">f4")
            part = arr[ty:ty + th, tx:tx + tw]
            block[:part.shape[0], :part.shape[1]] = np.where(np.isnan(part), -9999, part)
            tiles.append(zlib.compress(block.tobytes()))
    xmp = (f"<x:xmpmeta><Vexcel:product-type>dsm</Vexcel:product-type><Vexcel:collection>{collection}</Vexcel:collection>"
           f"<Vexcel:layer>urban</Vexcel:layer><Vexcel:first-capture-date>{last}</Vexcel:first-capture-date>"
           f"<Vexcel:last-capture-date>{last}</Vexcel:last-capture-date><Vexcel:min-gsd>0.07</Vexcel:min-gsd>"
           f"<Vexcel:max-gsd>0.08</Vexcel:max-gsd></x:xmpmeta>").encode()
    entries = [  # (tag, type, values)
        (256, 3, [w]), (257, 3, [h]), (258, 3, [32]), (259, 3, [32946]), (262, 3, [1]), (277, 3, [1]),
        (322, 3, [tw]), (323, 3, [th]), (324, 4, None), (325, 4, [len(t) for t in tiles]), (339, 3, [3]),
        (700, 1, list(xmp)),
        (33550, 12, [(x1 - x0) / w, (y1 - y0) / h, 0.0]),
        (33922, 12, [w / 2, h / 2, 0.0, (x0 + x1) / 2, (y0 + y1) / 2, 0.0]),  # tie point at the centre, as Vexcel does
        (34735, 3, [1, 1, 0, 2, 1024, 0, 1, 1, 3072, 0, 1, 3857]),
        (42113, 2, list(b"-9999\0")),
    ]
    fmt = {1: "B", 2: "B", 3: "H", 4: "I", 12: "d"}
    size = {1: 1, 2: 1, 3: 2, 4: 4, 12: 8}
    ifd_at = 8
    extra_at = ifd_at + 2 + 12 * len(entries) + 4
    extra = b""
    packed = {}
    for tag, typ, values in entries:      # first pass: lay out everything except the tile offsets
        if values is None:
            continue
        raw = struct.pack(">" + fmt[typ] * len(values), *values)
        packed[tag] = (len(values), raw)
    tile_table_len = 4 * len(tiles)
    sizes = sum(len(raw) for _, raw in packed.values() if len(raw) > 4) + (tile_table_len if tile_table_len > 4 else 0)
    data_at = extra_at + sizes
    offsets, at = [], data_at
    for t in tiles:
        offsets.append(at)
        at += len(t)
    packed[324] = (len(tiles), struct.pack(">" + "I" * len(tiles), *offsets))
    ifd = struct.pack(">H", len(entries))
    for tag, typ, _ in entries:
        count, raw = packed[tag]
        if len(raw) <= 4:
            ifd += struct.pack(">HHI", tag, typ, count) + raw.ljust(4, b"\0")
        else:
            ifd += struct.pack(">HHII", tag, typ, count, extra_at + len(extra))
            extra += raw
    assert extra_at + len(extra) == data_at
    return b"MM\x00\x2a" + struct.pack(">I", ifd_at) + ifd + struct.pack(">I", 0) + extra + b"".join(tiles)


# --- reading the file ---------------------------------------------------------------------------

def test_reads_tiled_float_heights_with_position_and_capture_date():
    bounds = [*ll(-80, -60), *ll(80, 60)]
    arr = np.arange(30 * 40, dtype=np.float32).reshape(30, 40)   # 30 rows by 40 columns, not a multiple of the tile
    arr[3, 5] = np.nan
    out, meta = R.read_height_tiff(geotiff(arr, bounds))
    assert out.shape == (30, 40)
    assert np.isnan(out[3, 5])
    assert np.array_equal(np.nan_to_num(out, nan=-1), np.nan_to_num(arr, nan=-1))
    assert meta["bounds"] == pytest.approx(bounds, abs=1e-9)
    assert meta["collection"] == "test-2026" and meta["last_capture"] == "2026-01-02"
    assert meta["metres_per_pixel"] == pytest.approx(4.0, rel=0.01)   # 160 m across 40 pixels
    # pixel centres: the first column sits half a pixel in from the west edge, rows run north to south
    assert meta["lons"][0] == pytest.approx(bounds[0] + (bounds[2] - bounds[0]) / 80, abs=1e-9)
    assert meta["lats"][0] > meta["lats"][-1]


def test_refuses_a_file_that_is_not_a_height_raster():
    with pytest.raises(R.ReconstructError):
        R.read_height_tiff(b"not a tiff at all")


# --- grid packing -------------------------------------------------------------------------------

def test_pack_and_unpack_keep_centimetres_and_gaps(tmp_path):
    h = np.array([[0.0, 0.004, 7.126], [np.nan, 30.5, 9999.0]], dtype=np.float32)
    packed = R.pack_heights(h)
    assert packed.dtype == np.uint16
    assert packed.tolist() == [[0, 0, 713], [R.NO_DATA, 3050, R.NO_DATA - 1]]   # too tall is capped, never wrapped
    back = R.unpack_heights(packed)
    assert back[0, 2] == pytest.approx(7.13) and np.isnan(back[1, 0])
    R.save_height_png(packed, tmp_path / "h.png")
    assert np.array_equal(R.load_height_png(tmp_path / "h.png"), packed)


def test_height_png_is_plain_8_bit_colour_a_browser_canvas_can_read(tmp_path):
    from PIL import Image
    R.save_height_png(R.pack_heights(np.array([[12.34, np.nan]], dtype=np.float32)), tmp_path / "h.png")
    with Image.open(tmp_path / "h.png") as im:
        assert im.mode == "RGB"
        r, g, b = im.getpixel((0, 0))
        assert (r * 256 + g) * 0.01 == pytest.approx(12.34) and b == 0
        assert im.getpixel((1, 0))[2] == 255   # blue flags "no data"


# --- height above ground ------------------------------------------------------------------------

def test_height_above_ground_subtracts_terrain_and_step():
    surface = np.array([[19.0, 28.0, 18.9], [np.nan, 19.0, 33.0]], dtype=np.float32)
    terrain = np.full((2, 3), 20.0, dtype=np.float32)
    h = R.height_above_ground(surface, terrain, offset_m=-1.0)   # this flight reads one metre low
    assert h[0, 0] == pytest.approx(0.0)
    assert h[0, 1] == pytest.approx(9.0)
    assert h[0, 2] == 0.0                # 10 cm below ground is noise, not a hole
    assert np.isnan(h[1, 0])             # a gap stays a gap
    assert h[1, 2] == pytest.approx(14.0)


def test_ground_offset_finds_the_step_on_open_ground_and_ignores_buildings():
    rng = np.random.default_rng(1)
    terrain = np.full((100, 100), 11.5)
    surface = terrain - 0.8 + rng.normal(0, 0.03, terrain.shape)
    surface[10:40, 10:50] += 9.0         # a building
    surface[60:70, 60:70] += rng.uniform(3, 14, (10, 10))   # trees
    step = R.ground_offset(surface, terrain)
    assert step["applied"] and step["offset_m"] == pytest.approx(-0.8, abs=0.02)
    assert 0.5 < step["share_of_cells"] < 1


def test_ground_offset_corrects_nothing_without_a_clear_ground_level():
    rng = np.random.default_rng(2)
    terrain = np.zeros((60, 60))
    step = R.ground_offset(rng.uniform(-30, 30, terrain.shape), terrain)
    assert step == {**step, "applied": False, "offset_m": 0.0}


# --- moving rasters onto the grid ---------------------------------------------------------------

def test_reduce_to_grid_keeps_the_tallest_point_of_each_cell():
    src = np.array([[1, 2, 3, 4], [5, 6, 7, 8], [9, 10, 11, 12], [13, 14, np.nan, np.nan]], dtype=np.float32)
    bounds = [0.0, 0.0, 4.0, 4.0]
    lons, lats = R.grid_axes(bounds, 4, 4)
    assert R.reduce_to_grid(src, lons, lats, bounds, 2, 2, "max").tolist() == [[6, 8], [14, 12]]
    assert R.reduce_to_grid(src, lons, lats, bounds, 2, 2, "min").tolist() == [[1, 3], [9, 11]]
    assert R.reduce_to_grid(src, lons, lats, bounds, 2, 2, "mean").tolist() == [[3.5, 5.5], [11.5, 11.5]]
    # a cell no source pixel falls in is left empty, not invented
    assert np.isnan(R.reduce_to_grid(src[:, :2], lons[:2], lats, bounds, 2, 2, "max")[:, 1]).all()


def test_sample_bilinear_reads_a_sloping_plane_exactly():
    bounds = [0.0, 0.0, 10.0, 6.0]
    lons, lats = R.grid_axes(bounds, 6, 10)
    plane = (2 * lons[None, :] + 3 * lats[:, None]).astype(np.float32)
    want_lons, want_lats = R.grid_axes([2.0, 1.0, 8.0, 5.0], 5, 7)
    got = R.sample_bilinear(plane, lons, lats, want_lons, want_lats)
    assert got == pytest.approx(2 * want_lons[None, :] + 3 * want_lats[:, None], abs=1e-4)


def test_shaded_relief_lights_the_north_west_side():
    flat = R.shaded_relief(np.zeros((5, 5)), 1.0, 1.0)
    assert flat == pytest.approx(math.sin(math.radians(45)))
    col, row = np.meshgrid(np.arange(20), np.arange(20))
    faces_nw = R.shaded_relief((col + row).astype(float), 1.0, 1.0)      # rises to the south-east, so it faces north-west
    faces_se = R.shaded_relief((-col - row).astype(float), 1.0, 1.0)
    assert faces_nw[10, 10] > flat[2, 2] > faces_se[10, 10]


# --- roofs and their neighbours -----------------------------------------------------------------

def _site_grid():
    """A 100 m by 80 m site at half-metre cells, flat, in the test fixture's lon/lat frame."""
    bounds = [*ll(-50, -40), *ll(50, 40)]
    rows, cols = 160, 200

    def cells(x0, y0, x1, y1):   # metres east/north of the centre to a (rows, cols) slice
        return (slice(int((40 - y1) / 0.5), int((40 - y0) / 0.5)), slice(int((x0 + 50) / 0.5), int((x1 + 50) / 0.5)))
    return bounds, np.zeros((rows, cols), dtype=np.float32), cells


def test_roof_height_and_tallest_object_near_each_structure():
    bounds, h, cells = _site_grid()
    h[cells(-30, -10, -10, 10)] = 9.0            # building A, 20 m square
    h[cells(-4, -2, -2, 0)] = 14.0               # a 2 m wide tree, 6 m east of A's wall
    h[cells(-9.5, 12, -3, 20)] = 15.0            # building B, taller, also within 10 m of A
    h[cells(30, 20, 32, 22)] = 30.0              # something very tall but far from both
    structures = [{"id": "A", "polygon": rect(-30, -10, -10, 10)}, {"id": "C", "polygon": rect(20, -30, 40, -20)}]
    h[cells(20, -30, 40, -20)] = 4.0             # building C with nothing tall around it
    h[cells(42, -26, 44, -24)] = 1.6             # a parked van near C: too low to count
    terrain = np.full(h.shape, 11.5, dtype=np.float32)
    rows = R.summarise_structures(h, bounds, structures, other_footprints=[rect(-9.5, 12, -3, 20)], terrain=terrain)
    a, c = rows
    assert a["roof_height_m"] == pytest.approx(9.0) and a["roof_ridge_m"] == pytest.approx(9.0)
    assert a["ground_elevation_m"] == pytest.approx(11.5)
    tall = a["tallest_nearby"]
    assert tall["height_m"] == pytest.approx(14.0)          # the tree, not the taller neighbouring roof
    assert tall["overtops_roof"] and tall["above_roof_m"] == pytest.approx(5.0)
    assert 5.5 <= tall["distance_to_wall_m"] <= 8.5
    east = (tall["lon"] - LON0) * KX
    north = (tall["lat"] - LAT0) * M
    assert -4.5 <= east <= -1.5 and -2.5 <= north <= 0.5    # reported where the tree stands
    assert a["area_above_roof_within_near_sqm"] == pytest.approx(4.0, abs=1.5)   # the tree's 2 m by 2 m crown
    assert c["roof_height_m"] == pytest.approx(4.0)
    assert c["tallest_nearby"] is None and c["area_above_roof_within_near_sqm"] == 0.0


def test_a_roofs_own_edge_is_never_reported_as_its_tall_neighbour():
    bounds, h, cells = _site_grid()
    h[cells(-30.5, -10.5, -9.5, 10.5)] = 9.0     # the measured roof spills half a metre past the drawn footprint
    rows = R.summarise_structures(h, bounds, [{"id": "A", "polygon": rect(-30, -10, -10, 10)}])
    assert rows[0]["tallest_nearby"] is None


def test_aerial_colour_is_passed_through_as_a_hint_only():
    bounds, h, cells = _site_grid()
    h[cells(-30, -10, -10, 10)] = 9.0
    h[cells(-4, -2, -2, 0)] = 14.0
    colours = np.full((*h.shape, 3), 90, dtype=np.uint8)
    colours[cells(-4, -2, -2, 0)] = (40, 110, 50)
    tall = R.summarise_structures(h, bounds, [{"id": "A", "polygon": rect(-30, -10, -10, 10)}], colours=colours)[0]["tallest_nearby"]
    assert tall["aerial_rgb"] == [40, 110, 50] and tall["aerial_looks_green"] is True


# --- Matterport asset listings ------------------------------------------------------------------

def test_scan_asset_summary_says_plainly_what_exists():
    plain = {"id": "a", "name": "Unit", "views": [{"type": "matterport.model.layered"}],
             "splat": {"availability": "unavailable", "assets": []},
             "pak": {"availability": "unlocked", "assets": [{"format": "zip", "status": "available"}]},
             "e57": {"availability": "unavailable", "assets": []},
             "assets": {"meshes": [{"format": "obj", "resolution": "50k", "status": "available"}]}}
    s = R.summarise_scan_assets(plain)
    assert s["matterpak"] and not s["exterior_splat"] and not s["e57_point_cloud"]
    assert s["meshes"] == ["obj 50k (available)"]
    with_splat = {**plain, "views": plain["views"] + [{"type": R.EXTERIOR_VIEW}]}
    assert R.summarise_scan_assets(with_splat)["exterior_splat"]
    locked = {**plain, "pak": {"availability": "locked", "assets": [{"format": "zip", "status": "locked"}]}}
    assert not R.summarise_scan_assets(locked)["matterpak"]


def test_sweeps_are_checked_against_the_point_cloud_frame():
    rng = np.random.default_rng(3)
    floor = np.column_stack([rng.uniform(0, 6, 20000), rng.uniform(0, 4, 20000), np.zeros(20000)])
    ceiling = floor + [0, 0, 2.4]
    outside = np.column_stack([rng.uniform(8, 14, 5000), rng.uniform(0, 4, 5000), rng.uniform(0, 3, 5000)])
    cloud = np.vstack([floor, ceiling, outside]).astype(np.float32)
    model = {"sweeps": [{"x": 2.0, "y": 2.0, "z": 1.4, "has_pano": True}, {"x": 4.0, "y": 1.0, "z": 1.4, "has_pano": True}],
             "rooms": [{"polygon": [[0, 0], [6, 0], [6, 4], [0, 4], [0, 0]]}]}
    f = R.relate_to_sweeps(model, cloud, None)
    assert f["sweeps"] == 2 and f["sweeps_inside_geometry_box"] == 2
    assert f["floor_z_m"] == pytest.approx(0.0, abs=0.05)
    assert f["camera_height_above_floor_m"] == pytest.approx(1.4, abs=0.05)
    assert f["share_outside_room_outlines"] == pytest.approx(5000 / 45000, abs=0.01)
    assert 6.5 <= f["outside_points_reach_m"] <= 8.0


# --- the whole thing, with the sponsor API replaced by made-up files -------------------------------

class _Reply:
    def __init__(self, status: int, content: bytes = b"", payload: dict | None = None):
        self.status_code, self.content, self._payload = status, content, payload
        self.is_success = 200 <= status < 300
        self.text = ""

    def json(self):
        return self._payload


def test_site_heights_end_to_end_without_network(site, tmp_path, monkeypatch):
    monkeypatch.setattr(R, "OUT", tmp_path / "open")
    monkeypatch.setattr(R, "BUILDINGS_DIR", tmp_path)
    monkeypatch.setattr(R, "_all_footprints", lambda bundle: [])
    bounds = site.bounds                                    # 160 m by 120 m, structures S1 and S2
    calls = []

    def raster(width, height, surface: bool):
        x = (np.arange(width) + 0.5) / width * 160 - 80     # metres east of the centre
        y = 60 - (np.arange(height) + 0.5) / height * 120   # metres north of the centre
        xx, yy = np.meshgrid(x, y)
        ground = np.full((height, width), 20.0, dtype=np.float32)
        if not surface:
            return ground
        out = ground - 1.0                                  # this flight reads a metre lower than the terrain flight
        out[(xx > -60) & (xx < 0) & (yy > -30) & (yy < 30)] += 9.0     # S1
        out[(xx > 20) & (xx < 60) & (yy > -20) & (yy < 20)] += 4.0     # S2
        out[(xx > 5) & (xx < 8) & (yy > 0) & (yy < 3)] += 13.0         # a tree between them, 5 m from S1
        return out

    def fake_send(method, path, *, params=None, body=None, timeout=300):
        calls.append(path)
        kind = path.split("/")[0]
        if path.endswith("/collections"):
            name = "urban-2026" if kind == "dsm" else "wide-2025"
            day = "2026-01-02T18:43:55" if kind == "dsm" else "2025-02-01T10:00:00"
            return _Reply(200, payload={"features": [{"properties": {
                "collection": name, "layer": "urban", "product-type": kind, "first-capture-date": day,
                "last-capture-date": day, "min-gsd": 0.07, "max-gsd": 0.08}}]})
        w, h = (int(v) for v in body["destination-dimensions"].split(","))
        assert body["collection"] == ("urban-2026" if kind == "dsm" else "wide-2025")
        return _Reply(200, content=geotiff(raster(w, h, kind == "dsm"), bounds, tile=(128, 128), collection=body["collection"]))

    monkeypatch.setattr(R.vexcel, "_send", fake_send)
    out = R.site_heights(7)
    assert out["available"] and out["capture_date"] == "2026-01-02"
    assert (out["cols"], out["rows"]) == (320, 240) and out["metres_per_cell"] == pytest.approx(0.5, abs=0.01)
    assert out["bounds"] == bounds and out["texture_bounds"] == bounds
    assert out["source"]["surface"]["collection"] == "urban-2026" and out["source"]["terrain"]["collection"] == "wide-2025"
    assert out["source"]["step_between_flights"]["offset_m"] == pytest.approx(-1.0, abs=0.02)
    by_id = {s["id"]: s for s in out["structures"]}
    assert by_id["S1"]["roof_height_m"] == pytest.approx(9.0, abs=0.05)
    assert by_id["S2"]["roof_height_m"] == pytest.approx(4.0, abs=0.05)
    tall = by_id["S1"]["tallest_nearby"]
    assert tall["height_m"] == pytest.approx(13.0, abs=0.05) and tall["overtops_roof"]
    assert 4.0 <= tall["distance_to_wall_m"] <= 8.5
    grid = R.unpack_heights(R.load_height_png(out["heights_png"]))
    assert grid.shape == (240, 320) and float(np.nanmax(grid)) == pytest.approx(13.0, abs=0.05)
    assert (tmp_path / "open" / "7" / "proof_relief.jpg").exists() and out["proof_side_by_side"]
    # a second run reads the saved answer and asks the sponsor nothing
    before = len(calls)
    assert R.site_heights(7)["rows"] == 240 and len(calls) == before
    assert json.loads((tmp_path / "open" / "7" / "heights.json").read_text())["available"]


def test_site_heights_says_so_when_vexcel_has_no_height_model(site, tmp_path, monkeypatch):
    monkeypatch.setattr(R, "OUT", tmp_path / "open")
    monkeypatch.setattr(R, "BUILDINGS_DIR", tmp_path)
    monkeypatch.setattr(R.vexcel, "_send", lambda *a, **k: _Reply(404))
    out = R.site_heights(7)
    assert out["available"] is False and "surface model" in out["reason"]
    assert not (tmp_path / "open" / "7" / "heights.png").exists()   # nothing is made up in its place
