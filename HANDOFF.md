# Brace — engineering handoff

For the lead engineer, working in Claude Code with the superpowers plugin.
Written 2026-11-14 (Saturday, early morning). Read this, then `PRD.md` and `README.md`.

**Deadline: submissions close Sunday 15 November, 8:00 AM.** Live demos run Sunday 9:30 AM to 2:30 PM, two minutes each. These dates, the prize list and the repo rule below come from a teammate's read of the HackPrinceton Discord; confirm them there before relying on them.

---

## 1. Where things stand

The team's pitch describes an idea. The prototype already exists and works end to end. Your job is to close the gaps between the two and make it submittable, not to start over.

**Built and verified (66 tests pass, both scenarios run on real data):**

| Piece | What it does | Where |
|---|---|---|
| Forecast replays | Hurricane Beryl 2024 (8 forecast steps, real NHC advisories) and the January 2025 Los Angeles Red Flag Warning (4 steps, real NWS products). Live NWS/NHC mode exists | `backend/hazards/` |
| Portfolio screening | For a forecast step, finds every CoStar building it touches and orders them, with reasons. No score is shown | `backend/screen.py` |
| Building bundle | CoStar record + Vexcel site photo, structures and roof facts + the Matterport scans attached to the property | `backend/building.py` |
| Planner agent | Claude tool loop: opens leads, looks at aerial and scan imagery, writes actions with timing, crew, hours and cost, then drafts a resident notice and contractor work orders | `backend/agent.py` |
| Web app | Forecast map with time slider and ranked list; building page with site photo, Matterport tour and plan panel; replay of saved plans | `frontend/src/` |
| Phone headset view | Split-screen 360° view of a scanned space with action badges, synced with the laptop | `frontend/src/components/VrPage.tsx` |

**Real results to quote:** at 36 hours before Beryl's landfall, 1,758 Houston buildings are in the forecast wind field. For The Parker at Ellington (265 homes) the agent produced 5 before-arrival actions costing $2,700 to $9,700, a resident notice and two work orders in 137 seconds. For Verdugo Mesa Apartments in Los Angeles, 12 actions and 4 messages in 172 seconds. A plan costs roughly a dollar in API usage (estimate, not measured precisely).

**Not verified:**
- Live mode against a real event. No storm or Red Flag Warning is active, so that path runs only against stand-in feeds in tests.
- The headset view on an actual phone (motion permission, certificate warning, venue Wi-Fi).
- The Los Angeles plan was built before a hindsight fix (see task 2) and must be rebuilt.

## 2. Run it

```bash
cd ~/brace
uv sync && (cd frontend && npm install)
uv run uvicorn backend.server:app --port 8001          # API; also warms flood-zone lookups in the background
(cd frontend && npm run dev)                           # http://localhost:5174  (must be localhost: Matterport key)
(cd frontend && npx vite --config vite.vr.config.ts)   # https://<lan-ip>:5175 for the phone headset
uv run pytest                                          # 66 tests, no network or keys needed
(cd frontend && npx tsc --noEmit)                      # type check
uv run python -m scripts.plan --list                   # scenario and step ids
uv run python -m scripts.plan --scenario beryl-2024 --step adv33 --top 4   # build plans from the CLI
```

Keys are in `.env` (git-ignored). The CoStar kit is at `data/kit` (a symlink to `~/plumbline/data/kit`, also ignored). The repo is **local only** right now; see task 1.

## 3. What the team said, and what the product actually does

The pitch transcript and the product differ in ways a judge will notice. Keep the product's version.

