"""Financial invariants: no model, network, kit records, or property prices needed."""
from copy import deepcopy

import pytest

from backend.recovery.domain.financial_models import FinancialInputError, number
from backend.recovery.domain.valuation import evaluate_valuation


def context(**changes):
    return {"assessment_as_of": "2026-11-14", "incident_at": "2026-11-01",
            "mode": "observed_recovery", "property_ref": {"dataset": "commercial_property", "id": "subject"}, **changes}


def location():
    return {"location_id": "roof-a", "label": "Roof A", "structure_id": "A", "scan_id": None,
            "sweep_id": None, "room_id": None, "unit_label": None, "binding": "verified_space",
            "longitude": -95.3, "latitude": 29.7, "bearing_degrees": None}


def evidence(eid="quote", kind="cost_source", **changes):
    return {"evidence_id": eid, "source_id": eid, "kind": kind, "effective_at": "2026-11-13",
            "captured_at": None, "available_at": "2026-11-13", **changes}


def sale(i, **changes):
    return {"comp_id": f"sale-{i}", "property_ref": {"dataset": "commercial_property", "id": f"property-{i}"},
            "label": f"Comparable {i}", "transaction_date": "2026-10-01", "available_at": "2026-10-05",
            "date_basis": "closed", "price_usd": i * 100_000, "price_status": "Confirmed", "allocated": False,
            "currency": "USD", "asset_type": "Multifamily", "city": "Houston", "state": "TX", "latitude": 29.7,
            "longitude": -95.3, "units": 10, "gba_sqft": 10_000, "sale_conditions": [], "source_ids": [f"sale-{i}"], **changes}


def inputs():
    return {"subject": {"id": "subject", "type": "Multifamily", "city": "Houston", "state": "TX",
                        "lat": 29.7, "lon": -95.3, "units": 20, "gba_sqft": 20_000},
            "sales": [sale(1), sale(2), sale(3)],
            "evidence": [evidence(), evidence("inspection", "inspection")], "financial_assumptions": {}}


def observation(status="verified"):
    return {"observation_id": "damage", "status": status, "verified_by": "inspector" if status == "verified" else None,
            "verification_note": "Reviewed scope" if status == "verified" else None,
            "evidence_ids": ["inspection"], "location": location()}


def financial():
    return {
        "reviewed_values": [{"condition": "restored", "low_usd": 1_000_000, "high_usd": 1_200_000,
                             "effective_at": "2026-11-14", "source_ids": ["inspection"], "reviewed_by": "reviewer",
                             "review_note": "Same-date restored condition assumption", "method": "Reviewed market evidence", "basis": "source"}],
        "repairs": [{"line_id": "repair-a", "scope_key": "roof-a-replace", "description": "Remaining roof repair",
                     "location": location(), "quantity": "10.5", "quantity_unit": "sqft", "quantity_basis": "Reviewed measured scope",
                     "rate_low_usd": "10.10", "rate_high_usd": "20.20", "rate_effective_at": "2026-11-13",
                     "source_ids": ["quote"], "observation_ids": ["damage"], "basis": "verified", "remaining": True}],
        "repair_scope_complete": True, "repair_scope_source_ids": ["inspection"],
        "downtime": {"low_usd": "1000.25", "high_usd": "2000.50", "effective_at": "2026-11-14",
                     "source_ids": ["quote"], "incremental": True, "includes_repair_costs": False,
                     "method": "Supplied temporary net disruption estimate", "basis": "user_supplied"},
    }


def test_benchmark_is_conditional_and_not_current_value():
    value = evaluate_valuation(inputs(), [], context())
    assert value["benchmark"]["low"] == 200_000
    assert value["benchmark"]["point"] == 400_000
    assert value["benchmark"]["high"] == 600_000
    assert value["benchmark"]["basis"] == "conditional"
    assert value["benchmark"]["range_kind"] == "comparable_dispersion"
    assert value["current_condition"]["low"] is None
    assert value["after_repair"]["low"] is None
    assert value["basis"] == "insufficient_evidence"


def test_interval_subtraction_and_decimal_rounding():
    data = inputs()
    data["financial_assumptions"] = financial()
    value = evaluate_valuation(data, [observation()], context())
    assert value["repair_cost"]["low"] == 106.05
    assert value["repair_cost"]["high"] == 212.10
    assert value["current_condition"]["low"] == 997_787.40
    assert value["current_condition"]["high"] == 1_198_893.70
    assert value["current_condition"]["basis"] == "conditional"
    assert value["after_repair"]["basis"] == "market_supported"


