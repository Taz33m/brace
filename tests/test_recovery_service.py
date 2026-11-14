"""Worker boundaries: no network, real threads, isolated persistence stand-in."""
from copy import deepcopy
from threading import Event

from PIL import Image
import pytest

from backend.recovery.domain.service import AssessmentService, EvidenceImages, failed_result, make_case_seed


def owner_snapshot():
    return {"case": {"case_id": "case-1", "analysis_revision": 1}, "evidence": [], "observations": []}


class Store:
    def __init__(self):
        self.snapshot = owner_snapshot()
        self.results = []

    def snapshot_for_analysis(self, case_id):
        return self.snapshot

    def complete_assessment(self, run_id, base_analysis_revision, result):
        result = deepcopy(result)
        if self.snapshot["case"]["analysis_revision"] != base_analysis_revision:
            result["assessment"]["status"] = "stale"
        self.results.append(result)
        return result


def test_worker_freezes_snapshot_and_late_report_forces_stale():
    store = Store()
    started, finish = Event(), Event()
    observed = []

    class Agent:
        def __init__(self, snapshot, inputs, **kwargs):
            self.snapshot = snapshot

        def run(self):
            started.set()
            assert finish.wait(timeout=3)
            observed.append(self.snapshot["case"]["analysis_revision"])
            return failed_result(self.snapshot, self.snapshot["run_id"], "Draft", status="draft")

    service = AssessmentService(store, lambda s: ({}, None), agent_factory=Agent)
    try:
        ticket = {"run_id": "run-1", "case_id": "case-1", "base_analysis_revision": 1}
        future = service.launch(ticket)
        assert started.wait(timeout=3)
        assert service.launch(ticket) is future
        store.snapshot["case"]["analysis_revision"] = 2
        finish.set()
        assert future.result(timeout=3)["assessment"]["status"] == "stale"
        assert observed == [1] and len(store.results) == 1
    finally:
        finish.set()
        service.close()


def test_stale_before_worker_start_does_not_call_model():
    store = Store()
    store.snapshot["case"]["analysis_revision"] = 2
    service = AssessmentService(store, lambda s: pytest.fail("stale inputs reached provider"))
    try:
        result = service.launch({"run_id": "r", "case_id": "case-1", "base_analysis_revision": 1}).result(3)
        assert result["assessment"]["status"] == "stale"
        assert result["assessment"]["base_analysis_revision"] == 1
    finally:
        service.close()


def test_provider_failure_is_persisted_without_sensitive_error_text():
    store = Store()

    def broken(_):
        raise ValueError("secret resident data and private token")

    service = AssessmentService(store, broken)
    try:
        result = service.launch({"run_id": "r", "case_id": "case-1", "base_analysis_revision": 1}).result(3)
        assert result["assessment"]["status"] == "failed"
        assert "private token" not in str(result)
        assert "retry" in result["assessment"]["failure_reason"]
    finally:
        service.close()


@pytest.mark.parametrize("fault", ["publish", "wrong_run", "accepted_task"])
def test_worker_rejects_out_of_contract_results(fault):
    store = Store()

    class BadAgent:
        def __init__(self, snapshot, inputs, **kw):
            self.snapshot = snapshot

        def run(self):
            result = failed_result(self.snapshot, "r", "Draft", status="draft")
            if fault == "publish":
                result["assessment"]["status"] = "published"
            elif fault == "wrong_run":
                result["assessment"]["run_id"] = "other"
            else:
                result["proposed_tasks"] = [{"status": "accepted"}]
            return result

    service = AssessmentService(store, lambda _: ({}, None), agent_factory=BadAgent)
    try:
        result = service.launch({"run_id": "r", "case_id": "case-1", "base_analysis_revision": 1}).result(3)
        assert result["assessment"]["status"] == "failed"
        assert result["proposed_tasks"] == []
    finally:
        service.close()


def test_commit_failure_remains_visible_to_worker_supervisor():
    store = Store()

    def broken_commit(*args):
        raise RuntimeError("database offline")

    store.complete_assessment = broken_commit
    store.snapshot["case"]["analysis_revision"] = 2
    service = AssessmentService(store, lambda _: ({}, None))
    try:
        future = service.launch({"run_id": "r", "case_id": "case-1", "base_analysis_revision": 1})
        with pytest.raises(RuntimeError, match="database offline"):
            future.result(3)
    finally:
        service.close()


