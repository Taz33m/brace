"""Deterministic recovery valuation. The model cannot supply prices or loss percentages.

``evaluate_valuation`` consumes normalized sources plus owner-supplied financial
assumptions and returns the exact ValuationResult wire shape. Absent sources leave
amounts unavailable. Displayed benchmark dispersion is never a damage estimate.
"""
from __future__ import annotations

from decimal import Decimal

from .comparables import select_comparables
from .costs import downtime_cost, repair_costs
from .financial_models import (FinancialInputError, assumption, bounds, money, same_effective_date,
                               source_index, unavailable, validate_financial_shape, validate_sources)


def _reviewed_values(financial: dict, evidence: dict[str, dict], context: dict) -> tuple[dict, list[dict], list[str]]:
    values, assumptions, limitations = {}, [], []
    items = financial.get("reviewed_values") or []
    conditions = [x.get("condition") for x in items]
    for item in items:
        condition = item.get("condition")
        try:
            if condition not in {"current", "restored"}:
                raise FinancialInputError("Reviewed value condition must be current or restored.")
            if conditions.count(condition) != 1:
                raise FinancialInputError("Conflicting reviewed values for the same condition require reconciliation.")
            same_effective_date(item.get("effective_at"), context)
            low, high = bounds(item.get("low_usd"), item.get("high_usd"), "Reviewed value")
            if not item.get("method") or not item.get("reviewed_by") or not item.get("review_note"):
                raise FinancialInputError("A reviewed estimate requires method, reviewer identity, and review note.")
            basis = item.get("basis")
            if basis not in {"source", "user_supplied", "scenario"}:
                raise FinancialInputError("Reviewed value basis must be source, user_supplied, or scenario.")
            sources = validate_sources(item.get("source_ids"), evidence, context,
                                       kinds={"costar_record", "inspection"})
            values[condition] = money(low, high, method=f"Reviewed {condition}-condition estimate: {item['method']}",
                                      source_ids=sources, basis="market_supported" if basis == "source" else "conditional",
                                      range_kind="source_range" if basis == "source" else "scenario")
            assumptions.append(assumption(f"reviewed-{condition}", f"Reviewed {condition}-condition value",
                                          f"Reviewer: {item['reviewed_by']}. {item['review_note']}", sources, basis))
        except FinancialInputError as exc:
            limitations.append(f"Reviewed {condition or 'unspecified'} value: {exc}")
    return values, assumptions, limitations


def evaluate_valuation(inputs: dict, observations: list[dict], context: dict) -> dict:
    """Calculate using immutable inputs. No IO, model calls, or source mutations.

    Inputs: ``subject``, normalized ``sales``, shared-contract ``evidence`` and
    optional ``financial_assumptions`` (reviewed_values, repairs,
    repair_scope_complete/source_ids, downtime). See docs/recovery-core.md.
    """
    input_issues = []
    try:
        financial = validate_financial_shape(inputs.get("financial_assumptions"))
    except FinancialInputError as exc:
        financial = {}
        input_issues.append(f"Financial assumptions rejected: {exc}")
    evidence = source_index(inputs.get("evidence") or [])
    comparables, benchmark, limitations = select_comparables(inputs.get("subject") or {}, inputs.get("sales") or [], context)
    limitations.extend(input_issues)
    reviewed, assumptions, notes = _reviewed_values(financial, evidence, context)
    limitations.extend(notes)
    lines, repairs, repair_assumptions, notes = repair_costs(financial, observations, evidence, context)
    assumptions.extend(repair_assumptions)
    limitations.extend(notes)
    downtime, downtime_assumptions, notes = downtime_cost(financial, evidence, context)
    assumptions.extend(downtime_assumptions)
    limitations.extend(notes)
    after_repair = reviewed.get("restored", unavailable("A reviewed restored-condition estimate at the assessment date is required. Comparable screening alone does not establish restored condition."))
    current = reviewed.get("current", unavailable("No reviewed current-condition market estimate or complete conditional cost-to-cure scenario is available."))
    if "current" not in reviewed and after_repair["low"] is not None and repairs["low"] is not None and downtime["low"] is not None:
        # Interval subtraction: worst costs against low restored value, and vice versa.
        raw_low = Decimal(str(after_repair["low"])) - Decimal(str(repairs["high"])) - Decimal(str(downtime["high"]))
        raw_high = Decimal(str(after_repair["high"])) - Decimal(str(repairs["low"])) - Decimal(str(downtime["low"]))
        current = money(max(Decimal(0), raw_low), max(Decimal(0), raw_high),
                        method="Conditional cost-to-cure: same-date restored-condition benchmark − remaining repairs − incremental disruption",
                        source_ids=after_repair["source_ids"] + repairs["source_ids"] + downtime["source_ids"],
                        basis="conditional", range_kind="scenario")
        assumptions.append(assumption("cost-to-cure", "Conditional cost-to-cure relationship",
                                      "Assumes no additional stigma, market shift, financing burden, undiscovered damage, or costs outside the reviewed scope. This is a scenario, not an observed market price.",
                                      current["source_ids"], "scenario"))
        if raw_low < 0:
            limitations.append("Cost-to-cure subtraction falls below zero and is floored at zero for display; this does not estimate land, demolition, or distressed-sale value.")
    if "current" in reviewed:
        limitations.append("The reviewed current-condition estimate is displayed directly; repair and disruption costs are not deducted again.")
    pending = [x for x in observations if x.get("status") in {"reported", "under_review"}]
    if pending:
        limitations.append(f"{len(pending)} condition report(s) remain unverified. They do not automatically reduce the value; any supplied hypothetical repair scopes are explicitly conditional.")
    limitations.extend([
        "No insurance proceeds or guaranteed recovery in market value are assumed.",
        "Asking rents do not establish collected rent or NOI; no income capitalization is inferred.",
        "This decision-support calculation does not establish habitability, occupancy clearance, or a formal appraisal.",
    ])
    return {"basis": current["basis"], "effective_at": context["assessment_as_of"], "benchmark": benchmark,
            "current_condition": current, "after_repair": after_repair, "repair_cost": repairs, "downtime_cost": downtime,
            "comparables": comparables, "repair_lines": lines, "assumptions": assumptions,
            "limitations": list(dict.fromkeys(limitations))}
