# Brace: PRD

**What a fire would cost an owner to put back, line by line, from the leasing scan they already have.**
HackPrinceton Fall 2026, CoStar track ("Inside and Out: AI for the Built World").

Status: 14 November 2026, 17:45. This replaces the storm and wildfire preparation PRD written at 00:41 the same
day; that version is in the git history. It follows the team's `DIRECTION.md` (17:13 version). The two-minute loop
is in `DEMO_LOOP.md`.

---

## 1. Summary

Brace reads the Matterport scan an apartment community already has for leasing, names what the owner would have to
replace, puts a price range with a source on each line, and multiplies it across the homes like it. Vexcel's
aerials say which of the community's buildings have fuel at the wall. CoStar says how many homes there are and
what they rent for. The output is one schedule: a total at the top, then building, home, room, item.

It is not a forecast and not a risk score. It states a scenario ("fire reaches this building") and says what that
would cost.

## 2. Who it is for

| User | What they do today | What Brace gives them |
| --- | --- | --- |
| **Owner or asset manager of an apartment community** (primary) | Files a statement of values with a broker, often from a cost per square foot | An itemised list of the fit-out they actually own, priced, with the scan as its record |
| The owner's broker | Asks the owner for values at each renewal | The same schedule, to check the cover is enough |
| An insurer's underwriter (secondary) | Benchmarks reported values against a database | The values with what they are made of, per building |

What the owner insures is the fit-out: floors, cabinets, counters, appliances, doors, fixtures. Under the standard
commercial property form these count as part of the building. Tenants' belongings are the tenants' own cover and
are out of scope.

## 3. What is different

Scan-based products for insurance exist, and they work after a loss, one property at a time: Matterport sells
sketches from its scans for the adjusters' estimating software, and others have people photograph items once the
damage is done. Brace differs in three ways:

1. **Before the loss.** At renewal and before a fire, not at first notice of loss.
2. **From scans that already exist.** Nobody is sent to the site. The leasing scan is the input.
3. **Across a portfolio, with every figure sourced.** A quantity from the scan times a price from a page that can be opened.

## 4. The data, as it really is

| Layer | What it gives Brace | Limits |
| --- | --- | --- |
| **Matterport** | Rooms with floor area and ceiling height, walls, doors, and panoramas at every standpoint | Scans cover one space (a home, an office, a gym), not a building. Homes are staged, so furniture is not a tenant's |
| **Vexcel** | Per building: vegetation within 5 ft of the walls, trees over the roof, footprint, heights; the aerial itself | A ranking of exposure, not a chance of fire |
| **CoStar** | Unit counts, building size, asking rents, type and age | Asking rents are listings, not leases. Many properties have no sale on record |
| **Public fire data** | California fire hazard severity zones | Today's map. Most kit buildings in Los Angeles are outside the highest zones; the count is shown as it is |

The index read for this PRD holds 3,339 properties and 13,096 scans; 11,872 of the scans are of apartment
communities. Scans in the kit are proof of concept, not an insured owner's data, and every deck and video says so.

## 5. The product

Each requirement has what counts as done.

| # | Requirement | Done when |
| --- | --- | --- |
| R1 | **Exposure.** Rank a site's buildings by fuel at the wall, trees over the roof, and fire zone | Every building at the lead site has a rank and the three facts behind it, each with its source |
| R2 | **Inventory.** Go through a scan room by room and name what the owner would replace, with a count or a measured quantity and where it is in the scan | Kitchen and bathroom fit-out and every room's floor, walls and doors are listed for the lead home; each item says whether it was read or measured |
| R3 | **Prices.** A price range per item, found on the web, kept only when the page confirms it | Each priced line links to its page; a line without a confirmed price shows no figure |
| R4 | **Schedule.** Item to room to home, with totals at each level | Totals add up; the count of priced lines is shown beside each total |
| R5 | **Rollup.** One scanned home times the homes like it, to building and property | The multiplication is on screen and labelled an extrapolation |
| R6 | **Lost rent.** Homes out of use, times months, times asking rent | A per-month figure with its arithmetic |
| R7 | **The tree screen.** Total at the top; open a building, a home, a room, an item | Any figure can be opened down to its source in three clicks or fewer |
| R8 | **The loop.** The home page plays the seven beats in `DEMO_LOOP.md` by scrolling | Runs three times in a row with no model call while it plays |
| R9 | **The numbers.** Scans read, items named, prices confirmed, minutes, model cost | Recorded by the run itself, not typed in |
| R10 | **Headset** (optional). Stand in the home while the tags appear | Works on the real phone and viewer by Sunday 01:00, or it is cut |