def test_retry_after_commit_failure_reuses_completed_agent_result():
    store = Store()
    commits, model_runs = [], []
    original_commit = store.complete_assessment

    def flaky_commit(*args):
        commits.append(args)
        if len(commits) == 1:
            raise RuntimeError("temporary database outage")
        return original_commit(*args)

    class Agent:
        def __init__(self, snapshot, inputs, **kw):
            self.snapshot = snapshot

        def run(self):
            model_runs.append(True)
            return failed_result(self.snapshot, "r", "Draft", status="draft")

    store.complete_assessment = flaky_commit
    service = AssessmentService(store, lambda _: ({}, None), agent_factory=Agent)
    ticket = {"run_id": "r", "case_id": "case-1", "base_analysis_revision": 1}
    try:
        with pytest.raises(RuntimeError, match="outage"):
            service.launch(ticket).result(3)
        store.snapshot["case"]["analysis_revision"] = 2
        result = service.launch(ticket).result(3)
        assert result["assessment"]["status"] == "stale"
        assert len(model_runs) == 1 and len(commits) == 2
        assert not service.pending_results
        with pytest.raises(ValueError, match="different inputs"):
            service.launch({**ticket, "case_id": "other-case"})
    finally:
        service.close()


def test_successful_future_retention_is_bounded():
    store = Store()
    store.snapshot["case"]["analysis_revision"] = 2  # stale tickets skip provider
    service = AssessmentService(store, lambda _: pytest.fail("should not run"), max_pending=1, retained_runs=2)
    try:
        for i in range(5):
            service.launch({"run_id": f"r{i}", "case_id": "case-1", "base_analysis_revision": 1}).result(3)
        assert len(service.futures) <= 2 and len(service.tickets) <= 2
    finally:
        service.close()


def test_image_provider_rejects_unscoped_and_path_escape(tmp_path):
    root = tmp_path / "cache"
    root.mkdir()
    private = tmp_path / "private.jpg"
    Image.new("RGB", (32, 32)).save(private)
    images = EvidenceImages({"e1": {"kind": "local_image", "path": str(private)}},
                            [{"evidence_id": "e1"}], cache_root=root)
    with pytest.raises(ValueError, match="authorized"):
        images("other")
    with pytest.raises(ValueError, match="outside"):
        images("e1")


def test_image_provider_decodes_and_strips_metadata(tmp_path):
    image = tmp_path / "image.jpg"
    Image.new("RGB", (1800, 900)).save(image)
    images = EvidenceImages({"e1": {"kind": "local_image", "path": str(image)}},
                            [{"evidence_id": "e1"}], cache_root=tmp_path)
    result = images("e1")
    assert result[0]["type"] == "image"
    assert result[0]["source"]["media_type"] == "image/jpeg"
    import base64
    from io import BytesIO

    with Image.open(BytesIO(base64.b64decode(result[0]["source"]["data"]))) as decoded:
        assert decoded.size == (1536, 768)
        assert not decoded.getexif()


def test_capture_requires_explicit_fetch_and_collection(tmp_path):
    evidence = [{"evidence_id": "a"}]
    images = EvidenceImages({"a": {"kind": "vexcel_capture", "area_wkt": "POINT(0 0)"}},
                            evidence, cache_root=tmp_path)
    with pytest.raises(ValueError, match="not been fetched"):
        images("a")
    images.allow_network = True
    with pytest.raises(ValueError, match="explicit collection"):
        images("a")


def test_image_hash_prevents_late_cache_replacement(tmp_path):
    from hashlib import sha256

    path = tmp_path / "image.jpg"
    Image.new("RGB", (32, 32), "red").save(path)
    fingerprint = sha256(path.read_bytes()).hexdigest()
    images = EvidenceImages({"a": {"kind": "local_image", "path": str(path), "sha256": fingerprint}},
                            [{"evidence_id": "a"}], cache_root=tmp_path)
    assert images("a")
    Image.new("RGB", (32, 32), "blue").save(path)
    with pytest.raises(ValueError, match="changed"):
        images("a")


def test_selected_capture_identity_is_checked(monkeypatch, tmp_path):
    from backend import vexcel

    path = tmp_path / "capture.jpg"
    Image.new("RGB", (32, 32)).save(path)
    monkeypatch.setattr(vexcel, "ortho", lambda *a, **kw: (path, {"collection": "wrong"}))
    images = EvidenceImages({"a": {"kind": "vexcel_capture", "area_wkt": "POINT(0 0)",
                                   "collection": "wanted", "expected_date": "2026-01-01"}},
                            [{"evidence_id": "a"}], allow_network=True, cache_root=tmp_path)
    with pytest.raises(ValueError, match="selected capture"):
        images("a")


def test_seed_has_real_identity_and_no_invented_damage():
    inventory = {"subject": {"id": 7, "name": "Test site", "address": "1 Test St", "city": "Houston"},
                 "evidence": [{"evidence_id": "record-7"}]}
    seed = make_case_seed(inventory, incident_name="Test event", incident_at="2024-07-08",
                          assessment_as_of="2026-11-14")
    assert seed["case"]["mode"] == "scenario_exercise"
    assert seed["case"]["property_ref"]["id"] == "7"
    assert seed["observations"] == [] and seed["reports"] == [] and seed["tasks"] == []
    seed["evidence"].clear()
    assert inventory["evidence"]
    with pytest.raises(ValueError, match="precedes"):
        make_case_seed(inventory, incident_name="Event", incident_at="2026-11-14", assessment_as_of="2024-01-01")
