# Brace — PRD

**What to fix on your building before the storm or fire arrives.**
HackPrinceton 2026, CoStar track ("Inside and Out: AI for the Built World").

Status: draft v1, 2026-11-14. Built on the registration, imagery clients and viewer from the earlier Plumbline project.

---

## 1. Summary

Brace is an AI agent for owners and property managers of commercial buildings. It watches the forecast, finds which buildings in a portfolio a hurricane (Houston) or a wildfire wind event (Los Angeles) will touch, and for each one writes a short fix list sized to the hours left: what to do, where on the building, who does it, what it costs. It then drafts the tenant notice and the contractor work orders that get it done.

The output is "here is what to fix and what it costs", not a risk score. Owners push back on scores.

## 2. Who it is for

| User | What they do today | What Brace gives them |
|---|---|---|
| **Property manager** with tens of buildings (primary) | A generic storm checklist emailed to every site | A different, specific list per building, ranked by which to call first, with the messages already written |
| Owner or asset manager | Learns about damage afterwards | The pre-event spend that avoids it, and a record that it was offered |
| Lender or insurer (secondary) | Exposure by address | Exposure plus the specific vulnerabilities and whether they were addressed |

The kit supports this user: of 3,339 commercial properties, 1,731 name their property manager and 1,937 have current tenants on record. 2,765 are apartment communities, so the typical user manages residents, not just business tenants.

## 3. What is different

Address-to-risk-score products, wildfire photo checks and post-storm damage reports exist. Brace differs in three ways:

1. **It acts on a specific forecast**, and the plan changes with the hours left. With 60 hours a tree crew is possible; with 18 it is not.
2. **It looks at the actual building, outside and inside.** Roof condition, rooftop units and nearby trees from the air; glass, ground-level spaces and what sits on the floor from the scans.
3. **It ends in actions and messages**, not a number.

## 4. The data, as it really is

Checked against the live APIs.

| Layer | What it gives Brace | Limits |
|---|---|---|
| **CoStar** | Type, age, storeys, construction, size, homes, parking; property manager and owner where named; current tenants with head counts | Owner named on only 262 properties; apartment residents are not listed |
| **Vexcel** | Per structure: roof material, condition 1 to 5, defects, counted rooftop units, vents, skylights, solar; tree cover over the roof and at 0 to 5, 5 to 30 and 30 to 100 ft; overhead and four angled photos; open-vocabulary detection | The roof analysis can be older than the photo |
| **Matterport** | Scans of individual spaces: suites, apartment units, leasing offices, gyms, lobbies, warehouse bays. Panoramas at every position, a GPS fix, floor from the title | **Not whole buildings and not plant rooms.** Windows are not labelled on commercial scans, so glass is read by a vision model |
| **Public hazard data** | NHC forecast advisories and cones, NWS alerts and Red Flag Warnings, FEMA flood zones, California fire hazard severity zones, past fire perimeters | Hurricane season ends 30 November, so the demo replays real past forecasts |

Across the portfolio the aerial analysis alone flags plenty to work with. Houston: 283 buildings with a roof at 2 of 5 or worse, 687 with four or more rooftop units, 338 with trees over the roof. Los Angeles: 345 with vegetation within 5 ft of the walls, 424 wood-frame.

**Correction to the original pitch:** the scans cannot show ground-floor electrical or mechanical rooms of a tower, because those rooms were never scanned. Brace uses the scans for what they do show and says plainly when a risk depends on a space with no scan.

## 5. Product

### 5.1 Flow

1. **Forecast.** Pick a scenario: a live alert, or a replay of a real one. Scrub the forecast back and forth in time.
2. **Portfolio.** The map shows the track, cone and wind field (or the warning area) and every building it touches. The list ranks them and says why each is there. Filter to one property manager.
3. **Building.** Open one. The site from the air on the left, its scanned spaces on the right, the threat at this exact site across the top.
4. **Plan.** The agent builds the plan while the viewers follow where it looks. Actions are grouped: do before it arrives, do after this event, plan and budget.
5. **Messages.** A notice for the people in the building and a work order per outside trade, ready to copy.

### 5.2 Scenarios

| Scenario | Source | Why |
|---|---|---|
| Hurricane Beryl, July 2024, Houston (replay) | NHC forecast advisories and cones as issued | A real storm that hit this portfolio; several forecast steps so the clock moves |
| Santa Ana wind event, January 2025, Los Angeles (replay) | NWS Red Flag Warning areas as issued | The warning that preceded the Palisades and Eaton fires; fire perimeters shown as hindsight |
| Live | NWS and NHC right now | Proves it is a watcher, not a canned demo; may be quiet |

### 5.3 The ranking

No model call. For each building the forecast touches: the forecast at that point, standing flood or fire zoning, and the aerial facts, combined into an ordering. The interface shows the reasons, never a score.

## 6. The agent

A tool loop on Claude with vision, one run per building per forecast step.

**Tools:** building record; the threat at this site; site facts per structure; aerial views (overhead with a grid, four angled); a detector to point at the site; the list of scans; a first-pass survey of a scan; a look from any scan position; leads; actions; messages.

**Rules enforced in code, not left to the prompt:**
- An action filed as "before it arrives" must fit in the hours left, less a six-hour stand-down for crews. Otherwise the tool refuses it and the agent must split it or file it for later.
- An action whose basis is "seen" must point at a structure, a grid cell or a scan position.
- Every lead must be resolved: actions, not a concern, or could not check.
- No finish without a notice to the people in the building.

## 7. Architecture

```
frontend (React + Vite, localhost:5174)     map (Leaflet), site pane, Matterport tour, plan panel
backend (FastAPI, :8001)
  portfolio.py   CoStar buildings, managers, tenants
  hazards/       forecasts, alerts, flood and fire zoning (public sources, cached)
  screen.py      which buildings a forecast touches, and why
  building.py    per-building bundle: record + site photo + structures + scans
  vision.py      first-pass read of a scan's panoramas
  agent.py       the planner: tools, rules, loop
  server.py      API and the live event stream
```

## 8. Demo (3 minutes)

1. Forecast map: Beryl, 60 hours out. Scrub forward; buildings enter the wind field and the count climbs.
2. Filter to one property manager: their buildings, ranked, each with reasons.
3. Open the top one. Threat strip: hours left, peak wind, flood zone.
4. Replay the plan being built: the site view jumps to the rooftop units, the scan flies to the glass-fronted leasing office.
5. The plan: before-arrival actions with cost and crew hours; the re-roof filed for afterwards because it cannot be done in time.
6. Messages: the resident notice and the work order.
7. Switch to Los Angeles and the Red Flag Warning: same product, different threat, different list.

**VR:** the Matterport tour runs in a headset browser, but the SDK key that drives the highlighted jumps only works on `localhost`. Treat the headset as a way to stand in the scanned space, not as the demo's spine.

## 9. Risks

| Risk | Mitigation |
|---|---|
| Scans do not cover the spaces that matter most (plant rooms, roofs) | Lean on the aerial layer for those; say what was not scanned |
| Forecast replays feel canned | Real advisories as issued, a time slider, and a live tab |
| Cost figures challenged | Ranges from stated anchors, labelled rough |
| The agent pads the list | Prompt asks for few specific actions; the "seen" rule forces evidence |
| Los Angeles kit buildings are mostly outside the highest fire zones | Rank by warning area plus vegetation and construction; show the count honestly |

## 10. Open questions

1. Team: who owns the headset demo, and is it worth the setup time?
2. Should the notice be sent anywhere (email, SMS) or stay as a draft to copy? Currently a draft.
