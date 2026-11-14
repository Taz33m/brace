# Brace

**What to fix on your building before the storm or fire arrives.** Built for the CoStar track at HackPrinceton 2026.

Brace is an AI agent for owners and managers of commercial buildings. It takes a forecast (a hurricane heading for
Houston, a Red Flag Warning over Los Angeles), finds which buildings in a portfolio it touches, and for each one
writes a short fix list sized to the hours left, with rough costs, then drafts the tenant notice and the contractor
work orders.

It combines four sources for the same address: CoStar (who owns, manages and occupies the building), Vexcel
(the roof and grounds from the air), Matterport (scanned spaces inside), and public forecasts and hazard maps.

See [PRD.md](PRD.md) for the product thinking.

## Setup

Requirements: Python 3.11+, [uv](https://docs.astral.sh/uv/), Node 20+.

```bash
cp .env.example .env                              # fill in the Matterport, Vexcel and Anthropic keys
mkdir -p data && unzip costar-hackathon-kit.zip -d data/kit   # so that data/kit/index.md exists
uv sync && (cd frontend && npm install)

# One-off data preparation
uv run python -m scripts.scan_parcels             # aerial parcel record for every building (about 12 minutes)
uv run python -m scripts.fetch_hazards            # forecasts, warnings and hazard zones
```

## Run

```bash
uv run uvicorn backend.server:app --port 8001     # API
(cd frontend && npm run dev)                      # web app on http://localhost:5174
```

Open `http://localhost:5174`. It must be `localhost`: the Matterport SDK key only works there.

Plans can be prepared ahead of time from the command line:

```bash
uv run python -m scripts.plan --list                          # scenarios and their forecast steps
uv run python -m scripts.plan --scenario <id> --top 4         # the most pressing buildings that have scans
```

### Phone headset

A phone in a cardboard-style headset can stand inside any scanned space and see the plan's actions pinned in it.

```bash
(cd frontend && npx vite --config vite.vr.config.ts)   # HTTPS on port 5175, reachable on the local network
```

On a building page click **Open in headset** and scan the QR code with the phone (same Wi-Fi as the computer).
The phone warns about the self-made certificate; continue, press Start, and slide it into the headset. Look at a blue
floor spot to walk there and at an orange number to read that action. Whatever is selected on the laptop, the headset
goes to; where the wearer looks shows on the laptop's site photo. If the venue Wi-Fi blocks devices from reaching each
other, put the computer on the phone's hotspot instead.

`data/` and `.env` are git-ignored. The kit, API responses and keys never go in the repo.

## Tests

```bash
uv run pytest
```

No network or keys needed. The agent loop is driven by a scripted stand-in for the model.
