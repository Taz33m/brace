"""What the inventory agent decides is kept: what the tools refused, what a reader left out and why, what the lead doubts, and what a second look changed."""
import json
import time
from types import SimpleNamespace

import pytest

from backend import flood, inventory_agent

SCAN = {"id": "u1", "name": "2BR", "structure": "A", "model_created_at": "2026-11-10T00:00:00Z",
        "rooms": [{"id": "rk", "type": "Kitchen", "area_sqft": 70.0, "height_m": 2.4384}, {"id": "rb", "type": "Bedroom", "area_sqft": 120.0, "height_m": 2.4384},
                  {"id": "rc", "type": "Closet", "area_sqft": 20.0, "height_m": 2.4384}],
        "sweeps": [{"id": "s1", "room_id": "rk", "heading": 90.0}, {"id": "s2", "room_id": "rk", "heading": 0.0}, {"id": "s3", "room_id": "rb", "heading": 0.0}]}


@pytest.fixture
def run(tmp_path, monkeypatch):
    (tmp_path / "b" / "7").mkdir(parents=True)
    (tmp_path / "b" / "7" / "building.json").write_text(json.dumps({"scans": [SCAN], "structures": [{"id": "A", "footprint_sqft": 3000}]}))
    monkeypatch.setattr(flood, "BUILDINGS", tmp_path / "b")
    monkeypatch.setattr(inventory_agent, "OUT", tmp_path / "inv")
    monkeypatch.setattr(inventory_agent.matterport, "face_image", lambda scan, sweep, face: tmp_path / "x.jpg")
    monkeypatch.setattr(inventory_agent.vision, "image_block", lambda path, max_side=896: {"type": "text", "text": "(the picture)"})
    return inventory_agent.InventoryRun(7, "u1")


def see(t, room, kind, quantity, standpoint="p1", direction="ahead", saw="x"):
    t["look"](room, standpoint, direction)
    return t["record_item"](room, kind, quantity, standpoint, direction, 0.5, 0.5, saw)


# ---- a to d: the tools, called as the agent calls them --------------------------------------------------

def test_every_record_the_tool_refuses_is_kept_with_what_was_wanted_and_why(run):
    t = run.tools()
    t["record_item"]("kitchen-1", "refrigerator", 1, "p1", "ahead", 0.5, 0.5, "white fridge")       # nobody has looked
    t["look"]("kitchen-1", "p1", "ahead")
    t["record_item"]("kitchen-1", "sofa", 1, "p1", "ahead", 0.5, 0.5, "blue sofa")                   # a tenant's
    t["record_item"]("kitchen-1", "refrigerator", 0, "p1", "ahead", 0.5, 0.5, "x")                   # none of it
    t["record_item"]("kitchen-1", "refrigerator", "a few", "p1", "ahead", 0.5, 0.5, "x")             # not a number
    t["record_item"]("garage-9", "refrigerator", 1, "p1", "ahead", 0.5, 0.5, "x")                    # not a room of this scan
    assert t["record_item"]("kitchen-1", "refrigerator", 1, "p1", "ahead", 0.5, 0.5, "white fridge") == "Recorded as i1: 1 x Refrigerator in Kitchen."
    assert [(r["room"], r["wanted"], r["why"]) for r in run.refused] == [
        ("kitchen-1", "refrigerator", "nobody had looked that way"), ("kitchen-1", "sofa", "not fit-out the owner insures"),
        ("kitchen-1", "refrigerator", "the quantity or the place in the picture was out of range"), ("kitchen-1", "refrigerator", "the quantity or the place in the picture was not a number"),
        ("garage-9", "refrigerator", "no such room")]
    assert run.refused[1] == {"room": "kitchen-1", "room_name": "Kitchen", "wanted": "sofa", "seen": "blue sofa", "why": "not fit-out the owner insures"} and run.refused[4]["room_name"] is None
    events = [e for e in run.events if e["kind"] == "refused"]
    assert len(events) == 5 and {k: events[1][k] for k in ("room", "wanted", "why")} == {"room": "kitchen-1", "wanted": "sofa", "why": "not fit-out the owner insures"}
    assert len(run.items) == 1                                                                       # a refusal records nothing