@pytest.mark.parametrize("changes,reason", [
    ({"price_usd": None}, "missing"),
    ({"price_usd": float("nan")}, "finite"),
    ({"price_usd": -1}, "positive"),
    ({"allocated": True}, "allocated"),
    ({"multiple_entities": True}, "Portfolio"),
    ({"price_status": "Approximate"}, "confirmed"),
    ({"currency": "CAD"}, "USD"),
    ({"asset_type": "Office"}, "asset class"),
    ({"sale_conditions": ["DistressSale"]}, "Sale conditions"),
    ({"units": 1}, "scale"),
    ({"longitude": -118.2}, "25-km"),
    ({"transaction_date": "2027-01-01"}, "after"),
    ({"transaction_date": "2023-01-01"}, "730-day"),
    ({"available_at": "2027-01-01"}, "unavailable"),
    ({"temporal_eligible": False, "temporal_exclusion_reason": "Excluded by source cutoff"}, "source cutoff"),
])
def test_unsuitable_comps_are_explained_and_no_minimum_fabricated(changes, reason):
    data = inputs()
    data["sales"][0].update(changes)
    value = evaluate_valuation(data, [], context())
    assert not value["comparables"][0]["included"]
    assert reason.lower() in value["comparables"][0]["reason"].lower()
    assert value["benchmark"]["low"] is None


def test_duplicate_transaction_with_different_id_does_not_inflate_sample():
    data = inputs()
    data["sales"] = [sale(1), sale(2), {**sale(2), "comp_id": "another-source"}]
    value = evaluate_valuation(data, [], context())
    assert value["benchmark"]["low"] is None
    assert "Duplicate" in value["comparables"][2]["reason"]


def test_unverified_report_cannot_create_deduction():
    data = inputs()
    data["financial_assumptions"] = financial()
    value = evaluate_valuation(data, [observation("reported")], context())
    assert value["repair_cost"]["low"] is None
    assert value["current_condition"]["low"] is None
    assert "unverified" in value["repair_lines"][0]["total"]["unavailable_reason"]


def test_explicit_hypothetical_scope_remains_scenario():
    data = inputs()
    data["financial_assumptions"] = financial()
    data["financial_assumptions"]["repairs"][0]["basis"] = "scenario"
    value = evaluate_valuation(data, [observation("reported")], context(mode="scenario_exercise"))
    assert value["basis"] == "conditional"
    assert any(x["label"] == "Hypothetical repair scope" and x["basis"] == "scenario" for x in value["assumptions"])


@pytest.mark.parametrize("mutate", [
    lambda f: f.update(repair_scope_complete=False),
    lambda f: f["repairs"][0].update(quantity=None),
    lambda f: f["repairs"][0].update(rate_low_usd=float("inf")),
    lambda f: f["repairs"][0].update(source_ids=["invented-quote"]),
    lambda f: f["repairs"][0].update(remaining=False),
    lambda f: f["repairs"].append({**f["repairs"][0], "line_id": "copy"}),
    lambda f: f["downtime"].update(includes_repair_costs=True),
    lambda f: f.update(downtime=None),
    lambda f: f["reviewed_values"][0].update(effective_at="2027-11-14"),
])
def test_incomplete_or_conflicting_scope_blocks_current_value(mutate):
    data = inputs()
    data["financial_assumptions"] = financial()
    mutate(data["financial_assumptions"])
    value = evaluate_valuation(data, [observation()], context())
    assert value["current_condition"]["low"] is None


def test_current_market_estimate_is_not_deducted_twice():
    data = inputs()
    data["financial_assumptions"] = financial()
    current = {**financial()["reviewed_values"][0], "condition": "current", "low_usd": 900_000, "high_usd": 950_000}
    data["financial_assumptions"]["reviewed_values"].append(current)
    value = evaluate_valuation(data, [observation()], context())
    assert value["current_condition"]["low"] == 900_000
    assert value["basis"] == "market_supported"
    assert any("not deducted again" in text for text in value["limitations"])


def test_historical_replay_excludes_unavailable_comps_and_cost_sources():
    data = inputs()
    data["sales"][0]["available_at"] = None
    data["financial_assumptions"] = financial()
    data["evidence"][0]["available_at"] = None
    value = evaluate_valuation(data, [observation()], context(mode="historical_replay"))
    assert not value["comparables"][0]["included"]
    assert value["repair_cost"]["low"] is None
    assert value["current_condition"]["low"] is None


