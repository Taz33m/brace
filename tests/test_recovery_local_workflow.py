"""Complete local recovery workflow using real persistence/routes and a scripted model.

All properties, pictures, reports, credentials, and prices are synthetic test data.
No provider, sponsor, or external messaging API is called.
"""
from io import BytesIO
from contextlib import ExitStack
from threading import Event
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image
import pytest

from backend.recovery.domain.agent import RecoveryAgent
from backend.recovery.domain.service import make_case_seed
from backend.recovery.local import LocalRecoveryLock, import_fresh_case, install_local_recovery
from backend.recovery.platform.auth import Actor, LOCAL_OWNER_ID
from tests.test_recovery_integration import fixture_case
from tests.test_recovery_valuation import location


ORIGIN = "http://localhost:5174"
OWNER_SECRET = "synthetic-test-secret-not-a-real-credential"


class Script:
    def __init__(self, snapshot, entered, release, block):
        self.snapshot, self.entered, self.release, self.block = snapshot, entered, release, block
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self.create))

    def create(self, **kwargs):
        if self.block:
            self.entered.set()
            assert self.release.wait(5), "Test did not release the model worker"
        calls = [("get_case", {}), ("list_evidence", {})]
        for evidence in self.snapshot["evidence"]:
            if evidence["kind"] == "resident_photo":
                calls.append(("inspect_view", {"evidence_id": evidence["evidence_id"]}))
        for index, report in enumerate(self.snapshot["reports"], 1):
            verified = report["status"] == "verified"
            calls.append(("resolve_question", {"question_id": f"{self.snapshot['run_id']}:question:{index}",
                "status": "resolved" if verified else "needs_verification", "basis": "inferred",
                "conclusion": "Authorized review is recorded." if verified else "The new report still needs authorized inspection.",
                "evidence_ids": ["inspection"]}))
            if not verified:
                calls.append(("propose_task", {"kind": "verification", "title": "Review the new report",
                    "scope": "Arrange an inspection with the reporting household.", "report_ids": [report["report_id"]]}))
        present = {row["kind"] for row in self.snapshot["evidence"]}
        missing = [kind for kind in ("costar_record", "vexcel_image", "matterport_view") if kind not in present]
        for index, kind in enumerate(missing, len(self.snapshot["reports"]) + 1):
            calls.append(("resolve_question", {"question_id": f"{self.snapshot['run_id']}:question:{index}",
                "status": "needs_verification", "basis": "inferred", "evidence_ids": [],
                "conclusion": f"The synthetic workflow fixture has no {kind} layer; obtain source coverage before extending conclusions."}))
        verified_reports = [r for r in self.snapshot["reports"] if r["status"] == "verified"]
        for observation in self.snapshot["observations"]:
            if observation["status"] == "verified":
                calls.append(("propose_task", {"kind": "repair", "title": "Address the reviewed roof scope",
                    "scope": "Obtain the repair scope and contractor confirmation before scheduling.",
                    "observation_ids": [observation["observation_id"]], "evidence_ids": observation["evidence_ids"],
                    "report_ids": [verified_reports[0]["report_id"]], "location_id": "roof-a"}))
        calls.extend([("calculate_valuation", {}), ("draft_notice", {"title": "Recovery review",
                      "body": "Reports are being reviewed. Work has not been scheduled.", "source_ids": ["inspection"]}),
                      ("finish", {"headline": "Review the recovery evidence", "summary": "Verified work and remaining questions are separated."})])
        return SimpleNamespace(stop_reason="tool_use", content=[SimpleNamespace(type="tool_use", id=str(index), name=name, input=args)
                                                                 for index, (name, args) in enumerate(calls)])