def test_a_reader_says_what_it_left_out_and_only_for_a_reason_on_the_list(run):
    t = run.tools()
    assert t["skip"]("kitchen-1", "grey sofa", "furniture or a tenant's own") == "Not noted: nobody has looked in this room yet. Call look first."
    t["look"]("kitchen-1", "p1", "ahead")
    assert t["skip"]("kitchen-1", "grey sofa", "furniture or a tenant's own") == "Noted: grey sofa in Kitchen was left out (furniture or a tenant's own)."
    assert t["skip"]("kitchen-1", "a vent above the door", " Could not see it well enough. ").startswith("Noted:")      # the reason is matched whatever its case and full stop
    said = t["skip"]("kitchen-1", "microwave on the counter", "it looked cheap")
    assert said.startswith("Not noted: why must be one of:") and all(r in said for r in inventory_agent.SKIP_REASONS)
    assert t["skip"]("garage-9", "x", "belongs to another room") == "Not noted: no such room." and t["skip"]("kitchen-1", " ", "belongs to another room").startswith("Not noted: say what you saw")
    assert run.skipped == [{"room": "kitchen-1", "room_name": "Kitchen", "saw": "grey sofa", "why": "furniture or a tenant's own"},
                           {"room": "kitchen-1", "room_name": "Kitchen", "saw": "a vent above the door", "why": "could not see it well enough"}]
    assert [(e["room"], e["saw"], e["why"]) for e in run.events if e["kind"] == "skipped"] == [("kitchen-1", "grey sofa", "furniture or a tenant's own"), ("kitchen-1", "a vent above the door", "could not see it well enough")]
    assert len(inventory_agent.SKIP_REASONS) == 4 and not run.items and not run.refused               # leaving a thing out records nothing and is not a refusal


def test_a_room_takes_only_a_few_things_left_out(run):
    t = run.tools()
    t["look"]("kitchen-1", "p1", "ahead"); t["look"]("bedroom-1", "p1", "ahead")
    said = [t["skip"]("kitchen-1", f"chair {n}", "furniture or a tenant's own") for n in range(inventory_agent.MAX_SKIPS + 1)]
    assert all(s.startswith("Noted:") for s in said[:-1]) and said[-1].startswith("Not noted: 6 things are already noted")
    assert t["skip"]("bedroom-1", "bed", "furniture or a tenant's own").startswith("Noted:")          # the count is for each room
    assert len(run.skipped) == inventory_agent.MAX_SKIPS + 1


def test_the_lead_flags_a_doubt_about_a_live_record_in_its_own_room_or_about_the_room(run):
    t = run.tools()
    see(t, "kitchen-1", "wall cabinet", 3); see(t, "kitchen-1", "wall cabinet", 3, "p2"); see(t, "bedroom-1", "ceiling fan", 1)
    t["merge"]("i1", ["i2"], "the same cabinets from the other standpoint")
    assert t["flag_doubt"]("garage-9", "", "x").startswith("Not flagged: no such room")
    assert t["flag_doubt"]("kitchen-1", "i9", "x").startswith("Not flagged: no such record")
    assert t["flag_doubt"]("kitchen-1", "i2", "x") == "Not flagged: that record was merged into i1. Flag the doubt against that one."
    assert t["flag_doubt"]("kitchen-1", "i3", "x") == "Not flagged: that record is in bedroom-1, not in kitchen-1."
    assert t["flag_doubt"]("kitchen-1", "i1", "  ").startswith("Not flagged: say the doubt")
    assert not run.doubts
    assert t["flag_doubt"]("kitchen-1", "i1", "There may be a fourth wall cabinet beside the window.") == "Flagged as d1."
    assert t["flag_doubt"]("bedroom-1", "", "The far corner is dark\nin every picture.") == "Flagged as d2." and t["flag_doubt"]("bedroom-1", None, "The closet door was shut.") == "Flagged as d3."
    assert run.doubts[:2] == [{"id": "d1", "room": "kitchen-1", "room_name": "Kitchen", "item_id": "i1", "kind": "wall cabinet", "doubt": "There may be a fourth wall cabinet beside the window."},
                              {"id": "d2", "room": "bedroom-1", "room_name": "Bedroom", "item_id": None, "kind": None, "doubt": "The far corner is dark in every picture."}]
    assert [(e["room"], e["item"]) for e in run.events if e["kind"] == "doubt"] == [("kitchen-1", "i1"), ("bedroom-1", None), ("bedroom-1", None)]
    assert len(run.items) == 3 and [i["quantity"] for i in run.items] == [3, 3, 1]                    # a doubt changes no count


