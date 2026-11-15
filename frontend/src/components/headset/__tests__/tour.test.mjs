import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import ts from "typescript";

// tour.ts has no runtime imports, so it transpiles and loads on its own (same pattern as tests/recovery-*.test.mjs).
const source = await readFile(new URL("../lib/tour.ts", import.meta.url), "utf8");
const { outputText } = ts.transpileModule(source, { compilerOptions: { target: ts.ScriptTarget.ES2020, module: ts.ModuleKind.ESNext } });
const { buildTour, circularMeanDeg, direction, range, label, scannedUnit } = await import(`data:text/javascript;base64,${Buffer.from(outputText).toString("base64")}`);

const total = (low, high, lines = 1, priced = 1) => ({ low, high, lines, lines_priced: priced });
const item = (what, sweep, yaw, pitch = 0, extra = {}) => ({ what, quantity: 1, unit: "each", low: 100, high: 200, seen: null, at: { sweep_id: sweep, yaw_deg: yaw, pitch_deg: pitch, heading_deg: 30 }, ...extra });
const schedule = (rooms) => ({
  property: { id: 1, name: "Test Apartments" },
  home: { name: "2BR", total: total(1000, 2000, 10, 8), multiplied_by: 12 },
  buildings: [{ units: [] }, { units: [{ scan_id: "SCAN", name: "2BR", rooms, total: total(1000, 2000) }] }],
});

test("lead rooms come first, then rooms by how many tags they have", () => {
  const s = schedule([
    { name: "Bedroom 1", area_sqft: 100, read: true, total: total(1, 2), items: [item("Fan", "a", 0), item("Blind", "a", 10), item("Heater", "a", 20)] },
    { name: "Bathroom", area_sqft: 40, read: true, total: total(1, 2), items: [item("Toilet", "b", 90)] },
    { name: "Kitchen", area_sqft: 70, read: true, total: total(1, 2), items: [item("Sink", "c", 180)] },
    { name: "Hallway", area_sqft: 30, read: true, total: total(1, 2), items: [item("Door", "d", 270), item("Light", "d", 280)] },
  ]);
  assert.deepEqual(buildTour(s, "SCAN").map((st) => st.room), ["Kitchen", "Bathroom", "Bedroom 1", "Hallway"]);
});

test("one stop per panorama, busiest panorama first, tags carry yaw and pitch", () => {
  const s = schedule([{ name: "Kitchen", area_sqft: 70, read: true, total: total(1, 2), items: [item("Sink", "p1", 10, -20), item("Range", "p2", 90), item("Fridge", "p2", 120, 5)] }]);
  const stops = buildTour(s, "SCAN");
  assert.deepEqual(stops.map((st) => [st.sweepId, st.tags.length]), [["p2", 2], ["p1", 1]]);
  assert.equal(stops[1].tags[0].pitch, -20);
  assert.equal(stops[0].heading, 30);
});

test("lines without a place in the scan are left out of the tour, rooms with none are skipped", () => {
  const s = schedule([
    { name: "Kitchen", area_sqft: 70, read: true, total: total(1, 2), items: [item("Sink", "p1", 10), { what: "Flooring", quantity: 70, unit: "sq ft", low: null, high: null, seen: null, at: null }] },
    { name: "Throughout the home", area_sqft: null, read: true, total: total(1, 2), items: [{ what: "Paint", quantity: 1, unit: "each", low: 1, high: 2, seen: null, at: null }] },
  ]);
  const stops = buildTour(s, "SCAN");
  assert.equal(stops.length, 1);
  assert.deepEqual(stops[0].tags.map((t) => t.what), ["Sink"]);
});

test("a panorama with no known heading is skipped unless the caller supplies one", () => {
  const noHeading = (what, sweep, yaw) => ({ ...item(what, sweep, yaw), at: { sweep_id: sweep, yaw_deg: yaw, pitch_deg: 0 } });
  const s = schedule([{ name: "Kitchen", area_sqft: 70, read: true, total: total(1, 2), items: [noHeading("Sink", "p1", 10)] }]);
  assert.equal(buildTour(s, "SCAN").length, 0);
  assert.equal(buildTour(s, "SCAN", { p1: 45 })[0].heading, 45);
});

test("facing is the circular middle of the tags, so 350 and 10 face 0", () => {
  assert.ok(Math.abs(circularMeanDeg([350, 10])) < 1e-9 || Math.abs(circularMeanDeg([350, 10]) - 360) < 1e-9);
  assert.ok(Math.abs(circularMeanDeg([80, 100]) - 90) < 1e-9);
  assert.equal(circularMeanDeg([]), 0);
});

test("direction: yaw 0 is -z, yaw 90 is +x, pitch up is +y (same frame as Loop.tsx)", () => {
  const near = (a, b) => a.every((v, i) => Math.abs(v - b[i]) < 1e-9);
  assert.ok(near(direction(0, 0), [0, 0, -1]));
  assert.ok(near(direction(90, 0), [1, 0, 0]));
  assert.ok(near(direction(180, 0), [0, 0, 1]));
  assert.ok(near(direction(0, 90), [0, 1, 0]));
});

test("figures: unpriced lines show no figure; ranges and single prices read naturally", () => {
  assert.equal(range(null, null), "no confirmed price");
  assert.equal(range(672, 1015), "$672–$1,015");
  assert.equal(range(145, 145), "$145");
  assert.equal(label({ what: "Base cabinet", quantity: 2, unit: "each" }), "Base cabinet ×2");
  assert.equal(label({ what: "Flooring", quantity: 332, unit: "sq ft" }), "Flooring");
});

test("scannedUnit finds the unit with located lines", () => {
  const s = schedule([{ name: "Kitchen", area_sqft: 70, read: true, total: total(1, 2), items: [item("Sink", "p1", 10)] }]);
  assert.equal(scannedUnit(s, "SCAN").name, "2BR");
  assert.equal(scannedUnit(s, "OTHER").name, "2BR");
});