Scenarios, stated on screen:

- **Fire reaches the building.** The fit-out of the affected homes is a total loss, so the schedule is the figure, plus rent for the months they cannot be lived in.
- **Fire stops nearby** (only if time allows). Smoke and ash: soft finishes and cleaning, not the whole schedule.

## 6. The schedule

One schedule per property, served as `GET /api/schedule/{property_id}`. Every screen reads this and nothing else.

```json
{
  "property": { "id": 0, "name": "", "homes": 0, "scenario": "fire reaches the building", "scan_date": "" },
  "total": { "low": 0, "high": 0, "lines": 0, "lines_priced": 0 },
  "lost_rent_per_month": { "low": 0, "high": 0, "how": "homes x asking rent" },
  "numbers": { "scans_read": 0, "items_named": 0, "prices_confirmed": 0, "minutes": 0, "model_cost_usd": 0 },
  "buildings": [
    { "id": "S1", "exposure_rank": 1, "brush_within_5ft_percent": 0, "in_fire_zone": true, "homes_assumed": 0,
      "total": { "low": 0, "high": 0 },
      "units": [
        { "scan_id": "", "name": "", "multiplied_by": 0, "extrapolated": true,
          "rooms": [
            { "name": "Kitchen",
              "items": [
                { "what": "Refrigerator", "quantity": 1, "unit": "each",
                  "from": "read from the scan",
                  "price_low": 0, "price_high": 0, "low": 0, "high": 0,
                  "source_url": "", "at": { "sweep_id": "", "yaw_deg": 0, "pitch_deg": 0 } }
              ] }
          ] }
      ] }
  ]
}
```