def test_wrong_location_cannot_support_repair():
    data = inputs()
    data["financial_assumptions"] = financial()
    report = observation()
    report["location"]["location_id"] = "another-roof"
    value = evaluate_valuation(data, [report], context())
    assert value["repair_cost"]["low"] is None
    assert "location" in value["repair_lines"][0]["total"]["unavailable_reason"]


def test_input_snapshot_is_not_mutated():
    data = inputs()
    data["financial_assumptions"] = financial()
    before = deepcopy(data)
    evaluate_valuation(data, [observation()], context())
    assert data == before


@pytest.mark.parametrize("value", [None, True, float("nan"), float("inf"), "NaN", -1, "1e10000"])
def test_invalid_financial_numbers_are_rejected(value):
    with pytest.raises(FinancialInputError):
        number(value, "amount")


def test_unknown_prices_never_become_zero():
    value = evaluate_valuation({"subject": {}, "sales": [], "evidence": []}, [], context())
    for key in ("benchmark", "current_condition", "after_repair", "repair_cost", "downtime_cost"):
        assert value[key]["low"] is None and value[key]["high"] is None


def test_zero_remaining_scope_is_allowed_only_when_explicit_and_sourced():
    data = inputs()
    data["financial_assumptions"] = financial()
    data["financial_assumptions"]["repairs"][0]["quantity"] = 0
    data["financial_assumptions"]["downtime"].update(low_usd=0, high_usd=0)
    value = evaluate_valuation(data, [observation()], context())
    assert value["repair_cost"]["low"] == 0
    assert value["downtime_cost"]["low"] == 0
    assert value["current_condition"]["low"] == 1_000_000
    assert value["basis"] == "conditional"


def test_conflicting_reviewed_values_are_not_arbitrarily_selected():
    data = inputs()
    data["financial_assumptions"] = financial()
    data["financial_assumptions"]["reviewed_values"].append(deepcopy(financial()["reviewed_values"][0]))
    value = evaluate_valuation(data, [observation()], context())
    assert value["after_repair"]["low"] is None
    assert value["current_condition"]["low"] is None
    assert any("reconciliation" in x for x in value["limitations"])


@pytest.mark.parametrize("dates", [
    {"observed_at": "2026-11-15", "updated_at": "2026-11-13T12:00:00Z"},
    {"observed_at": "2026-11-12", "updated_at": "2026-11-15T12:00:00Z"},
    {"observed_at": "2026-11-12", "updated_at": None},
    {"observed_at": None, "updated_at": "2026-11-13T12:00:00Z"},
])
def test_historical_repair_requires_condition_and_verification_known_by_cutoff(dates):
    data = inputs()
    data["financial_assumptions"] = financial()
    value = evaluate_valuation(data, [{**observation(), **dates}], context(mode="historical_replay"))
    assert value["repair_cost"]["low"] is None
    assert value["current_condition"]["low"] is None


def test_historical_verified_condition_with_dated_review_supports_scenario():
    data = inputs()
    data["financial_assumptions"] = financial()
    report = {**observation(), "observed_at": "2026-11-12", "updated_at": "2026-11-13T12:00:00Z"}
    value = evaluate_valuation(data, [report], context(mode="historical_replay"))
    assert value["current_condition"]["low"] == 997787.4


def test_future_condition_cannot_support_current_repair_even_outside_replay():
    data = inputs()
    data["financial_assumptions"] = financial()
    value = evaluate_valuation(data, [{**observation(), "observed_at": "2027-01-01"}], context())
    assert value["repair_cost"]["low"] is None


@pytest.mark.parametrize("malformed", [
    [1, 2], "invalid", False, {"repairs": "invalid"}, {"repairs": [None]},
    {"reviewed_values": {"condition": "current"}}, {"reviewed_values": [17]},
    {"reviewed_values": [{"condition": ["current"]}]}, {"reviewed_values": ["current"]},
    {"downtime": [1]}, {"repairs": [{"scope_key": []}]},
    {"repairs": [{"source_ids": {"quote": True}}]},
    {"repairs": [{"location": "roof"}]},
])
def test_malformed_financial_containers_return_unavailable_without_crashing(malformed):
    data = inputs()
    data["financial_assumptions"] = malformed
    value = evaluate_valuation(data, [observation()], context())
    assert value["current_condition"]["low"] is None
    assert any("Financial assumptions rejected" in x for x in value["limitations"])
    assert value["benchmark"]["low"] == 200000
