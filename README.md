# Brace

**If a wildfire burned an apartment building, what would the owner have to pay to replace everything inside it? Brace answers that with an itemised, priced list, built from a 3D scan the owner already has.**

Built at HackPrinceton Fall 2026 for the CoStar track ("Inside and Out: AI for the Built World"), with the Business and Enterprise and LangChain tracks.

## The problem

The owner of an apartment community insures the buildings and everything built into them: floors, cabinets, counters, appliances, doors, light fixtures. To buy that insurance they have to tell the insurer what it would all cost to replace. Most owners have no list of what is actually in their apartments, so they estimate from a rough cost per square foot. If the estimate is too low, a fire leaves them paying the difference.

## The idea

Most apartment communities already have a 3D walkthrough of a model apartment, made with a Matterport camera so renters can tour it online. That scan shows every room and everything in it. Nobody uses it for insurance.

Brace reads that scan and turns it into the missing list:

1. **Look through the scan, room by room,** and name each thing the owner would have to replace: one refrigerator, twelve feet of base cabinets, two ceiling fans.
2. **Measure the rooms** for the floors, walls, paint and doors.
3. **Find a price for each kind of item** on the web, and keep the price only if the page really says it.
4. **Add it up for one apartment, then multiply** across all the apartments like it in the community.

The result is one total with everything behind it. You can open the total into buildings, a building into apartments, an apartment into rooms, a room into items, and an item into the web page its price came from.

Brace does not predict fires. It answers one stated question: *if fire reached this building, what would it cost to replace what is inside?*

## Where the data comes from

Three datasets from the hackathon's sponsor kit, plus the web:

| Source | What it is | What Brace takes from it |
|---|---|---|
| **Matterport** | 3D scans of building interiors | The rooms, their measurements, and photos from every spot the camera stood |
| **Vexcel** | Aerial photos and measurements of buildings from above | How much vegetation grows close to each building's walls |
| **CoStar / Apartments.com** | Property records and apartment listings | How many apartments the community has, their floor plans, and the advertised rents |
| **Web cost guides** | Public pages that state what things cost to install | A price range for each kind of item |

## Words this project uses

| Term | Meaning |
|---|---|
| **Put back** | Replace or rebuild after a loss. "What a fire would cost to put back" means the cost to replace what burned |
| **Fit-out** | Everything built into an apartment that the owner owns: flooring, cabinets, counters, appliances, doors, fixtures. Not furniture, and not anything belonging to a tenant |
| **Leasing scan** | The 3D walkthrough of an apartment made to advertise it to renters |
| **Schedule** | The itemised, priced list. It is the insurance word for a list of what is insured and its value |
| **Fuel at the wall** | Plants that can burn (brush, shrubs, trees) growing within 5 feet of a building's walls. Not a gas line. Wildfires usually reach a building through vegetation touching it, so buildings with more of it are more exposed |
| **Kinds of home** | The community's floor plans, such as one-bedroom and two-bedroom |
| **Lost rent** | The rent the owner stops collecting while burned apartments cannot be lived in |

## How it works

```mermaid
flowchart LR
    MP["Matterport scan of one apartment"] --> MEAS["Measure rooms, walls, doors"]
    MP --> INV["AI agent names the items, one helper per room"]
    INV --> PRICE["Second agent finds a price for each kind of item"]
    WEB["Web cost guides"] --> PRICE
    AP["Apartments.com listing: floor plans, counts, rents"] --> SCHED
    VX["Vexcel: vegetation near the walls"] --> SCHED
    MEAS --> SCHED["Add up one apartment, multiply across the community"]
    PRICE --> SCHED
    SCHED --> TREE["The total, which opens down to every item"]
```

