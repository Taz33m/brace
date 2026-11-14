"""Deterministic resident draft projection; cached model output is not a booking.

Use this same pure function before preview, streaming and publication. Original
cache files and work orders remain unchanged.
"""
from __future__ import annotations

from copy import deepcopy
import math
import re

NOTICE_RULES = """Resident notices must distinguish sustained site wind estimates from gusts.
Quote only supplied forecast fields and anchor any time remaining to forecast issue time.
Never claim proposed work is booked, underway or complete; never announce unconfirmed
closures, work-from-home policies or parking safety. Do not bring grills, fuel or
propane cylinders indoors. Historical forecasts are scenario exercises, not live alerts.
Resident instructions must not invent deadlines or claim a location has been cleared safe.
"""

_EXERCISE = "SCENARIO EXERCISE — historical forecast; this is not a live weather alert."
_OPERATIONS = ("Property work in this plan is proposed, not booked or confirmed. "
               "Management must separately confirm work schedules, amenity closures and access arrangements. "
               "This notice does not establish that any parking area is safe.")
_FUEL = "Do not bring grills, fuel or propane cylinders indoors."
_BULLET = re.compile(r"^\s*(?:\d+[.)]|[-•])\s+(.+)$")
_OPERATIONS_HEADING = re.compile(r"^(?:what (?:we|building staff|our team) (?:are|will)|work (?:planned|scheduled)|management preparation)", re.I)
_RESIDENT_HEADING = re.compile(r"^(?:what we ask|please do|everyone\b|residents\b|tenants\b|ground.floor apartments\b|resident preparation)", re.I)
_STAFF = re.compile(r"\b(?:our (?:maintenance )?team|(?:building )?staff|maintenance team|crews?|roofer|contractor|management)\b.{0,100}\b(?:will|is|are|has|have|scheduled|booked)\b|\b(?:we (?:are|will|have)|is scheduled|has been booked)\b", re.I)
_CLOSURE = re.compile(r"\b(?:closed|close|closing|closures?|reopen\w*)\b", re.I)
_AMENITY = re.compile(r"\b(?:pools?|pool decks?|clubhouse|fitness cent(?:er|re)|training room|building|office|amenit\w*|courtyard)\b", re.I)
_PARKING = re.compile(r"\b(?:park(?:ing)?|carports?|vehicles?|cars?|garages?)\b", re.I)
_DEADLINE = re.compile(r"\b(?:by|before)\s+(?:(?:\d|tomorrow|Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)|(?:this|next)\s+(?:morning|afternoon|evening))", re.I)
_MOVE_INSIDE = re.compile(r"\b(?:bring|take)\b.{0,160}\b(?:inside|indoors|in)\b|\bmove\b.{0,160}\b(?:inside|indoors)\b", re.I)


def _number(value: object) -> str | None:
    if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value) or value < 0:
        return None
    return f"{value:g}"


def _forecast(threat: dict) -> str:
    site = threat.get("at_this_site") or {}
    name = threat.get("name") or "Weather preparation"
    issued = threat.get("forecast_issued")
    text = f"{name}. " + (f"Forecast issued {issued}. " if issued else "Forecast issue time is unavailable. ")
    if threat.get("kind") == "hurricane":
        wind = _number(site.get("peak_wind_mph"))
        text += (f"The site estimate is sustained winds near {wind} mph; this is not a gust estimate. "
                 if wind is not None else "A site-specific sustained wind estimate is unavailable. ")
        hours = _number(site.get("hours_until_tropical_storm_wind", threat.get("hours_left")))
        if hours is not None and issued:
            text += f"At issue time, approximately {hours} hours remained before tropical-storm winds could reach this site. "
        text += "The forecast cone describes uncertainty in the storm centre's track, not the boundary of dangerous weather."
    elif threat.get("kind") == "wildfire":
        gust = _number(site.get("gust_mph"))
        if gust is not None:
            text += f"The forecast for this site's warning zone includes gusts up to {gust} mph. "
        if site.get("in_warning"):
            text += "The site is in a Red Flag Warning area. "
            hours = _number(site.get("hours_until_warning"))
            if hours is not None and issued:
                text += f"At issue time, approximately {hours} hours remained until the warning began. "
        elif site.get("in_watch"):
            text += "The site is in a fire-weather watch area. "
        text += "A Red Flag Warning concerns conditions that can spread fire quickly; it does not establish that a fire is burning."
    else:
        text += "Use the supplied forecast and official local updates; no site-specific wind figure is available in this notice."
    return text.strip()


