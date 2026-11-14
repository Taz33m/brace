import type { Evidence, MoneyRange, OwnerCaseView, TaskStatus } from "../../../recovery/contracts";
import { FIXTURE_LABEL, fixtureCases, fixtureSnapshot, type FixtureVariant } from "../fixtures/preview-fixture";
import { assert, assertEqual, assertIncludes, test } from "./harness";

const VARIANTS: FixtureVariant[] = ["full", "conditional", "insufficient", "stale", "empty"];
const CASE_IDS = fixtureCases().map((c) => c.case_id);

function eachSnapshot(fn: (view: OwnerCaseView, where: string) => void): void {
  for (const case_id of CASE_IDS) {
    for (const variant of VARIANTS) fn(fixtureSnapshot(variant, case_id), `${case_id}/${variant}`);
  }
}

/** Every MoneyRange anywhere inside a value (found structurally by currency: "USD"). */
function moneyRanges(value: unknown, out: MoneyRange[] = []): MoneyRange[] {
  if (Array.isArray(value)) {
    for (const v of value) moneyRanges(v, out);
  } else if (value && typeof value === "object") {
    const rec = value as Record<string, unknown>;
    if (rec.currency === "USD" && "range_kind" in rec) out.push(value as MoneyRange);
    for (const v of Object.values(rec)) moneyRanges(v, out);
  }
  return out;
}

const isWholeUsd = (n: number | null) => n === null || (Number.isFinite(n) && Number.isInteger(n));

function allIds(view: OwnerCaseView): string[] {
  const ids: string[] = [view.case.case_id];
  ids.push(...view.evidence.map((e) => e.evidence_id));
  ids.push(...view.evidence.flatMap((e) => (e.media ? [e.media.media_id] : [])));
  ids.push(...view.observations.map((o) => o.observation_id));
  for (const a of view.assessments) ids.push(a.assessment_id, a.run_id);
  ids.push(...view.tasks.map((t) => t.task_id));
  ids.push(...view.reports.map((r) => r.report_id));
  ids.push(...view.reports.flatMap((r) => r.media.map((m) => m.media_id)));
  ids.push(...view.support_requests.map((s) => s.request_id));
  ids.push(...view.notices.map((n) => n.notice_id));
  ids.push(...view.household_labels.map((h) => h.household_id));
  return ids;
}

function duplicates(list: (string | number)[]): (string | number)[] {
  const seen = new Set<string | number>();
  const dup = new Set<string | number>();
  for (const x of list) (seen.has(x) ? dup : seen).add(x);
  return [...dup];
}

test("FIXTURE_LABEL is the agreed text and every case reads as a fixture", () => {
  assertEqual(FIXTURE_LABEL, "UI fixture — not a property assessment");
  const cases = fixtureCases();
  assertEqual(cases.length, 3, "three fixture cases");
  for (const c of cases) {
    assertIncludes(c.property_name, "(fixture)", `${c.case_id} property_name`);
    assertIncludes(c.address, "(fixture)", `${c.case_id} address`);
    assert(c.case_id.startsWith("fx-"), `${c.case_id} id is synthetic`);
    assert(c.property_ref.id.startsWith("fx-"), `${c.case_id} property_ref is synthetic`);
  }
});

test("fixture cases cover every CaseMode once and match their snapshots", () => {
  const cases = fixtureCases();
  assertEqual(cases.map((c) => c.mode).sort(), ["historical_replay", "observed_recovery", "scenario_exercise"]);
  for (const c of cases) {
    const view = fixtureSnapshot("full", c.case_id);
    assertEqual(view.case, c, `${c.case_id} summary equals full snapshot summary`);
  }
});

test("unknown case_id throws instead of silently falling back", () => {
  let threw = false;
  try {
    fixtureSnapshot("full", "real-case-123");
  } catch {
    threw = true;
  }
  assert(threw, "fixtureSnapshot should throw for an unknown case_id");
});

