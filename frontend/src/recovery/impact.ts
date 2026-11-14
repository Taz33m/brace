import type { MoneyRange } from "../../../docs/recovery-handoffs/shared-contract";

export interface ImpactStructure {
  structure_id: string; label: string; footprint_sqft: number | null;
  source_id: string | null; analysis_date: string | null;
}
export interface ImpactInputs {
  case_id: string; analysis_revision: number; structures: ImpactStructure[];
  subject_units: number | null; benchmark: MoneyRange; limitations: string[];
}
export interface ImpactAssumptions {
  affected_percent: number; unit_cost_low: number; unit_cost_high: number;
  affected_units: number; monthly_income_per_unit: number; downtime_months: number;
}
export interface ImpactRequest extends ImpactAssumptions {
  expected_analysis_revision: number; structure_id: string;
}
export interface ImpactResult {
  case_id: string; analysis_revision: number; subject_units: number | null;
  benchmark: MoneyRange; limitations: string[];
  preview_only: true; basis: "conditional"; structure: ImpactStructure;
  quantity_sqft: number | null; repair_cost: MoneyRange; disruption_cost: MoneyRange;
  total_cost: MoneyRange; current_range: MoneyRange; assumptions: ImpactAssumptions;
  source_ids: string[]; summary: string;
}