def _resident_lines(body: str) -> list[str]:
    """Keep the specific resident checklist, excluding unconfirmed operations.

    Generated forecast and footer paragraphs are not checklist entries, so a
    second projection produces exactly the same result.
    """
    result: list[str] = []
    operations = False
    context = ""
    for raw in body.splitlines():
        line = raw.strip()
        if _OPERATIONS_HEADING.match(line):
            operations = True
            context = ""
            continue
        if _RESIDENT_HEADING.match(line):
            operations = False
            context = "Ground-floor apartments: " if line.lower().startswith("ground-floor apartments") else ""
            continue
        if line.lower() in ("cars:", "vehicles:"):
            context = ""
            continue
        match = _BULLET.match(line)
        if not match or operations:
            continue
        content = match.group(1)
        first = re.split(r"(?<=[.!?])\s+", content)[0]
        if (_STAFF.search(first) or (_CLOSURE.search(first) and _AMENITY.search(first))
                or re.search(r"work from home|^Staff:", first, re.I)
                or (_PARKING.search(first) and not re.search(r"(?:never|do not|don't) (?:drive|walk).*water", first, re.I))):
            continue
        kept: list[str] = []
        for sentence in re.split(r"(?<=[.!?])\s+", content):
            sentence = sentence.replace(" (only if conditions allow; exclude grills, fuel and propane cylinders).", ".")
            # A plan is not evidence of booking, policy or a safe parking place.
            if (_STAFF.search(sentence) or _DEADLINE.search(sentence)
                    or (_CLOSURE.search(sentence) and _AMENITY.search(sentence))
                    or re.search(r"work from home|until we confirm|expect some noise", sentence, re.I)):
                continue
            if _PARKING.search(sentence) and not re.search(r"(?:never|do not|don't) (?:drive|walk).*water", sentence, re.I):
                continue
            if re.search(r"(?:most likely cause|our roof is old|has leaked in places)", sentence, re.I):
                continue
            # A sentence telling people what NOT to bring in, or what to leave out, is already the safe instruction:
            # keep it as written. Only an instruction to bring things in needs the fuel exclusion added.
            if _MOVE_INSIDE.search(sentence) and not re.match(r"\s*(?:do not|don't|never|leave)\b", sentence, re.I):
                # A source sentence can list fuel alongside furniture; never
                # preserve that instruction and merely append a contradiction.
                if re.search(r"\b(?:propane|fuel|gas cans?|cylinders?)\b", sentence, re.I):
                    continue
                sentence = re.sub(r"\bevery chair, table, grill cover, planter, bike, decoration\b",
                                  "chairs, tables, grill covers, planters, bikes, decorations", sentence, flags=re.I)
                sentence = re.sub(r"\bgrills?(?!\s+covers?\b)\s*,\s*", "", sentence, flags=re.I)
                sentence = re.sub(r",?\s*(?:and\s+)?grills?\b(?!\s+covers?\b)", "", sentence, flags=re.I)
                sentence = re.sub(r"\banything else(?:\s+(?:that is\s+)?loose)?\b", "other small loose items", sentence, flags=re.I)
                sentence = re.sub(r"\b(?:everything|anything|every chair)\b",
                                  lambda m: "small loose items" if m.group(0).lower() != "every chair" else "chairs",
                                  sentence, flags=re.I)
                # This condition travels with the instruction, including when
                # someone copies only a checklist item out of the draft.
                sentence = sentence.rstrip(".")
                condition = " (only if conditions allow; exclude grills, fuel and propane cylinders)."
                if "exclude grills, fuel and propane cylinders" not in sentence:
                    sentence += condition
                else:
                    sentence += "."
            kept.append(sentence)
        # A line left pointing at something an earlier sentence named ("If you have one outside...") says nothing alone.
        if kept and re.match(r"If you (?:have|keep|own) (?:one|them|any)\b", kept[0], re.I):
            kept = kept[1:]
        if kept:
            text = context + " ".join(kept)
            if text not in result:
                result.append(text)
    return result


def correct_notice(message: dict, threat: dict) -> dict:
    if message.get("kind") != "notice":
        return deepcopy(message)
    result = deepcopy(message)
    instructions = _resident_lines(str(result.get("body") or ""))
    sections = [_forecast(threat), "PREPARATION NOTICE — proposed property work requires separate management confirmation."]
    if threat.get("replay") is True:
        sections.insert(0, _EXERCISE)
    if instructions:
        sections.append("Resident preparation:\n" + "\n".join(f"- {line}" for line in instructions))
    else:
        sections.append("No resident checklist has been retained; contact management for confirmed preparation instructions.")
    sections.extend([_FUEL, _OPERATIONS])
    result["subject"] = (("[Scenario exercise] " if threat.get("replay") is True else "")
                         + f"{threat.get('name') or 'Weather'}: resident preparation update")
    if threat.get("label"):
        result["subject"] += f" ({threat['label']})"
    result["body"] = "\n\n".join(sections)
    return result


def correct_plan_notices(plan: dict) -> dict:
    result = deepcopy(plan)
    threat = result.get("threat") or {}
    result["messages"] = [correct_notice(message, threat) for message in result.get("messages", [])]
    by_id = {m.get("id"): m for m in result["messages"] if m.get("id")}
    for event in result.get("events", []):
        if event.get("type") == "message" and isinstance(event.get("message"), dict):
            message = event["message"]
            event["message"] = deepcopy(by_id.get(message.get("id")) or correct_notice(message, threat))
        # Some consumers retain a final plan in the event log as well.
        if event.get("type") == "done" and isinstance(event.get("plan"), dict):
            event["plan"] = correct_plan_notices({**event["plan"], "threat": event["plan"].get("threat") or threat})
    return result
