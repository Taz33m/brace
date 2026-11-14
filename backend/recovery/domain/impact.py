"""Stateless owner what-if arithmetic over registered source quantities."""
from copy import deepcopy
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .financial_models import FinancialInputError, money, number, unavailable
from .service import screen_case, valuation_inputs


class ImpactInput(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    expected_analysis_revision: int = Field(strict=True, ge=1)
    structure_id: str = Field(min_length=1, max_length=128)
    affected_percent: float = Field(strict=True, ge=0, le=100)
    unit_cost_low: float = Field(strict=True, ge=0, le=1_000_000)
    unit_cost_high: float = Field(strict=True, ge=0, le=1_000_000)
    affected_units: int = Field(strict=True, ge=0, le=1_000_000)
    monthly_income_per_unit: float = Field(strict=True, ge=0, le=1_000_000)
    downtime_months: float = Field(strict=True, ge=0, le=120)

    @model_validator(mode="after")
    def ordered_rates(self):
        if self.unit_cost_low > self.unit_cost_high:
            raise ValueError("The low unit cost must not exceed the high unit cost.")
        return self


LIMITATIONS = [
    "This is an owner-entered conditional planning scenario, not observed disaster loss or an appraisal.",
    "Vexcel footprint area is horizontal building footprint, not measured roof surface. The affected percentage and cost per footprint square foot are owner assumptions.",
    "Dated roof attributes and before/after imagery do not automatically establish the affected percentage or disaster causation.",
    "The CoStar comparable benchmark is a descriptive, unadjusted price proxy; it is not a restored-condition appraisal.",
    "Disruption is affected units × owner-entered monthly income per unit × downtime months. It excludes repairs and is not capitalized as perpetual income loss.",
    "No insurance proceeds, financing, hidden damage, market stigma or guaranteed recovery are included. This preview is not saved or published.",
]


def _quantity(value, *, integral=False):
    try:
        amount = number(value, "Source quantity", positive=True)
        if integral and amount != amount.to_integral_value():
            return None
        return int(amount) if integral else float(amount)
    except FinancialInputError:
        return None


def _benchmark(snapshot: dict, inventory: dict) -> dict:
    revision = snapshot["case"]["analysis_revision"]
    assessments = [row for row in snapshot.get("assessments", [])
                   if row.get("base_analysis_revision") == revision and row.get("status") in {"draft", "published"}
                   and isinstance(row.get("valuation"), dict)]
    chosen = next((row for row in assessments if row.get("assessment_id") == snapshot.get("current_assessment_id")), None)
    chosen = chosen or (assessments[-1] if assessments else None)
    if chosen:
        benchmark = chosen["valuation"].get("benchmark")
    else:
        benchmark = screen_case(snapshot, valuation_inputs(inventory, snapshot))["valuation"]["benchmark"]
    return deepcopy(benchmark) if isinstance(benchmark, dict) else unavailable("Comparable benchmark is unavailable.")


def impact_sources(inventory: dict, snapshot: dict) -> dict:
    structures = [{"structure_id": row["id"], "label": f"Structure {row['id']}",
                   "footprint_sqft": _quantity(row.get("footprint_sqft")),
                   "source_id": row.get("source_id"), "analysis_date": row.get("roof_analysis_date")}
                  for row in inventory.get("structures", [])]
    return {"case_id": snapshot["case"]["case_id"], "analysis_revision": snapshot["case"]["analysis_revision"],
            "structures": structures, "subject_units": _quantity(inventory.get("subject", {}).get("units"), integral=True),
            "benchmark": _benchmark(snapshot, inventory), "limitations": list(LIMITATIONS)}


def calculate_impact(inventory: dict, snapshot: dict, request: ImpactInput) -> dict:
    source = impact_sources(inventory, snapshot)
    structure = next((row for row in source["structures"] if row["structure_id"] == request.structure_id), None)
    if structure is None:
        raise FinancialInputError("Choose a structure in this case's registered source inventory.")
    units = source["subject_units"]
    if units is not None and request.affected_units > units:
        raise FinancialInputError("Affected units cannot exceed the property's recorded unit count.")
    footprint = structure["footprint_sqft"]
    source_ids = [structure["source_id"]] if structure["source_id"] else []
    quantity = None if footprint is None else number(footprint, "Footprint") * number(request.affected_percent, "Affected percent") / Decimal(100)
    repair = unavailable("The selected structure has no usable sourced footprint area.") if quantity is None else money(
        quantity * number(request.unit_cost_low, "Low unit cost"), quantity * number(request.unit_cost_high, "High unit cost"),
        method="Source footprint × owner-entered affected percentage × owner-entered cost per footprint sq ft", source_ids=source_ids)
    unit_sources = list(inventory.get("subject", {}).get("source_ids") or [])
    disruption = unavailable("The property's recorded unit count is unavailable; disruption cannot be bounded.")
    if units is not None:
        amount = number(request.affected_units, "Affected units") * number(request.monthly_income_per_unit, "Monthly income") * number(request.downtime_months, "Downtime")
        disruption = money(amount, amount, method="Affected units × monthly income per unit × downtime months; owner assumptions",
                           source_ids=unit_sources)
    total = unavailable("Both sourced footprint quantity and property unit count are required for the combined scenario.")
    if repair["low"] is not None and disruption["low"] is not None:
        total = money(Decimal(str(repair["low"])) + Decimal(str(disruption["low"])),
                      Decimal(str(repair["high"])) + Decimal(str(disruption["high"])),
                      method="Footprint-based repair proxy + finite disruption scenario", source_ids=source_ids + unit_sources)
    benchmark = source["benchmark"]
    current = unavailable("A usable comparable benchmark and complete scenario costs are required.")
    limitations = list(source["limitations"])
    if total["low"] is not None and benchmark.get("low") is not None and benchmark.get("high") is not None:
        low, high = number(benchmark["low"], "Benchmark low"), number(benchmark["high"], "Benchmark high")
        if low <= high:
            raw_low, raw_high = low - Decimal(str(total["high"])), high - Decimal(str(total["low"]))
            current = money(max(Decimal(0), raw_low), max(Decimal(0), raw_high),
                method="Descriptive comparable benchmark proxy minus owner-entered scenario costs; not current market value",
                source_ids=(benchmark.get("source_ids") or []) + total["source_ids"])
            if raw_low < 0:
                limitations.append("The proxy subtraction is floored at zero; this does not estimate land, demolition or distressed-sale value.")
    assumptions = request.model_dump(exclude={"structure_id", "expected_analysis_revision"})
    return {"case_id": source["case_id"], "analysis_revision": source["analysis_revision"],
            "preview_only": True, "basis": "conditional", "structure": structure, "subject_units": units,
            "quantity_sqft": float(quantity) if quantity is not None else None,
            "repair_cost": repair, "disruption_cost": disruption, "total_cost": total,
            "benchmark": benchmark, "current_range": current, "assumptions": assumptions,
            "source_ids": list(dict.fromkeys(source_ids + unit_sources + (benchmark.get("source_ids") or []))),
            "summary": f"Footprint-based planning scenario for {structure['label']}; all damage extent, unit costs and income inputs were entered by the owner.",
            "limitations": limitations}
