"""The spoken guide in the headset: a realtime voice session grounded in one saved plan.

The planner (agent.py) does the inspection. This module only gives that finished inspection a voice:
it builds the notes the voice may speak from, names the tools it can call in the headset, and asks
OpenAI for a short-lived key so the phone can open the session without ever seeing the real key.
"""
from __future__ import annotations

import os

import httpx

MODEL = os.environ.get("BRACE_VOICE_MODEL") or "gpt-realtime-2.1"
VOICE = os.environ.get("BRACE_VOICE") or "marin"
SECRETS_URL = "https://api.openai.com/v1/realtime/client_secrets"

# What an approval does, in fixed words. The voice is told to say these as written, so it can never
# promise that a crew is coming or that anything has left the building.
APPROVED_SAY = ("Approved, and marked on the plan. Nothing has been sent yet: "
                "the resident notice and the work order are drafted and waiting for you.")
UNKNOWN_SAY = "That is not an action in this plan."


class VoiceError(RuntimeError):
    pass


def ready() -> bool:
    return bool(os.environ.get("OPENAI_API_KEY"))


def _money(low: float, high: float) -> str:
    return f"${low:,.0f}" if low == high else f"${low:,.0f} to ${high:,.0f}"


def _where(action: dict) -> str:
    inside, site = action.get("interior"), action.get("site")
    if inside:
        return f"inside, in {inside.get('scan_name') or 'a scanned space'}"
    if site:
        return f"outside{', on ' + action['structure'] if action.get('structure') else ''}"
    return "no pinned location"


TIMING = {"before_arrival": "before it arrives", "after_event": "after the event", "capital": "plan and budget"}


WHERE_THE_OWNER_IS = {
    "headset": "You are speaking with the building's owner, who is wearing a headset and standing inside a scan of the building.",
    "screen": ("You are speaking with the building's owner, who is looking at a large screen: the site from the air on the left, "
               "a scanned interior on the right, and the plan beside them. When you show an action, both views move to it."),
}
# Only the big screen has a camera that reads the owner's head; in the headset a nod is never seen.
HOW_A_GESTURE_ANSWERS = {
    "headset": [],
    "screen": [
        "- A message starting [gesture] is the owner answering by moving their head: a nod means yes and a shake means no. "
        "Treat it as their answer to the yes-or-no question you last asked. If you had not asked one, say briefly that you saw it and ask what they would like.",
        "- When a decision needs a yes or no, for example before approving an action the owner has not clearly asked you to approve, "
        "ask one short yes-or-no question. The owner may answer aloud or with a nod or a shake.",
    ],
}
A_NOD_CAN_APPROVE = {
    "headset": [],
    "screen": ["- A nod in answer to \"Shall I approve it?\" counts as clearly asking. A shake means do not approve it."],
}
HOW_OUTSIDE_SHOWS = {
    "headset": "- Outside items are shown through the walls in their real direction; distances are approximate.",
    "screen": "- Outside items are marked on the site photo; inside items are shown in the scan.",
}