def test_the_saved_run_carries_the_decisions_and_their_counts(run):
    t = run.tools()
    see(t, "kitchen-1", "refrigerator", 1); see(t, "kitchen-1", "refrigerator", 1, "p2"); see(t, "kitchen-1", "sofa", 1)
    t["merge"]("i1", ["i2"], "the same refrigerator"); t["skip"]("kitchen-1", "sofa", "furniture or a tenant's own"); t["flag_doubt"]("kitchen-1", "", "The cupboard under the sink was shut.")
    rec = run.record("done", {}, {"input_tokens": 0, "output_tokens": 0}, "finished")
    assert rec["decisions"] == {"refused": 1, "skipped": 1, "merged": 1, "doubts": 1}
    assert rec["refused"] == run.refused and rec["skipped"] == run.skipped and rec["doubts"] == run.doubts
    assert rec["numbers"] == {"rooms_read": 1, "views_looked_at": 2, "items_named": 1, "lines": 1}    # the counts of what was found are as they were
    assert json.loads(json.dumps(rec))["doubts"][0]["item_id"] is None
    empty = inventory_agent.InventoryRun(7, "u1").record("", {}, {}, "finished")
    assert (empty["refused"], empty["skipped"], empty["doubts"], empty["decisions"]) == ([], [], [], {"refused": 0, "skipped": 0, "merged": 0, "doubts": 0})


def test_the_reader_can_skip_and_the_lead_can_flag_a_doubt_and_neither_has_the_others_tool(run, monkeypatch):
    import deepagents
    made = {}
    monkeypatch.setattr(deepagents, "create_deep_agent", lambda **kw: made.update(kw) or "the agent")
    assert inventory_agent.build(run, model=object()) == "the agent"
    assert [f.__name__ for f in made["tools"]] == ["rooms", "recorded", "merge", "flag_doubt"]
    assert [f.__name__ for f in made["subagents"][0]["tools"]] == ["standpoints", "look", "record_item", "skip"]
    assert list(run.tools()) == ["rooms", "standpoints", "look", "record_item", "skip", "recorded", "merge", "flag_doubt"]
    assert "flag_doubt" in inventory_agent.LEAD_PROMPT and "call skip" in inventory_agent.READER_PROMPT
    assert all(f'"{r}"' in run.tools()["skip"].__doc__ for r in inventory_agent.SKIP_REASONS)         # the reader is told the reasons the tool takes


# ---- the real graph, with a model that follows a script: no network, no key -------------------------------

def scripted(messages):
    from langchain_core.language_models.fake_chat_models import GenericFakeChatModel

    class Scripted(GenericFakeChatModel):
        def bind_tools(self, tools, **kw):
            return self
    return Scripted(messages=iter(messages))


def call(name, **args):
    from langchain_core.messages import AIMessage
    return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": f"call-{name}-{time.time_ns()}"}], usage_metadata={"input_tokens": 10, "output_tokens": 2, "total_tokens": 12})


