"""Resident uploads and protected media."""
from __future__ import annotations

from io import BytesIO

import pytest
from PIL import Image

from backend.recovery.platform import uploads
from tests.test_recovery_platform_api import (REPORT, app, invite, owner_client,  # noqa: F401 (fixtures)
                                              resident_client, store, world)


def png_bytes(size=(64, 48)) -> bytes:
    buf = BytesIO()
    Image.new("RGB", size, (200, 30, 30)).save(buf, "PNG")
    return buf.getvalue()


def jpeg_with_gps() -> bytes:
    img = Image.new("RGB", (80, 60), (10, 120, 200))
    exif = Image.Exif()
    exif[0x010F] = "SyntheticCam"
    gps = exif.get_ifd(0x8825)
    gps[1], gps[2] = "N", (40.0, 21.0, 0.0)
    buf = BytesIO()
    img.save(buf, "JPEG", exif=exif)
    return buf.getvalue()


def upload(client, data: bytes, key="upload-key-1", name="photo.png", ctype="image/png"):
    return client.post("/api/resident/uploads", files={"file": (name, data, ctype)},
                       headers={"Idempotency-Key": key})


@pytest.fixture
def phones(app, world):
    ha, hb, _, _ = world
    owner = owner_client(app)
    return owner, resident_client(app, invite(owner, ha)), resident_client(app, invite(owner, hb))


def test_valid_png_upload_returns_protected_media_ref(phones):
    _, a, _ = phones
    r = upload(a, png_bytes())
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["upload_id"] and body["media"]["url"] == f"/api/recovery/media/{body['media']['media_id']}"
    assert body["media"]["mime_type"] == "image/jpeg"
    got = a.get(body["media"]["url"])
    assert got.status_code == 200 and got.headers["content-type"] == "image/jpeg"
    assert Image.open(BytesIO(got.content)).size == (64, 48)


def test_upload_retry_with_same_key_returns_same_upload(phones):
    _, a, _ = phones
    data = png_bytes()
    first, again = upload(a, data).json(), upload(a, data).json()
    assert first["upload_id"] == again["upload_id"]
    assert upload(a, png_bytes((10, 10))).status_code == 409


def test_non_image_rejected_even_with_image_name(phones):
    _, a, _ = phones
    r = upload(a, b"hello, this is text", name="photo.jpg", ctype="image/jpeg")
    assert r.status_code == 422 and r.json()["error"]["code"] == "unsupported_media"


def test_unsupported_image_format_rejected(phones):
    _, a, _ = phones
    buf = BytesIO()
    Image.new("RGB", (8, 8)).save(buf, "BMP")
    assert upload(a, buf.getvalue(), name="x.bmp", ctype="image/bmp").status_code == 422


def test_oversized_upload_is_413(phones, monkeypatch):
    _, a, _ = phones
    monkeypatch.setattr(uploads, "MAX_UPLOAD_BYTES", 2_000)
    r = upload(a, png_bytes((400, 400)) + b"\0" * 5_000)
    assert r.status_code == 413 and r.json()["error"]["code"] == "upload_too_large"


def test_missing_file_part_is_422(phones):
    _, a, _ = phones
    r = a.post("/api/resident/uploads", files={"other": ("x.png", png_bytes(), "image/png")},
               headers={"Idempotency-Key": "upload-key-1"})
    assert r.status_code == 422


def test_display_copy_has_no_exif_location(phones, store):
    _, a, _ = phones
    original = jpeg_with_gps()
    assert Image.open(BytesIO(original)).getexif().get_ifd(0x8825)  # the fixture really has GPS
    media = upload(a, original, name="p.jpg", ctype="image/jpeg").json()["media"]
    served = a.get(media["url"]).content
    exif = Image.open(BytesIO(served)).getexif()
    assert not exif.get_ifd(0x8825) and 0x8825 not in exif and b"SyntheticCam" not in served


def test_other_resident_cannot_fetch_media(phones):
    _, a, b = phones
    media = upload(a, png_bytes()).json()["media"]
    assert b.get(media["url"]).status_code == 404


def test_owner_can_fetch_resident_media(phones):
    owner, a, _ = phones
    media = upload(a, png_bytes()).json()["media"]
    assert owner.get(media["url"]).status_code == 200


def test_media_requires_session_and_rejects_traversal(app, phones):
    from fastapi.testclient import TestClient

    _, a, _ = phones
    media = upload(a, png_bytes()).json()["media"]
    assert TestClient(app).get(media["url"]).status_code == 401
    for bad in ("..%2F..%2Frecovery.db", "med_..", "med_" + "0" * 20):
        assert a.get(f"/api/recovery/media/{bad}").status_code == 404


def test_report_attaches_own_upload_and_owner_sees_photo_evidence(phones):
    owner, a, _ = phones
    up = upload(a, png_bytes()).json()
    r = a.post("/api/resident/reports", json={**REPORT, "upload_ids": [up["upload_id"]]},
               headers={"Idempotency-Key": "report-key-1"})
    assert r.status_code == 200, r.text
    assert [m["media_id"] for m in r.json()["report"]["media"]] == [up["media"]["media_id"]]
    view = owner.get("/api/recovery/cases/case_test").json()
    photo = [e for e in view["evidence"] if e["kind"] == "resident_photo"]
    assert len(photo) == 1 and photo[0]["media"]["media_id"] == up["media"]["media_id"]
    assert photo[0]["captured_at"] is None
    assert view["observations"][0]["evidence_ids"] == [photo[0]["evidence_id"]]


def test_cannot_attach_other_households_upload_or_reuse_one(phones):
    _, a, b = phones
    up = upload(a, png_bytes()).json()
    r = b.post("/api/resident/reports", json={**REPORT, "upload_ids": [up["upload_id"]]},
               headers={"Idempotency-Key": "report-key-1"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "upload_unavailable"
    ok = a.post("/api/resident/reports", json={**REPORT, "upload_ids": [up["upload_id"]]},
                headers={"Idempotency-Key": "report-key-2"})
    assert ok.status_code == 200
    again = a.post("/api/resident/reports", json={**REPORT, "text": "second", "upload_ids": [up["upload_id"]]},
                   headers={"Idempotency-Key": "report-key-3"})
    assert again.status_code == 422


def test_owner_cannot_upload_as_resident(phones):
    owner, _, _ = phones
    assert upload(owner, png_bytes()).status_code == 401
