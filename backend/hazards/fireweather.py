"""Red Flag Warnings: parsing NWS fire weather products and replaying them step by step.

A Red Flag Warning is issued per NWS fire weather zone, not as a hand-drawn
polygon. Each product (RFW) is split into segments; a segment lists zone codes
(UGC, e.g. CAZ362) and VTEC lines that say what is happening to which hazard
(FW.W = Red Flag Warning, FW.A = Fire Weather Watch) and for what period.
Replaying the products in order rebuilds exactly which zones were under a
warning, and until when, as it stood after each product.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

from .errors import HazardError
from .util import hours_between, iso, parse_iso, trim

_UGC_START = re.compile(r"^[A-Z]{2}[CZ]\d{3}[\dA-Z>\-]*-$")
_UGC_MORE = re.compile(r"^[\dA-Z>\-]+-$")
_VTEC_RE = re.compile(
    r"/[OTEX]\.(NEW|CON|EXT|EXA|EXB|UPG|CAN|EXP|COR|ROU)\.([A-Z]{4})\.([A-Z]{2})\.([A-Z])\.(\d{4})\."
    r"(\d{6}T\d{4}Z)-(\d{6}T\d{4}Z)/")
_GUST_RE = re.compile(r"gusts?(?:\s+(?:of|to|up to|near|around|between))*\s+(\d{2,3})(?:\s+(?:to|and)\s+(\d{2,3}))?\s*mph", re.I)
_DIR = r"(?:north(?:east|west)?|south(?:east|west)?|east|west)"
_DIR_RE = re.compile(rf"\b({_DIR}(?:\s+to\s+{_DIR})?)\b", re.I)
_LOCAL_RE = re.compile(r"^(\d{1,2})(\d{2}) (AM|PM) ([A-Z]{3,4}) \w{3} (\w{3}) (\d{1,2}) (\d{4})\s*$", re.M)
_TZ_HOURS = {"PST": -8, "PDT": -7, "MST": -7, "MDT": -6, "CST": -6, "CDT": -5, "EST": -5, "EDT": -4,
             "AKST": -9, "AKDT": -8, "HST": -10}
_MONTHS = {m: i + 1 for i, m in enumerate("Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split())}
PDS_PHRASE = "PARTICULARLY DANGEROUS SITUATION"


def expand_ugc(code: str) -> list[str]:
    """'CAZ288-358-369>371-062245-' -> ['CAZ288', 'CAZ358', 'CAZ369', 'CAZ370', 'CAZ371']."""
    tokens = [t for t in code.replace("\n", "").replace(" ", "").strip("-").split("-") if t]
    if tokens and re.fullmatch(r"\d{6}", tokens[-1]):
        tokens = tokens[:-1]  # the trailing DDHHMM is the product purge time
    out: list[str] = []
    prefix = ""
    for tok in tokens:
        m = re.match(r"^([A-Z]{2}[CZ])(.*)$", tok)
        if m:
            prefix, tok = m.group(1), m.group(2)
        if not prefix or not tok:
            continue
        if ">" in tok:
            lo, hi = tok.split(">", 1)
            if lo.isdigit() and hi.isdigit():
                out += [f"{prefix}{n:03d}" for n in range(int(lo), int(hi) + 1)]
        elif tok.isdigit():
            out.append(f"{prefix}{int(tok):03d}")
    return out


def _vtec_time(stamp: str) -> str | None:
    if stamp.startswith("000000"):
        return None  # "already in effect" / "until further notice"
    return iso(datetime.strptime(stamp, "%y%m%dT%H%MZ").replace(tzinfo=timezone.utc))


def parse_vtec(text: str) -> list[dict]:
    """Every VTEC line in a block of text."""
    return [{
        "action": m.group(1), "office": m.group(2), "phenomenon": m.group(3), "significance": m.group(4),
        "etn": int(m.group(5)), "start": _vtec_time(m.group(6)), "end": _vtec_time(m.group(7)),
    } for m in _VTEC_RE.finditer(text)]


def parse_local_time(text: str) -> str | None:
    """First '240 PM PST Sun Jan 5 2025' style line in a product, as UTC ISO."""
    m = _LOCAL_RE.search(text)
    if not m or m.group(4) not in _TZ_HOURS or m.group(5) not in _MONTHS:
        return None
    hour = int(m.group(1)) % 12 + (12 if m.group(3) == "PM" else 0)
    local = datetime(int(m.group(7)), _MONTHS[m.group(5)], int(m.group(6)), hour, int(m.group(2)))
    return iso((local - timedelta(hours=_TZ_HOURS[m.group(4)])).replace(tzinfo=timezone.utc))


def parse_wind(text: str | None) -> dict | None:
    """Gusts and direction from a '* WINDS...' bullet (or any sentence about wind).

    "gust_mph" is the top of the first gust range mentioned, which in NWS
    fire weather wording is the main expected range; "peak_gust_mph" is the
    highest gust figure anywhere in the text (often "isolated gusts to ...").
    """
    flat = " ".join((text or "").split())
    gusts = [(int(m.group(1)), int(m.group(2) or m.group(1))) for m in _GUST_RE.finditer(flat)]
    if not gusts:
        return None
    direction = _DIR_RE.search(flat)
    return {
        "gust_mph": max(gusts[0]), "gust_range_mph": [min(gusts[0]), max(gusts[0])],
        "peak_gust_mph": max(max(g) for g in gusts),
        "direction": direction.group(1).lower() if direction else None,
        "text": trim(flat, 420),
    }


def wind_bullet(text: str) -> str | None:
    m = re.search(r"\*\s*WINDS?\.\.\.(.*?)(?=\n\s*\n|\n\*\s|\Z)", text, re.S)
    return " ".join(m.group(1).split()) if m else None


def _headlines(text: str) -> list[str]:
    """'...LIKE THIS...' headline paragraphs, cleaned to one line each."""
    out = []
    for m in re.finditer(r"(?:^|\n)\.\.\.(.+?)\.\.\.[ ]*(?=\n|$)", text, re.S):
        line = " ".join(m.group(1).split())
        if line:
            out.append(line)
    return out


def parse_rfw_product(text: str, issued: str | None = None) -> dict:
    """Parse one NWS Red Flag Warning / Fire Weather Watch product.

    Returns {"issued", "headline", "pds", "segments": [{"ugcs", "vtec",
    "headline", "wind", "pds"}]}. `issued` may be passed in when the archive
    already knows it; otherwise it is read from the product's local time line.
    """
    text = text.replace("\r", "")
    issued = issued or parse_local_time(text)
    if not issued:
        raise HazardError("fire weather product has no readable issue time")
    segments = []
    overview = None
    for chunk in text.split("$$"):
        lines = chunk.split("\n")
        start = next((i for i, ln in enumerate(lines) if _UGC_START.match(ln.strip())), None)
        if start is None:
            continue
        code, end = lines[start].strip(), start
        while not re.search(r"\d{6}-$", code) and end + 1 < len(lines) and _UGC_MORE.match(lines[end + 1].strip()):
            end += 1
            code += lines[end].strip()
        body = "\n".join(lines[end + 1:])
        vtec = parse_vtec(body)
        if not vtec:
            continue
        if overview is None:
            overview = "\n".join(lines[:start])
        heads = _headlines(body)
        segments.append({
            "ugcs": expand_ugc(code), "vtec": vtec, "headline": heads[0] if heads else None,
            "wind": parse_wind(wind_bullet(body)),
            "pds": any(PDS_PHRASE in h.upper() for h in heads),
        })
    if not segments:
        raise HazardError("fire weather product has no zone segments with VTEC lines")
    top = _headlines(overview or "")
    return {
        "issued": issued, "headline": top[0] if top else segments[0]["headline"],
        "pds": PDS_PHRASE in (overview or "").upper() or any(s["pds"] for s in segments),
        "segments": segments,
    }


def replay(products: list[dict]) -> list[dict]:
    """Apply parsed products in time order; return the zone state after each one.

    Each result is {"issued", "headline", "pds", "zones": [{"ugc", "sig": "W" or
    "A", "start", "end", "gust_mph", "peak_gust_mph", "direction", "wind_text",
    "pds", "headline"}]} listing every zone with a Red Flag Warning (W) or Fire
    Weather Watch (A) that is in force or scheduled as of that product.
    """
    state: dict[tuple[str, str], dict] = {}
    steps = []
    for product in sorted(products, key=lambda p: p["issued"]):
        issued = product["issued"]
        for seg in product["segments"]:
            wind = seg.get("wind") or {}
            for v in seg["vtec"]:
                if v["phenomenon"] != "FW" or v["significance"] not in ("W", "A"):
                    continue
                for ugc in seg["ugcs"]:
                    key = (ugc, v["significance"])
                    if v["action"] in ("CAN", "EXP", "UPG"):
                        state.pop(key, None)
                        continue
                    if v["action"] == "ROU":
                        continue
                    prev = state.get(key, {})
                    start = v["start"] or prev.get("start") or issued
                    end = v["end"] or prev.get("end")
                    state[key] = {
                        "ugc": ugc, "sig": v["significance"], "start": start, "end": end,
                        "gust_mph": wind.get("gust_mph", prev.get("gust_mph")),
                        "peak_gust_mph": wind.get("peak_gust_mph", prev.get("peak_gust_mph")),
                        "direction": wind.get("direction", prev.get("direction")),
                        "wind_text": wind.get("text", prev.get("wind_text")),
                        # A zone is PDS when its own segment says so, or when it was PDS before
                        # and this product's overview still declares the PDS (later updates
                        # shorten the per-zone headline and drop the phrase).
                        "pds": v["significance"] == "W" and bool(
                            seg.get("pds") or (prev.get("pds") and product.get("pds"))),
                        "headline": seg.get("headline"),
                    }
        zones = [dict(z) for z in state.values() if not z["end"] or z["end"] > issued]
        zones.sort(key=lambda z: (z["sig"] != "W", z["ugc"]))
        steps.append({"issued": issued, "headline": product.get("headline"), "pds": bool(product.get("pds")),
                      "zones": zones})
    return steps


def step_wind(zones: list[dict]) -> dict | None:
    """Scenario-level wind: the strongest warned zone's forecast gusts."""
    warned = [z for z in zones if z["sig"] == "W" and z.get("gust_mph")]
    if not warned:
        return None
    top = max(warned, key=lambda z: (z["gust_mph"], z.get("peak_gust_mph") or 0))
    return {"gust_mph": top["gust_mph"], "peak_gust_mph": max(z.get("peak_gust_mph") or 0 for z in warned),
            "direction": top.get("direction"), "text": top.get("wind_text")}