| The pitch says | The product does | Why it matters |
|---|---|---|
| "Predict areas at high risk" | Takes a real forecast or warning and finds the buildings it touches | We do not forecast weather. Say "flag from the forecast" |
| "Where the building should be reinforced" | Actions sized to the hours left (secure, trim, move, clear); real repairs are filed for after the event or for the budget | Nobody reinforces a building in 36 hours. The time rule is enforced in code |
| "Message tenants using the CoStar data" | Drafts the notice; nothing is sent | The kit's emails and phone numbers are deliberately fake, and apartment residents are not listed |
| "Walks the building in Matterport" | Scans cover single spaces: a suite, an apartment unit, a leasing office, a gym | No plant rooms or whole towers were scanned. The agent says when a risk depends on an unscanned space |
| "A value thing for CoStar: how weather drops property value" | Not built | See task 5. Must be framed as value exposed, not predicted loss |

## 4. Rules that must survive any change

1. **Never commit `data/`, `.env`, API keys, kit records, or Vexcel/Matterport imagery.** Check `git status` before every commit.
2. **Evidence rules live in code, not the prompt** (`backend/agent.py`, `t_add_action` and `t_finish`): a before-arrival action must fit in the hours left minus a six-hour crew stand-down; an action marked "seen" must point at a structure, grid cell or scan position; every lead must be resolved; no finish without a notice. Do not loosen these to make a demo look fuller.
3. **No hindsight in replays.** `screen.as_of()` strips the 2025 fires from the Los Angeles replay's standing risk. Anything new that reads hazard history must go through it.
4. **Real data only.** If a source cannot be fetched, the field is `None` and the UI says so. No invented polygons, depths, prices or damage percentages.
5. **No risk score in the UI.** The ordering exists; the interface shows reasons and actions.
6. **Wind is sustained wind, estimated from the advisory's wind radii.** Gusts run 20 to 30 percent higher. Being outside the forecast cone is not a safety signal.
7. **The app must run at `http://localhost:5174`.** The Matterport SDK key works nowhere else.

## 5. Tasks, in order

**Status, Saturday 2:00 AM:**

| Task | State |
|---|---|
| 1 Public repository | Pushed to `github.com/ryanwatach/HackPrinceton` (team repo). It is **private**; it must be made public before submission if the rule holds |
| 2 Rebuild the Los Angeles plan | Done: rebuilt after the hindsight fix (7 actions, 3 messages) |
| 3 Demo set | Ten plans saved across both scenarios, including the same two buildings at 36 and 12 hours. `DEMO.md` has the script. The plans have not each been read line by line |
| 4 Headset on a real phone | Needs a person with the phone |
| 5 Value exposed | Done and tested. 1,770 of 3,339 buildings have a priced sale, $42.6 billion in total |
| 6 Photon | Not started; needs Photon's guidelines and an account |
| 7 Observed rainfall | Done and tested. Anonymous read works in under a second; downtown Houston's cell got 4.1 in over 7 to 8 July 2024. Shown only at the landfall step |
| 8 Los Angeles validation | Done: see the result under the task |

Do tasks 1 to 4 before anything else; they are what makes the entry valid and demo-safe. Tasks 5 to 8 strengthen the pitch and are each independent, so they can run in parallel.

### Task 1 — Public repository (blocker for submission)
The rules reportedly require a public GitHub repo created this weekend. Brace is committed locally only.
- Confirm with Tazeem before publishing, then create the public repo and push.
- Before pushing: `git grep -n -e "vfa_" -e "sk-ant" -e "MATTERPORT_API_TOKEN=."` over the whole history must find nothing; `data/` and `.env` must be untracked.
- State in the README that the CoStar kit and API keys are provided by the sponsor and are not in the repo.
- **Done when:** a fresh clone, with `.env` and the kit added, passes `uv run pytest` and `npx tsc --noEmit`.

### Task 2 — Rebuild the Los Angeles plan
`data/cache/buildings/9519837/plans/la-red-flag-jan-2025__20250105T2240Z.json` was built before `as_of()` existed, so its reasoning may cite distance to the 2025 fires.
- Run `uv run python -m scripts.plan --scenario la-red-flag-jan-2025 --step 20250105T2240Z 9519837 --redo`.
- **Done when:** the saved plan's text does not mention the Palisades or Eaton fires.

