import type { MoneyRange, ObservationStatus, OwnerCaseView, TaskStatus } from "../../../recovery/contracts";
import { Button, ChangedBanner, InlineError, RangeRow, StatusMark } from "../../recovery-ui";
import { COMMAND_FALLBACK_ERROR, commandErrorMessage } from "../commands";
import { compareSourceDates, describeMoneyRange, formatSourceDate, formatTimestamp, rangeKindLabel } from "../format";
import {
  OBSERVATION_BASIS_LABEL,
  OBSERVATION_NEXT,
  TASK_NEXT,
  TASK_STATUS_LABEL,
  assessmentHistory,
  currentAssessment,
  isCurrentAssessmentStale,
  observationTransitionNeeds,
  taskTransitionNeeds,
} from "../model";
import { fixtureSnapshot } from "../fixtures/preview-fixture";
import { assert, assertEqual, assertIncludes, assertNotIncludes, render, test } from "./harness";

const range = (low: number | null, high: number | null, point: number | null, extra: Partial<MoneyRange> = {}): MoneyRange => ({
  currency: "USD",
  low,
  high,
  point,
  basis: "market_supported",
  range_kind: "source_range",
  method: "test",
  source_ids: [],
  unavailable_reason: null,
  ...extra,
});

/* ------------------------------------------------------------------ dates */

test("foundation/dates: test runner is in a timezone where a UTC-midnight parse would shift the day", () => {
  // Guards the next test: if this fails, the day-shift test proves nothing.
  assert(new Date(Date.UTC(2024, 6, 8)).getDate() !== 8, "runner TZ should be west of UTC (run.mjs sets America/Los_Angeles)");
});

test("foundation/dates: formatSourceDate keeps each precision with no day shift", () => {
  assertEqual(formatSourceDate("2024-07-08"), "8 Jul 2024");
  assertEqual(formatSourceDate("2024-01-01"), "1 Jan 2024", "new-year date-only stays in the same year");
  assertEqual(formatSourceDate("2024-07"), "Jul 2024");
  assertEqual(formatSourceDate("2024"), "2024");
  assertEqual(formatSourceDate(null), "Date unknown");
  assertEqual(formatSourceDate("2024-07-11T15:42:00Z"), "11 Jul 2024, 15:42 UTC");
  assertEqual(formatSourceDate("2024-07-08T23:30:00-04:00"), "9 Jul 2024, 03:30 UTC", "offset timestamps are shown in UTC");
});

test("foundation/dates: formatTimestamp null and date-only, compareSourceDates puts null last", () => {
  assertEqual(formatTimestamp(null), "Time unknown");
  assertEqual(formatTimestamp("2024-07-08"), "8 Jul 2024", "date-only is never shown as midnight UTC");
  assertEqual(["2024-07-11", null, "2024-05-18"].sort(compareSourceDates), ["2024-05-18", "2024-07-11", null]);
});

/* ------------------------------------------------------------------ money */

test("foundation/money: describeMoneyRange states", () => {
  const unavailable = describeMoneyRange(range(null, null, null, { unavailable_reason: "No comps" }));
  assertEqual(unavailable, { state: "unavailable", text: "Not enough evidence", detail: "No comps" });
  assertEqual(describeMoneyRange(range(null, null, 1_200)).state, "point");
  assertEqual(describeMoneyRange(range(1_000, 2_000, null)).state, "range");
  const withPoint = describeMoneyRange(range(1_000, 2_000, 1_500));
  assertEqual(withPoint.state, "range_with_point");
  assertIncludes(withPoint.text, "$1,500");
  assertIncludes(withPoint.text, "$1,000");
  assertIncludes(withPoint.text, "$2,000");
});

test("foundation/money: null or invalid input never yields $0", () => {
  const cases: [string, MoneyRange][] = [
    ["all null", range(null, null, null)],
    ["low only", range(0, null, null)],
    ["high only", range(null, 0, null)],
    ["low > high", range(10, 0, null)],
    ["NaN", range(Number.NaN, 5, null)],
    ["Infinity", range(0, Number.POSITIVE_INFINITY, null)],
  ];
  for (const [name, r] of cases) {
    const d = describeMoneyRange(r);
    assert(d.state === "unavailable" || d.state === "invalid", `${name}: state ${d.state}`);
    assertNotIncludes(d.text, "$0", name);
    assertNotIncludes(d.text, "$", `${name} shows no dollar figure`);
  }
  assertEqual(describeMoneyRange(range(0, null, null)).text, "Range unavailable (inconsistent data)");
});

