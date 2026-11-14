"""Furnishing a room again: what stood where comes from the scan, each new piece from a text-to-3D service, once."""
import json

import pytest

from backend.openproblems import furnish3d as f


@pytest.fixture
def room(tmp_path, monkeypatch):
    monkeypatch.setattr(f, "OUT", tmp_path)
    monkeypatch.setattr(f, "MODELS", tmp_path / "models")
    folder = tmp_path / "SCAN" / "pos"
    folder.mkdir(parents=True)
    def piece(name, look, e, n, w, d, h):
        return {"name": name, "kind": name.split()[-1], "look": look, "width_m": w, "depth_m": d, "height_m": h,
                "footprint": [[e - w / 2, n - d / 2], [e + w / 2, n - d / 2], [e + w / 2, n + d / 2], [e - w / 2, n + d / 2]]}
    (folder / "layout.json").write_text(json.dumps({
        "room": "Living Room", "source": {"sweep_id": "pos"}, "standpoint": {"e": 0, "n": 0, "z": 1.4, "h": 60.0}, "view": {"yaw_deg": 245},
        "note": "read from the scan", "pieces": [piece("blue sofa", "navy upholstered loveseat", -3.2, 3.8, 2.0, 0.9, 0.85),
                                                  piece("left side table", "grey round top", -4.2, 2.9, 0.55, 0.5, 0.67),
                                                  piece("left table lamp", "navy ceramic base with white drum shade", -6.2, 3.9, 0.67, 0.4, 1.24)]}))
    return "SCAN"


class Service:
    """Stands in for the text-to-3D service: a preview task, a refine task, then a file."""
    def __init__(self, fail=False):
        self.posts, self.fail = [], fail
    def post(self, url, headers=None, json=None):
        self.posts.append(json)
        return type("R", (), {"status_code": 200, "json": lambda s: {"result": f"task{len(self.posts)}"}})()
    def get(self, url, headers=None):
        if url.endswith(".glb"):
            return type("R", (), {"status_code": 200, "content": b"glTF-binary"})()
        status = "FAILED" if self.fail else "SUCCEEDED"
        return type("R", (), {"status_code": 200, "json": lambda s: {"id": url.rsplit("/", 1)[1], "status": status, "model_urls": {"glb": "https://files.example/model.glb"}}})()
    def close(self):
        pass


def test_the_request_describes_one_piece_as_it_looked(room):
    scene = f.scene(room)
    assert scene["contents"] == 3 and scene["models_made"] == 0 and scene["room"] == "Living Room"
    assert scene["pieces"][0]["prompt"] == "blue sofa, navy upholstered loveseat. A single piece of home furniture on its own, nothing else in the scene."
    assert "Not a photo of the building" in scene["labels"]["furnished"] and "not a photograph" in scene["labels"]["cleared"]


def test_a_table_lamp_stands_on_its_table_not_on_the_floor(room):
    sofa, table, lamp = f.scene(room)["pieces"]
    assert sofa["stands_on_m"] == 0.0
    assert (lamp["east_m"], lamp["north_m"]) == (table["east_m"], table["north_m"]) and lamp["stands_on"] == "left side table"
    assert lamp["stands_on_m"] == 0.67 and lamp["height_m"] == pytest.approx(0.57)


def test_a_model_is_made_once_and_counted(room, monkeypatch):
    monkeypatch.setenv(f.KEY_ENV, "test-key")
    service = Service()
    prompt = f.scene(room)["pieces"][0]["prompt"]
    path = f.generate(prompt, client=service, sleep=lambda s: None)
    assert path.read_bytes() == b"glTF-binary" and f.generations() == 1
    assert [p["mode"] for p in service.posts] == ["preview", "refine"] and service.posts[0]["prompt"] == prompt and service.posts[1]["preview_task_id"] == "task1"
    assert json.loads(path.with_suffix(".json").read_text())["generated"] is True
    f.generate(prompt, client=service, sleep=lambda s: None)                       # the same words again: no new request, no new charge
    assert len(service.posts) == 2 and f.generations() == 1
    assert f.scene(room)["models_made"] == 1 and f.scene(room)["pieces"][0]["model"] == f.model_key(prompt)


def test_nothing_is_made_without_a_key_or_past_the_limit(room, monkeypatch):
    monkeypatch.delenv(f.KEY_ENV, raising=False)
    with pytest.raises(f.Furnish3dError, match="no text-to-3D key"):
        f.generate("a chair", client=Service(), sleep=lambda s: None)
    assert f.scene(room)["can_generate"] is False
    monkeypatch.setenv(f.KEY_ENV, "test-key")
    monkeypatch.setattr(f, "MAX_MODELS", 0)
    with pytest.raises(f.Furnish3dError, match="limit"):
        f.generate("a chair", client=Service(), sleep=lambda s: None)


def test_furnishing_stops_at_the_first_failure_and_says_so(room, monkeypatch):
    monkeypatch.setenv(f.KEY_ENV, "test-key")
    got = f.furnish(room, client=Service(fail=True), sleep=lambda s: None)
    assert got["made"] == [] and "did not finish the model" in got["stopped"] and got["scene"]["models_made"] == 0