test("MoneyRange invariants hold everywhere (both-null or finite low <= high, whole USD)", () => {
  let checked = 0;
  eachSnapshot((view, where) => {
    for (const r of moneyRanges(view)) {
      checked++;
      const label = `${where} ${r.method}`;
      assertEqual(r.currency, "USD", label);
      assert((r.low === null) === (r.high === null), `${label}: low/high must both be null or both set`);
      assert(isWholeUsd(r.low) && isWholeUsd(r.high) && isWholeUsd(r.point), `${label}: amounts must be whole finite USD`);
      if (r.low !== null && r.high !== null) {
        assert(r.low <= r.high, `${label}: low ${r.low} > high ${r.high}`);
        if (r.point !== null) assert(r.low <= r.point && r.point <= r.high, `${label}: point outside range`);
      }
      if (r.low === null && r.point === null) {
        assert(typeof r.unavailable_reason === "string" && r.unavailable_reason.length > 0, `${label}: null amount needs unavailable_reason`);
      }
    }
    for (const a of view.assessments) {
      for (const c of a.valuation?.comparables ?? []) assert(isWholeUsd(c.price_usd), `${where} ${c.comp_id} price`);
      for (const l of a.valuation?.repair_lines ?? []) {
        assert(isWholeUsd(l.rate_low_usd) && isWholeUsd(l.rate_high_usd), `${where} ${l.line_id} rates`);
        assert((l.rate_low_usd === null) === (l.rate_high_usd === null), `${where} ${l.line_id} rate pair`);
      }
    }
  });
  assert(checked > 0, "found MoneyRanges to check");
});

test("IDs are unique and obviously synthetic", () => {
  eachSnapshot((view, where) => {
    const ids = allIds(view);
    assertEqual(duplicates(ids), [], `${where} duplicate IDs`);
    for (const id of ids) assert(id.startsWith("fx-"), `${where}: ID "${id}" is not obviously synthetic`);
    assertEqual(duplicates(view.events.map((e) => e.event_id)), [], `${where} duplicate event IDs`);
    assertEqual(duplicates(view.evidence.map((e) => e.source_id)), [], `${where} duplicate evidence source_ids`);
    // Comparables, repair lines and assumptions may recur across assessment versions; unique within each.
    for (const a of view.assessments) {
      if (!a.valuation) continue;
      const inner = [
        ...a.valuation.comparables.map((c) => c.comp_id),
        ...a.valuation.repair_lines.map((l) => l.line_id),
        ...a.valuation.assumptions.map((x) => x.assumption_id),
      ];
      assertEqual(duplicates(inner), [], `${where} ${a.assessment_id} duplicate valuation IDs`);
      for (const id of inner) assert(id.startsWith("fx-"), `${where}: ID "${id}" is not obviously synthetic`);
    }
  });
});

test("every referenced evidence, observation, assessment, household and source exists", () => {
  eachSnapshot((view, where) => {
    const evidence = new Set(view.evidence.map((e) => e.evidence_id));
    const sources = new Set(view.evidence.map((e) => e.source_id));
    const observations = new Set(view.observations.map((o) => o.observation_id));
    const assessments = new Set(view.assessments.map((a) => a.assessment_id));
    const households = new Set(view.household_labels.map((h) => h.household_id));
    const known = new Set(allIds(view));
    const ev = (id: string, ctx: string) => assert(evidence.has(id), `${where} ${ctx}: evidence ${id} missing`);
    const src = (id: string, ctx: string) => assert(sources.has(id), `${where} ${ctx}: source ${id} missing`);

    for (const o of view.observations) o.evidence_ids.forEach((id) => ev(id, o.observation_id));
    for (const t of view.tasks) {
      t.evidence_ids.forEach((id) => ev(id, t.task_id));
      t.completion_evidence_ids.forEach((id) => ev(id, `${t.task_id} completion`));
      t.household_ids.forEach((id) => assert(households.has(id), `${where} ${t.task_id}: household ${id} missing`));
    }
    for (const a of view.assessments) {
      a.observation_ids.forEach((id) => assert(observations.has(id), `${where} ${a.assessment_id}: observation ${id} missing`));
      for (const r of moneyRanges(a)) r.source_ids.forEach((id) => src(id, `${a.assessment_id} ${r.method}`));
      for (const c of a.valuation?.comparables ?? []) c.source_ids.forEach((id) => src(id, c.comp_id));
      for (const l of a.valuation?.repair_lines ?? []) l.source_ids.forEach((id) => src(id, l.line_id));
      for (const x of a.valuation?.assumptions ?? []) x.source_ids.forEach((id) => src(id, x.assumption_id));
    }
    for (const n of view.notices) n.source_ids.forEach((id) => src(id, n.notice_id));
    for (const r of view.reports) assert(households.has(r.household_id), `${where} ${r.report_id}: household missing`);
    for (const s of view.support_requests) assert(households.has(s.household_id), `${where} ${s.request_id}: household missing`);
    if (view.current_assessment_id !== null) {
      assert(assessments.has(view.current_assessment_id), `${where}: current_assessment_id ${view.current_assessment_id} missing`);
    }
    for (const e of view.events) {
      assertEqual(e.case_id, view.case.case_id, `${where} event ${e.event_id} case_id`);
      if (e.entity_id !== null) assert(known.has(e.entity_id), `${where} event ${e.event_id}: entity ${e.entity_id} missing`);
    }
  });
});

