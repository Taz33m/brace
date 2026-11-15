# Brace: deriving an interior replacement-cost schedule from existing building data

*Technical brief · 14 November 2026 · Implemented method and proposed evaluation*

## Abstract

Brace combines interior imagery and measurements with property records to produce an itemized estimate of owner-owned interior replacement costs. A LangChain Deep Agents orchestrator delegates visual inspection by room, reconciles observations and preserves uncertainty. Separate price research supplies cost evidence; deterministic code calculates totals. Aerial data provides exterior exposure context. This brief describes the implementation, not a validated study of appraisal accuracy or insurance outcomes.

## Inputs and scope

An online apartment tour is a collection of views from positions inside a home. Matterport supplies these panoramas, room labels and geometry. CoStar property and Apartments.com listing records supply apartment counts, floor plans, sizes and asking rents. Vexcel supplies aerial imagery, footprints and vegetation context.

The output covers inventoried fixtures, appliances and interior finishes. It does not estimate land value, whole-building reconstruction, fire probability or insurance payment. A representative home's inventory is a starting point for property-wide extrapolation, not proof that every apartment has the same interior.

## Method

1. **Inspect.** A lead agent discovers rooms and delegates each room to a reader with its own context. Readers inspect panorama directions and record supported item categories, quantities and viewing locations.
2. **Reconcile.** The lead merges repeated sightings and flags unresolved ambiguity. The run retains exclusions, refused records, merges, doubts and working notes.
3. **Measure and price.** Surface quantities use available geometry. Separate research gathers cost-guide prices or product matches. Price confirmation checks source-page support; it does not prove local suitability or exact product identity.
4. **Aggregate.** Code combines quantities and applicable prices into room and home totals. Floor-plan counts and explicit scaling assumptions extend the result across the property. Missing prices remain unavailable and are excluded from totals.
5. **Contextualize.** Exterior exposure ranking uses fire-zone and vegetation context. Asking rents support a separate income-exposure estimate. Neither ranking nor rent converts the interior estimate into a market valuation.

Conceptually, for priced lines with compatible quantity and price units:

`home estimate = sum(quantity × applicable unit cost)`

`property estimate = sum(floor-plan home count × estimated cost for that floor plan)`

## Why delegated agents matter

Room readers keep visual investigation focused; the lead reconciles findings across room boundaries. This matches the inspection task's structure. The implementation uses `create_deep_agent`, custom inspection tools, reader subagents and agent-written notes. We have not measured whether this architecture outperforms a single-agent baseline.

Tools reject unsupported item categories and records referencing views that were never opened. These controls improve traceability; opening an image does not guarantee that the model interpreted it correctly. Measurements and financial arithmetic remain outside the language model.

## Evidence and limitations

The repository contains checks for view requirements, category restrictions, duplicate handling, missing-price exclusion and property aggregation. These verify software behavior, not real-world inventory or estimating accuracy. Initial screens load saved runs; room rechecks invoke the agent again.

Occlusion, mistaken counts, broad price ranges, dated records and differences between apartments remain material sources of error. Generated burned and restored panoramas are illustrations and are excluded as evidence of actual damage. Furniture placement is a separate concept-visualization feature.

## Proposed evaluation—not completed results

Compare expert-labeled walkthroughs and independently prepared cost schedules against Brace on held-out homes. Measure item precision and recall, quantity errors, duplicate rates, source support, cost differences and human review time. Compare a single-agent inspection with room delegation under matched models and budgets. Separately test extrapolation against additional inspected apartments of each floor plan. Record latency and model cost alongside quality.

Until that evaluation exists, the supported claim is an inspectable estimation workflow—not proven savings or professional accuracy.

## Implementation references

- [Inventory agent and evidence tools](backend/inventory_agent.py)
- [Schedule arithmetic](backend/schedule.py)
- [Property records](backend/portfolio.py) and [exposure ranking](backend/exposure.py)
- [Inventory and schedule checks](tests/test_inventory_schedule.py)
- [Architecture](ARCHITECTURE.md) and [current features](FEATURES.md)
