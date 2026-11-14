"""The ground under each structure comes from the terrain model, as measured, or not at all."""
import json

from backend import site_model


def write(tmp_path, structures):
    d = tmp_path / "reconstruct" / "7"
    d.mkdir(parents=True)
    (d / "heights.json").write_text(json.dumps({"structures": structures, "source": {"terrain": {"first_capture": "2025-01-31", "last_capture": "2025-03-05"}}}))


def test_the_lowest_structures_are_named_with_how_far_below_the_highest_they_stand(tmp_path, monkeypatch):
    monkeypatch.setattr(site_model, "OPEN", tmp_path)
    write(tmp_path, [{"id": "S1", "ground_elevation_m": 9.7}, {"id": "S2", "ground_elevation_m": 10.3}, {"id": "S3", "ground_elevation_m": 9.9},
                     {"id": "S4", "ground_elevation_m": 10.1}, {"id": "S5"}])
    got = site_model.ground(7)
    assert [x["id"] for x in got["lowest"]] == ["S1", "S3", "S4"] and got["lowest"][0]["below_highest_m"] == 0.6
    assert got["highest"] == {"id": "S2", "elevation_m": 10.3} and got["spread_m"] == 0.6 and got["structures"] == 4
    assert got["source"] == "Vexcel terrain model (bare ground), flown 2025-01-31 to 2025-03-05"


def test_no_terrain_model_or_one_structure_says_nothing(tmp_path, monkeypatch):
    monkeypatch.setattr(site_model, "OPEN", tmp_path)
    assert site_model.ground(7) is None
    write(tmp_path, [{"id": "S1", "ground_elevation_m": 9.7}])
    assert site_model.ground(7) is None
