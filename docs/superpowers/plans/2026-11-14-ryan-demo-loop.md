# Ryan's Demo Loop Tasks Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the fire schedule a three-fact exposure rank per building, a portfolio list for beat 6, and a model cost the runs recorded themselves.

**Architecture:** A new `backend/exposure.py` reads the saved building file and the saved CAL FIRE map and returns ranked buildings; `backend/schedule.py` takes its order from it. A new `backend/run_cost.py` turns saved token counts into dollars. `schedule.portfolio()` lists communities from the kit. Nothing calls a model or the network at request time.

**Tech Stack:** Python 3.11, FastAPI, shapely, pytest, `uv`.

**Spec:** `docs/superpowers/specs/2026-11-14-ryan-demo-loop-design.md`

## Global Constraints

- Money or a fact that is not known is `None`, never zero, and is left out of totals.
- No forecast, probability or percent burned anywhere in code, field names or copy.
- No model call and no network call at request time; exposure reads only files already on disk.
- Every fact carries its source as a string.
- Commits carry no Claude co-author trailer and no "Generated with" line.
- Tests use stand-in data under `tmp_path`; never a paid model run.

## Review Focus

- A property with no saved building file: `exposure.exposure()` raises `ExposureError`, and the API answers 404.
- The fire-zone map is not on disk: every `fire_zone` is `None`, `in_fire_zone` is `None` (not `False`), and the rank still orders by vegetation.
- A building with no Vexcel vegetation figure sorts after every building that has one within its zone.
- A saved run whose model has no known price: cost is `None`, not zero, and the schedule still loads.
- A community with no Apartments.com listing in the portfolio list: homes and rent are `None` and it sorts last.

---

### Task 1: Exposure rank

**Files:**
- Create: `backend/exposure.py`
- Test: `tests/test_exposure.py`

**Interfaces:**
- Produces: `exposure.exposure(property_id: int) -> dict` with
  `{"property_id", "buildings": [row...], "how": str, "sources": {"vegetation": str, "fire_zone": str}}`.
  Each row: `{"id", "exposure_rank": int, "brush_within_5ft_percent": float|None, "tree_cover_over_roof_percent": float|None, "fire_zone": "Very High"|"High"|"Moderate"|None, "in_fire_zone": bool|None, "polygon", "footprint_sqft"}`.
  `exposure.zone_at(lat: float, lon: float) -> tuple[str | None, bool]` returns the zone and whether the map was available.
  `exposure.ExposureError(Exception)`. Module constant `exposure.BUILDINGS` (a `Path`, default `config.BUILDINGS_DIR`).

- [ ] **Step 1: Write the failing tests** in `tests/test_exposure.py`. Fixture writes `tmp_path/"7"/"building.json"` with four structures (`trees_within_5ft_percent`, `roof_tree_cover_percent`, `centroid`, `polygon`, `footprint_sqft`) and monkeypatches `exposure.BUILDINGS` and `exposure.zone_at`.

```python
def test_rank_is_zone_then_vegetation_at_the_wall_then_tree_cover_over_the_roof(site):
    # A: no zone, 90% at wall; B: High, 5%; C: High, 5%, roof 40; D: Very High, none measured
    assert [b["id"] for b in exposure.exposure(7)["buildings"]] == ["D", "C", "B", "A"]
    assert [b["exposure_rank"] for b in exposure.exposure(7)["buildings"]] == [1, 2, 3, 4]

def test_a_missing_fact_is_null_and_sorts_last_within_its_zone(site): ...
    # two buildings in the same zone, one with brush None: the measured one ranks first; None stays None

def test_no_fire_map_on_disk_leaves_the_zone_unknown_not_false(site, monkeypatch):
    monkeypatch.setattr(exposure, "zone_at", lambda lat, lon: (None, False))
    assert all(b["in_fire_zone"] is None and b["fire_zone"] is None for b in exposure.exposure(7)["buildings"])

def test_outside_every_mapped_zone_is_false(site, monkeypatch):
    monkeypatch.setattr(exposure, "zone_at", lambda lat, lon: (None, True))
    assert all(b["in_fire_zone"] is False for b in exposure.exposure(7)["buildings"])

def test_a_property_that_was_never_gathered_raises(site):
    with pytest.raises(exposure.ExposureError): exposure.exposure(999)
```