### Task 3 — Demo set
- Build plans for the top buildings that have scans: four for `beryl-2024` at `adv33` (36 hours) and two at `adv37` (12 hours), three for the Los Angeles replay. The 36-hour and 12-hour plans for the same building should differ; that contrast is the demo's best beat.
- Read every plan. Drop any with a weak or wrong action from the demo list rather than editing it.
- Write the chosen building ids and the click path into `DEMO.md` (two-minute version: map and slider, one building, replay, plan, messages).
- **Done when:** `DEMO.md` exists and the full path has been clicked through once without touching the terminal.

### Task 4 — Headset on a real phone
- Open a building, click **Open in headset**, scan the QR code with the phone that goes in the headset.
- Check: certificate warning can be passed, motion permission prompt appears on iPhone, head tracking is the right way round, gaze on a floor spot moves you, gaze on a badge opens the card, selecting an action on the laptop moves the headset.
- If the venue Wi-Fi isolates devices, put the laptop on the phone's hotspot and rescan.
- **Done when:** it works on the actual device, or it is cut from the demo. Do not leave it half-working.

### Task 5 — Value exposed (the CoStar value proposition)
The team's closing point was that this is a safety tool for people and a value tool for CoStar. Nothing shows value yet.
- Join `data/kit/data/commercial-sale-comp.jsonl` to buildings: `entities[].propertyId`, `soldForPrice`, `soldDate`, and `salePriceStatus` (carry the status every time; a comp with several entities is a portfolio sale whose price may be allocated, so exclude or flag those).
- Add to the map page tally: number of touched buildings with a recorded sale and the sum of their last sale prices, labelled "last recorded sale price of buildings in the wind field". Add to the building page: last sale price and date beside the plan's before-arrival cost.
- **Do not** compute a predicted loss or a damage percentage. There is no damage model, and inventing one breaks rule 4.
- **Done when:** the numbers appear with their caveat, and a test covers the join including a portfolio comp.

### Task 6 — Send the notice through Photon
The agent already drafts the notice; Photon is only the channel. This is what qualifies for Photon's messaging-agent prize.
- Read Photon's guidelines first (linked from the Discord). A teammate's notes say Photon lines may not be able to text people first; a past winner had users text "JOIN".
- Build it inbound-first: a person texts the demo number with a building name or address, and gets that building's notice for the current forecast step back. Recipients are opted-in demo phones only.
- Add a "Send to opted-in phones" control beside the notice in the Messages tab, disabled when nobody has opted in.
- **Done when:** a judge's phone can text in and receive a real notice. If Photon access is not sorted by Saturday 6 PM, cut it.

### Task 7 — Observed rainfall for Houston (timebox: 90 minutes)
The teammate's research found PARDIG, DeepMind's public rainfall dataset released this week: observed rain every 15 minutes on a roughly 10 km grid, archive back to 1999, no access form. It measures past rain; it does not forecast.
- Spike first: can you read rainfall for one Houston coordinate during Beryl (7 to 8 July 2024) from the public bucket or Earth Engine? If not within 45 minutes, stop and drop the task.
- If yes: add `rain_mm_24h` to the hurricane exposure for the landfall step only, shown as "rain that actually fell here", and pass it to the agent's threat. Rates are capped at 75 mm/h, so heavy bursts are understated; say so in the label's tooltip.
- Do not turn rainfall into flood depth inside a building. Rain on a lot is not water in a lobby.