- `from` is `read from the scan` (a vision model named it) or `measured from the scan` (Matterport's dimensions).
- `at` is where the item is in the scan, so a tag can be drawn on it.
- Money that is not known is null, never zero, and is left out of the totals.

## 7. The agent

A deep agent on LangChain's `deepagents`, as `backend/desk_agent.py` already is. One orchestrator takes a scan and
gives each room to a sub-agent with its own context. A room's sub-agent looks at that room's panoramas, names the
fit-out it can see, and returns items with where each is. The orchestrator merges the rooms, asks the price
research for a range per kind of item, and writes the schedule.

Rules, enforced in code and not left to the prompt:

- An item needs a standpoint and a direction it was seen in. No sighting, no item.
- A quantity that Matterport measured (floor area, wall length, door count) comes from the measurement, never from the model.
- A price is kept only when a fetch of its page finds the price and the sentence that states it.
- The agent names and counts. It does not total; code does.
- Furniture and anything a tenant would own is not listed.

## 8. Out of scope, and claims we do not make

- No forecast, no probability that a building burns, no percentage of a home that burns.
- No fire-spread rate from what the furniture is made of.
- No valuing of personal belongings, and no claim to verify a homeowner's contents.
- No cost comparison against manual scanning; the "$2,000 against $10" line has no source.
- No claim that the Los Angeles ranking was validated by the January 2025 fires.
- No invented examples. Everything on screen is from the kit.
- The preparation product (plans, crews, resident messages) and the flood test stay in the repo but are not pitched. `#/file` stays reachable as the partial-loss example.

## 9. Who builds what

Weighted by who can build fastest. Hours are estimates from now to Sunday 07:00.

### Tazeem: the engine and the loop (about 60% of the build)

| # | Task | Done when | By |
| --- | --- | --- | --- |
| T1 | Fetch the lead scan's wall measurements and quantities (R2, measured part) | Floor, wall and door quantities exist for every room of scan `CaSLe7ZwnfF` | Sat 19:00 |
| T2 | The inventory agent on `deepagents`, one sub-agent per room (R2, read part; section 7) | Kitchen and bathroom items are named with a standpoint and direction each; a test holds the "no sighting, no item" rule | Sat 21:00 |
| T3 | Prices for those items (R3) | Each kind of item has a confirmed range or shows none | Sat 21:30 |
| T4 | The schedule, the rollup and lost rent, served at `/api/schedule/{id}` (R4, R5, R6) | Returns the shape in section 6 for Verdugo Mesa with real figures; totals tested | Sat 22:00 |
| T5 | The tree screen (R7) | Opens from total to source | Sat 23:30 |
| T6 | The loop on the home page (R8) | All seven beats play by scrolling | Sun 01:00 |
| T7 | Final numbers to Kevin and Jimmy; fixes from the three runs | The narration and the video match the screen | Sun 05:00 |

### Ryan: the outside, the portfolio, and making it hold (about 25%)

| # | Task | Done when | By |
| --- | --- | --- | --- |
| R-1 | Exposure per building (R1): brush within 5 ft, trees over the roof, fire zone. New `backend/exposure.py`, `GET /api/exposure/{id}` | One rank per building at Verdugo Mesa with its three facts and sources; tested | Sat 19:30 |
| R-2 | The portfolio list for beat 6: scanned communities in the zone with homes and rents, ranked | `GET /api/schedule` lists them; missing rents are null | Sat 22:00 |
| R-3 | Saved runs and the `numbers` block (R9) | The schedule is read from disk; the run records its own counts, minutes and cost | Sun 00:00 |
| R-4 | One start command and three clean runs on the presenting laptop | Three in a row, written down with the time of each | Sun 05:00 |

### Jimmy: the headset and the film (about 15%)

| # | Task | Done when | By |
| --- | --- | --- | --- |
| J-1 | The headset beat (R10): point `#/inside` at the lead home and draw tags from the schedule's `at` fields | Works on the real phone in the viewer, or is cut | Sun 01:00 |
| J-2 | Screen recordings of each beat, the two-minute edit, an offline backup | The video plays without a network | Sun 05:00 |
| J-3 | Upload the video and screenshots to Devpost | Submitted | Sun 07:00 |

### Kevin: the script and the argument (no build)

| # | Task | Done when | By |
| --- | --- | --- | --- |
| K-1 | The narration, word for word against the seven beats | Under two minutes read aloud; first draft Saturday 19:00 | Sun 01:00 |
| K-2 | The answers to the judge questions in `DEMO_LOOP.md`, plus who inside an owner's company signs for this | One or two sentences each, rehearsed | Sun 01:00 |
| K-3 | Re-read each research line marked "search summary" at its page | Each is confirmed or struck | Sat 23:00 |
| K-4 | Read the video and the deck against section 8 | Nothing in section 8 is said | Sun 05:00 |
| K-5 | The Devpost text: what it does, how it was built, what is real and what is extrapolated | Ready for Jimmy to paste | Sun 05:00 |

## 10. Architecture

```
frontend (React + Vite)
  story/Home.tsx          the loop: the 2.5D site, played by the scroll
  story/InsurerFile.tsx   the schedule for one home; grows into the tree screen
  story/InsidePov.tsx     the room from where a person stands, for one eye or two
backend (FastAPI)
  portfolio.py            CoStar: homes, size, rents
  exposure.py             Vexcel and fire zones: a rank per building            (new, Ryan)
  inventory_agent.py      the deep agent that reads a scan room by room         (new, Tazeem)
  flood_agent.py          price research, each price checked against its page
  insurer_file.py         quantities from a scan; grows into the schedule
  server.py               /api/schedule, /api/exposure
```

## 11. Risks

| Risk | What we do about it |
| --- | --- |
| The vision read miscounts cabinets or misses an appliance | Each item carries the standpoint it was seen from, so a person can check it; counts that Matterport measured never come from the model |
| One scanned home stands for hundreds | Labelled an extrapolation everywhere, with the multiplication shown |
| Cost-guide prices are national ranges, not Los Angeles quotes | Ranges, both ends carried through, each linked to its page |
| "Why itemise a total loss?" | Lead with renewal and the dated record; `#/file` shows a partial loss |
| The lead building may not sit in a mapped fire zone | Show what the map says. The exposure rank rests on vegetation as well |
| A fourth change of direction costs the night | The table of what is settled in `DEMO_LOOP.md` closes at 19:00 |
| The headset has only been tried on a laptop | It is optional and has a cut-off |

## 12. Open questions

1. Who inside an owner's company buys this: the asset manager, the risk manager, or the broker on their behalf?
2. Does the LangChain track need more than an agent built on its library? Nobody has re-read that track's rules.
3. Does the smoke scenario get built, or is one scenario enough for two minutes?