@pytest.fixture
def world(tmp_path, monkeypatch, request):
    monkeypatch.setenv("BRACE_OWNER_SECRET", OWNER_SECRET)
    monkeypatch.setenv("BRACE_ALLOWED_ORIGINS", ORIGIN)
    app = FastAPI()

    @app.get("/api/config")
    @app.post("/api/legacy-write")
    def legacy():
        return {"owner_only": True}

    entered, release, factories = Event(), Event(), []

    def factory(snapshot, inputs, **kwargs):
        script = Script(snapshot, entered, release, block=not factories)
        agent = RecoveryAgent(snapshot, inputs, client=script, **kwargs)
        factories.append(agent)
        return agent

    service = install_local_recovery(app, root=tmp_path, agent_factory=factory)
    clients = [TestClient(app, headers={"Origin": ORIGIN}) for _ in range(3)]
    owner, resident_a, resident_b = clients
    lifespan = ExitStack()

    def shutdown():
        release.set()
        lifespan.close()  # one owner lifespan shuts workers down and releases the process lock
        with LocalRecoveryLock(tmp_path / "platform") as acquired:
            assert acquired.fd is not None

    request.addfinalizer(shutdown)
    lifespan.enter_context(owner)
    lifespan.callback(resident_a.close)
    lifespan.callback(resident_b.close)
    store, registry = app.state.brace_recovery_store, app.state.brace_recovery_registry
    inventory, _ = fixture_case()
    inventory["locations"] = [location()]
    seed = make_case_seed(inventory, incident_name="Synthetic recovery exercise", incident_at="2026-11-01",
                          assessment_as_of="2026-11-14", case_id="workflow-case")
    imported = import_fresh_case(store, registry, seed, inventory)
    assert imported["case"]["case_id"] == seed["case"]["case_id"]
    assert import_fresh_case(store, registry, seed, inventory)["case"]["case_revision"] == imported["case"]["case_revision"]
    actor = Actor("owner", LOCAL_OWNER_ID)
    households = [store.add_household(actor, "workflow-case", label, location_ids=["roof-a"] if label == "A" else [])
                  for label in ("A", "B")]
    assert owner.post("/api/recovery/session", json={"secret": OWNER_SECRET}).status_code == 200

    def snapshot():
        response = owner.get("/api/recovery/cases/workflow-case")
        assert response.status_code == 200, response.text
        return response.json()

    def command(kind, **body):
        response = owner.post("/api/recovery/cases/workflow-case/commands", json={
            "type": kind, "expected_revision": snapshot()["case"]["case_revision"], **body})
        assert response.status_code == 200, response.text
        return response.json()

    for household, resident in zip(households, (resident_a, resident_b)):
        invitation = command("create_invitation", household_id=household)
        assert resident.post("/api/resident/session", json={"invitation_token": invitation["invitation_token"]}).status_code == 200
    yield SimpleNamespace(owner=owner, a=resident_a, b=resident_b, households=households, store=store, registry=registry,
                          service=service, agents=factories, entered=entered, release=release, snapshot=snapshot,
                          command=command, seed=seed, inventory=inventory)


def report_body(**changes):
    return {"category": "roof", "text": "Synthetic test damage report", "selected_location_id": "roof-a",
            "location_description": "Roof A", "observed_at": "2026-11-12", "upload_ids": [], **changes}


