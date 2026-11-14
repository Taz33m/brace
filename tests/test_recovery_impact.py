"""Synthetic money inputs prove arithmetic and isolation; no rate defaults or live calls."""
from copy import deepcopy
from decimal import Decimal

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from backend.recovery.domain import impact
from backend.recovery.domain.financial_models import money, unavailable
from backend.recovery.domain.service import make_case_seed
from backend.recovery.impact_router import build_impact_router
from backend.recovery.registry import _case_context


@pytest.fixture
def case_data():
    evidence = {"evidence_id": "roof-evidence", "source_id": "vexcel:attributes:7:2026-01-01", "kind": "vexcel_image",
        "source_label": "Synthetic source footprint", "captured_at": None, "effective_at": "2026-01-01",
        "available_at": None, "received_at": "2026-11-14T00:00:00Z", "model_created_at": None,
        "location": None, "media": None, "summary": "Dated footprint; not damage", "limitations": []}
    inventory = {"subject": {"id": 7, "property_ref": {"dataset": "commercial_property", "id": "7"},
        "name": "Synthetic test property", "city": "Houston", "units": 10, "source_ids": ["costar:property:7"]},
        "structures": [{"id": "S1", "footprint_sqft": 22, "source_id": evidence["source_id"], "roof_analysis_date": "2026-01-01"}],
        "evidence": [evidence], "scans": [], "locations": [], "sales": []}
    snapshot = make_case_seed(inventory, case_id="case-test", incident_name="Synthetic incident", incident_at="2026-09-01", assessment_as_of="2026-11-14")
    snapshot["assessments"] = [{"assessment_id": "a1", "base_analysis_revision": 1, "status": "draft", "valuation": {
        "benchmark": money(Decimal(1000), Decimal(2000), point=Decimal(1500), method="Synthetic comparable proxy", source_ids=["sale:1"], range_kind="comparable_dispersion")}}]
    snapshot["current_assessment_id"] = "a1"
    inventory["_case_context"] = _case_context(snapshot)
    return inventory, snapshot


def assumptions(**updates):
    return {"expected_analysis_revision": 1, "structure_id": "S1", "affected_percent": 25,
            "unit_cost_low": 10.10, "unit_cost_high": 20.20, "affected_units": 2,
            "monthly_income_per_unit": 100.25, "downtime_months": 1.5, **updates}


def test_source_quantity_and_owner_inputs_drive_decimal_costs_without_mutation(case_data):
    inventory, snapshot = case_data
    original = deepcopy(case_data)
    result = impact.calculate_impact(inventory, snapshot, impact.ImpactInput(**assumptions()))
    assert result["quantity_sqft"] == 5.5
    assert (result["repair_cost"]["low"], result["repair_cost"]["high"]) == (55.55, 111.10)
    assert result["disruption_cost"]["low"] == result["disruption_cost"]["high"] == 300.75
    assert (result["total_cost"]["low"], result["total_cost"]["high"]) == (356.30, 411.85)
    assert (result["current_range"]["low"], result["current_range"]["high"]) == (588.15, 1643.70)
    assert result["current_range"]["basis"] == "conditional" and result["current_range"]["range_kind"] == "scenario"
    assert "not current market value" in result["current_range"]["method"]
    assert result["assumptions"]["affected_percent"] == 25 and result["preview_only"] is True
    assert result["structure"]["source_id"] in result["repair_cost"]["source_ids"]
    assert case_data == original


def test_missing_source_quantity_and_baseline_stay_unavailable(case_data):
    inventory, snapshot = case_data
    inventory["structures"][0]["footprint_sqft"] = None
    result = impact.calculate_impact(inventory, snapshot, impact.ImpactInput(**assumptions()))
    assert result["quantity_sqft"] is None and result["repair_cost"]["low"] is None and result["total_cost"]["low"] is None
    inventory["structures"][0]["footprint_sqft"] = 22
    snapshot["assessments"][0]["valuation"]["benchmark"] = unavailable("No eligible comparable sales")
    result = impact.calculate_impact(inventory, snapshot, impact.ImpactInput(**assumptions()))
    assert result["total_cost"]["low"] == 356.30 and result["current_range"]["low"] is None
    inventory["subject"]["units"] = None
    result = impact.calculate_impact(inventory, snapshot, impact.ImpactInput(**assumptions()))
    assert result["disruption_cost"]["low"] is None and result["total_cost"]["low"] is None