test("events increase in case_revision, end at the case revisions, and carry public summaries", () => {
  eachSnapshot((view, where) => {
    const ev = view.events;
    for (let i = 1; i < ev.length; i++) {
      assert(ev[i].case_revision > ev[i - 1].case_revision, `${where}: case_revision must increase`);
      assert(ev[i].analysis_revision >= ev[i - 1].analysis_revision, `${where}: analysis_revision must not decrease`);
      assert(ev[i].event_id > ev[i - 1].event_id, `${where}: event_id must increase`);
      assert(ev[i].at > ev[i - 1].at, `${where}: event time must increase`);
    }
    if (ev.length > 0) {
      const last = ev[ev.length - 1];
      assertEqual(last.case_revision, view.case.case_revision, `${where} last case_revision`);
      assertEqual(last.analysis_revision, view.case.analysis_revision, `${where} last analysis_revision`);
      assertEqual(view.event_cursor, last.event_id, `${where} event_cursor`);
      assert(ev.some((e) => e.public_summary !== null), `${where}: some public_summary`);
    }
    const pendingReports = view.reports.filter((r) => r.status === "reported" || r.status === "under_review").length;
    const pendingTasks = view.tasks.filter((t) => t.status !== "verified" && t.status !== "cancelled").length;
    assertEqual(view.case.pending_reports, pendingReports, `${where} pending_reports`);
    assertEqual(view.case.pending_tasks, pendingTasks, `${where} pending_tasks`);
  });
});

test("stale variant: current assessment is stale with base_analysis_revision < analysis_revision and a newer report", () => {
  for (const case_id of CASE_IDS) {
    const view = fixtureSnapshot("stale", case_id);
    const current = view.assessments.find((a) => a.assessment_id === view.current_assessment_id);
    assert(current, "stale variant has a current assessment");
    assertEqual(current.status, "stale");
    assert(current.base_analysis_revision < view.case.analysis_revision, "base_analysis_revision < analysis_revision");
    assert(
      view.reports.some((r) => r.received_at > current.created_at),
      "a resident report arrived after the stale assessment was created",
    );
    const full = fixtureSnapshot("full", case_id);
    const fullCurrent = full.assessments.find((a) => a.assessment_id === full.current_assessment_id);
    assertEqual(fullCurrent?.base_analysis_revision, full.case.analysis_revision, "full variant is not stale");
  }
});

test("insufficient variant: every amount is null and explained", () => {
  for (const case_id of CASE_IDS) {
    const view = fixtureSnapshot("insufficient", case_id);
    const current = view.assessments.find((a) => a.assessment_id === view.current_assessment_id);
    assertEqual(current?.valuation?.basis, "insufficient_evidence", "current basis");
    for (const a of view.assessments) {
      if (!a.valuation) continue;
      assertEqual(a.valuation.basis, "insufficient_evidence", `${a.assessment_id} basis`);
      const ranges = moneyRanges(a.valuation);
      assert(ranges.length >= 5, "has the five headline ranges");
      for (const r of ranges) {
        assertEqual([r.low, r.high, r.point], [null, null, null], `${a.assessment_id} ${r.method}`);
        assert(!!r.unavailable_reason, `${a.assessment_id} ${r.method} has unavailable_reason`);
      }
      for (const c of a.valuation.comparables) assertEqual(c.price_usd, null, `${c.comp_id} price`);
      for (const l of a.valuation.repair_lines) assertEqual([l.rate_low_usd, l.rate_high_usd], [null, null], `${l.line_id} rates`);
    }
  }
});

