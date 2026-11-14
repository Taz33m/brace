"""Remaining cost scopes and incremental disruption; no damage percentages."""
from __future__ import annotations

from decimal import Decimal

from .financial_models import (FinancialInputError, assumption, bounds, instant, money, number,
                               same_effective_date, unavailable, validate_sources)


def repair_costs(financial: dict, observations: list[dict], evidence: dict[str, dict], context: dict) -> tuple[list[dict], dict, list[dict], list[str]]:
    lines, assumptions, limitations = [], [], []
    observations_by_id = {x["observation_id"]: x for x in observations}
    seen_ids: set[str] = set()
    seen_scopes: set[str] = set()
    totals: list[tuple[Decimal, Decimal]] = []
    all_sources = []
    valid = True
    for index, line in enumerate(financial.get("repairs") or []):
        lid = str(line.get("line_id") or f"missing-line-{index}")
        row = {"line_id": lid, "description": line.get("description") or "Unspecified repair",
               "location": line.get("location"), "quantity": None,
               "quantity_unit": line.get("quantity_unit") or "unknown", "quantity_basis": line.get("quantity_basis") or "Unknown",
               "rate_low_usd": None, "rate_high_usd": None,
               "total": unavailable("Incomplete repair line."), "source_ids": line.get("source_ids") or []}
        try:
            scope = line.get("scope_key")
            if not line.get("line_id") or not scope:
                raise FinancialInputError("Repair requires line_id and a unique scope_key.")
            if lid in seen_ids or scope in seen_scopes:
                raise FinancialInputError("Duplicate repair line or scope; costs cannot be counted twice.")
            seen_ids.add(lid)
            seen_scopes.add(scope)
            if line.get("remaining") is not True:
                raise FinancialInputError("Repair scope must explicitly cover remaining work only.")
            if not line.get("description") or not line.get("quantity_unit") or not line.get("quantity_basis"):
                raise FinancialInputError("Repair scope, quantity unit, and quantity basis are required.")
            if not isinstance(line.get("location"), dict) or not line["location"].get("location_id"):
                raise FinancialInputError("Repair scope requires an identified location.")
            quantity = number(line.get("quantity"), "Repair quantity")
            low, high = bounds(line.get("rate_low_usd"), line.get("rate_high_usd"), "Repair rate")
            if instant(line.get("rate_effective_at"), end=True) > instant(context["assessment_as_of"], end=True):
                raise FinancialInputError("Repair rate is later than the assessment cutoff.")
            sources = validate_sources(line.get("source_ids"), evidence, context)
            if not any(evidence[s].get("kind") == "cost_source" for s in sources):
                raise FinancialInputError("Repair rates require an identified cost source.")
            if line.get("basis") == "scenario":
                assumptions.append(assumption(f"repair:{lid}", "Hypothetical repair scope",
                                              "This cost assumes the stated damage and quantity; it does not verify a resident report.", sources, "scenario"))
            elif line.get("basis") == "verified":
                obs_ids = line.get("observation_ids") or []
                if not obs_ids:
                    raise FinancialInputError("Verified repair scope requires verified condition observations.")
                for oid in obs_ids:
                    observation = observations_by_id.get(oid)
                    if not observation or observation.get("status") != "verified" or not observation.get("verified_by") or not observation.get("verification_note"):
                        raise FinancialInputError("An unverified report cannot establish a repair deduction.")
                    cutoff = instant(context["assessment_as_of"], end=True)
                    observed_at = observation.get("observed_at")
                    if observed_at and instant(observed_at, end=True) > cutoff:
                        raise FinancialInputError("The verified condition was observed after the assessment cutoff.")
                    if context.get("mode") == "historical_replay":
                        if not observed_at or not observation.get("updated_at"):
                            raise FinancialInputError("Historical repair scope requires dated observation and verification availability.")
                        if instant(observation["updated_at"], end=True) > cutoff:
                            raise FinancialInputError("The condition verification was unavailable at the historical assessment cutoff.")
                    validate_sources(observation.get("evidence_ids"), evidence, context)
                    obs_location = observation.get("location")
                    if not obs_location or obs_location.get("location_id") != line["location"]["location_id"]:
                        raise FinancialInputError("Repair location does not match its verified observation.")
                assumptions.append(assumption(f"repair:{lid}", "Remaining repair quantity and rate",
                                              f"{quantity} {line['quantity_unit']} at ${low}–${high}; rate dated {line['rate_effective_at']}.", sources))
            else:
                raise FinancialInputError("Repair basis must be verified or explicitly scenario.")
            row.update(quantity=float(quantity), rate_low_usd=float(low), rate_high_usd=float(high),
                       total=money(quantity * low, quantity * high, source_ids=sources,
                                   method="Remaining quantity × sourced unit-rate range"))
            totals.append((quantity * low, quantity * high))
            all_sources.extend(sources)
        except FinancialInputError as exc:
            valid = False
            row["total"] = unavailable(str(exc), method="Remaining quantity × sourced rate")
            limitations.append(f"Repair {lid}: {exc}")
        lines.append(row)
    if not lines:
        valid = False
        limitations.append("No remaining repair scope has been supplied; missing repair cost is not zero.")
    if financial.get("repair_scope_complete") is not True:
        valid = False
        limitations.append("Repair scope is incomplete or has not been explicitly reviewed as complete.")
    else:
        try:
            sources = validate_sources(financial.get("repair_scope_source_ids"), evidence, context,
                                       kinds={"inspection", "cost_source"})
            all_sources.extend(sources)
            assumptions.append(assumption("repair-scope-complete", "Remaining scope completeness",
                                          "The supplied remaining repair scope is assumed complete for this scenario.", sources, "user_supplied"))
        except FinancialInputError as exc:
            valid = False
            limitations.append(f"Repair scope completeness: {exc}")
    if valid:
        try:
            total = money(sum((x[0] for x in totals), Decimal(0)), sum((x[1] for x in totals), Decimal(0)),
                          source_ids=all_sources, method="Sum of complete remaining repair scopes")
        except FinancialInputError as exc:
            total = unavailable(str(exc))
            limitations.append(f"Repair total: {exc}")
    else:
        total = unavailable("A complete, sourced remaining repair scope is required; partial lines are shown separately.")
    return lines, total, assumptions, limitations


def downtime_cost(financial: dict, evidence: dict[str, dict], context: dict) -> tuple[dict, list[dict], list[str]]:
    item = financial.get("downtime")
    if not item:
        return unavailable("Incremental disruption cost has not been supplied; it is not assumed to be zero."), [], []
    try:
        low, high = bounds(item.get("low_usd"), item.get("high_usd"), "Incremental disruption cost")
        same_effective_date(item.get("effective_at"), context)
        if item.get("incremental") is not True or item.get("includes_repair_costs") is not False:
            raise FinancialInputError("Disruption must be incremental and explicitly exclude repair costs already counted.")
        if not item.get("method") or item.get("basis") not in {"source", "user_supplied", "scenario"}:
            raise FinancialInputError("Disruption requires a method and explicit source/user/scenario basis.")
        sources = validate_sources(item.get("source_ids"), evidence, context,
                                   kinds={"cost_source", "inspection", "costar_record"})
        out = money(low, high, source_ids=sources, method=item["method"])
        assumptions = [assumption("incremental-downtime", "Incremental temporary disruption",
                                  "Supplied finite-duration costs exclude repair costs and are not capitalized as perpetual NOI loss.",
                                  sources, item["basis"])]
        return out, assumptions, []
    except FinancialInputError as exc:
        return unavailable(str(exc)), [], [f"Disruption: {exc}"]
