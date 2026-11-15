"""The inventory of one scanned home, made by a deep agent: what the owner would have to replace, room by room.

Built on LangChain's deepagents. One orchestrator takes the scan, lists its rooms, and gives each room to a reader
(a sub-agent with its own context). A reader looks at that room's panoramas, one direction at a time, and records
each piece of fit-out it can see with where it saw it. The orchestrator then reconciles what came back, because the
same refrigerator is seen from two standpoints, and writes its notes to files.

The agent names and counts. It does not measure, price or total:

* an item is recorded only against a view the reader actually looked at (no sighting, no item);
* only kinds in KINDS can be recorded: the fit-out an owner insures, never furniture or anything a tenant owns;
* floor area, wall length and door counts come from Matterport's measurements (`insurer_file`), not from the model;
* prices and totals are worked out in `schedule.py`.

Run it with `python -m scripts.inventory <property> <scan>`. The run is saved in the data folder.
"""
from __future__ import annotations

import json
import math
import time
from datetime import datetime, timezone
from typing import Any

from . import flood, matterport, vision
from .config import AGENT_MODEL, CACHE_DIR

OUT = CACHE_DIR / "inventory"
MAX_STEPS = 200
SIDES = {"ahead": 1, "right": 2, "behind": 3, "left": 4}

# What an owner's building cover takes in inside a home, and nothing else. Each is counted, one line per kind.
KINDS = {
    "refrigerator": "Refrigerator", "range": "Range or stove with oven", "range hood": "Range hood", "built-in microwave": "Built-in microwave",
    "dishwasher": "Dishwasher", "kitchen sink": "Kitchen sink with faucet", "base cabinet": "Base cabinet", "wall cabinet": "Wall cabinet",
    "kitchen countertop": "Kitchen countertop, one run", "toilet": "Toilet", "bathtub or shower": "Bathtub or shower", "bathroom vanity": "Bathroom vanity with sink",
    "bathroom mirror": "Bathroom mirror or medicine cabinet", "light fixture": "Ceiling or wall light fixture", "ceiling fan": "Ceiling fan",
    "window blind": "Window blind", "closet door": "Closet door, sliding or folding", "air conditioner": "Wall or window air conditioner",
    "wall heater": "Wall heater", "water heater": "Water heater", "washer": "Washing machine", "dryer": "Clothes dryer",
}

LEAD_PROMPT = """You are making an inventory of one apartment home for its owner, from the scan Matterport made of it. The owner needs a list of the fit-out they would have to replace if the home were lost: appliances, cabinets, counters, bathroom fixtures, lights, blinds, built-in doors. Not furniture, not decoration, not anything a tenant would bring.

How to work
1. Call rooms to see the rooms of the scan.
2. Give every room to a reader with the task tool. Send them all in one turn. Tell each reader the room's id and name, and nothing else.
3. When the readers are back, call recorded. The same thing is often seen from two standpoints, or from a neighbouring room through a doorway. Where two records are the same physical thing, call merge and say why. Where a count looks doubled, merge.
4. Write /inventory.md with write_file: one line per room, what stands in it.
5. Finish with a statement of five lines or fewer: how many rooms were read, how many items remain, and anything a reader could not see.

Rules
- Say only what the tools returned. Do not add an item yourself; only a reader who looked can record one.
- Do not estimate a size, a price or a total. Those are worked out elsewhere."""

READER_PROMPT = """You read one room of a scanned apartment home and record the owner's fit-out in it. You are given the room's id and name.

How to work
1. Call standpoints for the room. Each standpoint is a place the camera stood.
2. From each standpoint, call look in all four directions: ahead, right, behind, left. Look before you record.
3. For each piece of fit-out you can see in this room, call record_item once, against the view you saw it best in. Count carefully: for cabinets count the cabinet boxes (a pair of doors on one box is one cabinet), base and wall cabinets separately.
4. Finish with three lines or fewer: what you recorded, and anything you could not see well.

Rules
- Record only the kinds the tool accepts. Furniture, rugs, pictures, lamps on tables, plants and anything a tenant would own are not recorded.
- Record a thing once. If you saw it from two standpoints, record it against the better view only.
- Record only what is in this room. Something seen through a doorway belongs to the other room.
- If you are not sure a thing is there, do not record it; say so in your last lines."""


