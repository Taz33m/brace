import assert from "node:assert/strict";
import test from "node:test";
import { loadTs } from "./load.mjs";

const t = await loadTs("lib/time.ts");
const CLOCK = /\d{1,2}[:.]\d{2}/;

test("localInputToIso round trips through toLocalInput", () => {
  for (const v of ["2026-11-14T15:30", "2026-01-01T00:05", "2026-07-04T23:59"]) {
    const iso = t.localInputToIso(v);
    assert.match(iso, /Z$/);
    assert.equal(t.toLocalInput(new Date(iso)), v);
  }
  assert.equal(t.localInputToIso(""), null);
  assert.equal(t.localInputToIso("not a date"), null);
});

test("formatWhen of missing or invalid values is Unknown", () => {
  assert.equal(t.formatWhen(null), "Unknown");
  assert.equal(t.formatWhen(undefined), "Unknown");
  assert.equal(t.formatWhen(""), "Unknown");
  assert.equal(t.formatWhen("garbage"), "Unknown");
  assert.equal(t.formatAgo(null), "Unknown");
});

test("date-only values stay date-only", () => {
  const now = new Date(2026, 10, 14, 9, 0);
  for (const v of ["2026-11-14", "2026-11-13", "2026-11-01"]) {
    const out = t.formatWhen(v, now);
    assert.doesNotMatch(out, CLOCK, v);
    assert.doesNotMatch(out, /Today|Yesterday/, v);
  }
  assert.equal(t.parseWhen("2026-11-14").getDate(), 14);
});

test("timestamps show a time, relative to today", () => {
  const now = new Date(2026, 10, 14, 18, 0);
  const today = new Date(2026, 10, 14, 15, 42).toISOString();
  const yesterday = new Date(2026, 10, 13, 15, 42).toISOString();
  const older = new Date(2026, 10, 2, 15, 42).toISOString();
  assert.match(t.formatWhen(today, now), /^Today /);
  assert.match(t.formatWhen(yesterday, now), /^Yesterday /);
  assert.match(t.formatWhen(older, now), CLOCK);
  assert.equal(t.formatAgo(new Date(now.getTime() - 10_000).toISOString(), now), "just now");
  assert.equal(t.formatAgo(new Date(now.getTime() - 4 * 60_000).toISOString(), now), "4 min ago");
});

test("formatAgo keeps date-only precision", () => {
  const now = new Date(2026, 10, 14, 12, 0, 20);
  assert.doesNotMatch(t.formatAgo("2026-11-14", now), /just now|min ago| h ago/);
});
