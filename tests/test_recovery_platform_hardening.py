"""Second-pass hardening: atomic command idempotency, uploads, housekeeping, throttling."""
from __future__ import annotations

import threading

import pytest
from pydantic import TypeAdapter

from backend.recovery.platform import models as m
from backend.recovery.platform.errors import PlatformError
from backend.recovery.platform.store import CaseStore
from tests.test_recovery_platform_api import app  # noqa: F401 (fixture)
from tests.test_recovery_platform_support import OWNER, seeded


@pytest.fixture
def store(tmp_path):
    return CaseStore(tmp_path / "recovery.db", tmp_path / "media")


@pytest.fixture
def world(store):
    return seeded(store)


def rev(store):
    return store.owner_snapshot(OWNER, "case_test").case.case_revision


def notice_cmd(expected, title="Water shutoff"):
    return TypeAdapter(m.OwnerCommand).validate_python({
        "type": "publish_notice", "title": title, "body": "Water is off.", "household_ids": None,
        "source_ids": [], "expected_revision": expected})


# ---------------------------------------------------------------- Task 1

def test_command_receipt_is_atomic_with_mutation(store, world, monkeypatch):
    """If recording the receipt fails, the mutation must not have committed either."""
    expected = rev(store)
    real = store._remember
    calls = []

    def flaky(*args, **kwargs):
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("simulated crash while recording the receipt")
        return real(*args, **kwargs)

    monkeypatch.setattr(store, "_remember", flaky)
    with pytest.raises(RuntimeError):
        store.apply_command(OWNER, "case_test", notice_cmd(expected), "owner-key-1")
    retry = store.apply_command(OWNER, "case_test", notice_cmd(expected), "owner-key-1")
    assert retry.case_revision == expected + 1
    assert len(store.owner_snapshot(OWNER, "case_test").notices) == 1


def test_command_replay_after_commit_returns_original_result(store, world):
    expected = rev(store)
    first = store.apply_command(OWNER, "case_test", notice_cmd(expected), "owner-key-1")
    store.apply_command(OWNER, "case_test", notice_cmd(rev(store), "Another"), "owner-key-2")
    again = store.apply_command(OWNER, "case_test", notice_cmd(expected), "owner-key-1")
    assert again == first


def test_concurrent_identical_commands_apply_once(store, world):
    expected, results, errors = rev(store), [], []
    barrier = threading.Barrier(4)

    def go():
        barrier.wait()
        try:
            results.append(store.apply_command(OWNER, "case_test", notice_cmd(expected), "owner-key-1"))
        except PlatformError as exc:
            errors.append(exc)

    threads = [threading.Thread(target=go) for _ in range(4)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert errors == [] and len(results) == 4 and all(r == results[0] for r in results)
    assert len(store.owner_snapshot(OWNER, "case_test").notices) == 1


def test_replayed_create_invitation_still_409(store, world):
    ha, _, _, _ = world
    cmd = TypeAdapter(m.OwnerCommand).validate_python(
        {"type": "create_invitation", "household_id": ha, "expected_revision": rev(store)})
    assert store.apply_command(OWNER, "case_test", cmd, "owner-key-1").invitation_token
    with pytest.raises(PlatformError) as e:
        store.apply_command(OWNER, "case_test", cmd, "owner-key-1")
    assert e.value.code == "invitation_already_issued"
    import sqlite3

    stored = sqlite3.connect(store.db_path).execute("SELECT response_json FROM idempotency").fetchall()
    assert all('"invitation_token":null' in row[0] for row in stored)


def test_same_key_different_command_conflicts(store, world):
    expected = rev(store)
    store.apply_command(OWNER, "case_test", notice_cmd(expected), "owner-key-1")
    with pytest.raises(PlatformError) as e:
        store.apply_command(OWNER, "case_test", notice_cmd(rev(store), "Other"), "owner-key-1")
    assert e.value.code == "idempotency_conflict"


# ---------------------------------------------------------------- Task 2

def test_upload_without_key_rejected_before_body_read(app, world):
    from tests.test_recovery_platform_api import invite, owner_client, resident_client
    from backend.recovery.platform import uploads

    ha, _, _, _ = world
    phone = resident_client(app, invite(owner_client(app), ha))
    big = b"\0" * (uploads.MAX_UPLOAD_BYTES + uploads.MULTIPART_OVERHEAD + 10)
    r = phone.post("/api/resident/uploads", files={"file": ("x.png", big, "image/png")})
    assert r.status_code == 422 and r.json()["error"]["code"] == "idempotency_key_required"


def test_startup_sweep_removes_old_orphans_only(tmp_path):
    import os
    import time
    from io import BytesIO

    from PIL import Image

    db, media = tmp_path / "recovery.db", tmp_path / "media"
    store = CaseStore(db, media)
    _, _, res_a, _ = seeded(store)
    buf = BytesIO()
    Image.new("RGB", (8, 8)).save(buf, "PNG")
    kept = store.save_upload(res_a, buf.getvalue(), "upload-key-1").media.media_id
    case_dir = media / "case_test"
    old_orphan = [case_dir / ("med_" + "a" * 20 + ext) for ext in (".orig", ".jpg")]
    fresh_orphan = case_dir / ("med_" + "b" * 20 + ".jpg")
    unrelated = case_dir / "notes.txt"
    for path in [*old_orphan, fresh_orphan, unrelated]:
        path.write_bytes(b"x")
    hour_ago = time.time() - 3600
    for path in [*old_orphan, unrelated]:
        os.utime(path, (hour_ago, hour_ago))
    committed = sorted(case_dir.glob(kept + ".*"))
    for path in committed:
        os.utime(path, (hour_ago, hour_ago))

    CaseStore(db, media)

    assert not any(p.exists() for p in old_orphan)
    assert fresh_orphan.exists() and unrelated.exists()
    assert len(committed) == 2 and all(p.exists() for p in committed)