test("conditional variant: cost to cure with current_condition withheld", () => {
  const view = fixtureSnapshot("conditional");
  const v = view.assessments.find((a) => a.assessment_id === view.current_assessment_id)?.valuation;
  assert(v, "conditional variant has a current valuation");
  assertEqual(v.basis, "conditional");
  assertEqual([v.current_condition.low, v.current_condition.high, v.current_condition.point], [null, null, null]);
  assert(!!v.current_condition.unavailable_reason, "current_condition.unavailable_reason");
  assert(v.repair_cost.low !== null, "repair cost is still estimated");
});

test("full variant: market-supported valuation with comparables, history and every range_kind", () => {
  const view = fixtureSnapshot("full");
  const current = view.assessments.find((a) => a.assessment_id === view.current_assessment_id);
  assert(current?.valuation, "full has a current valuation");
  const v = current.valuation;
  assertEqual(current.status, "published");
  assertEqual(v.basis, "market_supported");
  assert(v.comparables.some((c) => c.included) && v.comparables.some((c) => !c.included), "included and excluded comps");
  assert(v.comparables.some((c) => c.allocated && !c.included), "an excluded allocated portfolio share");
  assert(v.comparables.some((c) => c.price_usd === null), "a comp with price null");
  assertEqual(new Set(v.comparables.map((c) => c.date_basis)).size, 3, "date_basis variety");
  assert(v.repair_lines.length > 0 && v.assumptions.length > 0 && v.limitations.length > 0, "lines/assumptions/limitations");
  const older = view.assessments.filter((a) => a.assessment_id !== view.current_assessment_id && a.status === "published");
  assert(older.length > 0, "an older superseded published assessment");
  assert(older.every((a) => (a.published_at ?? "") < (current.published_at ?? "")), "older published before current");
});

test("range kinds: all four used, calibrated_confidence exactly once per case across variants", () => {
  for (const case_id of CASE_IDS) {
    const all = VARIANTS.flatMap((variant) => moneyRanges(fixtureSnapshot(variant, case_id).assessments));
    const kinds = new Set(all.map((r) => r.range_kind));
    for (const k of ["source_range", "scenario", "comparable_dispersion", "calibrated_confidence"] as const) {
      assert(kinds.has(k), `${case_id}: range_kind ${k} is used`);
    }
    assertEqual(all.filter((r) => r.range_kind === "calibrated_confidence").length, 1, `${case_id} calibrated count`);
  }
});

test("coverage: evidence kinds, aerial before/after, bindings, statuses and bases", () => {
  const view = fixtureSnapshot("full");
  const kinds: Evidence["kind"][] = ["costar_record", "vexcel_image", "matterport_view", "resident_photo", "inspection", "cost_source", "official_notice"];
  for (const k of kinds) assert(view.evidence.some((e) => e.kind === k), `evidence kind ${k}`);

  const aerials = view.evidence.filter((e) => e.kind === "vexcel_image");
  const incident = view.case.incident_at.slice(0, 10);
  assert(aerials.some((e) => e.media && e.captured_at !== null && e.captured_at.slice(0, 10) < incident), "aerial before incident with media");
  assert(aerials.some((e) => e.media && e.captured_at !== null && e.captured_at.slice(0, 10) > incident), "aerial after incident with media");
  assert(aerials.some((e) => e.media === null), "aerial with media null");

  const bindings = new Set(view.evidence.filter((e) => e.kind === "matterport_view").map((e) => e.location?.binding));
  assert(bindings.has("representative_layout") && bindings.has("unmapped") && bindings.size >= 3, "matterport bindings vary");

  for (const s of ["reported", "under_review", "verified", "dismissed"] as const) {
    assert(view.observations.some((o) => o.status === s), `observation status ${s}`);
  }
  for (const b of ["reported", "observed", "inferred"] as const) {
    assert(view.observations.some((o) => o.basis === b), `observation basis ${b}`);
  }
  assert(view.observations.filter((o) => o.basis === "inferred").every((o) => o.status !== "verified"), "inferred is never verified");

  assert(view.reports.some((r) => r.media.length > 0) && view.reports.some((r) => r.media.length === 0), "reports with and without media");
  assert(view.reports.some((r) => r.location === null && !!r.location_description), "report with only a location description");
  assert(view.support_requests.length > 0 && view.notices.length > 0 && view.household_labels.length > 0, "support/notices/households");
});

