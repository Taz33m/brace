"""Staging illustrations: no network and no keys. A scripted stand-in plays the image service."""
from __future__ import annotations

import io
import json

import pytest
from PIL import Image

from backend.openproblems import reimagine


class Scripted:
    """Stands in for the image service: counts calls and answers from a script."""

    def __init__(self, *answers):
        self.answers = list(answers)
        self.calls: list[tuple[int, str]] = []

    def __call__(self, images: list[bytes], instruction: str) -> dict:
        self.calls.append((len(images), instruction))
        answer = self.answers.pop(0) if self.answers else "picture"
        if isinstance(answer, Exception):
            raise answer
        buf = io.BytesIO()
        Image.new("RGB", (64, 64), (200, 180, 160)).save(buf, "PNG")
        return {"image": buf.getvalue(), "provider": "scripted", "model": "stand-in", "quality": "none", "size": "64x64", "usage": None}


@pytest.fixture
def room(tmp_path, monkeypatch):
    """Four real-looking side faces on disk, and an empty output folder."""
    faces = tmp_path / "faces"
    faces.mkdir()
    for f in (1, 2, 3, 4):
        Image.new("RGB", (128, 128), (40 * f, 90, 120)).save(faces / f"sw_{f}.jpg")
    monkeypatch.setattr(reimagine, "OUT", tmp_path / "out")
    monkeypatch.setattr(reimagine.matterport, "face_image", lambda model_id, sweep_id, face: faces / f"{sweep_id}_{face}.jpg")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)  # a real call from a test would be refused, not paid for
    return tmp_path


def files(room):
    out = room / "out"
    return sorted(p.name for p in out.rglob("*") if p.is_file() and p.name != "ledger.json") if out.exists() else []


def test_record_is_written_and_labelled_as_generated(room):
    service = Scripted()
    out = reimagine.stage("M", "sw", 1, "listing", service=service)
    assert out["ok"] and not out["cached"]
    record = json.loads(open(out["record_path"]).read())
    assert record == out["record"]
    assert record["generated"] is True and record["kind"] == "illustration"
    assert "Not a photo of the building" in record["label"]
    assert record["purpose"] == "listing" and record["instruction"] == reimagine.INSTRUCTIONS["listing"]
    assert record["source"]["real"] is True
    assert (record["source"]["model_id"], record["source"]["sweep_id"], record["source"]["face"]) == ("M", "sw", 1)
    assert len(record["source"]["sha256"]) == 64
    assert record["service"]["model"] == "stand-in" and "image" not in record["service"]
    assert record["created_at"] and record["reference"] is None
    # the picture sits beside its record, carries the label itself, and is recognised as generated
    assert out["image"].endswith(".png") and out["record_path"] == out["image"][:-4] + ".json"
    with Image.open(out["image"]) as im:
        assert im.text["generated"] == "true" and "Not a photo" in im.text["label"]
    assert reimagine.is_generated(out["image"]) and reimagine.is_generated(out["labelled"])
    assert not reimagine.is_generated(room / "faces" / "sw_1.jpg")
    assert service.calls == [(1, reimagine.INSTRUCTIONS["listing"])]


def test_cache_prevents_a_second_paid_call(room):
    service = Scripted()
    first = reimagine.stage("M", "sw", 1, "storm_ready", service=service)
    again = reimagine.stage("M", "sw", 1, "storm_ready", service=service)
    assert len(service.calls) == 1
    assert again["cached"] and again["image"] == first["image"] and again["record"] == first["record"]
    assert reimagine.budget()["used"] == 1
    # a different purpose is a different picture, and is paid for once
    reimagine.stage("M", "sw", 1, "listing", service=service)
    assert len(service.calls) == 2 and reimagine.budget()["used"] == 2


