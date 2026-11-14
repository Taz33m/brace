"""Conservative comparable screening; price dispersion is not an appraisal interval."""
from __future__ import annotations

import math
from decimal import Decimal
from statistics import median

from .financial_models import FinancialInputError, instant, money, number, unavailable

MIN_COMPS = 3
MAX_AGE_DAYS = 730
MAX_DISTANCE_KM = 25
PRICE_STATUSES = {"confirmed", "fullvalue", "affidavit", "declaration"}
POLICY = ("Comparable screening policy: at least 3 unique priced transactions, same asset class and state, "
          "within 25 km and 730 days, and 0.5–2 times the subject's unit count or gross area. "
          "These engineering thresholds do not establish appraisal accuracy. No market/time/condition adjustments are inferred.")


def _distance(subject: dict, sale: dict) -> float | None:
    try:
        coords = [float(subject["lat"]), float(subject["lon"]), float(sale["latitude"]), float(sale["longitude"])]
    except (KeyError, TypeError, ValueError):
        return None
    if not all(math.isfinite(x) for x in coords) or not all(-90 <= x <= 90 for x in coords[::2]) or not all(-180 <= x <= 180 for x in coords[1::2]):
        return None
    a, b, c, d = map(math.radians, coords)
    h = math.sin((c - a) / 2) ** 2 + math.cos(a) * math.cos(c) * math.sin((d - b) / 2) ** 2
    return 6371 * 2 * math.asin(min(1, math.sqrt(h)))


def select_comparables(subject: dict, sales: list[dict], context: dict) -> tuple[list[dict], dict, list[str]]:
    cutoff = instant(context["assessment_as_of"], end=True)
    size_key = "units" if subject.get("type") == "Multifamily" else "gba_sqft"
    size_label = "home" if size_key == "units" else "gross square foot"
    seen_ids: set[str] = set()
    seen_transactions: set[tuple] = set()
    eligible: list[tuple[dict, Decimal]] = []
    rows = []
    for original in sales:
        price = None
        reason = ""
        cid = str(original.get("comp_id") or "")
        pref = original.get("property_ref") or {"dataset": "commercial_property", "id": "unknown"}
        source_ids = original.get("source_ids") or []
        try:
            price = number(original.get("price_usd"), "Sale price", positive=True)
        except FinancialInputError as exc:
            reason = str(exc)
        try:
            transaction_day = instant(original.get("transaction_date")).date().isoformat()
        except FinancialInputError:
            transaction_day = original.get("transaction_date")
        transaction_key = (pref.get("dataset"), str(pref.get("id")), transaction_day, price)
        # Sort-independent eligibility: even rejected copies cannot create extra independent evidence.
        duplicate = cid in seen_ids or transaction_key in seen_transactions
        seen_ids.add(cid)
        seen_transactions.add(transaction_key)
        row = {"comp_id": cid, "property_ref": pref, "label": original.get("label") or cid,
               "transaction_date": original.get("transaction_date"),
               "date_basis": original.get("date_basis") if original.get("date_basis") in {"deed_recorded", "closed"} else "unknown",
               "price_usd": float(price) if price is not None else None,
               "price_status": original.get("price_status") or "Unknown", "allocated": bool(original.get("allocated")),
               "included": False, "reason": reason, "source_ids": source_ids}
        try:
            if not cid:
                raise FinancialInputError("Missing transaction identifier.")
            if duplicate:
                raise FinancialInputError("Duplicate transaction; counted once.")
            if reason:
                raise FinancialInputError(reason)
            if original.get("temporal_eligible") is False:
                raise FinancialInputError(original.get("temporal_exclusion_reason") or "Source failed the temporal evidence cutoff.")
            if original.get("currency") != "USD":
                raise FinancialInputError("Currency is not established as USD; no FX conversion inferred.")
            if row["allocated"] or original.get("multiple_entities") or original.get("number_of_entities", 1) != 1:
                raise FinancialInputError("Portfolio or allocated price excluded from primary comparables.")
            if row["price_status"].replace(" ", "").lower() not in PRICE_STATUSES:
                raise FinancialInputError("Sale price is not confirmed or disclosed under the screening policy.")
            if not source_ids:
                raise FinancialInputError("Missing transaction provenance.")
            conditions = [str(x) for x in original.get("sale_conditions") or [] if str(x).lower() not in {"none", "standardsale"}]
            if conditions:
                raise FinancialInputError("Sale conditions require review: " + ", ".join(conditions))
            if row["date_basis"] == "unknown":
                raise FinancialInputError("Transaction date basis is unknown.")
            trans = instant(row["transaction_date"], end=True)
            if trans > cutoff:
                raise FinancialInputError("Transaction occurred after the assessment cutoff.")
            if (cutoff - trans).days > MAX_AGE_DAYS:
                raise FinancialInputError("Transaction is older than the 730-day screening window.")
            available = original.get("available_at")
            if context.get("mode") == "historical_replay" and not available:
                raise FinancialInputError("Historical information availability is unknown.")
            if available and instant(available, end=True) > cutoff:
                raise FinancialInputError("Transaction information was unavailable at the cutoff.")
            if original.get("asset_type") != subject.get("type") or subject.get("type") in {None, "", "Unknown"}:
                raise FinancialInputError("Different or unknown asset class.")
            if not subject.get("state") or original.get("state") != subject["state"]:
                raise FinancialInputError("Different or unknown state/market.")
            if not pref.get("id") or pref.get("id") == "unknown":
                raise FinancialInputError("Comparable property identifier is missing.")
            if pref.get("dataset") != context.get("property_ref", {}).get("dataset", "commercial_property"):
                raise FinancialInputError("Different property dataset.")
            if str(pref.get("id")) == str(subject.get("id")):
                raise FinancialInputError("Subject's own transaction is a historical benchmark, not an independent comparable.")
            distance = _distance(subject, original)
            if distance is None or distance > MAX_DISTANCE_KM:
                raise FinancialInputError("Location is unknown or outside the 25-km screening radius.")
            subject_size = number(subject.get(size_key), "Subject scale", positive=True)
            sale_size = number(original.get(size_key), "Comparable scale", positive=True)
            if not Decimal("0.5") <= sale_size / subject_size <= Decimal("2"):
                raise FinancialInputError("Comparable scale is outside 0.5–2 times the subject.")
            normalized_value = number(price / sale_size * subject_size, "Normalized benchmark")
            row["included"] = True
            row["reason"] = f"Screened same-class sale, {distance:.1f} km away; normalized per {size_label}. Condition and market adjustments remain unverified."
            eligible.append((row, normalized_value))
        except FinancialInputError as exc:
            row["reason"] = str(exc)
        rows.append(row)
    limitations = [POLICY, "Comparable dispersion is a descriptive range, not a calibrated confidence interval or a current-condition appraisal."]
    if len(eligible) < MIN_COMPS:
        benchmark = unavailable(f"Only {len(eligible)} eligible independent comparables; screening minimum is {MIN_COMPS}.", method="Comparable screening")
    else:
        values = [value for _, value in eligible]
        benchmark = money(min(values), max(values), point=median(values),
                          method=f"Unadjusted observed sale price per {size_label} × subject scale; descriptive min/median/max",
                          source_ids=[sid for row, _ in eligible for sid in row["source_ids"]],
                          range_kind="comparable_dispersion")
    last_sale = subject.get("last_sale")
    if last_sale:
        limitations.append(f"Subject last recorded sale ({last_sale.get('date') or 'date unknown'}, price basis {last_sale.get('basis') or 'unknown'}) remains a historical transaction; it is not used as present value.")
    return rows, benchmark, limitations
