# The demo loop

Written Saturday 14 November 2026, about 17:20. It follows the team's `DIRECTION.md`, which is not in this repo yet (wildfire in Los Angeles, an
itemised replacement schedule, the customer is the owner of an apartment community). That file marks the customer
as proposed, not decided. If the team changes it, this loop changes with it.

Two minutes, one building, one number at the end. The loop is one move at three scales: outside, inside, then
multiplied.

## The loop

| Time | On screen | Say | Exists on `main` today |
| --- | --- | --- | --- |
| 0:00 | Los Angeles from above. The apartment communities in the fire zones light up, with a count | "These owners know what their buildings sold for. They don't know what's in them." | Mostly. The lit-city descent in `frontend/src/story/StormStory.tsx` (Los Angeles chapter) |
| 0:12 | Push in to Verdugo Mesa Apartments standing up in 2.5D. Brush within 5 ft of the walls is marked and its buildings rank by exposure | "From Vexcel's aerials: which buildings have fuel at the wall." | Mostly. The 2.5D scene in `frontend/src/story/Home.tsx`; vegetation per building is in the height files |
| 0:30 | A floor plan slides under the roof it belongs to | "This is the unit Matterport scanned for leasing, placed under its roof." | Yes. The snap in `frontend/src/components/ScenePage.tsx`, from `backend/openproblems/geolocation.py` |
| 0:40 | Inside the scan. An agent turns through the rooms. Each thing it names gets a tag and a line in the schedule: flooring, cabinets, range, refrigerator, doors | "Every line is a quantity from the scan and a price from a page you can open." | Half. Measurements and confirmed prices exist (`backend/insurer_file.py`, `backend/flood_agent.py`). Reading cabinets and appliances does not |
| 1:15 | The schedule folds into a tree: item, room, unit, then times the homes like it, plus the rent lost for each month they are empty | "One scanned home, multiplied across the homes like it." | No |
| 1:40 | Pull back out. Every community in the zone, ranked by exposed value | "Before the fire, across a portfolio." | No |
| 1:50 | One line and three uses: at renewal, before a fire, after a loss | "From the scan you already have." | No |

The unit count and asking rents come from CoStar and appear on screen from the kit. They are not written in this
file because kit data is never committed.

## The pitch, in five lines

1. **Problem.** An owner insures what is inside a building without a list of it.
2. **Insight.** The list already exists as a leasing scan nobody reads for this.
3. **Proof.** We ran it: scans read, items named, prices confirmed against their pages, minutes and dollars per building.
4. **Why all three datasets.** Vexcel says which buildings. Matterport says what is in them. CoStar says how many homes and what rent.
5. **The number.** The property total, on screen at the end.

## The two questions a judge will ask

- **"If fire takes everything, why itemise?"** Lead with renewal (is the cover enough for what is there) and the dated
  record after a loss. Fire is the scenario, not the argument.
- **"One scan for a whole community?"** Yes, and the screen says so: the multiplication is shown and labelled an
  extrapolation.

## The lead building

Verdugo Mesa Apartments (CoStar 9519837). It has the unit count and asking rents the multiplication needs, 24
buildings with measured ground and vegetation, and one scanned two-bedroom home. Prime Hollywood Hills (10655549)
has more scans but no unit count or rent on record, so it cannot carry the last two beats.

## The headset

It fits the inside beat: the judge stands in the unit while the tags appear round them. `#/inside` already plays a
room for one eye or two; it needs pointing at this unit and given the tags.

## What is cut from the loop

Flood, the $500K and 48 hours budget, forecasts, a fire-spread rate from furniture, and tenants' belongings. The
flood pages stay in the repo and open by address; they are not shown.

## What every screen reads

One schedule, served as `GET /api/schedule/{property_id}`. Build against this shape with placeholder numbers until
the real one is live:

