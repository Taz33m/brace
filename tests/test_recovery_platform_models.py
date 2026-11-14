"""Wire models must match docs/recovery-handoffs/shared-contract.ts field for field."""
from __future__ import annotations

import re
from pathlib import Path

import pytest
from pydantic import TypeAdapter, ValidationError

from backend.recovery.platform import models

CONTRACT = Path(__file__).resolve().parents[1] / "docs" / "recovery-handoffs" / "shared-contract.ts"


def _ts_interfaces() -> dict[str, set[str]]:
    text = CONTRACT.read_text()
    out: dict[str, set[str]] = {}
    for match in re.finditer(r"export interface (\w+) \{(.*?)\n\}", text, re.S):
        name, body = match.group(1), match.group(2)
        # Only top-level fields (two-space indent), not nested object literal members.
        out[name] = set(re.findall(r"^  (\w+)\??:", body, re.M))
    return out


def test_every_ts_interface_has_matching_model_fields():
    interfaces = _ts_interfaces()
    assert len(interfaces) > 20
    for name, fields in interfaces.items():
        if name == "ResidentApi":
            continue
        model = getattr(models, name, None)
        assert model is not None, f"missing model {name}"
        assert set(model.model_fields) == fields, name


def test_owner_command_union_matches_ts_command_types():
    text = CONTRACT.read_text()
    ts_types = set(re.findall(r'\{type: "(\w+)"', text))
    adapter = TypeAdapter(models.OwnerCommand)
    for t in ts_types:
        with pytest.raises(ValidationError):
            adapter.validate_python({"type": t})  # missing expected_revision / fields
    cmd = adapter.validate_python({"type": "start_assessment", "expected_revision": 3})
    assert cmd.type == "start_assessment" and cmd.expected_revision == 3


def test_owner_command_union_rejects_unknown_type():
    with pytest.raises(ValidationError):
        TypeAdapter(models.OwnerCommand).validate_python({"type": "run_sql", "expected_revision": 1})


def test_money_range_low_high_both_null_or_ordered():
    base = dict(currency="USD", point=None, basis="conditional", range_kind="scenario",
                method="m", source_ids=[], unavailable_reason="unknown")
    models.MoneyRange(low=None, high=None, **base)
    models.MoneyRange(low=1, high=2, **base)
    with pytest.raises(ValidationError):
        models.MoneyRange(low=1, high=None, **base)
    with pytest.raises(ValidationError):
        models.MoneyRange(low=3, high=2, **base)


def test_report_input_has_no_household_and_rejects_extra_fields():
    with pytest.raises(ValidationError):
        models.ReportInput(category="water", text="x", selected_location_id=None,
                           location_description=None, observed_at=None, upload_ids=[],
                           household_id="h_other")


def test_error_envelope_shape():
    from backend.recovery.platform.errors import PlatformError

    err = PlatformError(409, "revision_conflict", "This case changed.", retryable=True, current_revision=12)
    assert err.envelope() == {"error": {"code": "revision_conflict", "message": "This case changed.",
                                        "retryable": True, "current_revision": 12}}
