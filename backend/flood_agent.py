"""The research step of the flood test, done by an agent.

Before a plan can be made, somebody has to find out what can be put round a building ahead of a flood, what it
costs and how long it takes. This agent does that on the web and records each fix with the page it came from and
the sentence that states the price. It decides what to search for and what is worth recording; it does not decide
the plan. The plan is a rule in `flood.py`, and it uses a fix only when `check` has fetched the page and found
the price and the sentence there. A fix the agent found but the fetch could not confirm is kept, listed, and never
planned.

Run it with `python -m scripts.flood_research`. What it found is saved in the data folder, which is never committed.
"""
from __future__ import annotations

import html
import io
import ipaddress
import json
import re
import socket
import time
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

import anthropic
import httpx

from . import flood
from .config import AGENT_MODEL

MAX_TURNS = 14
MAX_SEARCHES = 12
MAX_FETCHES = 16
SEARCH = {"type": "web_search_20260209", "name": "web_search", "max_uses": MAX_SEARCHES}
FETCH = {"type": "web_fetch_20260209", "name": "web_fetch", "max_uses": MAX_FETCHES}      # the page as the API's own fetcher read it; the check runs on that text

SYSTEM = """You research for Brace, which plans what to do at apartment buildings in Houston in the days before flood water arrives. Find what can be put round a building to keep water out, what it costs, and how long it takes to have in place.

Cover both kinds:
- quick fixes, in place within hours or a few days: water-filled barriers, sandbag walls, modular panel or box barriers
- long-term fixes, weeks or more: a permanent floodwall or berm, dry floodproofing of a building, raising utilities

For each fix a page supports, call record_fix once.

Rules
- Record a price only when a page states it. Copy the sentence that states the price into quote, word for word, and give that page's address.
- When the page gives a range, record its low end as price and its high end as price_high.
- Record the unit the page uses. Do not work out a price, a height or a rate yourself, and do not convert one unit into another.
- A barrier is of no use to the plan without its height. Record the barrier's height in the unit the page uses, with the sentence that states it. If the page with the price does not state the height, find it on the maker's page or another page and give that page's address in height_source_url.
- Record how long it takes, or how fast it goes in, only when the page states it. Otherwise leave those fields null.
- Open the page with web_fetch before you record from it, so the price can be checked against the page as it was read.
- Prefer a maker's own page, a government or university page, or a news report that quotes a price. Prefer a web page to a PDF file: a PDF cannot be checked here. Leave out pages that only sell something without a stated price.
- If you cannot find a stated price for a kind of fix, do not record that kind.
- Stop when you have covered the kinds above or have searched twelve times. Finish with one line saying how many fixes you recorded."""

RECORD = {
    "name": "record_fix",
    "description": "Record one flood fix that a page supports, with its stated price and the page it came from. Call once for each fix. Call it again for the same product at another height if the page prices each height.",
    "input_schema": {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "What it is, in a few plain words, with its height if it has one. For example: Water-filled barrier, 4 ft."},
            "type": {"type": "string", "enum": ["quick", "long-term"], "description": "quick: in place within hours or a few days. long-term: weeks or more."},
            "price": {"type": "number", "description": "The stated price in US dollars, in the unit given by price_unit. The low end if the page gives a range."},
            "price_high": {"type": ["number", "null"], "description": "The high end of the price, if the page gives a range. Otherwise null."},
            "height": {"type": ["number", "null"], "description": "For a barrier or wall: its height as a page states it, in the unit given by height_unit. Null if no page states it, or if it is not a barrier."},
            "height_unit": {"type": ["string", "null"], "enum": ["ft", "in", "cm", "m", None]},
            "height_quote": {"type": ["string", "null"], "description": "The sentence that states the height, word for word. Null if height is null."},
            "height_source_url": {"type": ["string", "null"], "description": "The page that states the height, if it is not the page that states the price. Otherwise null."},
            "price_unit": {"type": "string", "enum": ["per linear foot", "per sandbag", "per square foot", "per building", "other"]},
            "crew_hours_per_100ft": {"type": ["number", "null"], "description": "Crew hours to set up 100 feet, only if the page states a rate that gives this directly. Otherwise null."},
            "bags_per_person_hour": {"type": ["number", "null"], "description": "For sandbags only: bags one person fills and places in an hour, only if the page states it. Otherwise null."},
            "weeks": {"type": ["number", "null"], "description": "For a long-term fix: weeks to design and build, only if the page states it. Otherwise null."},
            "time_text": {"type": ["string", "null"], "description": "The page's own words on how long it takes, if it says. Otherwise null."},
            "source_title": {"type": "string"},
            "source_url": {"type": "string"},
            "quote": {"type": "string", "description": "The sentence on the page that states the price, word for word."},
        },
        "required": ["name", "type", "price", "price_high", "price_unit", "height", "height_unit", "height_quote", "height_source_url", "crew_hours_per_100ft", "bags_per_person_hour", "weeks", "time_text", "source_title", "source_url", "quote"],
        "additionalProperties": False,
    },
}
TOOLS = [SEARCH, FETCH, RECORD]


