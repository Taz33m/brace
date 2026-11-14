"""The site model: one object per address, every fact with its sources, assembled only from what stages saved."""
import json

import pytest

from backend import site_model as sm


@pytest.fixture
def site(tmp_path, monkeypatch):
    """A two-roof site with one scan, a height model and a search index, written the way the stages write them."""
    cache = tmp_path / "cache"
    monkeypatch.setattr(sm, "CACHE_DIR", cache)
    monkeypatch.setattr(sm, "OPEN", cache / "open")
    monkeypatch.setattr(sm, "MP_CACHE", cache / "matterport")
    monkeypatch.setattr(sm, "building_dir", lambda pid: cache / "buildings" / str(pid))

    def write(path, data):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data))

    write(cache / "buildings" / "7" / "building.json", {
        "record": {"id": 7, "name": "Test Court", "address": "1 Test St", "city": "Houston", "state": "TX", "type_label": "Apartments", "units": 40},
        "site": {"roof_analysis_date": "2023-12-03"}, "aerial": {"captured": "Thu Feb 12 16:44:18 UTC 2026"},
        "structures": [
            {"id": "S1", "footprint_sqft": 9000, "roof_material": "shingle", "roof_objects": {"ac-unit": 4, "roof-vent": 2}},
            {"id": "S2", "footprint_sqft": 400, "roof_material": "metal", "roof_objects": {}}],
        "scans": [{"id": "scanA", "name": "1BR - A1", "kind": "unit", "structure": "S1", "sweeps": [{"id": "p1"}, {"id": "p2"}],
                   "rooms": [{"id": "r1", "type": "Bedroom", "area_sqft": 120}, {"id": "r2", "type": "", "area_sqft": 80}]}],
    })
    write(cache / "open" / "reconstruct" / "7" / "heights.json", {
        "cell_m": [0.5, 0.5],
        "source": {"surface": {"collection": "tx-2026", "first_capture": "2026-01-02", "last_capture": "2026-02-12", "native_gsd_m": 0.07},
                   "terrain": {"collection": "tx-2025", "first_capture": "2025-01-31", "last_capture": "2025-03-05"}},
        "structures": [{"id": "S1", "roof_height_m": 7.4,
                        "tallest_nearby": {"height_m": 15.5, "distance_to_wall_m": 3.3, "above_roof_m": 8.1, "lon": -95.0, "lat": 29.0}}]})
    write(cache / "open" / "geolocation" / "7.json", {"scans": [{
        "id": "scanA", "status": "aligned", "structure": "S1", "position_pinned": False,
        "correction": {"shift_m": 5.3, "rotation_deg": 4.5}, "raw": {"inside": 0.7}, "fitted": {"inside": 1.0, "position": [-95.0, 29.0]}}]})
    write(cache / "open" / "search" / "7.json", {"total_positions": 2, "indexed_positions": 2, "scans": ["scanA"], "positions": [
        {"scan_id": "scanA", "scan_name": "1BR - A1", "sweep_id": "p1", "room_id": "r1", "room_label": "Bedroom", "room_type": "bedroom", "heading": 0.0,
         "things": [{"name": "window", "quarter": 2, "where": "in this room"}]},
        {"scan_id": "scanA", "scan_name": "1BR - A1", "sweep_id": "p2", "room_id": "r2", "room_label": "", "room_type": "kitchen", "heading": 90.0,
         "things": [{"name": "refrigerator", "quarter": 1, "where": "in this room"}]}]})
    return 7


def test_every_fact_names_sources_that_exist(site):
    model = sm.build(site)

    def facts(node):
        if isinstance(node, dict):
            if "src" in node and "value" in node:
                yield node
            for v in node.values():
                yield from facts(v)
        elif isinstance(node, list):
            for v in node:
                yield from facts(v)

    found = list(facts(model))
    assert len(found) > 8
    for f in found:
        assert f["src"], f
        assert all(s in model["sources"] for s in f["src"]), f


def test_stages_come_in_pipeline_order_and_report_only_what_ran(site):
    stages = {s["key"]: s for s in sm.build(site)["stages"]}
    assert list(stages) == ["join", "classify", "inventory", "expose", "surface", "search"]
    assert stages["join"]["state"] == "ready" and stages["join"]["number"] == 1
    assert stages["surface"]["number"] == 1
    assert stages["search"]["number"] == 2
    assert stages["expose"]["state"] == "not_run"          # nothing saved for it, so nothing claimed
    assert stages["inventory"]["state"] == "partial"       # roofs counted by Vexcel; the grounds were never inventoried


def test_a_room_matterport_left_blank_takes_the_type_seen_from_inside_it(site):
    rooms = {r["id"]: r for r in sm.build(site)["scans"][0]["rooms"]}
    assert rooms["r1"]["type"]["value"] == "Bedroom" and rooms["r1"]["type"]["how"] == "Matterport's own room label"
    assert rooms["r2"]["type"]["value"] == "kitchen" and rooms["r2"]["type"]["how"] == "seen from a scan position"


