/** Brace recovery wire contract v1. Lead owns semantics; no runtime dependencies. */
export type ID = string;
export type SourceDate = string;
export type CaseMode = "observed_recovery" | "historical_replay" | "scenario_exercise";
export type ValueBasis = "market_supported" | "conditional" | "insufficient_evidence";
export type ObservationStatus = "reported" | "under_review" | "verified" | "dismissed";
export type TaskStatus = "proposed" | "approved" | "accepted" | "in_progress" | "completion_submitted" | "verified" | "cancelled";
export type AssessmentStatus = "running" | "draft" | "published" | "stale" | "failed";

export interface PropertyRef {
  dataset: "commercial_property" | "residential_property";
  id: string;
}
export interface LocationRef {
  location_id: ID;
  label: string;
  structure_id: string | null;
  scan_id: string | null;
  sweep_id: string | null;
  room_id: string | null;
  unit_label: string | null;
  binding: "verified_unit" | "verified_space" | "representative_layout" | "unverified" | "unmapped";
  longitude: number | null;
  latitude: number | null;
  bearing_degrees: number | null;
}
export interface MediaRef {
  media_id: ID;
  url: string;
  alt: string;
  mime_type: string;
}
export interface Evidence {
  evidence_id: ID;
  kind: "costar_record" | "vexcel_image" | "matterport_view" | "resident_photo" | "inspection" | "cost_source" | "official_notice";
  source_id: string;
  source_label: string;
  captured_at: SourceDate | null;
  effective_at: SourceDate | null;
  available_at: SourceDate | null;
  received_at: string;
  model_created_at: SourceDate | null;
  location: LocationRef | null;
  media: MediaRef | null;
  summary: string;
  limitations: string[];
}
export interface Observation {
  observation_id: ID;
  title: string;
  description: string;
  basis: "reported" | "observed" | "inferred";
  status: ObservationStatus;
  evidence_ids: ID[];
  location: LocationRef | null;
  observed_at: SourceDate | null;
  updated_at: string;
  verification_note: string | null;
  verified_by: string | null;
}
export interface MoneyRange {
  currency: "USD";
  low: number | null;
  high: number | null;
  point: number | null;
  basis: ValueBasis;
  range_kind: "source_range" | "scenario" | "comparable_dispersion" | "calibrated_confidence";
  method: string;
  source_ids: string[];
  unavailable_reason: string | null;
}
export interface Assumption {
  assumption_id: ID;
  label: string;
  value: string;
  basis: "source" | "user_supplied" | "scenario";
  source_ids: string[];
}
export interface Comparable {
  comp_id: ID;
  property_ref: PropertyRef;
  label: string;
  transaction_date: SourceDate | null;
  date_basis: "deed_recorded" | "closed" | "unknown";
  price_usd: number | null;
  price_status: string;
  allocated: boolean;
  included: boolean;
  reason: string;
  source_ids: string[];
}
export interface RepairLine {
  line_id: ID;
  description: string;
  location: LocationRef | null;
  quantity: number | null;
  quantity_unit: string;
  quantity_basis: string;
  rate_low_usd: number | null;
  rate_high_usd: number | null;
  total: MoneyRange;
  source_ids: string[];
}
export interface ValuationResult {
  basis: ValueBasis;
  effective_at: SourceDate;
  benchmark: MoneyRange;
  current_condition: MoneyRange;
  after_repair: MoneyRange;
  repair_cost: MoneyRange;
  downtime_cost: MoneyRange;
  comparables: Comparable[];
  repair_lines: RepairLine[];
  assumptions: Assumption[];
  limitations: string[];
}
export interface Assessment {
  assessment_id: ID;
  run_id: ID;
  base_analysis_revision: number;
  status: AssessmentStatus;
  headline: string;
  summary: string;
  created_at: string;
  published_at: string | null;
  valuation: ValuationResult | null;
  observation_ids: ID[];
  unresolved_questions: string[];
  failure_reason: string | null;
}
export interface RecoveryTask {
  task_id: ID;
  revision: number;
  title: string;
  scope: string;
  status: TaskStatus;
  location: LocationRef | null;
  evidence_ids: ID[];
  household_ids: ID[];
  assignee_label: string | null;
  confirmation_source: string | null;
  confirmed_schedule: string | null;
  completion_evidence_ids: ID[];
  updated_at: string;
  superseded_scope: string | null;
}
export interface PublishedNotice {
  notice_id: ID;
  title: string;
  body: string;
  published_at: string;
  published_by: string;
  source_ids: string[];
}
export interface RecoveryCaseSummary {
  case_id: ID;
  property_ref: PropertyRef;
  property_name: string;
  address: string;
  city: string;
  incident_name: string;
  incident_at: SourceDate;
  assessment_as_of: SourceDate;
  mode: CaseMode;
  mode_label: string;
  case_revision: number;
  analysis_revision: number;
  pending_reports: number;
  pending_tasks: number;
  next_action: string;
}
export interface OwnerCaseView {
  case: RecoveryCaseSummary;
  evidence: Evidence[];
  observations: Observation[];
  assessments: Assessment[];
  current_assessment_id: ID | null;
  tasks: RecoveryTask[];
  reports: ResidentReport[];
  support_requests: SupportReceipt[];
  notices: PublishedNotice[];
  household_labels: {household_id: ID; unit_label: string | null}[];
  events: CaseEvent[];
  event_cursor: number;
}
export type OwnerCommand = {expected_revision: number} & (
  | {type: "start_assessment"}
  | {type: "publish_assessment"; assessment_id: ID}
  | {type: "review_observation"; observation_id: ID; status: ObservationStatus; note: string; evidence_ids: ID[]}
  | {type: "transition_task"; task_id: ID; expected_task_revision: number; status: TaskStatus; note: string; confirmation_source: string | null; evidence_ids: ID[]}
  | {type: "publish_notice"; title: string; body: string; household_ids: ID[] | null; source_ids: string[]}
  | {type: "create_invitation"; household_id: ID}
);
export interface CommandResult {
  case_revision: number;
  analysis_revision: number;
  run_id: ID | null;
  invitation_token: string | null;
  invitation_expires_at: string | null;
}
export interface CaseEvent {
  event_id: number;
  case_id: ID;
  case_revision: number;
  analysis_revision: number;
  type: string;
  at: string;
  entity_id: ID | null;
  public_summary: string | null;
}