test("foundation/money: only calibrated_confidence is called a confidence interval", () => {
  const kinds: MoneyRange["range_kind"][] = ["source_range", "scenario", "comparable_dispersion", "calibrated_confidence"];
  for (const k of kinds) {
    const label = rangeKindLabel(k).toLowerCase();
    if (k === "calibrated_confidence") {
      assertIncludes(label, "confidence interval", k);
      assertNotIncludes(label, "not", k);
    } else {
      assert(!label.includes("confidence interval") || label.includes("not a confidence interval"), `${k}: "${label}" claims a confidence interval`);
    }
  }
  assertIncludes(rangeKindLabel("comparable_dispersion"), "not a confidence interval");
  assertEqual(rangeKindLabel("scenario"), "scenario range");
  assertEqual(rangeKindLabel("source_range"), "range given by the source");
});

/* ------------------------------------------------------------ transitions */

test("foundation/transitions: TASK_NEXT matches the contract exactly", () => {
  const expected: Record<TaskStatus, TaskStatus[]> = {
    proposed: ["approved", "cancelled"],
    approved: ["accepted", "cancelled"],
    accepted: ["in_progress", "cancelled"],
    in_progress: ["completion_submitted", "cancelled"],
    completion_submitted: ["verified", "cancelled"],
    verified: [],
    cancelled: [],
  };
  assertEqual(TASK_NEXT, expected);
});

test("foundation/transitions: taskTransitionNeeds", () => {
  assertEqual(taskTransitionNeeds("accepted"), { note: "optional", confirmation_source: true, evidence: false });
  assertEqual(taskTransitionNeeds("completion_submitted"), { note: "optional", confirmation_source: false, evidence: true });
  assertEqual(taskTransitionNeeds("verified").note, "required");
  assertEqual(taskTransitionNeeds("cancelled").note, "required");
  for (const t of ["approved", "in_progress"] as const) {
    assertEqual(taskTransitionNeeds(t), { note: "optional", confirmation_source: false, evidence: false }, t);
  }
});

test("foundation/transitions: OBSERVATION_NEXT and observationTransitionNeeds", () => {
  const expected: Record<ObservationStatus, ObservationStatus[]> = {
    reported: ["under_review", "verified", "dismissed"],
    under_review: ["verified", "dismissed"],
    verified: [],
    dismissed: [],
  };
  assertEqual(OBSERVATION_NEXT, expected);
  const v = observationTransitionNeeds("verified");
  assertEqual(v.note, "required");
  assert(v.evidence && v.min_evidence >= 1, "verify needs at least one evidence id");
  const d = observationTransitionNeeds("dismissed");
  assertEqual(d.note, "required");
  assertEqual(d.evidence, false);
  assertEqual(observationTransitionNeeds("under_review").note, "optional");
});

test("foundation/labels: proposed and inferred labels say plainly what they are not", () => {
  assertIncludes(TASK_STATUS_LABEL.proposed.toLowerCase(), "not approved");
  assertIncludes(TASK_STATUS_LABEL.approved.toLowerCase(), "not yet accepted");
  assertIncludes(OBSERVATION_BASIS_LABEL.inferred.toLowerCase(), "not verified");
});

/* -------------------------------------------------------------- selectors */

test("foundation/selectors: isCurrentAssessmentStale on fixtures", () => {
  assertEqual(isCurrentAssessmentStale(fixtureSnapshot("stale")), true, "stale");
  assertEqual(isCurrentAssessmentStale(fixtureSnapshot("full")), false, "full");
  assertEqual(isCurrentAssessmentStale(fixtureSnapshot("empty")), false, "empty has no current");

  // Revision-based staleness even when the status still says published.
  const v: OwnerCaseView = fixtureSnapshot("full");
  v.case.analysis_revision += 1;
  assertEqual(isCurrentAssessmentStale(v), true, "published but built on an older analysis revision");
});