class InventoryRun:
    """What one run looked at, recorded and merged."""

    def __init__(self, property_id: int, scan_id: str, only: list[str] | None = None):
        try:
            bundle = json.loads((flood.BUILDINGS / str(property_id) / "building.json").read_text())
        except OSError:
            raise ValueError("this building has not been gathered")
        scan = next((s for s in bundle.get("scans") or [] if s["id"] == scan_id), None)
        if scan is None:
            raise ValueError("no such scan at this building")
        self.property_id, self.scan_id, self.scan = property_id, scan_id, scan
        by_room: dict[str, list[dict]] = {}
        for sw in scan.get("sweeps") or []:
            by_room.setdefault(sw.get("room_id"), []).append(sw)
        self.rooms: dict[str, dict] = {}
        seen: dict[str, int] = {}
        for r in scan.get("rooms") or []:
            kind = r.get("type") or ""
            if kind in ("", "Void") or not by_room.get(r["id"]):
                continue                      # a room nobody stood in cannot be read
            seen[kind] = seen.get(kind, 0) + 1
            rid = f"{kind.lower().replace(' ', '-')}-{seen[kind]}"
            if only and rid not in only and kind not in only:
                continue
            self.rooms[rid] = {"id": rid, "matterport_id": r["id"], "name": kind, "area_sqft": r.get("area_sqft"),
                               "standpoints": {f"p{i + 1}": sw for i, sw in enumerate(by_room[r["id"]])}}
        self.looked: set[tuple[str, str, str]] = set()
        self.items: list[dict] = []
        self.merges: list[dict] = []
        self.events: list[dict] = []
        self.t0 = time.time()

    def note(self, kind: str, **data: Any) -> None:
        self.events.append({"t": round(time.time() - self.t0, 1), "kind": kind, **data})

    def _room(self, room_id: str) -> dict | None:
        return self.rooms.get(str(room_id).strip())

    # ---- what the readers and the lead can do ---------------------------------------------------------
    def tools(self) -> dict[str, Any]:
        run = self

        def rooms() -> str:
            """The rooms of this scan that the camera stood in: id, name, floor area, and how many standpoints each has."""
            run.note("rooms", count=len(run.rooms))
            return json.dumps([{"id": r["id"], "name": r["name"], "area_sqft": r["area_sqft"], "standpoints": len(r["standpoints"])} for r in run.rooms.values()])

        def standpoints(room_id: str) -> str:
            """The places the camera stood in one room. Look from each of them in all four directions."""
            room = run._room(room_id)
            if not room:
                return "No such room. Use the room id you were given."
            return json.dumps({"room": room["id"], "name": room["name"], "standpoints": list(room["standpoints"]), "directions": list(SIDES)})

        def look(room_id: str, standpoint: str, direction: str) -> list:
            """Look from one standpoint in one direction (ahead, right, behind or left). Returns the picture the scan took that way."""
            room = run._room(room_id)
            sw = (room or {}).get("standpoints", {}).get(str(standpoint).strip())
            if not room or not sw or direction not in SIDES:
                return [{"type": "text", "text": "No such view. Call standpoints for the room, then use one of its standpoints and ahead, right, behind or left."}]
            try:
                path = matterport.face_image(run.scan_id, sw["id"], SIDES[direction])
            except matterport.MatterportError as e:
                return [{"type": "text", "text": f"That picture could not be fetched: {e}"}]
            run.looked.add((room["id"], standpoint, direction))
            run.note("look", room=room["id"], standpoint=standpoint, direction=direction)
            return [{"type": "text", "text": f"{room['name']}, standpoint {standpoint}, looking {direction}. Across runs 0 at the left edge to 1 at the right; up runs 0 at the top to 1 at the bottom."},
                    vision.image_block(path, max_side=896)]

        def record_item(room_id: str, kind: str, quantity: int, standpoint: str, direction: str, across: float, down: float, what_you_saw: str) -> str:
            """Record one kind of fit-out seen in this room. kind must be one of the listed kinds. quantity is how many of it are in the room.
            standpoint and direction are the view you saw it best in; across and down are where it is in that picture, each from 0 to 1.
            what_you_saw is a few plain words, for example 'white top-freezer refrigerator'."""
            room = run._room(room_id)
            if not room:
                return "Not recorded: no such room."
            if kind not in KINDS:
                return f"Not recorded: '{kind}' is not fit-out the owner insures. The kinds are: {', '.join(KINDS)}."
            if (room["id"], str(standpoint).strip(), direction) not in run.looked:
                return "Not recorded: nobody has looked that way from that standpoint. Call look first, then record what you saw."
            try:
                n, x, y = int(quantity), float(across), float(down)
            except (TypeError, ValueError):
                return "Not recorded: quantity must be a whole number and across and down numbers from 0 to 1."
            if not (1 <= n <= 40 and 0 <= x <= 1 and 0 <= y <= 1):
                return "Not recorded: quantity must be from 1 to 40 and across and down from 0 to 1."
            sw = room["standpoints"][str(standpoint).strip()]
            # Where it is, as a turn and a tilt from the standpoint: a cube face spans 90 degrees each way about its centre.
            dx, dy = 2 * x - 1, 1 - 2 * y
            yaw = ((sw.get("heading") or 0) + 90 * (SIDES[direction] - 1) + math.degrees(math.atan(dx))) % 360
            pitch = math.degrees(math.atan(dy / math.hypot(1, dx)))
            item = {"id": f"i{len(run.items) + 1}", "room": room["id"], "room_name": room["name"], "kind": kind, "what": KINDS[kind], "quantity": n, "seen": str(what_you_saw).strip()[:120],
                    "at": {"sweep_id": sw["id"], "standpoint": str(standpoint).strip(), "direction": direction, "yaw_deg": round(yaw, 1), "pitch_deg": round(pitch, 1)}, "merged_into": None}
            run.items.append(item)
            run.note("item", room=room["id"], item=kind, quantity=n)
            return f"Recorded as {item['id']}: {n} x {KINDS[kind]} in {room['name']}."

        def recorded() -> str:
            """Everything the readers recorded, by room, less what has been merged away."""
            live = [i for i in run.items if not i["merged_into"]]
            return json.dumps([{k: i[k] for k in ("id", "room", "kind", "quantity", "seen")} for i in live]) if live else "Nothing has been recorded."

        def merge(keep_id: str, drop_ids: list[str], why: str) -> str:
            """Say that some records are the same physical things as another record, seen twice. The dropped records no longer count."""
            by = {i["id"]: i for i in run.items}
            keep = by.get(keep_id)
            drops = [by[d] for d in drop_ids if d in by and d != keep_id and not by[d]["merged_into"]]
            if not keep or keep["merged_into"] or not drops:
                return "Nothing merged: use ids from recorded, and keep one that has not been merged away."
            if any(d["kind"] != keep["kind"] for d in drops):
                return "Nothing merged: records of different kinds are different things."
            for d in drops:
                d["merged_into"] = keep_id
            run.merges.append({"keep": keep_id, "drop": [d["id"] for d in drops], "why": str(why).strip()[:200]})
            run.note("merge", keep=keep_id, dropped=len(drops))
            return f"Merged {len(drops)} record(s) into {keep_id}."

        return {f.__name__: f for f in (rooms, standpoints, look, record_item, recorded, merge)}

    def record(self, statement: str, files: dict[str, str], usage: dict, stop: str) -> dict:
        live = [i for i in self.items if not i["merged_into"]]
        return {
            "property_id": self.property_id, "scan_id": self.scan_id, "scan_name": self.scan.get("name"), "made_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "seconds": round(time.time() - self.t0, 1), "model": AGENT_MODEL, "stop": stop,
            "rooms": [{"id": r["id"], "name": r["name"], "area_sqft": r["area_sqft"], "standpoints": len(r["standpoints"])} for r in self.rooms.values()],
            "items": live, "merged_away": [i for i in self.items if i["merged_into"]], "merges": self.merges,
            "numbers": {"rooms_read": len({room for room, _, _ in self.looked}), "views_looked_at": len(self.looked), "items_named": sum(i["quantity"] for i in live), "lines": len(live)},
            "notes": files, "statement": statement, "events": self.events, "usage": usage,
        }


