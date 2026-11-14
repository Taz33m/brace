"""Supplied artwork for the historical forecasts the cards describe."""
from pathlib import Path


ASSETS = Path(__file__).with_name("assets")
FORECAST_CARDS = {
    "hurricane-beryl": ASSETS / "hurricane-beryl.png",
    "los-angeles-red-flag": ASSETS / "los-angeles-red-flag.png",
}


def forecast_card(property_name: str, threat: dict) -> str | None:
    if threat.get("replay") is not True:
        return None
    scenario = threat.get("scenario_id")
    step = threat.get("step_id")
    site = threat.get("at_this_site") or {}
    if (scenario == "beryl-2024" and step == "adv37"
            and property_name == "The Parker at Ellington"
            and threat.get("forecast_issued") == "2024-07-07T21:00:00Z"
            and site.get("peak_wind_mph") == 55
            and site.get("hours_until_tropical_storm_wind") == 7.5):
        return "hurricane-beryl"
    if (scenario == "la-red-flag-jan-2025" and step == "20250105T2240Z"
            and site.get("in_warning") is True):
        return "los-angeles-red-flag"
    return None
