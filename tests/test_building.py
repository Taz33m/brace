import pytest

from backend import building
from tests.conftest import ll


@pytest.mark.parametrize("name,expected", [
    ("Suite 1280 - 2,108 SF", ("suite", 12)),
    ("Suite 230", ("suite", 2)),
    ("5380 Alhambra Ave - 2nd Floor", ("suite", 2)),
    ("Fitness Center", ("shared space", None)),
    ("Leasing Office", ("shared space", None)),
    ("1BR, 1BA - 811SF", ("apartment unit", None)),
    ("Studio - 476SF", ("apartment unit", None)),
    ("Warehouse Space - 1281SF", ("warehouse", 1)),
    ("10880 Wilshire", ("space", None)),
    (None, ("space", None)),
])
def test_classify_scan(name, expected):
    assert building.classify_scan(name) == expected


def test_grid_round_trip_and_orientation(site):
    assert site.cell_of(*site.cell_center("A1")) == "A1"
    assert site.cell_of(*site.cell_center("h6")) == "H6"
    (lon_a, lat_1), (lon_h, lat_6) = site.cell_center("A1"), site.cell_center("H6")
    assert lon_a < lon_h and lat_1 > lat_6        # columns run west to east, rows north to south
    with pytest.raises(ValueError):
        site.parse_cell("Z9")


def test_structure_lookup(site):
    assert site.structure_at(*ll(-30, 0))["id"] == "S1"
    assert site.structure_at(*ll(40, 0))["id"] == "S2"
    assert site.structure_at(*ll(1.5, 0))["id"] == "S1"   # just outside the wall still counts as beside it
    assert site.structure_at(*ll(10, 50)) is None


def test_face_for_compass_and_missing_heading(site):
    assert site.face_for("SCAN1", "w1", "east") == (1, 90.0)
    assert site.face_for("SCAN1", "w1", "south") == (2, 180.0)
    assert site.face_for("SCAN1", "w2", "north") == (1, 0.0)
    assert site.face_for("SCAN1", "w1", "up") == (0, None)
    site.scans["SCAN1"]["sweeps"][0]["heading"] = None
    assert site.face_for("SCAN1", "w1", "west") == (4, None)  # no compass fix: a stable guess, flagged by the None bearing


def test_render_and_crop(site):
    assert site.render_aerial().size == (800, 600)
    crop = site.render_aerial(grid=False, markers=[{"lon": ll(0, 0)[0], "lat": ll(0, 0)[1]}], crop_cell="D3")
    assert max(crop.size) >= 900 and crop.size != (800, 600)