def test_owner_resident_assessment_and_publication_loop(world):
    image = BytesIO()
    Image.new("RGB", (32, 32), (120, 140, 160)).save(image, format="PNG")
    upload = world.a.post("/api/resident/uploads", files={"file": ("synthetic.png", image.getvalue(), "image/png")},
                          headers={"Idempotency-Key": "workflow-upload-1"})
    assert upload.status_code == 200, upload.text
    uploaded = upload.json()
    upload_retry = world.a.post("/api/resident/uploads", files={"file": ("synthetic.png", image.getvalue(), "image/png")},
                                headers={"Idempotency-Key": "workflow-upload-1"})
    assert upload_retry.status_code == 200 and upload_retry.json()["upload_id"] == uploaded["upload_id"]
    body = report_body(upload_ids=[uploaded["upload_id"]])
    first = world.a.post("/api/resident/reports", json=body, headers={"Idempotency-Key": "workflow-report-1"})
    assert first.status_code == 200, first.text
    again = world.a.post("/api/resident/reports", json=body, headers={"Idempotency-Key": "workflow-report-1"})
    assert again.json()["duplicate"] and again.json()["report"]["report_id"] == first.json()["report"]["report_id"]
    assert len(world.snapshot()["reports"]) == 1
    assert world.b.get("/api/resident/home").json()["reports"] == []
    assert world.b.get(uploaded["media"]["url"]).status_code == 404
    foreign_attachment = world.b.post("/api/resident/reports", json=report_body(selected_location_id=None, upload_ids=[uploaded["upload_id"]]),
                                      headers={"Idempotency-Key": "foreign-upload-attachment"})
    assert foreign_attachment.status_code == 422
    own_image = world.a.get(uploaded["media"]["url"])
    assert own_image.status_code == 200 and own_image.headers["cache-control"] == "private, no-store"
    observation = world.snapshot()["observations"][0]
    world.command("review_observation", observation_id=observation["observation_id"], status="verified",
                  note="Authorized review of synthetic test evidence.", evidence_ids=observation["evidence_ids"])
    initial = world.command("start_assessment")
    assert world.entered.wait(5)
    new_report = world.a.post("/api/resident/reports", json=report_body(text="A second synthetic report needs review"),
                             headers={"Idempotency-Key": "workflow-report-2"})
    assert new_report.status_code == 200
    world.release.set()
    stale = world.service.futures[initial["run_id"]].result(timeout=5)
    assert stale.status == "stale"
    assert set(observation["evidence_ids"]) <= world.agents[0].inspected
    assert world.agents[0].request_count == 1
    assert world.snapshot()["current_assessment_id"] is None and world.snapshot()["tasks"] == []
    fresh = world.command("start_assessment")
    assessment = world.service.futures[fresh["run_id"]].result(timeout=5)
    assert assessment.status == "draft" and assessment.valuation.basis == "insufficient_evidence"
    assert len(world.snapshot()["tasks"]) == 2
    assert world.a.get("/api/resident/home").json()["tasks"] == []
    world.command("publish_assessment", assessment_id=assessment.assessment_id)
    task = next(t for t in world.snapshot()["tasks"] if t["title"] == "Address the reviewed roof scope")
    world.command("transition_task", task_id=task["task_id"], expected_task_revision=task["revision"], status="approved",
                  note="Approve a repair scope for contractor review.", confirmation_source=None, evidence_ids=[])
    world.command("publish_notice", title="Your report update", body="Your reviewed work is approved; scheduling is still pending.",
                  household_ids=[world.households[0]], source_ids=["inspection"])
    a, b = world.a.get("/api/resident/home").json(), world.b.get("/api/resident/home").json()
    assert a["tasks"][0]["status"] == "approved" and a["tasks"][0]["confirmed_schedule"] is None
    assert a["notices"][0]["title"] == "Your report update" and not b["notices"] and not b["tasks"]
    assert "valuation" not in str(a) and "assessment" not in a
    current = world.snapshot()
    assert current["current_assessment_id"] == assessment.assessment_id
    assert next(a for a in current["assessments"] if a["assessment_id"] == assessment.assessment_id)["status"] == "published"
    assert world.registry.load_inventory(current)["subject"]["id"] == world.inventory["subject"]["id"]


def test_live_local_gates_reject_resident_and_same_site_wrong_origin(world):
    assert world.a.get("/api/config", headers={"X-Role": "owner"}).status_code == 401
    assert world.a.get("/api/recovery/cases/workflow-case").status_code == 401
    assert world.owner.get("/api/config").status_code == 200
    response = world.owner.post("/api/legacy-write", headers={"Origin": "http://localhost:9999", "Sec-Fetch-Site": "same-site"})
    assert response.status_code == 403 and response.json()["error"]["code"] == "cross_site_request"
    assert world.owner.post("/api/legacy-write").status_code == 200
    assert world.a.post("/api/resident/reports", json=report_body(), headers={"Origin": "https://foreign.invalid", "Idempotency-Key": "evil-request-1"}).status_code == 403
    assert world.b.post("/api/resident/reports", json=report_body(), headers={"Idempotency-Key": "foreign-room-1"}).status_code == 422
