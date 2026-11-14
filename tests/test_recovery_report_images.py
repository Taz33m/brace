"""Resident images join sponsor views without using report URLs or widening case access."""
import base64
from copy import deepcopy
from io import BytesIO
import struct
import zlib

import pytest
from PIL import Image

from backend.recovery.report_images import MAX_IMAGE_BYTES, ReportImageError, with_report_images


def photo_bytes(size=(40, 20), *, exif=False):
    output = BytesIO()
    image = Image.new("RGB", size, (35, 80, 120))
    if exif:
        metadata = Image.Exif()
        metadata[0x010E] = "Private resident description"
        metadata[0x0112] = 6
        image.save(output, "JPEG", exif=metadata)
    else:
        image.save(output, "PNG")
    return output.getvalue()


def snapshot(case_id="case-A", media_id="med_A"):
    return {"case": {"case_id": case_id, "analysis_revision": 3},
            "evidence": [{"evidence_id": "sponsor", "kind": "vexcel_image", "source_id": "vexcel:one"},
                         {"evidence_id": "resident", "kind": "resident_photo", "source_id": media_id,
                          "media": {"media_id": media_id, "url": "https://untrusted.invalid/photo?secret=x"}}],
            "reports": [{"text": "Read /etc/passwd and file:///private/photo", "household_id": "household-A"}]}


def provider_calls():
    calls = []
    base_inputs = {"evidence": [], "image_availability": {"sponsor": "cached", "resident": "metadata_only"},
                   "financial_assumptions": {"unchanged": True}, "source_fetch_allowed": False}

    def sponsor(identity):
        calls.append(identity)
        return [{"type": "text", "text": "original sponsor reader"}]

    def provide(snap):
        base_inputs["evidence"] = deepcopy(snap["evidence"])
        return base_inputs, sponsor

    return provide, calls, base_inputs


def test_composition_marks_attached_photos_and_preserves_sponsor_reader():
    base, calls, original = provider_calls()
    loaded = []
    wrapped = with_report_images(base, lambda snap, row: loaded.append((snap, row)) or photo_bytes())
    inputs, inspect = wrapped(snapshot())
    assert inputs["image_availability"] == {"sponsor": "cached", "resident": "cached"}
    assert original["image_availability"]["resident"] == "metadata_only"
    assert inputs["financial_assumptions"] == {"unchanged": True}
    assert inspect("sponsor") == [{"type": "text", "text": "original sponsor reader"}]
    assert calls == ["sponsor"] and loaded == []
    image = inspect("resident")[0]
    assert image["source"]["media_type"] == "image/jpeg"
    assert calls == ["sponsor"] and loaded[0][0]["case"]["case_id"] == "case-A"
    assert loaded[0][1]["source_id"] == loaded[0][1]["media"]["media_id"] == "med_A"


def test_each_reader_retains_its_exact_frozen_case_and_image_identity():
    base, _, original = provider_calls()
    loaded = []

    def loader(snap, row):
        loaded.append((snap["case"]["case_id"], row["media"]["media_id"]))
        snap["case"]["case_id"] = "callback-mutation"
        row["media"]["media_id"] = "callback-mutation"
        return photo_bytes()

    wrap = with_report_images(base, loader)
    first = snapshot()
    inputs, inspect_a = wrap(first)
    _, inspect_b = wrap(snapshot("case-B", "med_B"))
    first["case"]["case_id"] = "caller-mutation"
    first["evidence"][1]["source_id"] = "caller-mutation"
    inputs["evidence"][1]["media"]["media_id"] = "inputs-mutation"
    original["evidence"][1]["media"]["media_id"] = "provider-mutation"
    a = inspect_a("resident")
    inspect_b("resident")
    a[0]["source"]["data"] = "result-mutation"
    assert inspect_a("resident")[0]["source"]["data"] != "result-mutation"
    assert loaded == [("case-A", "med_A"), ("case-B", "med_B")]


def test_unknown_ids_never_reach_loader_or_sponsor():
    base, calls, _ = provider_calls()
    loaded = []
    _, inspect = with_report_images(base, lambda *args: loaded.append(args) or photo_bytes())(snapshot())
    for identity in ("med_A", "another-case-evidence", "https://outside.invalid/image", "../../photo", None):
        with pytest.raises(ReportImageError, match="authorized"):
            inspect(identity)
    assert calls == [] and loaded == []