def test_a_whole_run_leaves_a_trace_of_each_decision_and_is_saved(run):
    from langchain_core.messages import AIMessage
    at = {"room_id": "kitchen-1", "standpoint": "p1", "direction": "ahead"}
    model = scripted([
        call("rooms"), call("task", description="Read room kitchen-1, Kitchen.", subagent_type="reader"),
        call("look", **at),                                                                                                              # from here the reader speaks
        call("record_item", **at, kind="sofa", quantity=1, across=0.5, down=0.5, what_you_saw="grey sofa"),
        call("record_item", **at, kind="wall cabinet", quantity=3, across=0.5, down=0.3, what_you_saw="white wall cabinets"),
        call("record_item", **at, kind="wall cabinet", quantity=3, across=0.6, down=0.3, what_you_saw="the same cabinets"),
        call("skip", room_id="kitchen-1", what_you_saw="grey sofa", why="furniture or a tenant's own"),
        AIMessage(content="Recorded the wall cabinets. There may be a fourth beside the window."),
        call("recorded"), call("merge", keep_id="i1", drop_ids=["i2"], why="the same three cabinets recorded twice"),                    # and from here the lead again
        call("flag_doubt", room_id="kitchen-1", about="i1", doubt="There may be a fourth wall cabinet beside the window."),
        AIMessage(content="One room read. Three items remain. One doubt flagged."),
    ])
    rec = inventory_agent.run_inventory(7, "u1", only=["kitchen-1"], model=model)
    assert rec["stop"] == "finished" and rec["statement"] == "One room read. Three items remain. One doubt flagged." and rec["usage"]["input_tokens"] >= 10
    assert rec["decisions"] == {"refused": 1, "skipped": 1, "merged": 1, "doubts": 1} and rec["numbers"]["items_named"] == 3
    assert [e["kind"] for e in rec["events"]] == ["rooms", "look", "refused", "item", "item", "skipped", "merge", "doubt"]
    assert rec["doubts"][0]["item_id"] == "i1" and rec["refused"][0]["wanted"] == "sofa" and rec["skipped"][0]["saw"] == "grey sofa"
    assert inventory_agent.saved("u1")["decisions"] == rec["decisions"]


def test_a_run_that_fails_is_returned_as_failed_and_not_saved(run, monkeypatch):
    def broken(messages, config=None):
        raise RuntimeError("the model did not answer")
    monkeypatch.setattr(inventory_agent, "build", lambda r, model=None: SimpleNamespace(invoke=broken))
    rec = inventory_agent.run_inventory(7, "u1")
    assert (rec["stop"], rec["statement"], rec["items"], rec["usage"]) == ("error", "The inventory stopped: the model did not answer", [], {"input_tokens": 0, "output_tokens": 0})
    assert inventory_agent.saved("u1") is None


# ---- e: a second look at one room ---------------------------------------------------------------------------

@pytest.fixture
def first(run, tmp_path):
    """A first reading, saved: a kitchen with three wall cabinets, a hood and a refrigerator seen twice; a bedroom with a fan; a doubt in each."""
    t = run.tools()
    see(t, "kitchen-1", "wall cabinet", 3); see(t, "kitchen-1", "range hood", 1); see(t, "kitchen-1", "refrigerator", 1); see(t, "kitchen-1", "refrigerator", 1, "p2")
    see(t, "bedroom-1", "ceiling fan", 1); see(t, "bedroom-1", "sofa", 1)
    t["merge"]("i3", ["i4"], "the same refrigerator from the other standpoint")
    t["skip"]("kitchen-1", "bar stools", "furniture or a tenant's own"); t["skip"]("bedroom-1", "bed", "furniture or a tenant's own")
    t["flag_doubt"]("kitchen-1", "i1", "There may be a fourth wall cabinet beside the window."); t["flag_doubt"]("bedroom-1", "", "The far corner is dark.")
    rec = run.record("Two rooms read.", {}, {"input_tokens": 0, "output_tokens": 0}, "finished")
    (tmp_path / "inv").mkdir()
    (tmp_path / "inv" / "u1.json").write_text(json.dumps(rec, indent=1))
    return rec


def second_look(monkeypatch, act, statement="Read again. Four wall cabinets."):
    """Stand in for the agent: a thing whose invoke uses the run's own tools, as the lead and its reader do."""
    asked = []

    def build(r, model=None):
        def invoke(messages, config=None):
            asked.append(messages["messages"][0]["content"])
            act(r.tools())
            return {"messages": [SimpleNamespace(type="ai", content=statement, usage_metadata={"input_tokens": 7, "output_tokens": 3})], "files": {}}
        return SimpleNamespace(invoke=invoke)
    monkeypatch.setattr(inventory_agent, "build", build)
    return asked