def _text(content: Any) -> str:
    if isinstance(content, str):
        return content
    return "\n".join(b.get("text", "") for b in content or [] if isinstance(b, dict) and b.get("type") == "text").strip()


def build(run: InventoryRun, model: Any = None):
    """The lead and its room reader, wired to one run's tools."""
    from deepagents import create_deep_agent
    if model is None:
        from langchain_anthropic import ChatAnthropic
        model = ChatAnthropic(model=AGENT_MODEL, max_tokens=8000)
    t = run.tools()
    reader = {"name": "reader", "description": "Reads one room of the scan: looks from every standpoint in every direction and records the owner's fit-out it sees. Give it one room id and name.",
              "system_prompt": READER_PROMPT, "tools": [t["standpoints"], t["look"], t["record_item"]]}
    return create_deep_agent(model=model, system_prompt=LEAD_PROMPT, subagents=[reader], name="brace-inventory", tools=[t["rooms"], t["recorded"], t["merge"]])


def saved(scan_id: str) -> dict | None:
    try:
        return json.loads((OUT / f"{scan_id}.json").read_text())
    except (OSError, ValueError):
        return None


def tokens(counted: dict, messages: list) -> dict:
    """The tokens a run used. `counted` is what was counted at every model call, lead and readers alike, by model;
    when nothing was counted on the way, the lead's own messages are all there is to add up."""
    rows = list(counted.values()) if counted else [getattr(m, "usage_metadata", None) or {} for m in messages]
    return {k: sum(r.get(k, 0) or 0 for r in rows) for k in ("input_tokens", "output_tokens")}