```json
{
  "property": { "id": 0, "name": "", "homes": 0, "scenario": "fire reaches the building" },
  "total": { "low": 0, "high": 0 },
  "lost_rent_per_month": { "low": 0, "high": 0, "how": "homes x asking rent" },
  "numbers": { "scans_read": 0, "items_named": 0, "prices_confirmed": 0, "minutes": 0, "model_cost_usd": 0 },
  "buildings": [
    { "id": "S1", "exposure_rank": 1, "brush_within_5ft_percent": 0, "homes_assumed": 0,
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

`from` is either `read from the scan` (a vision model named it) or `measured from the scan` (Matterport's own
dimensions). `at` is where the item is in the scan, so a tag can be drawn on it. A line with no confirmed price has
null money and is left out of the totals.

## What the research found (14 November, evening)

Answers to the four open questions in `DIRECTION.md`, section 10. "Opened" means the page itself was read; "search
summary" means only a search result was, so check it before it goes on a slide.

1. **The "$2,000 a scan against $10" claim: drop it.** Nothing supports $2,000. Matterport's own page gives no
   figure for its insurance sketch ("competitive per-file pricing", opened). Search summaries put it from about $79
   by floor area, and a photographer's scan at $0.20 to $0.50 a square foot with a $400 to $750 minimum. Use our own
   numbers: the price run took 112 seconds, 11 searches and 9 confirmed prices.
2. **How insurers document fit-out, and who buys.**
   - The standard commercial property form counts the owner's fit-out as part of the **building**: fixtures,
     permanently installed equipment, floor coverings, and appliances for refrigerating, cooking, dishwashing and
     laundering (a study guide to the ISO form, opened; the form itself could not be read). That is our schedule.
     A tenant's own improvements are the tenant's property.
   - At policy start the owner files a statement of values per location, on rebuilding cost, never sale price; land
     cannot be insured. Underwriters check it against cost per square foot (search summary).
   - At a claim the insured must supply an inventory of what was damaged with quantities and values, and a sworn
     proof of loss, typically within 60 to 90 days (search summary).
   - The buyer inside an insurer is not established. Underwriting and loss control order inspections; claims uses
     the estimating software. Our customer is the owner, who files the statement of values with a broker.
3. **Do scan-to-inventory products exist: yes, after a loss, one property at a time.**
   - Matterport sells sketches from its scans for Verisk's Xactimate, the adjusters' estimating software (TruePlan,
     opened). Its own post describes scans taken at first notice of loss and does not claim to list or value
     contents (opened, 2018).
   - CoStar has owned Matterport since 28 February 2025 (release opened). The release does not mention insurance.
   - Encircle: people photograph items after a loss and software writes the descriptions (opened). DocuSketch and
     Yembo make floor plans, estimates or inventories from a capture (search summaries).
   - Nothing found builds a fit-out schedule before a loss, from leasing scans that already exist, across a
     portfolio. A few searches are not proof that nobody does.
4. **The gap between scan date and loss date.** Values are set at the time of the loss, not the scan: a full
   appraisal every three to five years (opened), trended each year in between (search summary). So the scan proves
   what was there and in what condition, and the price comes from today's costs. That is how our schedule already
   works: quantity from the scan, price from a page read now. Every schedule shows its scan date.

What this changes in the loop: the loss is on rebuilding cost only, never sale price; staged furniture stays out of
the owner's schedule; the contrast with Matterport is "after the loss, one at a time" against "before it, across a
portfolio"; and the cost comparison is gone.

## Who does what

Weighted by who can build fastest. Times are Saturday night into Sunday; submissions are reported to close Sunday
08:00.

### Tazeem: the engine and the loop (most of the build)

1. **The inventory.** A vision pass over each room of the scan that names what the owner would replace (cabinets,
   counters, appliances, fixtures, doors, flooring) and where it is. New module beside `backend/vision.py`.
2. **The prices.** Run the existing price research (`flood_agent.price`) on those items. A line is priced only when
   its page confirms it.
3. **The schedule and the rollup.** Item to room to unit, times the homes like it, to building and property, with
   the lost-rent line. Grows out of `backend/insurer_file.py`. Serve it as `/api/schedule/{id}`.
4. **The loop on the home page.** Point the scroll at Los Angeles and Verdugo Mesa: the lit zone, the 2.5D site with
   exposure, the snap, the inside beat with tags, the tree, the pull back.
5. **The tree screen.** Total at the top; open a building, a unit, a room, an item; every figure links to its source.
6. **Final numbers** into the narration and the video once the real run is saved.

### Ryan: the outside, the portfolio, and making it hold

1. **Exposure ranking.** For each building at a site: brush within 5 ft of the walls, trees over the roof, and
   whether it stands in a Los Angeles fire hazard zone. One rank per building, no probability. From
   `backend/vexcel.py` and the height files. Feeds `exposure_rank` in the schedule.
2. **The portfolio beat.** Every scanned community in the zone with its homes and rents, ranked, for the pull-back
   shot. From `backend/portfolio.py`.
3. **Saved runs.** The schedule is computed once and saved, so the loop never waits on a model. Record the
   `numbers` block as it runs: scans read, items named, prices confirmed, minutes, model cost.
4. **Three clean runs.** One start command, the whole loop start to finish three times in a row on the laptop that
   will present.

### Jimmy: the headset and the film

1. **The headset beat.** Point `#/inside` at the Verdugo Mesa unit and draw the tags from the schedule's `at`
   fields as the view turns. Test it on the real phone and viewer early; it has only been checked on a laptop.
2. **Screen recordings** of each beat once it is live, then the two-minute edit and an offline backup copy.
3. **Devpost page**: the video, the screenshots, the build notes.

### Kevin: the script and the argument (no build)

1. **The narration.** Word for word against the loop above, under two minutes read aloud.
2. **The answers.** One or two sentences each for the two judge questions above and for: staged units are not real
   tenants' homes; what happens when the scan is old; who inside an owner's company buys this.
3. **Checks before the pitch.** The four research questions are answered above. Still open: who inside an owner's
   company signs for this, and re-reading the lines marked "search summary" at their source.
4. **The claims list.** Read every line of the video and the deck against `DIRECTION.md`, section 8, and strike
   what we must not say.

### Handoffs

| When | What |
| --- | --- |
| Saturday 19:00 | The schedule shape above is agreed. Ryan has a rank per building. Kevin has a first narration |
| Saturday 22:00 | `/api/schedule` returns real numbers for Verdugo Mesa. The tree screen opens |
| Sunday 01:00 | The whole loop runs on the home page. Jimmy starts recording |
| Sunday 05:00 | Three clean runs. The video is cut with the final numbers |
| Sunday 07:00 | Submitted, with an hour in hand |
