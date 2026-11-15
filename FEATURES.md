# Brace — feature guide

**Existing apartment walkthroughs + aerial imagery + property records → a priced inventory of what the owner owns, what replacing it could cost, and the evidence behind each number.**

## Main flow

**Plane → clouds → Los Angeles → community → home → wildfire → burned home → costs/PDFs → QR → cleanup/refurnishing.**

| Feature | What it does |
|---|---|
| Cinematic walkthrough | Scroll-driven flight, aerial descent, terrain, building selection and interior tour; immediate aftermath on return, without a pre-fire flash. |
| Three data layers | Matterport: interiors/measurements. Vexcel: aerials/elevation/roofs/vegetation. CoStar / Apartments.com: property records/home counts/floor plans/asking rents. |
| Spatial alignment | Fits the interior footprint under its aerial roof; distinguishes candidate associations from verified locations. |
| Inventory agent | Room helpers inspect panoramas, identify owner-owned fixtures/appliances, merge duplicates, and retain uncertainties and exclusions. |
| Quantities | Geometry measures floors/walls/paint; visual observations retain their supporting viewpoints. |
| Pricing and matching | Checks web prices; uses cost guides or plausible product matches plus fitting allowances where available. Unpriced items stay excluded. |
| Financial rollup | Code calculates item → room → home → floor-plan mix → property totals, with central estimates and likely bands where supplied. |
| Property logistics | Uses apartment counts/sizes; estimates building allocations by roof area; shows monthly asking-rent exposure for unavailable homes. |
| Exterior priority | Ranks buildings by fire-zone context, nearby vegetation and roof tree cover, with reasons. |
| Evidence tree | Click through buildings, homes, rooms and items to quantities, price sources, assumptions and uncertainties. |
| Agent rechecks | Reinspect a room or research a product; refreshed evidence can update the schedule. Initial viewing uses saved results. |
| Two PDFs | Before-fire evidence and after-fire recovery: branded summaries, cost tables, room evidence, numbered sources, assumptions, recovery steps and pagination. |
| Report voice | Explains the current paper and figures, opens evidence, and requests rechecks. |
| Fire aftermath | Illustrative burned kitchen/bathroom with missing contents and door leaves; original pre-fire doors remain. |
| QR entry | “Enter the home” opens the burned home on a phone or this screen. |
| Cleanup | “Clean up” removes contents but retains damage; “more” restores empty surfaces. |
| Instant furniture | Chair, sofa, table, lamp, plant, bed or toilet; colors/gold/chrome/wood; place, move, resize, remove and undo. Tap a floor spot, then say “there.” |
| Room voice | Separate companion executes cleanup/furnishing; “look left/right/up/down” turns the view; “take me there” faces the object in its room. |
| Phone controls | Drag, optional orientation permission and split-screen headset view. Microphone/motion need browser permission; physical handset verification remains. |

## Additional workflows in the repository

Separate from the main flow; configuration and prepared data may be required.

- **Weather preparation:** Beryl/LA replays, live-feed support, portfolio screening, located plans, work orders and notices; deadline rules defer work beyond the crew cutoff.
- **Crew coordination:** Allocates trades across plans; does not book contractors.
- **Flood / 2.5D planner:** Hypothetical water levels; place barriers/shutters/equipment lifts/tree-removal proposals; compare views and edit costs/crew-hours. No water-flow simulation.
- **Resident loop:** Household onboarding, private invitations, approved Photon iMessages, reports/help requests, owner review, assessment updates and follow-ups.
- **Recovery valuation:** Comparable screening, repair/disruption assumptions, conditional valuation and agent-proposed tasks; code calculates financial amounts.
- **Spatial tools:** Interior search, wayfinding, geolocation, reconstruction and reimagining. Optional Meshy integration is unconfigured; instant furniture uses a fixed 3D catalog.

## Access and boundaries

Run `uv run python -m scripts.start`. Current desktop: **http://localhost:5184/**; API **8011**; HTTPS phone **5185**. Defaults: 5174 / 8001 / 5175.

Routes: `/` · `#/schedule` · `#/restore/9519837/kitchen` · `#/flood` · `#/recovery` · `#/resident`.

Replacement cost ≠ market value or insurance payout. One home does not verify every home; asking rents are not leases. Resident reports need verification. Generated damage/restoration and furniture placement are illustrative, not measured damage or safe-re-entry findings.
