import assert from "node:assert/strict";
import test from "node:test";
import { loadTs } from "./load.mjs";

const { createEventGate, isNewerSnapshot } = await loadTs("lib/events.ts");
const ev = (event_id, type = "task.updated") => ({
  event_id, case_id: "c", case_revision: event_id, analysis_revision: 1, type, at: "2026-11-14T00:00:00Z", entity_id: null, public_summary: null,
});

test("duplicate event IDs are acted on once", () => {
  const gate = createEventGate(42);
  assert.equal(gate.accept(ev(43)), "refresh");
  assert.equal(gate.accept(ev(43)), "ignore");
  assert.equal(gate.cursor(), 43);
});

test("events at or below the starting cursor are ignored", () => {
  const gate = createEventGate(42);
  assert.equal(gate.accept(ev(42)), "ignore");
  assert.equal(gate.accept(ev(7)), "ignore");
  assert.equal(gate.cursor(), 42);
});

test("session.revoked expires even when old", () => {
  const gate = createEventGate(42);
  assert.equal(gate.accept(ev(5, "session.revoked")), "expire");
  assert.equal(createEventGate(42).accept(ev(50, "session.revoked")), "expire");
});

test("unknown types are ignored but still advance the cursor", () => {
  const gate = createEventGate(42);
  assert.equal(gate.accept(ev(43, "owner.secret_thing")), "ignore");
  assert.equal(gate.cursor(), 43);
  assert.equal(gate.accept(ev(43, "task.updated")), "ignore");
  assert.equal(gate.accept(ev(44, "notice.published")), "refresh");
});

test("non-finite event IDs are ignored", () => {
  const gate = createEventGate(0);
  assert.equal(gate.accept(ev(Number.NaN)), "ignore");
  assert.equal(gate.cursor(), 0);
});

test("advance() from a snapshot moves the cursor forward only", () => {
  const gate = createEventGate(42);
  gate.advance(50);
  assert.equal(gate.cursor(), 50);
  assert.equal(gate.accept(ev(49)), "ignore");
  assert.equal(gate.accept(ev(50)), "ignore");
  assert.equal(gate.accept(ev(51)), "refresh");
  gate.advance(10);
  assert.equal(gate.cursor(), 51);
});

test("isNewerSnapshot: older never replaces newer", () => {
  const cur = { case_revision: 8, event_cursor: 44 };
  assert.equal(isNewerSnapshot(null, cur), true);
  assert.equal(isNewerSnapshot(cur, { case_revision: 9, event_cursor: 44 }), true);
  assert.equal(isNewerSnapshot(cur, { case_revision: 9, event_cursor: 40 }), true, "higher revision wins");
  assert.equal(isNewerSnapshot(cur, { case_revision: 7, event_cursor: 99 }), false, "lower revision loses");
  assert.equal(isNewerSnapshot(cur, { case_revision: 8, event_cursor: 45 }), true);
  assert.equal(isNewerSnapshot(cur, { case_revision: 8, event_cursor: 43 }), false);
});