def kitchen_again(t):
    see(t, "kitchen-1", "wall cabinet", 4, saw="four white wall cabinets"); see(t, "kitchen-1", "refrigerator", 1); see(t, "kitchen-1", "dishwasher", 1, "p2")
    see(t, "kitchen-1", "sofa", 1); t["skip"]("kitchen-1", "a rug", "furniture or a tenant's own")
    assert t["rooms"]().count('"id"') == 1 and t["look"]("bedroom-1", "p1", "ahead")[0]["text"].startswith("No such view")      # the second look has only the one room
    t["flag_doubt"]("kitchen-1", "i1", "The fourth cabinet is half hidden by the refrigerator.")


def test_a_second_look_replaces_one_rooms_items_and_doubts_and_says_what_changed(first, monkeypatch, tmp_path):
    asked = second_look(monkeypatch, kitchen_again)
    entry = inventory_agent.recheck(7, "u1", "kitchen-1")
    assert "second, more careful look" in asked[0] and "The room is Kitchen, id kitchen-1." in asked[0]
    assert '- "There may be a fourth wall cabinet beside the window." (about the wall cabinet)' in asked[0] and "far corner" not in asked[0]      # the lead is told this room's doubts and no other's
    assert entry["before"] == [{"kind": "wall cabinet", "quantity": 3}, {"kind": "range hood", "quantity": 1}, {"kind": "refrigerator", "quantity": 1}]
    assert entry["after"] == [{"kind": "wall cabinet", "quantity": 4}, {"kind": "refrigerator", "quantity": 1}, {"kind": "dishwasher", "quantity": 1}]
    assert entry["changed"] == ["Wall cabinet: 3 became 4", "Range hood: removed", "Dishwasher: added"]
    assert (entry["room"], entry["room_name"], entry["stop"], entry["statement"], entry["views_looked_at"]) == ("kitchen-1", "Kitchen", "finished", "Read again. Four wall cabinets.", 2)
    assert entry["at"].endswith("+00:00") and entry["seconds"] >= 0 and entry["usage"] == {"input_tokens": 7, "output_tokens": 3}

    now = json.loads((tmp_path / "inv" / "u1.json").read_text())
    assert [i for i in now["items"] if i["room"] == "bedroom-1"] == [i for i in first["items"] if i["room"] == "bedroom-1"]                     # the other room is as it was
    kitchen = [i for i in now["items"] if i["room"] == "kitchen-1"]
    assert [(i["id"], i["kind"], i["quantity"]) for i in kitchen] == [("r1-i1", "wall cabinet", 4), ("r1-i2", "refrigerator", 1), ("r1-i3", "dishwasher", 1)]
    assert kitchen[0]["seen"] == "four white wall cabinets" and kitchen[2]["at"]["sweep_id"] == "s2" and len({i["id"] for i in now["items"]}) == len(now["items"])
    assert [(d["id"], d["room"], d["item_id"], d["doubt"]) for d in now["doubts"]] == [("d2", "bedroom-1", None, "The far corner is dark."),
                                                                                         ("r1-d1", "kitchen-1", "r1-i1", "The fourth cabinet is half hidden by the refrigerator.")]
    assert entry["doubts"] == now["doubts"][1:]
    assert now["merged_away"] == [] and now["merges"] == []                                                                                      # the refrigerator seen twice went with the room's old records
    assert [(s["room"], s["saw"]) for s in now["skipped"]] == [("bedroom-1", "bed"), ("kitchen-1", "a rug")] and [(r["room"], r["wanted"]) for r in now["refused"]] == [("bedroom-1", "sofa"), ("kitchen-1", "sofa")]
    assert now["decisions"] == {"refused": 2, "skipped": 2, "merged": 0, "doubts": 2}
    assert now["numbers"] == {**first["numbers"], "items_named": 7, "lines": 4} and now["rechecks"] == [entry]
    assert now["statement"] == "Two rooms read." and now["made_at"] == first["made_at"] and now["events"] == first["events"]

    second_look(monkeypatch, lambda t: see(t, "kitchen-1", "wall cabinet", 4), "Read a third time.")                                             # and again: ids from each look stay apart
    again = inventory_agent.recheck(7, "u1", "kitchen-1")
    assert again["changed"] == ["Refrigerator: removed", "Dishwasher: removed"] and again["doubts"] == []
    now = inventory_agent.saved("u1")
    assert [i["id"] for i in now["items"]] == ["i5", "r2-i1"] and [d["id"] for d in now["doubts"]] == ["d2"] and len(now["rechecks"]) == 2 and now["numbers"]["items_named"] == 5


