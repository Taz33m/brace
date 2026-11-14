# Brace — demo script

Two minutes. Everything on screen is real: real forecasts as issued, real buildings, real plans built by the agent.

## Before you start

1. Servers running: `uv run uvicorn backend.server:app --port 8001` and `(cd frontend && npm run dev)`.
2. Open `http://localhost:5174` in Chrome. It must be `localhost`.
3. Open each building below once beforehand so its 3D scan is cached by the browser.
4. Headset only if it has been tested on the actual phone (`HANDOFF.md`, task 4). Otherwise leave it out.

## The two-minute path

| Time | Do | Say |
|---|---|---|
| 0:00 | Map, Hurricane Beryl, slider at **72 hours** | "This is the real National Hurricane Center forecast for Beryl, three days out. It is pointed at South Texas. Nothing in Houston is touched." |
| 0:15 | Drag the slider to **36 hours** | "A day and a half later the forecast has moved. 1,758 of the CoStar buildings in Houston are now in the wind field, holding about 400,000 homes. Each one is on the list for a reason you can read." |
| 0:30 | Click **The Parker at Ellington** (`#/beryl-2024/adv33/b/4303509`) | "265 homes. Tropical-storm winds arrive here in about 39 hours. Outside on the left from Vexcel, inside on the right from Matterport." |
| 0:40 | Click **Replay how it was built** | "The agent reads the roof analysis, looks from four sides, checks the pools and carports, then walks the leasing office and the units. The viewers follow where it looks." |
| 1:05 | **Plan** tab | "Five things to do before it arrives, $2,700 to $9,700: a tree crew for one courtyard tree over three roofs, tie-downs on about two dozen rooftop AC units, pool furniture, balconies, drains. It also found that the 'tarp on the roof' flag was out of date, so no roofer." |
| 1:20 | **Messages** tab | "And the messages that get it done: a notice to residents and work orders for the tree crew and the HVAC contractor." |
| 1:30 | Back to the map, slider to **12 hours**, open the same building (`#/beryl-2024/adv37/b/4303509`) | "Same building, twelve hours out. Crews cannot work safely now, so the plan is different: four staff tasks, under $550, and the tree and AC work is filed for after the storm. The clock is part of the plan." |
| 1:50 | Top bar: Los Angeles scenario, open **Prime Hollywood Hills** (`#/la-red-flag-jan-2025/20250105T2240Z/b/10655549`) | "Different city, different threat. This is the Red Flag Warning issued two days before the January 2025 fires. The list is now dead brush on the slope, branches on roofs, gutters." |
| 2:00 | Stop | "It does not give owners a risk score. It tells them what to fix, what it costs and who to call, before it arrives." |

## If there is more time

- **A different kind of building.** 333 Northbelt, a 12-storey office in a high-risk flood zone (`#/beryl-2024/adv33/b/23347`): the plan is about keeping water out of the ground-floor gym, training room and lobby. 130 Mitchell Rd, a warehouse (`#/beryl-2024/adv33/b/239313`): fasten a rusted metal roof, close bay doors, lift stock off the floor.
- **Value.** On the map: "The buildings in the wind field last sold for a combined figure shown here." It is last recorded sale prices, not today's value and not a loss estimate. Say that.
- **What then happened.** Slider to **Landfall**, open any building: the strip shows the rain that actually fell on that building's area, from DeepMind's rainfall dataset released this week. It is shown as hindsight and the agent never sees it.
- **Filter to one property manager** on the map to show the portfolio view.

## Plans that are ready

| Building | Type | Forecast step | Before-arrival actions | Cost before arrival |
|---|---|---|---|---|
| The Parker at Ellington (4303509) | Apartments, 265 homes | Beryl, 36 h | 5 | $2,700 to $9,700 |
| The Parker at Ellington (4303509) | Apartments | Beryl, 12 h | 4 | $0 to $550 |
| Providence at Heights (8030510) | Apartments, 260 homes | Beryl, 36 h | 7 | $3,200 to $10,900 |
| Providence at Heights (8030510) | Apartments | Beryl, 12 h | 7 | $0 to $900 |
| Valencia Grove (1507455) | Apartments, 1,057 homes | Beryl, 36 h | 9 | $3,400 to $11,100 |
| 333 Northbelt (23347) | Office, 12 storeys | Beryl, 36 h | 10 | $2,200 to $15,100 |
| 130 Mitchell Rd (239313) | Industrial | Beryl, 36 h | 7 | $1,450 to $7,100 |
| Verdugo Mesa Apartments (9519837) | Apartments, 268 homes | Red Flag, 43 h | 5 | $2,900 to $9,500 |
| Pasadena Park Place (1190364) | Apartments, 122 homes | Red Flag, 43 h | 7 | $4,800 to $13,000 |
| Prime Hollywood Hills (10655549) | Apartments | Red Flag, 43 h | 6 | $3,650 to $11,600 |

Read a plan yourself before you present it. These were built by the agent and have not each been checked line by line.

## Honest answers to likely questions

- **"Do you predict the storm?"** No. We use the official forecast and warnings as issued.
- **"Is the wind figure a gust?"** No, sustained wind estimated from the forecast's wind radii. Gusts run 20 to 30 percent higher.
- **"Can you see inside the whole building?"** No. The scans cover single spaces: a leasing office, a unit, a suite. The agent says when something was not scanned.
- **"Did it get the Los Angeles fires right?"** None of the kit's buildings burned. The nine nearest the Palisades fire, about 3 km away, were all on the list 43 hours before the warning began.
- **"Does it text tenants?"** It drafts the notice. The kit's contact details are deliberately fake, so nothing is sent to real tenants.
- **"What does a plan cost to produce?"** Roughly a dollar of model usage and two to four minutes.

## If something breaks

- **3D scan will not load:** check the address bar says `localhost:5174`.
- **Live run fails:** every building above has a saved plan; use Replay.
- **Map tiles missing:** the forecast shapes and buildings still draw; carry on.