# ---- checking what the agent recorded against the page itself ------------------------------------

def _public(url: str) -> bool:
    """Only ordinary web pages are fetched: http or https, and never an address on this machine or a private network."""
    u = urlparse(url)
    if u.scheme not in ("http", "https") or not u.hostname:
        return False
    try:
        return all(ipaddress.ip_address(info[4][0]).is_global for info in socket.getaddrinfo(u.hostname, None))
    except (OSError, ValueError):
        return False


def page_text(url: str) -> str | None:
    """The words on a page, or None if it could not be read. A PDF is read only when pypdf is installed."""
    if not _public(url):
        return None
    try:
        r = httpx.get(url, headers={"User-Agent": "Mozilla/5.0 (compatible; price-check)"}, timeout=25, follow_redirects=True)
    except httpx.HTTPError:
        return None
    if r.status_code != 200:
        return None
    if "pdf" in r.headers.get("content-type", "").lower() or r.content[:5] == b"%PDF-":
        try:
            from pypdf import PdfReader
            return "\n".join(page.extract_text() or "" for page in PdfReader(io.BytesIO(r.content)).pages[:80])
        except Exception:      # not installed, or a file it cannot read
            return None
    text = re.sub(r"(?is)<(script|style|noscript)\b.*?</\1>", " ", r.text)
    return html.unescape(re.sub(r"(?s)<[^>]+>", " ", text))


def _norm(text: str) -> str:
    text = text.lower().replace("\u2019", "'").replace("\u2018", "'").replace("\u201c", '"').replace("\u201d", '"').replace("\u00a0", " ")
    return re.sub(r"\s+", " ", re.sub(r"\$\s+", "$", text)).strip()


def _has_price(page: str, price: float) -> bool:
    forms = {f"${price:,.0f}", f"${price:.0f}", f"${price:,.2f}", f"${price:.2f}", f"${price:g}", f"${price:.2f}".replace("$0.", "$.")} if price == round(price, 2) else {f"${price:g}"}
    return any(re.search(re.escape(f) + r"(?![\d,]*\d)", page) for f in forms) or (price == int(price) and re.search(rf"(?<![\d,.$]){int(price):,}(?![\d,]*\d)", page) is not None and "$" in page)


def _has_sentence(page: str, sentence: str) -> bool:
    quote = _norm(sentence)
    words = re.findall(r"[a-z0-9$.,']+", quote)
    grams = [" ".join(words[i:i + 4]) for i in range(max(1, len(words) - 3))]
    return quote in page or (bool(grams) and sum(1 for g in grams if g in page) / len(grams) >= 0.7)