def test_stale_assessment_cannot_supply_the_benchmark(case_data, monkeypatch):
    inventory, snapshot = case_data
    snapshot["case"]["analysis_revision"] = 2
    calls = []
    def screen(current, inputs):
        calls.append((current["case"]["analysis_revision"], inputs["subject"]["id"]))
        return {"valuation": {"benchmark": unavailable("Fresh screen lacks sufficient comps")}}
    monkeypatch.setattr(impact, "screen_case", screen)
    sources = impact.impact_sources(inventory, snapshot)
    assert calls == [(2, 7)] and sources["benchmark"]["low"] is None


@pytest.fixture
def api(case_data, monkeypatch):
    inventory, snapshot = case_data
    reads = []
    monkeypatch.setenv("BRACE_ALLOWED_ORIGINS", "https://owner.example")
    async def owner_case(request, case_id):
        actor = request.headers.get("x-test-role")
        if actor != "owner":
            raise HTTPException(401 if actor is None else 403)
        if case_id != snapshot["case"]["case_id"]:
            raise HTTPException(404)
        return deepcopy(snapshot)
    def registered(current):
        reads.append(current["case"]["case_id"])
        return deepcopy(inventory)
    app = FastAPI()
    app.include_router(build_impact_router(owner_case, registered))
    with TestClient(app, headers={"Origin": "https://owner.example"}) as client:
        yield client, reads


PATH = "/api/recovery/cases/case-test/value-impact"
OWNER = {"x-test-role": "owner"}


def test_owner_get_and_preview_use_only_scoped_sources(api, case_data):
    client, reads = api
    original = deepcopy(case_data)
    source = client.get(PATH, headers=OWNER)
    assert source.status_code == 200 and source.headers["cache-control"] == "private, no-store"
    assert source.json()["structures"] == [{"structure_id": "S1", "label": "Structure S1", "footprint_sqft": 22,
        "source_id": "vexcel:attributes:7:2026-01-01", "analysis_date": "2026-01-01"}]
    assert source.json()["subject_units"] == 10
    result = client.post(PATH, json=assumptions(), headers=OWNER)
    assert result.status_code == 200 and result.json()["quantity_sqft"] == 5.5
    assert reads == ["case-test", "case-test"] and case_data == original


def test_unauthorized_foreign_case_and_cross_origin_are_rejected(api):
    client, reads = api
    for headers, status in (({}, 401), ({"x-test-role": "resident"}, 403)):
        assert client.get(PATH, headers=headers).status_code == status
        assert client.post(PATH, json=assumptions(), headers=headers).status_code == status
    assert client.get(PATH.replace("case-test", "foreign"), headers=OWNER).status_code == 404
    assert client.post(PATH, json=assumptions(), headers={**OWNER, "Origin": "https://foreign.example"}).status_code == 403
    assert reads == []


def test_stale_revision_and_manifest_fail_closed(api, case_data):
    client, _ = api
    stale = client.post(PATH, json=assumptions(expected_analysis_revision=2), headers=OWNER)
    assert stale.status_code == 409 and stale.json()["error"]["code"] == "analysis_revision_conflict"
    case_data[0]["_case_context"]["case_id"] = "another-case"
    response = client.get(PATH, headers=OWNER)
    assert response.status_code == 503 and response.json()["error"]["code"] == "source_refresh_required"


@pytest.mark.parametrize("updates", [
    {"affected_percent": 101}, {"affected_percent": True}, {"unit_cost_low": 21},
    {"affected_units": 11}, {"affected_units": 1.5}, {"downtime_months": 121},
    {"monthly_income_per_unit": "NaN"}, {"structure_id": "other-case-structure"},
])
def test_invalid_or_unbounded_assumptions_are_rejected(api, updates):
    client, _ = api
    assert client.post(PATH, json=assumptions(**updates), headers=OWNER).status_code == 422
