import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import ts from "typescript";

const source = await readFile(new URL("../src/recovery/capture-comparison.ts", import.meta.url), "utf8");
const { outputText } = ts.transpileModule(source, { compilerOptions: { target: ts.ScriptTarget.ES2020, module: ts.ModuleKind.ESNext } });
const { captureComparison, captureWindow, captureDate } = await import(`data:text/javascript;base64,${Buffer.from(outputText).toString("base64")}`);

const evidence = { evidence_id: "before-image", kind: "vexcel_image", source_id: "vexcel:collection:flight-before:1190364" };
const snapshot = () => ({ case: { case_id: "case-a", analysis_revision: 4, property_ref: { id: "1190364" } }, evidence: [evidence] });
const spatial = () => ({ case_id: "case-a", analysis_revision: 4, image_evidence_ids: ["before-image"], capture_pairs: {
  before: { evidence_id: "before-image", collection: "flight-before", image_available: true, first_date: "2024-08-02", last_date: "2024-08-13" },
  after: null, limitation: "Different viewing geometry requires review.",
} });

test("same source IDs cannot carry images across cases or analysis revisions", () => {
  const value = spatial();
  assert.equal(captureComparison(value, { ...snapshot(), case: { ...snapshot().case, case_id: "case-b" } }), null);
  assert.equal(captureComparison(value, { ...snapshot(), case: { ...snapshot().case, analysis_revision: 5 } }), null);
  assert.equal(captureComparison(null, snapshot()), null);
  assert.equal(captureComparison(value, null), null);
});

test("both reviewed image availability and advertised case evidence are necessary", () => {
  const value = spatial();
  assert.equal(captureComparison(value, snapshot()).before.available, true);
  value.capture_pairs.before.image_available = false;
  assert.equal(captureComparison(value, snapshot()).before.available, false);
  value.capture_pairs.before.image_available = true;
  value.image_evidence_ids = [];
  assert.equal(captureComparison(value, snapshot()).before.available, false);
  assert.equal(captureComparison(spatial(), { ...snapshot(), evidence: [] }).before.evidence, null);
});

test("a supplied foreign evidence ID cannot fall back to a different source image", () => {
  const value = spatial();
  value.capture_pairs.before.evidence_id = "foreign-image";
  const result = captureComparison(value, snapshot());
  assert.equal(result.before.evidence, null);
  assert.equal(result.before.available, false);
});

test("legacy lookup requires an exact collection and property source ID, uniquely", () => {
  const value = spatial();
  delete value.capture_pairs.before.evidence_id;
  assert.equal(captureComparison(value, snapshot()).before.evidence.evidence_id, "before-image");
  assert.equal(captureComparison(value, { ...snapshot(), evidence: [{ ...evidence, source_id: "vexcel:collection:flight-before:OTHER" }] }).before.evidence, null);
  assert.equal(captureComparison(value, { ...snapshot(), evidence: [evidence, { ...evidence, evidence_id: "another" }] }).before.evidence, null);
  assert.equal(captureComparison(value, { ...snapshot(), evidence: [{ ...evidence, kind: "resident_photo" }] }).before.evidence, null);
});

test("missing and uncached sides remain explicitly unavailable", () => {
  const value = spatial();
  const result = captureComparison(value, snapshot());
  assert.equal(result.after.available, false);
  assert.match(result.after.unavailable, /No eligible after-incident capture/);
  value.capture_pairs.before.image_available = false;
  value.capture_pairs.before.unavailable_reason = "Returned capture window crossed the incident.";
  assert.equal(captureComparison(value, snapshot()).before.unavailable, "Returned capture window crossed the incident.");
  value.capture_pairs.before = [];
  assert.equal(captureComparison(value, snapshot()).before.evidence, null);
});

test("capture windows preserve multi-day acquisition and unknown starts", () => {
  assert.equal(captureWindow({ first_date: "2024-08-02", last_date: "2024-08-13" }), "Aug 2, 2024 – Aug 13, 2024");
  assert.equal(captureWindow({ first_date: "2025-01-20", last_date: "2025-01-20" }), "Jan 20, 2025 (one-day window)");
  assert.equal(captureWindow({ date: "2024-08-13" }), "Start unknown – Aug 13, 2024");
  assert.equal(captureWindow({ first_date: "2024-08-02" }), "Aug 2, 2024 – end unknown");
  assert.equal(captureWindow({}), "Capture window unknown");
});

test("invalid and reversed dates do not become plausible capture labels", () => {
  assert.equal(captureDate("2025-02-30"), "unknown");
  assert.equal(captureDate("yesterday"), "unknown");
  assert.equal(captureWindow({ first_date: "2025-01-20", last_date: "2024-08-13" }), "Capture window needs review");
});