def instructions(record: dict, threat: dict, plan: dict | None, scans: list[dict], view: str = "headset") -> str:
    """Everything the voice may say, and the rules for saying it. No contact details, no tenant records."""
    view = view if view in WHERE_THE_OWNER_IS else "headset"
    site = threat.get("at_this_site") or {}
    hours = threat.get("hours_left")
    lines = [
        "You are Brace, an inspector that has just examined one building before a storm or fire arrives.",
        WHERE_THE_OWNER_IS[view],
        "",
        "HOW TO SPEAK",
        "- First person, plain words, one or two short sentences a turn. Never read a list aloud unless asked.",
        "- Speak English. Give money as a range and say it is a rough estimate when asked.",
        "- A message starting [inspection] is what you are doing at this moment in the walk-through: say it in one short sentence.",
        "- A message starting [finding] is something you just added to the plan: say what it is, what to do and the rough cost, in two sentences.",
        *HOW_A_GESTURE_ANSWERS[view],
        "- Those bracketed tags are stage directions. Never say them, and never say the word in brackets.",
        "- Before a tool call say nothing; speak once, after the tool has answered.",
        "",
        "RULES YOU MUST NOT BREAK",
        "- State only what is in the notes below or returned by a tool. If asked about anything else, say you did not inspect that.",
        "- Never give a risk score, a probability or a damage estimate.",
        "- Wind figures are sustained wind from the forecast, not gusts.",
        "- Never say a crew is coming, booked or on the way, and never say a message was sent to a contractor.",
        "- When a tool result has a 'say' field, speak that sentence exactly as written and add nothing to it.",
        "- Approve an action only when the owner clearly asks you to approve it.",
        *A_NOD_CAN_APPROVE[view],
        HOW_OUTSIDE_SHOWS[view],
        "- A message starting [on screen] tells you what the owner is looking at now, so 'this' and 'that one' mean it. Do not reply to it.",
        "- Saved plans were made for particular forecast steps. Moving the clock shows the plan made for that step; it is a replay, not a new inspection. Say so if asked.",
        "",
        "USING THE TOOLS",
        "- To show something, call go_to_action with its id. To move on, call next_finding.",
        "- Call where_am_i if asked where they are standing or what they are looking at.",
        "- If the owner says how much time is left, or asks what changes with less or more time, call set_hours_left.",
        "- When a notice is waiting for approval on screen, nothing is approved until the owner says so. If they say yes or nod, "
        "call approve_action for the action it names. If they say no, wait or not now, or shake their head, call hold_approval. "
        "Silence is not approval.",
        "",
        "THE BUILDING",
        f"- {record.get('name')}, {record.get('city')}, {record.get('state')}. {record.get('type_label')}"
        + (f", {record['units']} homes" if record.get("units") else "")
        + (f", built {record['year_built']}" if record.get("year_built") else "")
        + (f", {record['stories']} storeys" if record.get("stories") else "") + ".",
        f"- Scanned spaces you can stand in: {', '.join(s.get('name') or 'unnamed' for s in scans) or 'none'}.",
        "",
        "THE THREAT",
        f"- {threat.get('name')}: {threat.get('label') or 'no label'}{' (a replay of the real forecast as issued)' if threat.get('replay') else ''}.",
        "- " + ("No arrival time is available for this site." if hours is None
                else "Damaging conditions are already here." if hours <= 0
                else f"Damaging conditions reach this site in about {round(hours)} hours."),
    ]
    if site.get("peak_wind_mph") is not None:
        lines.append(f"- Forecast peak sustained wind here: about {round(site['peak_wind_mph'])} mph.")
    if plan is None:
        lines += ["", "THE PLAN", "- No inspection has been saved for this building and forecast. Say so if asked what to fix."]
        return "\n".join(lines)
    lines += ["", "THE PLAN", f"- In one line: {plan.get('headline') or 'no headline'}"]
    for timing, total in (plan.get("totals") or {}).items():
        if total.get("count"):
            lines.append(f"- {TIMING.get(timing, timing)}: {total['count']} actions, {_money(total['cost_low'], total['cost_high'])}.")
    lines += ["", "ACTIONS (id, when, where, what, why, who, cost)"]
    for a in plan.get("actions") or []:
        lines.append(f"- {a['id']} | {TIMING.get(a.get('timing'), a.get('timing'))} | {_where(a)} | {a['title']} | {a.get('why')} | "
                     f"{a.get('crew')}, {a.get('hours_of_work')} hours | {_money(a.get('cost_low', 0), a.get('cost_high', 0))}")
    closed = [l for l in plan.get("leads") or [] if l.get("status") in ("not_a_concern", "cannot_check")]
    if closed:
        lines += ["", "CHECKED AND SET ASIDE"]
        lines += [f"- {l['title']}: {'not a concern' if l['status'] == 'not_a_concern' else 'could not check'}. {l.get('note') or ''}".rstrip()
                  for l in closed]
    drafted = plan.get("messages") or []
    if drafted:
        lines += ["", "MESSAGES DRAFTED (nothing has been sent)"]
        lines += [f"- {'Resident notice' if m.get('kind') == 'notice' else 'Work order'} to {m.get('to')}: {m.get('subject')}" for m in drafted]
    return "\n".join(lines)


def tools() -> list[dict]:
    action = {"type": "object", "properties": {"action_id": {"type": "string", "description": "An action id from the plan, such as A1."}},
              "required": ["action_id"]}
    empty = {"type": "object", "properties": {}}
    return [
        {"type": "function", "name": "go_to_action", "parameters": action,
         "description": "Take the owner to an action: move to it if it is inside, or turn them to face it through the wall if it is outside."},
        {"type": "function", "name": "next_finding", "parameters": empty,
         "description": "Move on to the next action in the plan and return it."},
        {"type": "function", "name": "approve_action", "parameters": action,
         "description": "Record the owner's approval of one action. Only when the owner clearly asks."},
        {"type": "function", "name": "where_am_i", "parameters": empty,
         "description": "The scanned space the owner is in or looking at, and what is pinned there."},
        {"type": "function", "name": "hold_approval", "parameters": empty,
         "description": "Put aside the notice that is waiting for approval on screen. It stays unapproved."},
        {"type": "function", "name": "set_hours_left",
         "parameters": {"type": "object", "properties": {"hours": {"type": "number", "description": "Hours left before damaging conditions arrive."}},
                        "required": ["hours"]},
         "description": "Move the clock to the forecast step closest to this many hours left and show the plan made for it. "
                        "Returns what changed between the two plans."},
    ]


def session(record: dict, threat: dict, plan: dict | None, scans: list[dict], view: str = "headset") -> dict:
    """The request body for a short-lived key. Near-field noise reduction suits a phone held at the face."""
    return {"session": {
        "type": "realtime", "model": MODEL,
        "instructions": instructions(record, threat, plan, scans, view),
        "audio": {"input": {"turn_detection": {"type": "semantic_vad"}, "noise_reduction": {"type": "near_field"},
                            "transcription": {"model": "gpt-4o-mini-transcribe"}},
                  "output": {"voice": VOICE}},
        "tools": tools(), "tool_choice": "auto"}}


def mint(body: dict) -> dict:
    """Ask for a short-lived key the phone can use. The real key never leaves this process."""
    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        raise VoiceError("voice is not configured")
    try:
        r = httpx.post(SECRETS_URL, headers={"Authorization": f"Bearer {key}"}, json=body, timeout=20)
    except httpx.HTTPError as e:
        raise VoiceError(f"the voice service could not be reached: {type(e).__name__}") from e
    if r.status_code != 200:
        raise VoiceError(f"the voice service refused the session (HTTP {r.status_code})")
    data = r.json()
    return {"value": data["value"], "expires_at": data.get("expires_at"), "model": body["session"]["model"]}
