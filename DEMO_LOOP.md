# The demo loop

Final as of Saturday 14 November 2026, 17:40. It follows the team's `DIRECTION.md` (the 17:13 version, not in this
repo). The requirements and the full split of the work are in `PRD.md`.

**The product in one sentence:** Brace tells the owner of an apartment community what a fire would cost to put
back, line by line, from the leasing scan they already have.

## What is settled

| Question | Answer | Who settled it |
| --- | --- | --- |
| Hazard | Wildfire, Los Angeles | The team, in the feedback session |
| Output | An itemised schedule as a tree: total, building, home, room, item | The team |
| Forecasts | None | The team |
| The preparation product (plans, crews, resident messages) | Cut from the pitch. The code stays | Tazeem, 14 November |
| Customer | The owner of an apartment community | Proposed in `DIRECTION.md`; this loop is built on it |
| Fire-spread rate from furniture | Dropped. "Fire reaches the building" is a stated scenario | Proposed in `DIRECTION.md`; this loop is built on it |
| Flood | Not in the two minutes. `#/file` stays open in a tab as the partial-loss answer | Tazeem's recommendation |
| Style | Real data, sober. No mascot, no toy diorama | Tazeem's recommendation |
| Headset | A live extra at the table. Not in the video's critical path | Tazeem's recommendation |
| Tracks | Business and Enterprise, CoStar, and LangChain if the inventory agent is built on it | `DIRECTION.md`, current thinking |

If anyone disagrees with a row marked proposed or recommended, say so before 19:00. After that we build on it.

## The loop

Two minutes, one building, one number at the end. One move at three scales: outside, inside, multiplied.

| # | Time | On screen | Say | Needs | If it is not ready |
| --- | --- | --- | --- | --- | --- |
| 1 | 0:00 | Los Angeles from above. The apartment communities inside the fire zones light up, with a count | "These owners know what their buildings sold for. They don't know what's in them." | The lit-city descent that exists, pointed at the fire zones | Open on beat 2 |
| 2 | 0:12 | Push in to Verdugo Mesa Apartments standing up in 2.5D. Brush at the walls is marked; its 24 buildings rank by exposure | "From Vexcel's aerials: which buildings have fuel at the wall." | Ryan's rank per building; the 2.5D scene pointed at this site | Show the site standing up, no ranking |
| 3 | 0:30 | The scanned home's floor plan slides under the roof it belongs to | "This is the home Matterport scanned for leasing, placed under its roof." | Exists | Cut; go straight inside |
| 4 | 0:40 | Inside the scan. The view turns through the rooms. Each thing the agent named gets a tag and a line in the schedule: flooring, cabinets, range, refrigerator, doors | "Every line is a quantity from the scan and a price from a page you can open." | Tazeem's inventory and prices | The schedule fills beside a still of the room |
| 5 | 1:15 | The schedule folds into a tree: item, room, home, then times the homes like it, plus rent lost for each month they are empty | "One scanned home, multiplied across the homes like it." | Tazeem's rollup and the tree screen | The one home's schedule and the multiplication as one line |
| 6 | 1:40 | Pull back out. Every community in the zone, ranked by exposed value | "Before the fire, across a portfolio." | Ryan's portfolio list | End on the property total |
| 7 | 1:50 | One line and three uses: at renewal, before a fire, after a loss | "From the scan you already have." | Words only | |

Beats 4 and 5 are the product. If time runs short, everything else gives way to them.

Kit figures for one property (unit counts, rents, vegetation percentages) appear on screen from the data. They are
not written in this file because sponsor records are never committed.

## Done means

- The loop runs start to finish on the presenting laptop three times in a row, with no model call while it plays.
- Every dollar on screen opens to a quantity from the scan and a price from a page.
- A line with no confirmed price shows no figure and is left out of the totals, and the screen says how many lines the total covers.
- The multiplication from one scanned home to the rest is shown and labelled an extrapolation.
- Nothing on screen says forecast, probability, or percent burned.
- A backup video of the loop plays offline.

## The pitch, in five lines

1. **Problem.** An owner insures what is inside a building without a list of it.
2. **Insight.** The list already exists as a leasing scan nobody reads for this.
3. **Proof.** We ran it: scans read, items named, prices confirmed against their pages, minutes and dollars per building.
4. **Why all three datasets.** Vexcel says which buildings. Matterport says what is in them. CoStar says how many homes and what rent.
5. **The number.** The property total, on screen at the end.

## What a judge will ask

| Question | Answer |
| --- | --- |
| If fire takes everything, why itemise? | The schedule is for renewal (is the cover enough for what is there) and for the claim (a dated record). And most losses are partial: open `#/file`, where the same kind of schedule changes with two feet of water |
| One scan for a whole community? | Yes, and the screen says so. The multiplication is shown and labelled |
| These are staged homes, not real tenants' things | Right. The owner insures the fit-out: floors, cabinets, appliances, doors. Under the standard commercial form those are part of the building. Tenants' belongings are the tenants' own cover, and we leave them out |
| The scan is old by the time of a loss | Values are set at the time of loss. The scan proves what was there; the price is read today. Every schedule shows its scan date |
| Doesn't Matterport already do this? | It sells sketches from scans into claims, after a loss, one property at a time. This is before the loss, from scans that already exist, across a portfolio |
| Where does a number come from? | Click it |

## The lead building

Verdugo Mesa Apartments, Los Angeles (CoStar 9519837, scan `CaSLe7ZwnfF`). It has what the last two beats need: a
unit count and asking rents on record, 24 buildings with measured vegetation, and one scanned two-bedroom home
with a kitchen and a bathroom. Two things it lacks today: the scan's walls have not been measured (one fetch from
Matterport), and no sale price is on record, which no longer matters because the loss is on rebuilding cost.

## What every screen reads

One schedule, served as `GET /api/schedule/{property_id}`. The shape is in `PRD.md`, section 6. Build against it
with placeholder numbers until the real one is live.

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

The tasks, what counts as done for each, and the hours are in `PRD.md`, section 9. In short:

- **Tazeem** (most of the build): the inventory agent, the prices, the schedule and rollup, the tree screen, the loop on the home page.
- **Ryan:** the exposure rank per building, the portfolio list, saved runs, three clean runs.
- **Jimmy:** the headset beat on the real phone, the recordings and the edit.
- **Kevin** (no build): the narration, the answers, re-checking the sources, the claims list, the Devpost text.

| When | What |
| --- | --- |
| Saturday 19:00 | Objections to the settled table are in. Ryan has a rank per building. Kevin has a first narration |
| Saturday 22:00 | `/api/schedule` returns real numbers for Verdugo Mesa. The tree screen opens |
| Sunday 01:00 | The whole loop runs on the home page. The headset works or is cut. Jimmy starts recording |
| Sunday 05:00 | Three clean runs. The video is cut with the final numbers |
| Sunday 07:00 | Submitted, with an hour in hand |