### Task 8 — Validation slide for Los Angeles (timebox: 60 minutes)
- Using the fire perimeters already downloaded (`data/hazards/calfire/january_2025_fires.json`), count kit buildings inside or within 1 km of the Palisades and Eaton perimeters, and report where they sat in the ranking at the first replay step (43 hours before the warning).
- This is hindsight used for checking only. It must not feed the ranking or the agent.
- **Done when:** one honest sentence with numbers exists for the pitch, whatever the result is.
- **Result:** none of the 1,581 Los Angeles buildings in the kit sat inside or within 1 km of any January 2025 fire. The nine closest are 2.7 to 3.0 km from the Palisades perimeter, in Brentwood. All nine were inside the warning area at the first forecast step, 43 hours out, and four ranked in the top 25 of 84. So the honest line is: "None of our buildings burned; the ones nearest the Palisades fire were already on the list 43 hours before the warning began." It is not a validation of anything stronger than that.

### Not doing
- **Flood depth per room** ("which rooms flood at X ft"). FEMA's base flood elevation is empty for most of the Houston flood zones we checked, scan floor heights are noisy, and scans do not cover plant rooms. If flood needs more weight, use stated scenarios for ground-level scanned spaces and label them as scenarios.
- **Rewriting the agent on LangChain deepagents** for that prize. The loop works and is tested.
- **Earthquake, heat, freeze.** Two hazards done properly beat five done thinly.
- **New scenarios.** Beryl and the Red Flag Warning are enough.

## 6. Track notes (for the team, not code)

- Each team enters one main track plus any number of sponsor tracks. The product's user is a property manager, which fits Business and Enterprise; resident safety fits Sustainability. Pick with the judging criteria in mind: Creativity, Utility, Charity, Avidity.
- Sponsor tracks this build can enter with little or no extra work: CoStar (all three data layers are used), Amazon Best Practical AI, Photon (after task 6), ChatOverflow (decision pending with Tazeem; it publishes notes from coding sessions).
- "Church" in the meeting transcript is unclear; it may be a mis-hearing of LangChain or ChatOverflow.
- The CoStar workshop's message was that the interface should not be a chat window: voice, the phone as controller, the big screen as the view. Brace has no chat box, the agent drives the viewers, and the headset is synced to the laptop. Say that in the pitch.

## 7. Working with superpowers

- These tasks are already specified, so skip brainstorming except for task 6, where Photon's rules decide the design.
- For each task: use **writing-plans** to turn it into steps, then **executing-plans** or **subagent-driven-development**. Tasks 5 to 8 touch different files and suit **dispatching-parallel-agents**; give each agent its own files.
- Backend changes: **test-driven-development**. The agent loop is tested with a scripted stand-in for the model (`tests/test_agent.py`); follow that pattern rather than calling the API in tests.
- Before calling a task done: **verification-before-completion**, which here means `uv run pytest`, `npx tsc --noEmit`, and looking at the change in the running app.
- A plan run spends real money (about a dollar each). Batch them and do not loop them in tests.
- Commit after each task with a message that says what changed and why.

## 8. Useful facts

- Scenario ids: `beryl-2024` (steps `adv27` 72 h, `adv29` 60 h, `adv31` 48 h, `adv33` 36 h, `adv35` 24 h, `adv37` 12 h, `adv38` 6 h, `adv39` landfall) and `la-red-flag-jan-2025` (steps `20250105T2240Z`, `20250106T1955Z`, `20250106T2324Z`, `20250107T2237Z`).
- At 72 and 60 hours the real Beryl forecast pointed at South Texas, so Houston is untouched until the 48-hour step. That is correct, and it makes the slider worth showing.
- The portfolio: 3,339 buildings, 2,765 of them apartment communities; 1,731 name a property manager, 262 an owner; 1,937 have current tenants on record.
- Vexcel's roof analysis can be a year or two older than its photo. The agent is told both dates and has already caught one stale "tarp on the roof" flag.
- Plans are saved per building and forecast step at `data/cache/buildings/<id>/plans/<scenario>__<step>.json`.
- Plumbline, the earlier home-inspection project, lives at `~/plumbline`. Its scan-to-aerial alignment answers one of Matterport's stated open problems (median 2.0 m correction on 45 homes) and is worth one slide.