def test_a_second_look_that_finds_the_same_says_nothing_changed_and_need_not_be_saved(first, monkeypatch, tmp_path):
    before = (tmp_path / "inv" / "u1.json").read_text()

    def same(t):
        see(t, "kitchen-1", "wall cabinet", 2); see(t, "kitchen-1", "wall cabinet", 1, "p2"); see(t, "kitchen-1", "range hood", 1); see(t, "kitchen-1", "refrigerator", 1)
    second_look(monkeypatch, same)
    entry = inventory_agent.recheck(7, "u1", "kitchen-1", save=False)
    assert entry["changed"] == [] and entry["after"] == entry["before"] and entry["stop"] == "finished"                                         # two lines of one kind are counted together
    assert (tmp_path / "inv" / "u1.json").read_text() == before


def test_a_second_look_that_fails_or_sees_no_picture_leaves_the_saved_run_as_it_was(first, monkeypatch, tmp_path):
    before = (tmp_path / "inv" / "u1.json").read_text()

    def fails(t):
        see(t, "kitchen-1", "dishwasher", 1)
        raise RuntimeError("the model did not answer")
    second_look(monkeypatch, fails)
    entry = inventory_agent.recheck(7, "u1", "kitchen-1")
    assert entry["stop"] == "error" and entry["statement"] == "The second look stopped: the model did not answer" and entry["changed"] == [] and entry["after"] == entry["before"]
    assert (tmp_path / "inv" / "u1.json").read_text() == before

    second_look(monkeypatch, lambda t: None, "Nothing to add.")                                                                                 # it finished, but looked at nothing
    entry = inventory_agent.recheck(7, "u1", "kitchen-1")
    assert entry["stop"] == "error" and "saw no picture" in entry["statement"] and (tmp_path / "inv" / "u1.json").read_text() == before


def test_a_second_look_needs_a_saved_run_and_one_of_its_rooms(first, monkeypatch, tmp_path):
    second_look(monkeypatch, kitchen_again)
    with pytest.raises(ValueError, match="no such room"):
        inventory_agent.recheck(7, "u1", "garage-9")
    (tmp_path / "inv" / "u2.json").write_text((tmp_path / "inv" / "u1.json").read_text())                                                       # a saved run for a scan this building does not have
    with pytest.raises(ValueError, match="no such scan"):
        inventory_agent.recheck(7, "u2", "kitchen-1")
    assert inventory_agent.saved("u1") == first and "rechecks" not in inventory_agent.saved("u2")                                               # nothing was asked of the agent, nothing was changed
    (tmp_path / "inv" / "u1.json").unlink()
    with pytest.raises(ValueError, match="has not been read yet"):
        inventory_agent.recheck(7, "u1", "kitchen-1")


def test_a_run_saved_before_decisions_were_kept_can_still_be_looked_at_again(first, monkeypatch, tmp_path):
    old = {k: v for k, v in first.items() if k not in ("refused", "skipped", "doubts", "decisions")}
    (tmp_path / "inv" / "u1.json").write_text(json.dumps(old))
    asked = second_look(monkeypatch, kitchen_again)
    entry = inventory_agent.recheck(7, "u1", "kitchen-1")
    assert "no doubt was flagged for this room" in asked[0] and entry["changed"] == ["Wall cabinet: 3 became 4", "Range hood: removed", "Dishwasher: added"]
    now = inventory_agent.saved("u1")
    assert now["decisions"] == {"refused": 1, "skipped": 1, "merged": 0, "doubts": 1} and [d["id"] for d in now["doubts"]] == ["r1-d1"] and len(now["rechecks"]) == 1