test("foundation/selectors: currentAssessment and assessmentHistory ordering", () => {
  const v = fixtureSnapshot("full");
  assertEqual(currentAssessment(v)?.assessment_id, "fx-asmt-current");
  const history = assessmentHistory(v).map((a) => a.assessment_id);
  assertEqual(history, ["fx-asmt-failed", "fx-asmt-previous"], "newest first, current excluded");
  // Order must come from created_at, not array order.
  v.assessments.reverse();
  assertEqual(assessmentHistory(v).map((a) => a.assessment_id), history, "independent of array order");
  assertEqual(currentAssessment(fixtureSnapshot("empty")), null);
  const dangling = fixtureSnapshot("full");
  dangling.current_assessment_id = "fx-asmt-missing";
  assertEqual(currentAssessment(dangling), null, "dangling current id gives null");
});

/* ----------------------------------------------------------------- errors */

test("foundation/errors: commandErrorMessage", () => {
  assertEqual(commandErrorMessage(new Error("Boom")), "Boom");
  assertEqual(
    commandErrorMessage({ error: { code: "revision_conflict", message: "This case changed. Reload before applying this edit.", retryable: true } }),
    "This case changed. Reload before applying this edit.",
  );
  assertEqual(commandErrorMessage("Network down"), "Network down");
  assertEqual(commandErrorMessage(undefined), "The server did not confirm this change.");
  assertEqual(commandErrorMessage(42), COMMAND_FALLBACK_ERROR);
  assertEqual(commandErrorMessage({}), COMMAND_FALLBACK_ERROR);
  assertEqual(commandErrorMessage(new Error("")), COMMAND_FALLBACK_ERROR, "empty message falls back");
});

/* ------------------------------------------------------------- primitives */

test("foundation/primitives: unavailable RangeRow is hatched with no dot and shows its readout", () => {
  const html = render(<RangeRow label="Current" readout="Not enough evidence" low={null} high={null} point={null} domain={[0, 100]} unavailable />);
  assertIncludes(html, "r-range-hatch");
  assertNotIncludes(html, "r-range-dot");
  assertNotIncludes(html, "r-range-span");
  assertIncludes(html, "Not enough evidence");
  assertNotIncludes(html, "$0");

  const ok = render(<RangeRow label="Benchmark" readout="$50" low={20} high={80} point={50} domain={[0, 100]} />);
  assertIncludes(ok, "r-range-dot");
  assertNotIncludes(ok, "r-range-hatch");

  const inconsistent = render(<RangeRow label="Bad" readout="Range unavailable" low={80} high={20} point={null} domain={[0, 100]} />);
  assertIncludes(inconsistent, "r-range-hatch", "low > high with no point is drawn as unavailable");
  assertNotIncludes(inconsistent, "r-range-dot");
});

test("foundation/primitives: StatusMark always renders its text label", () => {
  for (const shape of ["filled", "hollow", "ring", "hatched"] as const) {
    const html = render(<StatusMark tone="verified" shape={shape} label={`Label ${shape}`} />);
    assertIncludes(html, `Label ${shape}`, shape);
  }
});

test("foundation/primitives: Button pending is busy and disabled; ChangedBanner and InlineError roles", () => {
  const pending = render(<Button pending>Publish</Button>);
  assertIncludes(pending, 'aria-busy="true"');
  assertIncludes(pending, "disabled");
  assertIncludes(pending, "Saving…");
  assertNotIncludes(pending, "Publish", "pending label replaces the action text");
  const idle = render(<Button>Publish</Button>);
  assertNotIncludes(idle, "aria-busy");
  assertIncludes(idle, 'type="button"');

  const banner = render(<ChangedBanner title="Scope changed" previous="Old scope" />);
  assertIncludes(banner, 'role="status"');
  assertIncludes(banner, "<s>Old scope</s>");

  const err = render(<InlineError message="Server said no" onRetry={() => undefined} />);
  assertIncludes(err, 'role="alert"');
  assertIncludes(err, "Server said no");
  assertIncludes(err, "Retry");
});