// Resident inputs never contain a household ID, role, or client-certified binding.
export interface ReportInput {
  category: "water" | "roof" | "smoke_or_fire" | "power_or_access" | "other";
  text: string;
  selected_location_id: ID | null;
  location_description: string | null;
  observed_at: SourceDate | null;
  upload_ids: ID[];
}
export interface UploadedMedia {
  upload_id: ID;
  media: MediaRef;
}
export interface ResidentReport {
  report_id: ID;
  household_id: ID;
  category: ReportInput["category"];
  text: string;
  location: LocationRef | null;
  location_description: string | null;
  observed_at: SourceDate | null;
  received_at: string;
  status: ObservationStatus;
  media: MediaRef[];
  public_status_detail: string;
}
export interface ReportReceipt {
  report: ResidentReport;
  case_revision: number;
  analysis_revision: number;
  duplicate: boolean;
}
export interface SupportInput {
  category: "housing" | "access" | "communication" | "other";
  description: string;
}
export interface SupportReceipt {
  request_id: ID;
  household_id: ID;
  category: SupportInput["category"];
  description: string;
  status: "received" | "under_review" | "responded" | "closed";
  received_at: string;
  public_status_detail: string;
  duplicate: boolean;
}
export interface ResidentTask {
  task_id: ID;
  revision: number;
  title: string;
  status: TaskStatus;
  public_status_detail: string;
  confirmed_schedule: string | null;
  updated_at: string;
}
export interface ResidentHome {
  case_id: ID;
  case_revision: number;
  property_name: string;
  address: string;
  unit_label: string | null;
  unit_confirmed: boolean;
  mode: CaseMode;
  mode_label: string;
  incident_name: string;
  updated_at: string;
  selectable_locations: LocationRef[];
  reports: ResidentReport[];
  support_requests: SupportReceipt[];
  tasks: ResidentTask[];
  notices: PublishedNotice[];
  event_cursor: number;
}
export interface ResidentApi {
  get_home(): Promise<ResidentHome>;
  upload_image(file: File, idempotency_key: string): Promise<UploadedMedia>;
  submit_report(input: ReportInput, idempotency_key: string): Promise<ReportReceipt>;
  request_support(input: SupportInput, idempotency_key: string): Promise<SupportReceipt>;
  subscribe(args: {
    after: number;
    on_event: (event: CaseEvent) => void;
    on_connection: (state: "connected" | "reconnecting" | "expired") => void;
  }): () => void;
}
export interface ApiErrorBody {
  error: {
    code: string;
    message: string;
    retryable: boolean;
    current_revision?: number;
  };
}