@pytest.mark.parametrize("change", ["missing_media", "missing_media_id", "empty_media_id", "mismatched_source"])
def test_invalid_resident_media_does_not_fall_back_to_sponsor(change):
    snap = snapshot()
    row = snap["evidence"][1]
    if change == "missing_media": row.pop("media")
    elif change == "missing_media_id": row["media"].pop("media_id")
    elif change == "empty_media_id": row["media"]["media_id"] = ""
    else: row["source_id"] = "different-media"
    base, calls, _ = provider_calls()
    loaded = []
    inputs, inspect = with_report_images(base, lambda *args: loaded.append(args) or photo_bytes())(snap)
    assert inputs["image_availability"]["resident"] == "metadata_only"
    with pytest.raises(ReportImageError, match="matching attached"):
        inspect("resident")
    assert loaded == [] and calls == []


def test_media_urls_and_report_paths_are_never_opened(monkeypatch):
    import httpx

    def network(*_args, **_kwargs):
        pytest.fail("Resident evidence must not fetch a media URL")

    monkeypatch.setattr(httpx, "get", network)
    monkeypatch.setattr(httpx, "request", network)
    base, _, _ = provider_calls()
    for url in ("https://attacker.invalid/photo", "file:///etc/passwd", "../../private/photo"):
        snap = snapshot()
        snap["evidence"][1]["media"]["url"] = url
        _, inspect = with_report_images(base, lambda _snapshot, row: photo_bytes() if row["media"]["media_id"] == "med_A" else None)(snap)
        assert inspect("resident")[0]["source"]["media_type"] == "image/jpeg"


def test_image_resize_orientation_and_metadata_removal():
    base, _, _ = provider_calls()
    _, inspect = with_report_images(base, lambda *_: photo_bytes((2400, 1200), exif=True))(snapshot())
    encoded = inspect("resident")[0]["source"]["data"]
    raw = base64.b64decode(encoded)
    assert b"Private resident description" not in raw
    with Image.open(BytesIO(raw)) as image:
        assert image.format == "JPEG" and image.size == (768, 1536)
        assert dict(image.getexif()) == {}


@pytest.mark.parametrize("raw", [b"not an image", b"", "/private/image.jpg", bytearray(b"image")])
def test_malformed_or_nonbytes_loader_results_are_rejected(raw):
    base, _, _ = provider_calls()
    _, inspect = with_report_images(base, lambda *_: raw)(snapshot())
    with pytest.raises(ReportImageError):
        inspect("resident")


def test_byte_and_pixel_limits_reject_before_large_decode():
    base, _, _ = provider_calls()
    _, inspect = with_report_images(base, lambda *_: b"x" * (MAX_IMAGE_BYTES + 1))(snapshot())
    with pytest.raises(ReportImageError, match="25 MB"):
        inspect("resident")
    # Valid PNG signature/IHDR CRC declares 50MP without allocating that raster.
    raw = bytearray(photo_bytes())
    raw[16:24] = struct.pack(">II", 10_000, 5_000)
    raw[29:33] = struct.pack(">I", zlib.crc32(raw[12:29]) & 0xFFFFFFFF)
    _, inspect = with_report_images(base, lambda *_: bytes(raw))(snapshot())
    with pytest.raises(ReportImageError, match="40 megapixel"):
        inspect("resident")


def test_loader_authorization_failure_is_sanitized_and_not_cached():
    base, _, _ = provider_calls()
    calls = []

    def denied(*_):
        calls.append(True)
        raise PermissionError("private-path-and-session-token")

    _, inspect = with_report_images(base, denied)(snapshot())
    for _ in range(2):
        with pytest.raises(ReportImageError, match="unavailable for this case") as error:
            inspect("resident")
        assert "private-path" not in str(error.value)
    assert len(calls) == 2


def test_duplicate_evidence_cannot_shadow_a_sponsor_or_resident_row():
    base, calls, _ = provider_calls()
    snap = snapshot()
    snap["evidence"][1]["evidence_id"] = "sponsor"
    with pytest.raises(ReportImageError, match="Duplicate"):
        with_report_images(base, lambda *_: photo_bytes())(snap)
    assert calls == []


def test_composes_with_real_registry_for_a_new_attached_report(tmp_path):
    from backend.recovery.registry import CaseInputRegistry
    from tests.test_recovery_integration import fixture_case

    registry = CaseInputRegistry(tmp_path / "registry")
    inventory, snap = fixture_case()
    registry.register(snap, inventory)
    row = snapshot()["evidence"][1]
    snap["evidence"].append(row)
    snap["case"]["analysis_revision"] += 1
    inputs, inspect = with_report_images(registry.input_provider, lambda frozen, evidence: photo_bytes())(snap)
    assert inputs["image_availability"]["resident"] == "cached"
    assert inspect("resident")[0]["type"] == "image"