def run_inventory(property_id: int, scan_id: str, only: list[str] | None = None, model: Any = None, save: bool = True) -> dict:
    """Read one scan and save what the owner would have to replace in it."""
    run = InventoryRun(property_id, scan_id, only)
    agent = build(run, model)
    stop, statement, files, usage = "finished", "", {}, {"input_tokens": 0, "output_tokens": 0}
    from langchain_core.callbacks import UsageMetadataCallbackHandler
    counter = UsageMetadataCallbackHandler()       # hears every model call, the readers' as well as the lead's
    try:
        out = agent.invoke({"messages": [{"role": "user", "content": f"Make the inventory of this home: {run.scan.get('name')}. It has {len(run.rooms)} rooms the camera stood in."}]},
                           config={"recursion_limit": MAX_STEPS, "callbacks": [counter]})
        statement = next((_text(m.content) for m in reversed(out["messages"]) if getattr(m, "type", "") == "ai" and _text(m.content)), "")
        for path, data in (out.get("files") or {}).items():
            content = data.get("content") if isinstance(data, dict) else data
            files[path] = "\n".join(content) if isinstance(content, list) else str(content or "")
        usage = tokens(counter.usage_metadata, out["messages"])
    except Exception as e:      # a failed run is recorded as failed, with what it had recorded so far
        stop, statement = "error", f"The inventory stopped: {e}"
        usage = tokens(counter.usage_metadata, [])
    record = run.record(statement, files, usage, stop)
    if save and stop == "finished" and record["items"]:
        OUT.mkdir(parents=True, exist_ok=True)
        (OUT / f"{scan_id}.json").write_text(json.dumps(record, indent=1))
    return record