def confirm(fix: dict, text: str | None) -> tuple[bool, str]:
    """Whether the page holds the price and the sentence the agent recorded. Both must be there, and both ends of a range."""
    if text is None:
        return False, "the page could not be read"
    page = _norm(text)
    if not _has_price(page, float(fix["price"])) or (fix.get("price_high") and not _has_price(page, float(fix["price_high"]))):
        return False, "the price is not on the page"
    if not _has_sentence(page, fix["source"]["quote"]):
        return False, "the price is on the page but the sentence is not"
    return True, "the price and the sentence are on the page"


def confirm_height(fix: dict, text: str | None) -> bool:
    """Whether the page holds the sentence that states the barrier's height, and that sentence holds the figure."""
    h = fix.get("height")
    if not h or text is None:
        return False
    figure = f"{h['value']:g}"
    return re.search(rf"(?<![\d.]){re.escape(figure)}(?![\d]|\.\d)", _norm(h["quote"])) is not None and _has_sentence(_norm(text), h["quote"])


# ---- the run ---------------------------------------------------------------------------------------

_TO_FT = {"ft": 1.0, "in": 1 / 12, "cm": 1 / 30.48, "m": 1 / 0.3048}


def _clean(args: dict[str, Any]) -> dict | None:
    """One recorded fix in the shape that is saved, or None if it is not usable as a record at all."""
    try:
        price = float(args["price"])
    except (KeyError, TypeError, ValueError):
        return None
    if price <= 0 or args.get("type") not in ("quick", "long-term") or not str(args.get("source_url") or "").startswith("http") or not str(args.get("quote") or "").strip():
        return None
    num = lambda k: float(args[k]) if isinstance(args.get(k), (int, float)) and not isinstance(args.get(k), bool) and args[k] > 0 else None
    high = num("price_high")
    height = None
    if num("height") and args.get("height_unit") in _TO_FT and str(args.get("height_quote") or "").strip():
        other = str(args.get("height_source_url") or "").strip()
        height = {"value": num("height"), "unit": args["height_unit"], "quote": str(args["height_quote"]).strip()[:500], "url": other if other.startswith("http") else str(args["source_url"]).strip()}
    return {"name": str(args.get("name") or "").strip()[:80], "type": args["type"], "price": price, "price_high": high if high and high > price else None, "price_unit": args.get("price_unit") or "other",
            "height": height, "holds_ft": round(height["value"] * _TO_FT[height["unit"]], 2) if height else None,
            "crew_hours_per_100ft": num("crew_hours_per_100ft"), "bags_per_person_hour": num("bags_per_person_hour"), "weeks": num("weeks"),
            "time_text": (str(args["time_text"]).strip()[:200] if args.get("time_text") else None),
            "source": {"title": str(args.get("source_title") or "").strip()[:160], "url": str(args["source_url"]).strip(), "quote": str(args["quote"]).strip()[:500]}}