test("coverage: every TaskStatus, changed scope, unconfirmed proposal", () => {
  const tasks = fixtureSnapshot("full").tasks;
  const statuses: TaskStatus[] = ["proposed", "approved", "accepted", "in_progress", "completion_submitted", "verified", "cancelled"];
  for (const s of statuses) assert(tasks.some((t) => t.status === s), `task status ${s}`);
  assert(tasks.some((t) => t.superseded_scope !== null && t.superseded_scope !== t.scope), "a task with changed scope");
  assert(tasks.some((t) => t.status === "proposed" && t.confirmed_schedule === null), "proposed task with no schedule");
  assert(tasks.filter((t) => t.status === "proposed").every((t) => t.confirmation_source === null), "proposed tasks have no confirmation");
});

test("SourceDate values mix date-only, month-only and timestamps with timezone", () => {
  const view = fixtureSnapshot("full");
  const dates = view.evidence.flatMap((e) => [e.captured_at, e.effective_at, e.available_at, e.model_created_at]).filter((d): d is string => d !== null);
  assert(dates.some((d) => /^\d{4}-\d{2}-\d{2}$/.test(d)), "date-only");
  assert(dates.some((d) => /^\d{4}-\d{2}$/.test(d)), "month-only");
  assert(dates.some((d) => /T.*(Z|[+-]\d{2}:\d{2})$/.test(d)), "timestamp with timezone");
  const stamps = [...view.evidence.map((e) => e.received_at), ...view.tasks.map((t) => t.updated_at), ...view.events.map((e) => e.at)];
  for (const s of stamps) assert(/T.*(Z|[+-]\d{2}:\d{2})$/.test(s), `timestamp ${s} has a timezone`);
});

test("media are small inline SVGs stamped SYNTHETIC FIXTURE", () => {
  const view = fixtureSnapshot("stale");
  const media = [...view.evidence.flatMap((e) => (e.media ? [e.media] : [])), ...view.reports.flatMap((r) => r.media)];
  assert(media.length >= 5, "several media items");
  for (const m of media) {
    assert(m.url.startsWith("data:image/svg+xml,"), `${m.media_id} is an inline SVG`);
    assert(m.url.length <= 1600, `${m.media_id} is ${m.url.length} chars`);
    assertIncludes(decodeURIComponent(m.url), "SYNTHETIC FIXTURE", m.media_id);
    assertEqual(m.mime_type, "image/svg+xml", m.media_id);
  }
  const before = view.evidence.find((e) => e.evidence_id === "fx-ev-aerial-before")?.media?.url;
  const after = view.evidence.find((e) => e.evidence_id === "fx-ev-aerial-after")?.media?.url;
  assert(before && after && before !== after, "before and after images differ");
});

test("empty variant has no evidence, observations, tasks, assessments or events", () => {
  for (const case_id of CASE_IDS) {
    const view = fixtureSnapshot("empty", case_id);
    assertEqual(
      [view.evidence.length, view.observations.length, view.tasks.length, view.assessments.length, view.events.length],
      [0, 0, 0, 0, 0],
    );
    assertEqual(view.current_assessment_id, null);
    assertEqual(view.event_cursor, 0);
  }
});

test("fixtureSnapshot and fixtureCases return fresh deep copies", () => {
  for (const variant of VARIANTS) {
    const a = fixtureSnapshot(variant);
    const b = fixtureSnapshot(variant);
    assert(a !== b && a.case !== b.case, `${variant}: distinct objects`);
    assertEqual(a, b, `${variant}: equal content`);
    a.case.property_name = "mutated";
    a.case.case_revision = -1;
    a.evidence.length = 0;
    a.events.push({ ...b.events[0], event_id: -1 } as OwnerCaseView["events"][number]);
    a.assessments.forEach((x) => {
      x.status = "failed";
      if (x.valuation) x.valuation.benchmark.low = -1;
    });
    assertEqual(fixtureSnapshot(variant), b, `${variant}: mutation did not leak`);
  }
  const one = fixtureSnapshot("full");
  const loc1 = one.tasks[0].location;
  const loc2 = one.observations.find((o) => o.location?.location_id === loc1?.location_id)?.location;
  assert(loc1 && loc2 && loc1 !== loc2, "same location in different records is not a shared object");

  const c1 = fixtureCases();
  c1[0].property_name = "mutated";
  c1.reverse();
  assertEqual(fixtureCases()[0].property_name, "Sample Apartments A (fixture)", "fixtureCases is fresh");
});