- **Naming the items.** An AI agent built on LangChain's `deepagents` gives each room to its own helper. The helper looks at that room's photos and records what it sees. It may only record 23 kinds of item that an owner owns. The code refuses furniture, and refuses any item recorded from a photo the helper never looked at.
- **Pricing.** A second agent searches the web for what each kind of item costs to install. The code then fetches the page itself and keeps the price only if the price is really on it.
- **Adding up.** Plain code does all the arithmetic. No AI model touches a total.
- **Ranking buildings.** Buildings are ordered by their official fire hazard zone (from CAL FIRE's map), then by how much vegetation grows within 5 feet of their walls, then by how much of the roof is under trees.

The AI steps run ahead of time and their results are saved. The screens only read saved results, so nothing waits on a model.

## How far to trust the numbers

- **Prices are ranges for a kind of item**, such as "a refrigerator, installed", taken from national cost guides. They are not a valuation of the specific refrigerator in the scan, and some ranges are wide.
- **One apartment was scanned; the rest are estimated from it.** A floor plan with the same bedrooms and bathrooms gets the same figure. A different floor plan gets the figure scaled by its floor area. The screen marks these as estimates.
- **An item with no confirmed price shows no figure** and is left out of the total. Each total says how many of its lines are priced.
- **Apartments per building are estimated from roof area**, because no source counts them per building.
- **The building ranking is about exposure, not the chance of a fire.** It orders buildings by official fire zone, then vegetation near the walls, then tree cover over the roof.
- **Advertised rents are not what tenants actually pay.**
- **The scans are sample data from the sponsor kit**, not a real customer's insured property.

## What is built

| Piece | What it does |
|---|---|
| Inventory agent | Reads a scanned apartment and saves the list of items it found |
| Price research | Finds and confirms a price range for each kind of item |
| Schedule | Builds the full list for a property, with totals at every level and lost rent per month. Served at `GET /api/schedule/{property_id}` |
| Exposure rank | Orders a property's buildings by fire zone, vegetation near the walls and tree cover over the roof. Served at `GET /api/exposure/{property_id}` |
| Portfolio list | Lists the scanned Los Angeles apartment communities inside a fire zone, ranked. Served at `GET /api/schedule` |
| Run cost | Works out what the AI runs cost from the tokens they recorded, and shows it with the other run figures |
| Tree screen (`#/schedule`) | The total at the top; click down through building, apartment, room and item to the source page |
| Voice | You can ask the schedule questions out loud. It answers by opening the relevant part of the screen. It can also have the agent look at a room again, find a likely make and model for an item, or check the owner's cover |
| Phone as microphone (`#/ctl`) | The same screen on a phone. The big screen follows whatever the phone opens |
| First-person room (`#/inside`, `#/inside/vr`) | The room as seen by a person standing in it, on a screen or in a phone headset |

Not built yet: a screen for the portfolio list, narrowing price ranges by item quality, and scanning more than one apartment per property.

For more detail:

| Document | What it holds |
|---|---|
| [ARCHITECTURE.md](ARCHITECTURE.md) | How the system is put together and where each number comes from |
| [DEMO_LOOP.md](DEMO_LOOP.md) | Presentation sequence and team decisions |
| [PRD.md](PRD.md) | Requirements and who builds what |

## Run locally

Use Python 3.11+, [uv](https://docs.astral.sh/uv/), and Node.js.

From the repository root:

```bash
uv sync
npm --prefix frontend ci
cp -n .env.example .env
```

The copy command keeps an existing `.env` intact.

Extract the sponsor kit so these paths exist:

```text
data/kit/index.md
data/kit/commercial-properties.csv
data/kit/residential-listings.csv
data/kit/data/commercial-property.jsonl
data/kit/data/apartment-listing.jsonl
data/kit/data/residential-listings.jsonl
```

Use your own sponsor credentials and model keys in `.env`:

| Setting | Used for |
|---|---|
| `MATTERPORT_API_KEY`, `MATTERPORT_API_TOKEN` | Fetching scan data |
| `MATTERPORT_SDK_KEY` | Embedded Matterport viewer |
| `VEXCEL_API_KEY` | Aerial imagery and site data |
| `ANTHROPIC_API_KEY` | The inventory agent, price research, plans and visual analysis |
| `OPENAI_API_KEY` | Optional voice |
| `MESHY_API_KEY` | Optional new 3D furniture generation |

Model overrides are `BRACE_AGENT_MODEL`, `BRACE_VISION_MODEL`, `BRACE_AGENT_EFFORT`, `BRACE_VOICE_MODEL` and `BRACE_VOICE`. New source fetches and model runs can incur provider usage; saved results are reused where available.

### Build a schedule

The lead property is a Los Angeles apartment community, CoStar ID `9519837`, with Matterport scan `CaSLe7ZwnfF`. Its building data and the scan's room measurements must already be downloaded into `data/cache/`.

```bash
uv run python -m scripts.flood_research --prices 9519837 CaSLe7ZwnfF   # price the building work, once
uv run python -m scripts.inventory 9519837 CaSLe7ZwnfF                 # read the scan, about 80 seconds for one home
uv run python -m scripts.inventory 9519837 CaSLe7ZwnfF --prices        # price what it named, about 3 minutes
```

Add `--only kitchen-1 --dry` to the inventory command for a short run that saves nothing.

Saved runs live in `data/cache/inventory/` and `data/cache/flood/` and are never committed. A fresh clone has none, and the schedule endpoint answers 404 until a scan has been read.

### Start

```bash
uv run python -m scripts.start
```

The single start command runs the API, desktop web app and HTTPS phone app. Ctrl-C stops them together.

- Desktop: **http://localhost:5174**
- API: **http://127.0.0.1:8001**
- Phone: **https://YOUR-LAN-IP:5175** — the start command prints the address.

The supplied Matterport SDK configuration requires `localhost` for the desktop viewer. For phones, use the same network and accept the local certificate once. If the network isolates devices, connect the computer through the phone's hotspot. The phone's microphone needs the HTTPS address.

To choose other ports, pass them in the shell:

```bash
BRACE_API_PORT=8011 BRACE_WEB_PORT=5184 BRACE_VR_PORT=5185 uv run python -m scripts.start
```

### Where to go

| Route | Purpose |
|---|---|
| `#/schedule` | The tree for the lead property. `#/schedule/<property>` for another |
| `#/ctl` | The same schedule on a phone, as the microphone. The "Phone" button on the big screen shows a QR code for it |
| `#/inside`, `#/inside/vr` | The room from where a person stands, for one eye or two |
| `/` | The property, interior inventory, fire-aftermath illustration and replacement-cost schedule |
| `#/restore/9519837/kitchen` | Burned-room entry, cleanup and instant concept furniture |

To talk to the schedule without a microphone, shift-click "Talk with Brace", then press `/` to type.

## Checks

```bash
uv run pytest
npm --prefix frontend run build
```

## Code map

| Location | Responsibility |
|---|---|
| `backend/inventory_agent.py` | The deep agent: lead, readers, tools and the rules held in code |
| `backend/schedule.py` | The tree and all its arithmetic |
| `backend/flood_agent.py` | Price research with web search and page fetch; `confirm()` |
| `backend/insurer_file.py`, `backend/openings.py` | Room and opening quantities measured from interior geometry |
| `backend/portfolio.py` | CoStar records; Apartments.com floor plans and rents |
| `backend/exposure.py` | Each building's fire zone, vegetation and tree cover, and the order they put it in |
| `backend/run_cost.py` | What the saved runs cost, from their own token counts |
| `backend/flood.py` | Buildings, outlines and vegetation, from the kit and Vexcel |
| `backend/voice.py` | The voice session and what it is told about a schedule |
| `backend/server.py` | The API |
| `scripts/inventory.py`, `scripts/flood_research.py` | Run the inventory agent and the price research |
| `frontend/src/story/` | `ScheduleTree.tsx`, `Home.tsx`, `InsurerFile.tsx`, `InsidePov.tsx`, and the earlier scroll scenarios |
| `tests/test_inventory_schedule.py`, `tests/test_insurer_file.py`, `tests/test_flood_agent.py` | Tests for the new product |

## Recovery valuation and spatial tools

**The current product calculates interior replacement cost.** This is the cost of replacing inventoried owner-owned contents and finishes, not a property's market value or an insurance payout. See [FEATURES.md](FEATURES.md) for the current feature list.

An older **recovery valuation** backend screens comparable sales and combines reviewed current/restored property values with sourced repair and downtime assumptions. With sufficient inputs, it can calculate a conditional cost-to-cure scenario: reviewed restored value minus remaining repairs and disruption costs. Without those inputs, the result remains unavailable. It is separate from the main schedule and does not turn AI-generated fire imagery into a claimed market loss.

**Spatial tools** connect interior observations to real locations:

- **Measurements and alignment:** room geometry supplies quantities; scan-to-roof fitting places the interior footprint against the aerial building.
- **Site geometry:** Vexcel elevation supplies the exterior surface; Matterport supplies existing interior geometry. This is not newly generated Gaussian splatting.
- **Search and navigation:** additional modules search indexed panorama descriptions, face matching objects, and navigate connected scan viewpoints.
- **Room reimagining:** AI-edited panoramas show illustrative damage and cleanup. Instant furniture uses editable geometry from a fixed catalog; optional Meshy generation is not configured.

## Working in this repo

Development is on **main**. Keep changes focused so parallel work can be integrated without replacing another contributor's changes. The sponsor kit, cached imagery, saved runs, resident data, `.env`, and credentials remain local and are not committed. Figures for a single property come from the data at run time and are not written into tracked documents.
