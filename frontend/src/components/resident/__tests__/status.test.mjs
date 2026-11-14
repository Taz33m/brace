import assert from "node:assert/strict";
import test from "node:test";
import { loadTs } from "./load.mjs";

const s = await loadTs("lib/status.ts");
const TASK_STATUSES = ["proposed", "approved", "accepted", "in_progress", "completion_submitted", "verified", "cancelled"];
const TONES = new Set(["neutral", "info", "ok", "warn", "bad"]);

test("every task status has resident copy", () => {
  for (const status of TASK_STATUSES) {
    const copy = s.taskStatus({ status, confirmed_schedule: null });
    assert.ok(copy && copy.label.trim(), status);
    assert.ok(TONES.has(copy.tone), status);
  }
});

test("'Scheduled' only for accepted with a confirmed schedule", () => {
  const when = "2026-11-15T15:00:00Z";
  assert.equal(s.taskStatus({ status: "accepted", confirmed_schedule: when }).label, "Scheduled");
  assert.notEqual(s.taskStatus({ status: "accepted", confirmed_schedule: null }).label, "Scheduled");
  for (const status of TASK_STATUSES.filter((x) => x !== "accepted")) {
    for (const confirmed_schedule of [null, when]) {
      assert.doesNotMatch(s.taskStatus({ status, confirmed_schedule }).label, /schedul/i, `${status} ${confirmed_schedule}`);
    }
  }
});

test("a proposed task never reads as booked or scheduled", () => {
  for (const confirmed_schedule of [null, "2026-11-15T15:00:00Z"]) {
    assert.doesNotMatch(s.taskStatus({ status: "proposed", confirmed_schedule }).label, /book|schedul/i);
  }
  // Approved may only mention booking to deny it.
  const approved = s.taskStatus({ status: "approved", confirmed_schedule: null }).label;
  if (/book/i.test(approved)) assert.match(approved, /not booked/i);
});

test("taskStepStates walks the timeline", () => {
  const n = s.TASK_STEPS.length;
  assert.equal(n, 6);
  assert.deepEqual(s.taskStepStates("proposed"), ["current", ...Array(n - 1).fill("todo")]);
  assert.deepEqual(s.taskStepStates("in_progress"), ["done", "done", "done", "current", "todo", "todo"]);
  assert.deepEqual(s.taskStepStates("verified"), Array(n).fill("done"));
  assert.deepEqual(s.taskStepStates("cancelled"), Array(n).fill("todo"));
  assert.ok(!s.TASK_STEPS.some((step) => step.status === "cancelled"));
});

test("checked repair carries the not-occupancy-clearance line", () => {
  assert.equal(typeof s.NOT_OCCUPANCY_CLEARANCE, "string");
  assert.match(s.NOT_OCCUPANCY_CLEARANCE, /safe/i);
  assert.match(s.NOT_OCCUPANCY_CLEARANCE, /move back/i);
});

test("report and support labels cover every contract value", () => {
  const report = ["water", "roof", "smoke_or_fire", "power_or_access", "other"];
  const support = ["housing", "access", "communication", "other"];
  assert.deepEqual(s.REPORT_CATEGORIES.map((c) => c.value), report);
  assert.deepEqual(s.SUPPORT_CATEGORIES.map((c) => c.value), support);
  for (const c of report) assert.notEqual(s.categoryLabel(c), "Report", c);
  for (const c of support) assert.notEqual(s.supportLabel(c), "Support request", c);
  assert.equal(new Set(report.map(s.categoryLabel)).size, report.length);
  assert.equal(new Set(support.map(s.supportLabel)).size, support.length);
  for (const st of ["reported", "under_review", "verified", "dismissed"]) assert.ok(s.reportStatus(st).label, st);
  for (const st of ["received", "under_review", "responded", "closed"]) assert.ok(s.supportStatus(st).label, st);
});
