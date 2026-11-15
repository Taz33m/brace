# Ryan's part of the demo loop: design

14 November 2026. Covers tasks R-1 to R-4 in `PRD.md` section 9. Approved by Ryan in conversation.

## Why

The two-minute loop in `DEMO_LOOP.md` needs three things from outside the scanned home: a rank per building
(beat 2), a list of communities for the pull-back (beat 6), and figures the run recorded itself (the pitch's
"proof" line). Submission is Sunday 15 November, 07:00.

## Goals

- **R-1 Exposure.** Every building at a property has a rank and the three facts behind it, each with its source.
- **R-2 Portfolio list.** `GET /api/schedule` lists the scanned Los Angeles apartment communities inside a mapped fire zone.
- **R-3 Numbers.** `numbers.model_cost_usd` is computed from what the runs saved, not typed in.
- **R-4 Clean runs.** The lead property's schedule loads on this laptop from saved runs, three times in a row.

## Not doing

- No forecast, probability or percent burned. The rank is an ordering of exposure.
- No model call at request time.
- No change to the customer, the hazard, or the shape of the schedule in `PRD.md` section 6 beyond added fields.

## Approaches considered for the rank

1. **Ordered by fire zone, then vegetation within 5 ft, then tree cover over the roof (chosen).** Each step is one
   stated fact, so the order can be explained in a sentence and checked by eye.
2. A weighted score of the three. Rejected: the weights would be invented and could not be sourced.
3. Vegetation within 5 ft alone (what exists today). Rejected: the PRD asks for three facts.

## Design

- **`backend/exposure.py`** reads the saved building file and the saved fire-zone map. For each building:
  vegetation within 5 ft of the walls (Vexcel), tree cover over the roof (Vexcel), and the fire hazard severity
  zone at its centre (CAL FIRE). Sort by zone (Very High, High, Moderate, none), then 5 ft, then roof cover; ties
  keep building order. A missing fact is null and sorts last. Served at `GET /api/exposure/{property_id}`.
- **`schedule.py`** takes its building order, `exposure_rank` and `in_fire_zone` from `exposure.py`, and adds
  `fire_zone` and `tree_cover_over_roof_percent` to each building.
- **Portfolio list.** `schedule.portfolio()` at `GET /api/schedule`: Los Angeles apartment communities with at
  least one scan and a mapped fire zone at their address. Each row has homes and asking rents from the
  Apartments.com listing, rent per month, and the replacement total only where a scan has been read; otherwise
  null. Ranked by replacement total where known, then by rent per month, because rent is the one dollar figure
  every community can have. Missing rents are null.
- **Cost.** Each saved run already holds its model and token counts. `model_cost_usd` is tokens times the
  published price for that model, summed over the inventory run and both price runs. The inventory run counts
  its sub-agents' tokens as well as the lead's. An unknown model gives null, not zero.
- **Clean runs.** After the data is regenerated here, load the schedule, the exposure and the portfolio list three
  times and write down the time of each.

## Left to the builder

Field names beyond those above, test fixtures, and the wording of source labels.