def _loop(client: anthropic.Anthropic, system: str, ask: str, tools: list[dict], handle, fetch) -> dict:
    """One run of a research agent: it searches, it records, and each record is handed to `handle(name, input, read)`,
    which returns the line the agent is told. Returns how the run stopped, its steps, and what it used."""
    t0, steps, pages = time.time(), [], {}

    def read(url: str) -> str | None:      # the page as the agent's own fetch returned it, else a fetch from here; once each in a run
        key = _url_key(url)
        if key not in pages:
            pages[key] = fetch(url)
        return pages[key]

    usage = {"input_tokens": 0, "output_tokens": 0}
    note = lambda kind, text, **more: steps.append({"t": round(time.time() - t0, 1), "kind": kind, "text": text, **more})
    messages: list[dict] = [{"role": "user", "content": ask}]
    stop = "max_turns"
    try:
        for _ in range(MAX_TURNS):
            resp = client.beta.messages.create(
                model=AGENT_MODEL, max_tokens=16000, system=system, tools=tools, messages=messages,
                thinking={"type": "adaptive"}, output_config={"effort": "medium"},
                betas=["server-side-fallback-2026-07-01"], fallbacks="default",
            )
            for k in usage:
                usage[k] += getattr(resp.usage, k, 0) or 0
            for block in resp.content:
                if block.type == "server_tool_use" and block.name == "web_search" and isinstance(block.input, dict) and block.input.get("query"):
                    note("search", str(block.input["query"]))
                elif block.type == "web_fetch_tool_result":
                    url, text = _fetched(block)
                    if url and text:
                        pages[_url_key(url)] = text
                        note("read", url)
            if resp.stop_reason == "refusal":
                stop = "refusal"
                break
            messages.append({"role": "assistant", "content": resp.content})     # thinking blocks go back unchanged
            if resp.stop_reason == "pause_turn":
                continue
            calls = [b for b in resp.content if b.type == "tool_use"]
            if not calls:
                stop = resp.stop_reason or "end_turn"
                break
            results = []
            for c in calls:
                said, error = handle(c.name, dict(c.input), read, note)
                results.append({"type": "tool_result", "tool_use_id": c.id, "content": said, **({"is_error": True} if error else {})})
            messages.append({"role": "user", "content": results})
    except anthropic.APIStatusError as e:
        stop = f"error: {e.status_code}"
    except anthropic.APIConnectionError:
        stop = "error: no connection"
    return {"made_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "model": AGENT_MODEL, "seconds": round(time.time() - t0, 1), "stop": stop, "steps": steps, "usage": usage}


def _url_key(url: str) -> str:
    u = urlparse(url.strip())
    return f"{(u.hostname or '').removeprefix('www.')}{u.path.rstrip('/')}?{u.query}".lower()


def _fetched(block: Any) -> tuple[str | None, str | None]:
    """The address and the words of a page the agent's web_fetch read, or (None, None) when the fetch failed or returned a file that is not text."""
    got = getattr(block, "content", None)
    got = got.model_dump() if hasattr(got, "model_dump") else got
    if not isinstance(got, dict) or not got.get("url"):
        return None, None
    source = ((got.get("content") or {}).get("source") or {}) if isinstance(got.get("content"), dict) else {}
    return got["url"], source.get("data") if source.get("type") == "text" else None


def research(client: anthropic.Anthropic | None = None, save: bool = True, fetch=page_text) -> dict:
    """Run the research once and save what was found, each fix marked with whether its page confirmed it."""
    fixes: list[dict] = []

    def handle(name: str, args: dict, read, note) -> tuple[str, bool]:
        fix = _clean(args) if name == "record_fix" else None
        if fix is None:
            return "Not recorded: a fix needs a price above zero, a type, a page address and the sentence that states the price.", True
        fix["checked"], fix["check_note"] = confirm(fix, read(fix["source"]["url"]))
        if fix["height"] and not confirm_height(fix, read(fix["height"]["url"])):      # a height that its page does not bear out is dropped, not trusted
            fix["holds_ft"], fix["check_note"] = None, fix["check_note"] + "; the height is not"
        fixes.append(fix)
        note("found", f"{fix['name']}: ${fix['price']:,.2f} {fix['price_unit']}", type=fix["type"], checked=fix["checked"], source=fix["source"]["url"])
        return f"Recorded. Check of the page: {fix['check_note']}.", False

    run = _loop(client or anthropic.Anthropic(), SYSTEM, "Research flood fixes for apartment buildings in Houston, with prices and times, and record each one.", TOOLS, handle, fetch)
    run = {**run, "fixes": fixes}
    if save and fixes and not run["stop"].startswith("error"):
        flood.RESEARCH.parent.mkdir(parents=True, exist_ok=True)
        flood.RESEARCH.write_text(json.dumps(run, indent=1))
    return run


# ---- what it costs to put a flooded home back: a price for each line of the insurer's file ---------

PRICE_SYSTEM = """You research prices for Brace, which prepares a file for a property insurer on what it costs to put a flooded apartment in Houston back as it was. You are given a list of things to price: building work, each in a stated unit, and pieces of furniture.

For each thing on the list, find a page that states what it costs in the United States and call record_price once.

Rules
- Record a price only when a page states it, in the unit asked for. Copy the sentence that states the price into quote, word for word, and give that page's address.
- When the page gives a range, record its low end as price and its high end as price_high.
- Do not work out a price yourself and do not convert one unit into another. If a page prices the thing in another unit, look for another page.
- For building work, the price should cover materials and labour together. Prefer a cost guide, a government or university page, or a trade publication.
- For furniture, the price is what a comparable new piece sells for. A retailer's or a buying guide's stated price range for that kind of piece is what is wanted.
- Open the page with web_fetch before you record from it, so the price can be checked against the page as it was read.
- Prefer a web page to a PDF file: a PDF cannot be checked here.
- If you cannot find a stated price for something, leave it out.
- Stop when the list is covered or after twelve searches. Finish with one line saying how many you recorded."""


def _price_tool(ids: list[str]) -> dict:
    return {
        "name": "record_price",
        "description": "Record the stated price of one thing on the list, with the page it came from. Call once for each thing.",
        "input_schema": {
            "type": "object",
            "properties": {
                "item": {"type": "string", "enum": ids, "description": "Which thing on the list this prices."},
                "price": {"type": "number", "description": "The stated price in US dollars, in the unit the list asks for. The low end if the page gives a range."},
                "price_high": {"type": ["number", "null"], "description": "The high end, if the page gives a range. Otherwise null."},
                "source_title": {"type": "string"},
                "source_url": {"type": "string"},
                "quote": {"type": "string", "description": "The sentence on the page that states the price, word for word."},
            },
            "required": ["item", "price", "price_high", "source_title", "source_url", "quote"],
            "additionalProperties": False,
        },
    }


def price(items: list[dict], client: anthropic.Anthropic | None = None, save_to=None, fetch=page_text) -> dict:
    """Find a stated price for each item ({"id", "what", "unit"}) and check each against its page. Saves to `save_to` when given."""
    known = {i["id"]: i for i in items}
    prices: list[dict] = []

    def handle(name: str, args: dict, read, note) -> tuple[str, bool]:
        try:
            item, low = known[args["item"]], float(args["price"])
        except (KeyError, TypeError, ValueError):
            return "Not recorded: the item must be one on the list and the price a number.", True
        if low <= 0 or not str(args.get("source_url") or "").startswith("http") or not str(args.get("quote") or "").strip():
            return "Not recorded: a price needs to be above zero, with a page address and the sentence that states it.", True
        high = args.get("price_high")
        high = float(high) if isinstance(high, (int, float)) and not isinstance(high, bool) and high > low else None
        row = {"item": item["id"], "price": low, "price_high": high, "unit": item["unit"],
               "source": {"title": str(args.get("source_title") or "").strip()[:160], "url": str(args["source_url"]).strip(), "quote": str(args["quote"]).strip()[:500]}}
        row["checked"], row["check_note"] = confirm(row, read(row["source"]["url"]))
        prices.append(row)
        note("found", f"{item['what']}: ${low:,.2f}" + (f" to ${high:,.2f}" if high else "") + f" {item['unit']}", checked=row["checked"], source=row["source"]["url"])
        return f"Recorded. Check of the page: {row['check_note']}.", False

    listed = "\n".join(f"- {i['id']}: {i['what']} ({i['unit']})" for i in items)
    run = _loop(client or anthropic.Anthropic(), PRICE_SYSTEM, f"Price each of these and record it:\n{listed}",
                [SEARCH, FETCH, _price_tool(list(known))], handle, fetch)
    run = {**run, "items": items, "prices": prices}
    if save_to is not None and prices and not run["stop"].startswith("error"):
        save_to.parent.mkdir(parents=True, exist_ok=True)
        save_to.write_text(json.dumps(run, indent=1))
    return run
