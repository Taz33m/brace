"""Asking rents come from the apartment listing, as they are, or not at all."""
import json

from backend import portfolio


def test_rent_is_the_listings_own_range_and_missing_when_there_is_no_listing(tmp_path, monkeypatch):
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "apartment-listing.jsonl").write_text("\n".join(json.dumps(r) for r in [
        {"propertyId": 7, "minRent": 800, "maxRent": 1200, "totalNumUnits": 240, "numUnitsAvailable": 12, "apartmentModels": [{}, {}, {}]},
        {"propertyId": 8, "totalNumUnits": 50},                                       # a listing with no rents says nothing about rent
    ]))
    monkeypatch.setattr(portfolio, "KIT_DIR", tmp_path)
    monkeypatch.setattr(portfolio, "_RENTS", None)
    assert portfolio.rent(7) == {"low": 800, "high": 1200, "currency": "USD", "homes_listed": 240, "available": 12, "floor_plans": 3,
                                 "source": "CoStar apartment listing"}
    assert portfolio.rent(8) is None and portfolio.rent(9) is None


def test_no_kit_means_no_rent(tmp_path, monkeypatch):
    monkeypatch.setattr(portfolio, "KIT_DIR", tmp_path)
    monkeypatch.setattr(portfolio, "_RENTS", None)
    assert portfolio.rent(7) is None
