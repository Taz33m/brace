# Brace — feature guide

**Existing apartment walkthroughs + aerial imagery + property records → a priced inventory of what the owner owns, what replacing it could cost, and the evidence behind each number.**

## Main flow

**Home inventory → sourced replacement costs → property total → evidence/recovery papers → burned-room illustration → cleanup/refurnishing.**

| Feature | What it does |
|---|---|
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
| Phone controls | Drag, or turn the phone once motion is allowed. A phone signs in once with the owner password before the room voice will open. |
| Headset view | One tap asks for motion, keeps the screen awake, starts the room voice and fits the two pictures to the viewer's lenses (remembered on the phone). Inside: the head is the camera, each eye has its own picture so furniture has depth, the room's words ride at the foot of the view, a tap cleans up one step, “there” is where the eyes rest on the floor, and a tap near the top edge comes out. Checked in a headless browser at phone size; a real phone in a real viewer is still to be tried. |

## Two terms clarified

**Recovery valuation — older backend capability, separate from the current cost schedule.** Screens comparable sales and accepts reviewed property values, repair costs and downtime assumptions. When the required inputs exist, it can calculate a conditional current value: **reviewed restored value − remaining repairs − disruption costs**. Missing inputs leave the value unavailable. It does not infer a market-value drop from the burned-room illustration. The current product's headline is **interior replacement cost**.

**Spatial tools — working with where things are.** The current experience uses room measurements, scan-to-roof alignment, and aerial elevation to connect the interior to the building. Additional modules can search descriptions of panorama contents, turn toward a matching object, and navigate connected viewpoints. “Reconstruction” uses existing Vexcel elevation and Matterport geometry; it does not generate Gaussian splats from photographs. Cleanup edits panorama imagery; the furniture is editable concept geometry from a fixed catalog. Optional Meshy generation is unconfigured.

## Access and boundaries

Run `uv run python -m scripts.start`. Current desktop: **http://localhost:5184/**; API **8011**; HTTPS phone **5185**. Defaults: 5174 / 8001 / 5175.

Routes: `/` · `#/schedule` · `#/restore/9519837/kitchen`.

Replacement cost ≠ market value or insurance payout. One home does not verify every home; asking rents are not leases. Generated damage/restoration and furniture placement are illustrative, not measured damage or safe-re-entry findings.
