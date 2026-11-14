import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import ts from "typescript";

const source = await readFile(new URL("../src/recovery/spatial.ts", import.meta.url), "utf8");
const { outputText } = ts.transpileModule(source, { compilerOptions: { target: ts.ScriptTarget.ES2020, module: ts.ModuleKind.ESNext } });
const { SpatialCaseController, currentSpatial, evidenceImageUrl, preferredEvidence, permittedEvidenceImage } =
  await import(`data:text/javascript;base64,${Buffer.from(outputText).toString("base64")}`);

const manifest = (case_id, analysis_revision = 1, image_evidence_ids = ["image-1"]) => ({
  case_id, analysis_revision, image_evidence_ids, locations: [], structures: [], scans: [],
  capture_pairs: {}, source_status: {}, limitations: [],
});
const deferred = () => {
  let resolve, reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
};

test("case switch aborts old spatial request and late results cannot replace the new case", async () => {
  const first = deferred(), second = deferred(), requests = [], states = [];
  const controller = new SpatialCaseController({ get_spatial: (id, signal) => {
    requests.push({ id, signal }); return id === "first" ? first.promise : second.promise;
  } }, state => states.push(state));
  const a = controller.load("first", 1);
  const b = controller.load("second", 4);
  assert.equal(requests[0].signal.aborted, true);
  assert.equal(controller.state.data, null);
  assert.equal(controller.state.case_id, "second");
  second.resolve(manifest("second", 4)); await b;
  first.resolve(manifest("first", 1)); await a;
  assert.equal(controller.state.data.case_id, "second");
  assert.ok(states.every(state => state.state !== "ready" || state.case_id === "second"));
  assert.equal(currentSpatial(controller.state, "first", 1), null);
  assert.equal(currentSpatial(controller.state, "second", 3), null);
  assert.equal(currentSpatial(controller.state, "second", 4).case_id, "second");
});

test("analysis changes clear existing images and mismatched server revisions are rejected", async () => {
  const pending = deferred();
  let calls = 0;
  const controller = new SpatialCaseController({ get_spatial: async () => ++calls === 1 ? manifest("same", 1) : pending.promise }, () => {});
  await controller.load("same", 1);
  assert.equal(controller.state.state, "ready");
  const next = controller.load("same", 2);
  assert.equal(controller.state.data, null);
  pending.resolve(manifest("same", 1)); await next;
  assert.equal(controller.state.state, "error");
  assert.equal(controller.state.data, null);
  assert.match(controller.state.error, /changed/);
});

test("disposal cancels pending reads and never emits a result afterward", async () => {
  const pending = deferred(), states = [];
  let signal;
  const controller = new SpatialCaseController({ get_spatial: (_id, provided) => { signal = provided; return pending.promise; } }, state => states.push(state));
  const run = controller.load("case", 1);
  controller.dispose();
  pending.resolve(manifest("case", 1)); await run;
  assert.equal(signal.aborted, true);
  assert.deepEqual(states.map(state => state.state), ["loading"]);
});

test("image URLs require matching case, analysis revision and advertised evidence", () => {
  const source = { evidence_id: "image / 1", kind: "vexcel_image", media: null };
  const spatial = manifest("case / 1", 5, ["image / 1"]);
  const origin = "http://localhost:5174";
  assert.equal(evidenceImageUrl(source, spatial, "case / 1", 5, origin), "/api/recovery/cases/case%20%2F%201/evidence/image%20%2F%201/image");
  assert.equal(evidenceImageUrl(source, spatial, "different", 5, origin), null);
  assert.equal(evidenceImageUrl(source, spatial, "case / 1", 6, origin), null);
  assert.equal(evidenceImageUrl({ ...source, evidence_id: "not-registered" }, spatial, "case / 1", 5, origin), null);
  assert.equal(evidenceImageUrl(source, null, "case / 1", 5, origin), null);
});

test("resident photos retain authorized media endpoints without sponsor-image substitution", () => {
  const origin = "http://localhost:5174";
  const photo = { evidence_id: "resident-1", kind: "resident_photo", media: { url: "/api/recovery/media/upload-1" } };
  assert.equal(evidenceImageUrl(photo, null, "case", 1, origin), "/api/recovery/media/upload-1");
  assert.equal(evidenceImageUrl({ ...photo, media: { url: "https://outside.example/image.jpg" } }, null, "case", 1, origin), null);
  assert.equal(evidenceImageUrl({ ...photo, media: { url: "/api/recovery/cases/other/evidence/e/image" } }, null, "case", 1, origin), null);
  assert.equal(permittedEvidenceImage("/api/buildings/1/aerial.jpg", origin), null);
});

test("default evidence prefers cached images while explicit selection preserves metadata-only choice", () => {
  const metadata = { evidence_id: "attributes", kind: "vexcel_image" };
  const image = { evidence_id: "photo", kind: "vexcel_image" };
  const inside = { evidence_id: "inside", kind: "matterport_view" };
  const imageUrl = value => value.evidence_id === "photo" ? "/pinned-image" : null;
  assert.equal(preferredEvidence([metadata, image, inside], null, ["vexcel_image"], imageUrl), image);
  assert.equal(preferredEvidence([metadata, image, inside], "attributes", ["vexcel_image"], imageUrl), metadata);
  assert.equal(preferredEvidence([metadata, image, inside], "inside", ["vexcel_image"], imageUrl), image);
});