def test_budget_refuses_a_ninth_generation(room, monkeypatch):
    monkeypatch.setattr(reimagine, "MAX_GENERATIONS", 8)   # the rule is tested at eight, whatever today's limit is
    service = Scripted()
    views = [(face, purpose) for face in (1, 2, 3, 4) for purpose in ("listing", "storm_ready")]
    for face, purpose in views:
        assert reimagine.stage("M", "sw", face, purpose, service=service)["ok"]
    assert reimagine.budget() == {"used": 8, "limit": 8, "left": 0}
    before = files(room)
    ninth = reimagine.stage("M2", "sw", 1, "listing", service=service)
    assert ninth["ok"] is False and ninth["reason"]["kind"] == "budget"
    assert ninth["image"] is None and ninth["record"] is None
    assert len(service.calls) == 8 and files(room) == before
    # what was already made is still served from the cache
    assert reimagine.stage("M", "sw", 1, "listing", service=service)["cached"]


def test_refused_request_is_reported_and_writes_no_file(room):
    service = Scripted(reimagine.ServiceRefused(400, "moderation_blocked", "Your request was rejected."))
    out = reimagine.stage("M", "sw", 1, "listing", service=service)
    assert out["ok"] is False
    assert out["reason"] == {"kind": "service_refused", "status": 400, "code": "moderation_blocked", "message": "Your request was rejected."}
    assert out["image"] is None and out["record_path"] is None and out["record"] is None
    assert files(room) == []
    assert reimagine.budget()["used"] == 0  # nothing was generated, so nothing is counted
    # the same request can be tried again, and is not answered from a cache of the refusal
    assert reimagine.stage("M", "sw", 1, "listing", service=service)["ok"] and len(service.calls) == 2


def test_unclear_failure_counts_against_the_budget_and_writes_no_file(room):
    out = reimagine.stage("M", "sw", 1, "listing", service=Scripted(reimagine.ServiceError("ReadTimeout")))
    assert out["ok"] is False and out["reason"]["kind"] == "service_error"
    assert files(room) == [] and reimagine.budget()["used"] == 1


def test_missing_key_is_a_refusal_not_a_crash(room):
    out = reimagine.stage("M", "sw", 1, "listing")  # the real service, with no key in the environment
    assert out["ok"] is False and out["reason"]["code"] == "no_key" and files(room) == []


def test_reference_must_be_an_earlier_staged_neighbour_and_is_recorded_as_generated(room):
    service = Scripted()
    with pytest.raises(ValueError):
        reimagine.stage("M", "sw", 2, "listing", reference_face=1, service=service)  # face 1 not staged yet
    first = reimagine.stage("M", "sw", 1, "listing", service=service)
    with pytest.raises(ValueError):
        reimagine.stage("M", "sw", 3, "listing", reference_face=1, service=service)  # opposite face, not a neighbour
    second = reimagine.stage("M", "sw", 2, "listing", reference_face=1, service=service)
    assert service.calls[-1][0] == 2 and "immediately to the left" in service.calls[-1][1]
    ref = second["record"]["reference"]
    assert ref["generated"] is True and ref["path"] == first["image"] and ref["face"] == 1
    assert second["record"]["source"]["real"] is True and second["record"]["source"]["face"] == 2
    assert set(second["record"]["seam_with_reference"]) == {"real_pair", "staged_pair", "note"}
    assert second["image"] != first["image"]


def test_only_known_purposes_and_side_faces(room):
    with pytest.raises(ValueError):
        reimagine.stage("M", "sw", 1, "luxury", service=Scripted())
    with pytest.raises(ValueError):
        reimagine.stage("M", "sw", 0, "listing", service=Scripted())


def test_a_generated_picture_is_never_accepted_as_the_source(room, monkeypatch):
    made = reimagine.stage("M", "sw", 1, "listing", service=Scripted())
    monkeypatch.setattr(reimagine.matterport, "face_image", lambda *a: made["image"])
    with pytest.raises(ValueError):
        reimagine.stage("M", "sw", 2, "listing", service=Scripted())