- [ ] **Step 2: Run** `uv run pytest tests/test_exposure.py -q`. Expected: fails on import.
- [ ] **Step 3: Implement.** `zone_at` uses `hazards.static._load_la(allow_download=False)` and `la_fire_lookup`; if the load returns `None` or raises, return `(None, False)`. Sort key: `(-zone_rank, -(brush if brush is not None else -1), -(roof if roof is not None else -1), original_index)` with zone ranks Very High 3, High 2, Moderate 1, none 0. `centroid` is `[lon, lat]`.
- [ ] **Step 4: Run** the same command. Expected: 5 passed.
- [ ] **Step 5: Commit** `Exposure: rank each building by fire zone, vegetation at the wall and trees over the roof`.

### Task 2: The schedule and the API use the exposure rank

**Files:**
- Modify: `backend/schedule.py` (the building loop in `schedule()`, and the last line of `assumptions`)
- Modify: `backend/server.py` (add `GET /api/exposure/{property_id}` beside the schedule routes)
- Modify: `frontend/src/story/ScheduleTree.tsx` (the `Building` interface and the row at the `% of walls` span)
- Test: `tests/test_inventory_schedule.py`

**Interfaces:**
- Consumes: `exposure.exposure(property_id)` from Task 1.
- Produces: each schedule building gains `fire_zone` and `tree_cover_over_roof_percent`; `exposure_rank`, `brush_within_5ft_percent`, `in_fire_zone` now come from exposure. Top level gains `"exposure": {"how", "sources"}`.

- [ ] **Step 1: Write the failing test** `test_the_schedule_takes_its_building_order_and_fire_zone_from_exposure`: monkeypatch `schedule.exposure.exposure` to return two rows in a known order with `fire_zone="High"`; assert the schedule's buildings come back in that order with `in_fire_zone is True`, `fire_zone == "High"`, and that `sum(b["homes_assumed"])` still equals `property.homes`.
- [ ] **Step 2: Run** `uv run pytest tests/test_inventory_schedule.py -q`. Expected: the new test fails.
- [ ] **Step 3: Implement.** Replace the `rows = sorted(...)` line with exposure's rows restricted to ids present in `s["buildings"]`; keep the roof-area share. If `ExposureError`, fall back to today's order with the new fields `None`. Replace the last assumption with exposure's `how`.
- [ ] **Step 4: Add the route** returning `exposure.exposure(property_id)`, 404 on `ExposureError`.
- [ ] **Step 5: Frontend.** Add `fire_zone: string | null; tree_cover_over_roof_percent: number | null` to `Building`; in the building row show the zone and roof cover after the wall figure when present.
- [ ] **Step 6: Run** `uv run pytest -q` and `npx tsc --noEmit` in `frontend/`. Expected: all pass, no type errors.
- [ ] **Step 7: Commit** `Schedule: rank buildings by exposure and say which fire zone each is in`.

### Task 3: The run's own cost

