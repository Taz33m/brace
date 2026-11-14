"""Pydantic mirror of docs/recovery-handoffs/shared-contract.ts (contract v1, lead-owned).

Field names and shapes match the TypeScript exactly; tests/test_recovery_platform_models.py
checks this. Do not add or rename wire fields here without a contract change from the lead.
"""
from __future__ import annotations

from typing import Annotated, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, model_validator

ID = str
SourceDate = str
CaseMode = Literal["observed_recovery", "historical_replay", "scenario_exercise"]
ValueBasis = Literal["market_supported", "conditional", "insufficient_evidence"]
ObservationStatus = Literal["reported", "under_review", "verified", "dismissed"]
TaskStatus = Literal["proposed", "approved", "accepted", "in_progress", "completion_submitted",
                     "verified", "cancelled"]
AssessmentStatus = Literal["running", "draft", "published", "stale", "failed"]
ReportCategory = Literal["water", "roof", "smoke_or_fire", "power_or_access", "other"]
SupportCategory = Literal["housing", "access", "communication", "other"]


class Wire(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PropertyRef(Wire):
    dataset: Literal["commercial_property", "residential_property"]
    id: str


class LocationRef(Wire):
    location_id: ID
    label: str
    structure_id: Optional[str]
    scan_id: Optional[str]
    sweep_id: Optional[str]
    room_id: Optional[str]
    unit_label: Optional[str]
    binding: Literal["verified_unit", "verified_space", "representative_layout", "unverified", "unmapped"]
    longitude: Optional[float]
    latitude: Optional[float]
    bearing_degrees: Optional[float]


class MediaRef(Wire):
    media_id: ID
    url: str
    alt: str
    mime_type: str


class Evidence(Wire):
    evidence_id: ID
    kind: Literal["costar_record", "vexcel_image", "matterport_view", "resident_photo", "inspection",
                  "cost_source", "official_notice"]
    source_id: str
    source_label: str
    captured_at: Optional[SourceDate]
    effective_at: Optional[SourceDate]
    available_at: Optional[SourceDate]
    received_at: str
    model_created_at: Optional[SourceDate]
    location: Optional[LocationRef]
    media: Optional[MediaRef]
    summary: str
    limitations: list[str]


class Observation(Wire):
    observation_id: ID
    title: str
    description: str
    basis: Literal["reported", "observed", "inferred"]
    status: ObservationStatus
    evidence_ids: list[ID]
    location: Optional[LocationRef]
    observed_at: Optional[SourceDate]
    updated_at: str
    verification_note: Optional[str]
    verified_by: Optional[str]


class MoneyRange(Wire):
    currency: Literal["USD"]
    low: Optional[float]
    high: Optional[float]
    point: Optional[float]
    basis: ValueBasis
    range_kind: Literal["source_range", "scenario", "comparable_dispersion", "calibrated_confidence"]
    method: str
    source_ids: list[str]
    unavailable_reason: Optional[str]

    @model_validator(mode="after")
    def _range(self):
        if (self.low is None) != (self.high is None):
            raise ValueError("low and high must both be null or both be set")
        if self.low is not None and self.low > self.high:
            raise ValueError("low must not exceed high")
        return self


class Assumption(Wire):
    assumption_id: ID
    label: str
    value: str
    basis: Literal["source", "user_supplied", "scenario"]
    source_ids: list[str]


class Comparable(Wire):
    comp_id: ID
    property_ref: PropertyRef
    label: str
    transaction_date: Optional[SourceDate]
    date_basis: Literal["deed_recorded", "closed", "unknown"]
    price_usd: Optional[float]
    price_status: str
    allocated: bool
    included: bool
    reason: str
    source_ids: list[str]


class RepairLine(Wire):
    line_id: ID
    description: str
    location: Optional[LocationRef]
    quantity: Optional[float]
    quantity_unit: str
    quantity_basis: str
    rate_low_usd: Optional[float]
    rate_high_usd: Optional[float]
    total: MoneyRange
    source_ids: list[str]


class ValuationResult(Wire):
    basis: ValueBasis
    effective_at: SourceDate
    benchmark: MoneyRange
    current_condition: MoneyRange
    after_repair: MoneyRange
    repair_cost: MoneyRange
    downtime_cost: MoneyRange
    comparables: list[Comparable]
    repair_lines: list[RepairLine]
    assumptions: list[Assumption]
    limitations: list[str]


class Assessment(Wire):
    assessment_id: ID
    run_id: ID
    base_analysis_revision: int
    status: AssessmentStatus
    headline: str
    summary: str
    created_at: str
    published_at: Optional[str]
    valuation: Optional[ValuationResult]
    observation_ids: list[ID]
    unresolved_questions: list[str]
    failure_reason: Optional[str]


class RecoveryTask(Wire):
    task_id: ID
    revision: int
    title: str
    scope: str
    status: TaskStatus
    location: Optional[LocationRef]
    evidence_ids: list[ID]
    household_ids: list[ID]
    assignee_label: Optional[str]
    confirmation_source: Optional[str]
    confirmed_schedule: Optional[str]
    completion_evidence_ids: list[ID]
    updated_at: str
    superseded_scope: Optional[str]


class PublishedNotice(Wire):
    notice_id: ID
    title: str
    body: str
    published_at: str
    published_by: str
    source_ids: list[str]


class RecoveryCaseSummary(Wire):
    case_id: ID
    property_ref: PropertyRef
    property_name: str
    address: str
    city: str
    incident_name: str
    incident_at: SourceDate
    assessment_as_of: SourceDate
    mode: CaseMode
    mode_label: str
    case_revision: int
    analysis_revision: int
    pending_reports: int
    pending_tasks: int
    next_action: str


class HouseholdLabel(Wire):
    household_id: ID
    unit_label: Optional[str]


class CaseEvent(Wire):
    event_id: int
    case_id: ID
    case_revision: int
    analysis_revision: int
    type: str
    at: str
    entity_id: Optional[ID]
    public_summary: Optional[str]


class ResidentReport(Wire):
    report_id: ID
    household_id: ID
    category: ReportCategory
    text: str
    location: Optional[LocationRef]
    location_description: Optional[str]
    observed_at: Optional[SourceDate]
    received_at: str
    status: ObservationStatus
    media: list[MediaRef]
    public_status_detail: str


class SupportReceipt(Wire):
    request_id: ID
    household_id: ID
    category: SupportCategory
    description: str
    status: Literal["received", "under_review", "responded", "closed"]
    received_at: str
    public_status_detail: str
    duplicate: bool


class OwnerCaseView(Wire):
    case: RecoveryCaseSummary
    evidence: list[Evidence]
    observations: list[Observation]
    assessments: list[Assessment]
    current_assessment_id: Optional[ID]
    tasks: list[RecoveryTask]
    reports: list[ResidentReport]
    support_requests: list[SupportReceipt]
    notices: list[PublishedNotice]
    household_labels: list[HouseholdLabel]
    events: list[CaseEvent]
    event_cursor: int


# ---- Owner commands: discriminated on `type`; every command carries expected_revision.

class _Command(Wire):
    expected_revision: int


class StartAssessment(_Command):
    type: Literal["start_assessment"]


class PublishAssessment(_Command):
    type: Literal["publish_assessment"]
    assessment_id: ID


class ReviewObservation(_Command):
    type: Literal["review_observation"]
    observation_id: ID
    status: ObservationStatus
    note: str
    evidence_ids: list[ID]


class TransitionTask(_Command):
    type: Literal["transition_task"]
    task_id: ID
    expected_task_revision: int
    status: TaskStatus
    note: str
    confirmation_source: Optional[str]
    evidence_ids: list[ID]


class PublishNotice(_Command):
    type: Literal["publish_notice"]
    title: str
    body: str
    household_ids: Optional[list[ID]]
    source_ids: list[str]


class CreateInvitation(_Command):
    type: Literal["create_invitation"]
    household_id: ID


OwnerCommand = Annotated[
    Union[StartAssessment, PublishAssessment, ReviewObservation, TransitionTask, PublishNotice,
          CreateInvitation],
    Field(discriminator="type"),
]


class CommandResult(Wire):
    case_revision: int
    analysis_revision: int
    run_id: Optional[ID]
    invitation_token: Optional[str]
    invitation_expires_at: Optional[str]


# ---- Resident side. Inputs never contain a household ID, role, or client-certified binding.

class ReportInput(Wire):
    category: ReportCategory
    text: str = Field(max_length=4000)
    selected_location_id: Optional[ID]
    location_description: Optional[str] = Field(default=None, max_length=500)
    observed_at: Optional[SourceDate]
    upload_ids: list[ID] = Field(max_length=10)


class UploadedMedia(Wire):
    upload_id: ID
    media: MediaRef


class ReportReceipt(Wire):
    report: ResidentReport
    case_revision: int
    analysis_revision: int
    duplicate: bool


class SupportInput(Wire):
    category: SupportCategory
    description: str = Field(max_length=4000)


class ResidentTask(Wire):
    task_id: ID
    revision: int
    title: str
    status: TaskStatus
    public_status_detail: str
    confirmed_schedule: Optional[str]
    updated_at: str


class ResidentHome(Wire):
    case_id: ID
    case_revision: int
    property_name: str
    address: str
    unit_label: Optional[str]
    unit_confirmed: bool
    mode: CaseMode
    mode_label: str
    incident_name: str
    updated_at: str
    selectable_locations: list[LocationRef]
    reports: list[ResidentReport]
    support_requests: list[SupportReceipt]
    tasks: list[ResidentTask]
    notices: list[PublishedNotice]
    event_cursor: int


class ApiErrorDetail(Wire):
    code: str
    message: str
    retryable: bool
    current_revision: Optional[int] = None


class ApiErrorBody(Wire):
    error: ApiErrorDetail


# ---- Session request bodies (contract HTTP table).

class OwnerSessionInput(Wire):
    secret: str


class ResidentSessionInput(Wire):
    invitation_token: str


# ---- Store-only bootstrap input (lead domain operation; not a public route).

class CaseInput(Wire):
    case_id: Optional[ID] = None
    property_ref: PropertyRef
    property_name: str
    address: str
    city: str
    incident_name: str
    incident_at: SourceDate
    assessment_as_of: SourceDate
    mode: CaseMode
    mode_label: Optional[str] = None
    next_action: str = "Review dated evidence and obtain verified condition and cost inputs"
    evidence: list[Evidence] = []
    locations: list[LocationRef] = []

    @classmethod
    def from_seed(cls, seed: dict) -> "CaseInput":
        """Accept the lead's make_case_seed(...) OwnerCaseView."""
        case = seed["case"]
        keep = {k: case[k] for k in ("case_id", "property_ref", "property_name", "address", "city",
                                     "incident_name", "incident_at", "assessment_as_of", "mode",
                                     "mode_label", "next_action") if k in case}
        return cls(**keep, evidence=seed.get("evidence", []), locations=seed.get("locations", []))
