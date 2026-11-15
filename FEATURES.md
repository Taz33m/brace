# Brace — the whole product, briefly

**Brace turns an apartment's existing walkthrough, aerial imagery and property records into a priced inventory: what the owner owns, what replacing it could cost, and the evidence behind each number.**

## Main experience

**Plane window → clouds → Los Angeles aerial → community → home interior → wildfire → same home after fire → cost breakdown and PDFs → QR room restoration.**

| Feature | What it does |
|---|---|
| Cinematic walkthrough | Scroll drives the flight, aerial descent, terrain, building selection and room tour. The fire return immediately shows the damaged version, without flashing the original. |
| Three connected datasets | Matterport supplies interiors and measurements; Vexcel supplies aerials, elevation, roofs and vegetation; CoStar / Apartments.com supply property records, home counts, floor plans and asking rents. |
| Scan-to-building fit | Fits the interior footprint under an aerial roof and shows the alignment. Candidate associations remain distinct from verified locations. |
| Interior inventory agent | Room helpers inspect panoramas, identify owner-owned fixtures and appliances, merge duplicate sightings, and preserve uncertainties and excluded items. |
| Measurements | Uses room geometry for quantities such as flooring, walls and paint; retains the view behind visual observations. |
| Price research | Searches and checks source pages. Uses cost guides or appearance-matched products with fitting allowances where available; missing prices remain excluded. |
| Product matching | Finds plausible makes/models and linked prices. A visual resemblance is not a confirmed identification. |
| Deterministic cost rollup | Code calculates item → room → reference home → floor-plan mix → property totals, including a central estimate and likely band where supplied. |
| Property logistics | Applies listing home counts and floor-plan sizes; estimates building allocations from roof area; shows monthly asking-rent exposure if homes become unavailable. |
| Exterior prioritization | Orders buildings using fire-zone context, vegetation within five feet of walls, and tree cover. Shows reasons rather than a claimed fire probability. |
| Interactive evidence tree | Open a building, home, room or item to inspect quantities, pricing basis, source links, uncertainties and recheck results. |
| Agent rechecks | Ask for another look at a room or a product match; refreshed evidence can update the schedule. Saved results make initial viewing fast. |
| Two printable papers | Before-fire evidence schedule and after-fire recovery file: branded summary, cost tables, room evidence, numbered sources, assumptions, recovery steps and page numbers. |
| Report voice | “Talk with Brace” explains the current paper, its figures, context and assumptions; can open relevant evidence and request rechecks. |
| Fire aftermath | AI-edited kitchen and bathroom panoramas retain the layout but show fire damage, removed door leaves and missing contents. Original pre-fire doors remain. |
| QR room entry | “Enter the home” opens the same burned home directly on a phone; also offers a desktop link. |
| Two-stage cleanup | “Clean up” removes contents while retaining burn marks; “more” restores the empty room's surfaces. |
| Instant furnishing | Place chairs, sofas, tables, lamps, plants, beds or toilets; choose colors/materials, including gold. Move, resize, remove, undo, or tap a floor spot and say “there.” |
| Separate room voice | Executes cleanup, furnishing and navigation commands. “Look left/right/up/down” turns the view; “take me there” switches to/faces the placed object's room. |
| Phone viewing | Drag to look, optionally enable device orientation, or use split-screen headset view. Microphone/motion require supported browsers and permissions; phone motion still needs handset verification. |

## Additional tools in the repository

These are separate routes/workflows, not all part of the main walkthrough; some require configured services and prepared case data.

- **Weather preparation:** Beryl and Los Angeles fire-weather replays, live-feed support, portfolio screening, spatial action plans, contractor work orders and resident notices. Deadline rules defer work that cannot fit before the crew cutoff.
- **Crew coordination:** Allocates available trades across building plans; does not book contractors.
- **Flood / 2.5D planning:** Explore hypothetical water levels; place barriers, shutters, equipment lifts and tree-removal proposals; compare views and edit cost/crew-hour allowances. The placement tool does not simulate water flow or prove protection.
- **Resident recovery loop:** Household onboarding and private invitations; approved notices and Photon iMessage; resident reports/help requests; owner review, assessment updates and resident follow-ups. Reporting a problem does not itself verify damage.
- **Recovery valuation:** Evidence inventory, comparable screening, repair/disruption assumptions and conditional valuation; deterministic financial calculations with agent-proposed recovery tasks.
- **Spatial tools:** Interior search, wayfinding, scan geolocation, reconstruction and reimagining. Meshy integration exists but is optional and unconfigured; instant furnishing uses a fixed parametric 3D catalog.

## Open it

Run `uv run python -m scripts.start` from the root. Current local ports: desktop **5184**, API **8011**, HTTPS phone **5185** (defaults are 5174 / 8001 / 5175).

Main: `/` · Evidence: `#/schedule` · Room: `#/restore/9519837/kitchen` · Flood: `#/flood` · Recovery: `#/recovery` · Resident: `#/resident`.

**Boundaries:** replacement cost is not market value or an insurance payout. One observed home does not verify every home. Asking rents are not leases. Generated damage/restoration and furniture placement are illustrative; they do not establish actual loss, dimensions or safe re-entry.