**Files:**
- Create: `backend/run_cost.py`
- Modify: `backend/inventory_agent.py` (`run_inventory`: count every model call, including the readers')
- Modify: `backend/schedule.py` (`numbers.model_cost_usd`, `numbers.cost_how`)
- Test: `tests/test_run_cost.py`

**Interfaces:**
- Produces: `run_cost.usd(model: str | None, usage: dict | None) -> float | None`; `run_cost.PRICES: dict[str, tuple[float, float]]` in dollars per million input and output tokens: `claude-opus-5-5` (4.00, 20.00), `claude-sonnet-5-5` (2.00, 10.00), `claude-haiku-5-5` (0.10, 0.50), `claude-fable-5-2` (8.00, 40.00). `run_cost.total(runs: list[dict]) -> float | None` sums runs that have a cost and returns `None` if none do.

- [ ] **Step 1: Write the failing tests.**

```python
def test_cost_is_tokens_times_the_published_price():
    assert run_cost.usd("claude-opus-5-5", {"input_tokens": 1_000_000, "output_tokens": 100_000}) == 6.0

def test_an_unknown_model_or_missing_usage_is_null_not_zero():
    assert run_cost.usd("some-other-model", {"input_tokens": 5, "output_tokens": 5}) is None
    assert run_cost.usd("claude-opus-5-5", None) is None

def test_total_leaves_out_runs_without_a_cost_and_is_null_when_none_have_one():
    assert run_cost.total([{"model": "claude-opus-5-5", "usage": {"input_tokens": 1_000_000, "output_tokens": 0}}, {"model": "x", "usage": {}}]) == 4.0
    assert run_cost.total([{"model": "x", "usage": {}}]) is None
```

- [ ] **Step 2: Run** `uv run pytest tests/test_run_cost.py -q`. Expected: fails on import.
- [ ] **Step 3: Implement `run_cost.py`.** Round to cents.
- [ ] **Step 4: Count the readers' tokens.** In `run_inventory`, pass a `langchain_core.callbacks.UsageMetadataCallbackHandler` in `config={"callbacks": [...]}` and sum its `usage_metadata` across models into `usage`; if it recorded nothing (a scripted stand-in model), keep the existing sum over `out["messages"]`. Existing tests must still pass.
- [ ] **Step 5: Schedule.** `model_cost_usd = run_cost.total([inventory record, fit-out price run, building-work price run])`; add `cost_how`: `"tokens times the published price per model; web search fees are not counted"`.
- [ ] **Step 6: Run** `uv run pytest -q`. Expected: all pass.
- [ ] **Step 7: Commit** `Schedule: work out what the runs cost from the tokens they recorded`.

### Task 4: The portfolio list

**Files:**
- Modify: `backend/schedule.py` (add `portfolio()`)
- Modify: `backend/server.py` (add `GET /api/schedule`, declared before `/api/schedule/{property_id}`)
- Test: `tests/test_schedule_portfolio.py`

**Interfaces:**
- Consumes: `exposure.zone_at`, `portfolio.buildings()`, `portfolio.floor_plans()`, `schedule.schedule()`.
- Produces: `schedule.portfolio(city: str = "Los Angeles") -> dict` with `{"city", "communities": [row...], "counted": {"scanned": int, "in_zone": int}, "how": str}`. Row: `{"id", "name", "address", "fire_zone", "scans": int, "homes": int|None, "rent_per_month": {"low","high"}|None, "total": {"low","high"}|None, "rank": int}`.

- [ ] **Step 1: Write the failing tests**, monkeypatching `schedule.portfolio_source` helpers (`portfolio.buildings`, `portfolio.floor_plans`, `exposure.zone_at`, `schedule.schedule`):

```python
def test_only_scanned_apartment_communities_in_a_mapped_zone_are_listed(kit): ...
    # four records: apartment+scan+zone, apartment+scan+no zone, apartment+no scan+zone, office+scan+zone -> one row

def test_a_community_with_a_read_scan_ranks_first_then_by_rent_and_missing_rent_is_null(kit): ...
    # three in zone: one with a schedule total, one with rent 50k, one with no listing -> order [total, rent, none]; last has homes None and rent_per_month None

def test_a_community_whose_schedule_cannot_be_built_still_lists_with_a_null_total(kit): ...
```

- [ ] **Step 2: Run** `uv run pytest tests/test_schedule_portfolio.py -q`. Expected: fails.
- [ ] **Step 3: Implement.** Apartment means `type_label`/`type` names apartments (match how `portfolio.TYPE_LABEL` labels them); scanned means `model_ids` non-empty; in zone means `zone_at(lat, lon)[0]` is not `None`. Rent per month is the sum of homes times asking rent over floor plans that have both. Call `schedule.schedule(id)` inside a `try`; `ScheduleError` gives `total = None`.
- [ ] **Step 4: Add the route.**
- [ ] **Step 5: Run** `uv run pytest -q`. Expected: all pass.
- [ ] **Step 6: Commit** `Schedule: list the scanned communities inside a fire zone, ranked`.

### Task 5: Real figures and three clean runs

**Files:**
- Modify: `ARCHITECTURE.md` ("Not built yet" table and the listed endpoints), `README.md` (the same two places)

- [ ] **Step 1: Re-read the lead scan** so its saved run carries the readers' tokens: `uv run python -m scripts.inventory 9519837 CaSLe7ZwnfF`. If it names a kind with no saved price, run it again with `--prices`.
- [ ] **Step 2: Start** `uv run python -m scripts.start` and request `/api/exposure/9519837`, `/api/schedule/9519837` and `/api/schedule` three times each. Expected: HTTP 200 each time, identical bodies across runs, 24 ranked buildings, a non-null `model_cost_usd`. Write down the time of each run.
- [ ] **Step 3: Open** `#/schedule` in the browser and confirm the building rows show the new facts.
- [ ] **Step 4: Update the two documents** to move the finished rows out of "Not built yet".
- [ ] **Step 5: Commit** `Docs: exposure rank, portfolio list and run cost are built`.