def warning_label(issued: str, zones: list[dict], pds: bool) -> str:
    """Plain label for a step, relative to when the first warning takes effect."""
    starts = [z["start"] for z in zones if z["sig"] == "W" and z.get("start")]
    if not starts:
        return "Fire Weather Watch only" if zones else "No warning in effect"
    lead = hours_between(issued, min(starts))
    if lead >= 1:
        return f"{round(lead)} hours before the Red Flag Warning starts"
    return "Red Flag Warning in effect" + (" (particularly dangerous situation)" if pds else "")


def zone_exposure(issued: str, zones_here: list[dict]) -> dict:
    """Exposure of a point given the zone records (from one step) that cover it.

    "hours_until_warning" counts from the step's issue time and is 0.0 once the
    warning is in effect. "warning_hours" is how long the warning then runs:
    from its start (or from the issue time if it has already started) to its end.
    """
    warned = sorted((z for z in zones_here if z["sig"] == "W"), key=lambda z: z.get("start") or "")
    watch = [z for z in zones_here if z["sig"] == "A"]
    out = {"kind": "wildfire", "in_warning": bool(warned), "hours_until_warning": None, "warning_hours": None,
           "in_watch": bool(watch), "zone": None, "zone_name": None, "gust_mph": None, "pds": False}
    pick = warned[0] if warned else (watch[0] if watch else None)
    if pick:
        out.update(zone=pick["ugc"], zone_name=pick.get("name"), gust_mph=pick.get("gust_mph"))
    if warned:
        z = warned[0]
        t0, start = parse_iso(issued), parse_iso(z["start"] or issued)
        out["hours_until_warning"] = round(max(0.0, (start - t0).total_seconds() / 3600.0), 1)
        if z.get("end"):
            out["warning_hours"] = round(max(0.0, (parse_iso(z["end"]) - max(start, t0)).total_seconds() / 3600.0), 1)
        out["pds"] = any(w.get("pds") for w in warned)
    return out
