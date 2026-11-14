"""Vexcel request/cache behavior with synthetic metadata; no sponsor API calls."""
import json
from types import SimpleNamespace

import pytest

from backend import vexcel


AREA = "POINT(-95 29)"


def response(properties, status=200):
    return SimpleNamespace(status_code=status, is_success=status == 200, text="unsupported include",
                           json=lambda: {"features": [{"properties": item} for item in properties]})


def test_capture_layers_are_isolated_and_unfiltered_search_preserves_windows_and_precision(tmp_path, monkeypatch):
    monkeypatch.setattr(vexcel, "VX_CACHE", tmp_path)
    calls = []

    def send(*args, **kwargs):
        calls.append(kwargs["params"])
        return response([
            {"collection": "fine", "layer": kwargs["params"]["layer"], "min-gsd": .1200001,
             "max-gsd": .23456789, "graysky-event": "test-storm", "first-capture-date": "2024-07-07T14:12:31Z",
             "last-capture-date": "2024-07-09T18:43:55Z", "first-publish-date": "2024-07-10",
             "last-publish-date": "2024-07-11"},
            {"collection": "coarse", "min-gsd": .8, "last-capture-date": "2024-07-12"},
            {"collection": "unknown-gsd", "last-capture-date": "2024-07-13"},
            {"collection": "undated", "min-gsd": .2},
        ])

    monkeypatch.setattr(vexcel, "_send", send)
    rows = vexcel.captures(AREA, max_gsd=None, layers="graysky", thin=False)
    assert len(rows) == 4
    fine = next(row for row in rows if row["collection"] == "fine")
    assert (fine["first_date"], fine["last_date"], fine["date"]) == ("2024-07-07", "2024-07-09", "2024-07-09")
    assert fine["first_capture"] == "2024-07-07T14:12:31Z"
    assert fine["last_capture"] == "2024-07-09T18:43:55Z"
    assert fine["gsd"] == fine["min_gsd"] == .1200001
    assert fine["max_gsd"] == .23456789 and fine["graysky_event"] == "test-storm"
    assert fine["first_publish"] == "2024-07-10" and fine["last_publish"] == "2024-07-11"
    assert next(row for row in rows if row["collection"] == "unknown-gsd")["gsd"] is None
    assert calls[0]["layer"] == "graysky" and "first-capture-date" in calls[0]["include"]
    assert vexcel.captures(AREA, layers="graysky", thin=False, cached_only=True) == [], "Do not round GSD below the filter boundary"
    assert vexcel.captures(AREA, max_gsd=None, thin=False, cached_only=True) == [], "Default layers must not reuse graysky results"
    assert len(vexcel.captures(AREA, max_gsd=None, thin=False)) == 4
    assert calls[-1]["layer"] == vexcel.VEXCEL_LAYERS and len(calls) == 2
    assert len(list((tmp_path / "captures_v2").glob("*.json"))) == 2


def test_catalog_rejecting_publication_metadata_falls_back_without_inventing_dates(tmp_path, monkeypatch):
    monkeypatch.setattr(vexcel, "VX_CACHE", tmp_path)
    calls = []

    def send(*args, **kwargs):
        calls.append(kwargs["params"])
        if "first-publish-date" in kwargs["params"]["include"]:
            return response([], 422)
        return response([{"collection": "storm", "last-capture-date": "2024-07-09", "min-gsd": .1}])

    monkeypatch.setattr(vexcel, "_send", send)
    row = vexcel.captures(AREA, layers="graysky", thin=False)[0]
    assert len(calls) == 2 and all(call["layer"] == "graysky" for call in calls)
    assert row["first_date"] is None and row["first_publish"] is None and row["last_publish"] is None
    assert row["last_date"] == row["date"] == "2024-07-09"


def test_existing_default_v2_capture_cache_is_reused_without_inventing_window(tmp_path, monkeypatch):
    monkeypatch.setattr(vexcel, "VX_CACHE", tmp_path)
    path = tmp_path / "captures_v2" / f"{vexcel._key(AREA, vexcel.VEXCEL_LAYERS)}.json"
    path.parent.mkdir()
    old = [{"collection": "legacy", "date": "2024-07-09", "layer": "urban", "gsd": .1}]
    path.write_text(json.dumps(old))
    monkeypatch.setattr(vexcel, "_send", lambda *a, **k: pytest.fail("cache attempted a network call"))
    assert vexcel.captures(AREA, thin=False) == old
    assert vexcel.captures(AREA, layers="graysky", cached_only=True) == []


def xmp_image():
    fields = {"collection": "storm", "first-capture-date": "Sun Jul 07 14:12:31 UTC 2024",
              "last-capture-date": "Tue Jul 09 18:43:55 UTC 2024", "first-publish-date": "2024-07-10",
              "last-publish-date": "2024-07-11", "layer": "graysky", "graysky-event": "test-storm",
              "min-gsd": "0.123456789", "max-gsd": "0.234567891", "product-type": "ortho",
              "geometry": "POLYGON((-95 29,-94 29,-94 30,-95 30,-95 29))"}
    return ("<x:xmpmeta>" + "".join(f"<Vexcel:{key}>{value}</Vexcel:{key}>" for key, value in fields.items()) + "</x:xmpmeta>").encode()


@pytest.mark.parametrize("has_metadata", [True, False])
def test_old_image_metadata_is_upgraded_locally_without_altering_image(tmp_path, monkeypatch, has_metadata):
    monkeypatch.setattr(vexcel, "VX_CACHE", tmp_path)
    body = {"wkt": AREA, "layer": "graysky", "collection": "storm"}
    image = tmp_path / "images" / f"{vexcel._key('ortho/extract', body)}.jpg"
    meta = image.with_suffix(".json")
    image.parent.mkdir()
    original = xmp_image()
    image.write_bytes(original)
    if has_metadata:
        meta.write_text(json.dumps({"collection": "storm", "product": "ortho"}))
    monkeypatch.setattr(vexcel, "_send", lambda *a, **k: pytest.fail("upgrade attempted a network call"))
    path, info = vexcel._image("ortho/extract", body)
    assert path == image and path.read_bytes() == original
    assert info["first_date"] == "2024-07-07" and info["last_date"] == "2024-07-09"
    assert info["first_publish"] == "2024-07-10" and info["last_publish"] == "2024-07-11"
    assert info["layer"] == "graysky" and info["graysky_event"] == "test-storm"
    assert info["min_gsd"] == "0.123456789" and info["max_gsd"] == "0.234567891"
    assert info["bounds"] == [-95, 29, -94, 30]
    assert json.loads(meta.read_text()) == info


def test_ortho_layers_are_in_request_and_image_cache_identity(tmp_path, monkeypatch):
    monkeypatch.setattr(vexcel, "VX_CACHE", tmp_path)
    calls = []

    def send(*args, **kwargs):
        calls.append(kwargs["body"])
        return SimpleNamespace(is_success=True, status_code=200, content=xmp_image())

    monkeypatch.setattr(vexcel, "_send", send)
    default, _ = vexcel.ortho(AREA, collection="storm")
    disaster, info = vexcel.ortho(AREA, collection="storm", layers="graysky")
    assert default != disaster and len(calls) == 2
    assert calls[0]["layer"] == vexcel.VEXCEL_LAYERS and calls[1]["layer"] == "graysky"
    assert info["first_date"] != info["last_date"]
    assert vexcel.ortho(AREA, collection="storm", layers="graysky")[0] == disaster
    assert len(calls) == 2