def test_a_height_traces_to_the_two_flights_it_was_measured_from(site):
    model = sm.build(site)
    tall = model["structures"][0]["tallest_beside_it"]
    assert tall["value"]["height_m"] == 15.5 and "not proven to be a tree" in tall["limits"]
    sources = sm.expand(model, tall["src"])
    assert [s["collection"] for s in sources] == ["tx-2026", "tx-2025"]
    assert sources[0]["captured"] == "2026-01-02 to 2026-02-12"
    assert "limits" not in model["structures"][1].get("tallest_beside_it", {})   # S2 was not measured: no fact at all
    assert "roof_height_m" not in model["structures"][1]


def test_measurements_attach_to_the_action_that_names_the_roof_and_the_subject(site):
    model = sm.build(site)
    tree = sm.measured_for(model, {"structure": "S1", "title": "Cut back the limbs over S1", "why": ""})
    assert [f["label"] for f in tree] == ["Roof S1", "Beside roof S1"]
    assert "15.5 m tall" in tree[1]["text"] and "3.3 m from the wall" in tree[1]["text"]
    assert tree[1]["sources"][0]["provider"] == "Vexcel"
    units = sm.measured_for(model, {"structure": "S1", "title": "Strap the rooftop condensers on S1", "why": ""})
    assert any(f["label"] == "Rooftop units" and f["text"].startswith("4 ") for f in units)
    assert not any(f["label"].startswith("Beside") for f in units)                 # a condenser job is not about the tree
    assert sm.measured_for(model, {"structure": None, "title": "Send the notice", "why": ""}) == []


def test_a_report_is_filed_against_the_room_and_thing_it_names_and_kept_as_reported(site):
    report = sm.add_report(site, "The bedroom window is cracked and letting water in", "scanA")
    assert report["where"]["room"] == "Bedroom" and report["where"]["thing"] == "window" and report["where"]["position_id"] == "p1"
    assert report["status"] == "reported, not yet reviewed"
    assert sm.build(site)["reports"][0]["id"] == report["id"]                        # the after side lands in the same model
    assert sm.locate(site, "my bicycle was stolen", "scanA") is None                 # names nothing the scan saw
    with pytest.raises(ValueError):
        sm.add_report(site, "   ")
    sm.clear_reports(site)
    assert sm.build(site)["reports"] == []


def test_a_site_nobody_gathered_is_an_error_not_an_empty_model(site):
    with pytest.raises(KeyError):
        sm.build(999)


def test_the_board_adds_up_across_sites(site):
    board = sm.board([site])
    stages = {s["key"]: s for s in board["stages"]}
    assert board["sites"] == 1
    assert stages["join"]["number"] == 1 and stages["join"]["of"] == 1 and stages["join"]["median_move_m"] == 5.3
    assert stages["search"]["of"] == 2


def test_a_look_at_the_photo_names_the_tall_thing_and_says_how_it_was_identified(site, tmp_path):
    (tmp_path / "cache" / "open" / "reconstruct" / "7" / "checked.json").write_text(json.dumps(
        {"basis": "looked at once on the aerial photo", "structures": {"S1": {"what": "a tree", "note": "bare crown over the roof"}}}))
    model = sm.build(site)
    tall = model["structures"][0]["tallest_beside_it"]
    assert tall["value"]["what"] == "a tree"
    assert "looked at once on the aerial photo" in tall["limits"] and "not proven" not in tall["limits"]
    assert "vexcel:aerial" in tall["src"]                                           # the photo it was identified on is a source
    said = sm.measured_for(model, {"structure": "S1", "title": "Cut back the limbs over S1", "why": ""})[1]["text"]
    assert said.startswith("a tree 15.5 m tall")


def test_an_action_is_credited_only_with_measurements_its_own_words_quote(site):
    model = sm.build(site)
    quoting = {"id": "A1", "title": "Remove the tree standing 3.3 m from the S1 wall", "why": "It is 15.5 metres tall, well above the 7.4 m roof.", "crew": "tree crew"}
    assert [c["metres"] for c in sm.cited(model, quoting)] == ["3.3", "15.5", "7.4"]
    assert sm.cited(model, {"title": "Strap units within 2 m of the edge", "why": "About 40 m of gutter"}) == []   # numbers not in the model


def test_comparing_a_measured_plan_reports_new_jobs_and_quotes_without_claiming_cause(site):
    model = sm.build(site)
    old = {"actions": [{"id": "A1", "title": "Cut back limbs over the S1 roof", "crew": "tree crew"},
                       {"id": "A2", "title": "Clear the drain grates", "crew": "on-site staff"}], "totals": {}}
    new = {"actions": [{"id": "A1", "title": "Cut back the limbs over the S1 roof", "why": "A tree 15.5 m tall stands 3.3 m from the wall.", "crew": "tree crew"},
                       {"id": "A2", "title": "Move cars from under the leaning pine", "crew": "on-site staff", "why": ""}], "totals": {}}
    got = sm.what_measuring_changed(model, old, new)
    by = {r["after"]["title"] if r["after"] else r["before"]["title"]: r for r in got["rows"]}
    assert by["Cut back the limbs over the S1 roof"]["change"] == "in both" and len(by["Cut back the limbs over the S1 roof"]["quotes"]) == 2
    assert by["Move cars from under the leaning pine"]["change"] == "only in the measured plan"
    assert by["Clear the drain grates"]["change"] == "only in the earlier plan"
    assert got["actions_quoting_a_measurement"] == 1 and "differ for many reasons" in got["note"]
