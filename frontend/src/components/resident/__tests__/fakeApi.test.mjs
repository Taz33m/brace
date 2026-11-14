import assert from "node:assert/strict";
import test from "node:test";
import { loadTs } from "./load.mjs";

const { FakeResidentApi } = await loadTs("fixtures/fakeApi.ts");

const make = (scenario = "happy") => {
  const api = new FakeResidentApi(scenario);
  api.latency = 0;
  return api;
};
const photo = (name = "leak.jpg") => new File([new Uint8Array(64)], name, { type: "image/jpeg" });
const report = (over = {}) => ({
  category: "water", text: "Water dripping from the hallway ceiling", selected_location_id: "fx-loc-hall",
  location_description: null, observed_at: null, upload_ids: [], ...over,
});
const waitFor = async (check, ms = 2000) => {
  const end = Date.now() + ms;
  while (!check()) {
    if (Date.now() > end) throw new Error("waitFor timed out");
    await new Promise((r) => setTimeout(r, 10));
  }
};

test("happy path: upload then report", async () => {
  const api = make();
  const up = await api.upload_image(photo(), "u-1");
  assert.match(up.upload_id, /^upl_/);
  const receipt = await api.submit_report(report({ upload_ids: [up.upload_id] }), "r-1");
  assert.equal(receipt.duplicate, false);
  assert.equal(receipt.report.status, "reported");
  assert.equal(receipt.report.media.length, 1);
  assert.equal(receipt.report.location.binding, "verified_unit");
  const home = await api.get_home();
  assert.equal(home.reports.length, 1);
  assert.equal(home.reports[0].report_id, receipt.report.report_id);
});

test("lost_response: retry with the same key returns the same report once", async () => {
  const api = make("lost_response");
  await assert.rejects(api.submit_report(report(), "r-lost"), TypeError);
  const retry = await api.submit_report(report(), "r-lost");
  assert.equal(retry.duplicate, true);
  const home = await api.get_home();
  assert.equal(home.reports.length, 1);
  assert.equal(home.reports[0].report_id, retry.report.report_id);
  const again = await api.submit_report(report(), "r-lost");
  assert.equal(again.report.report_id, retry.report.report_id);
});

test("a new key creates a new report", async () => {
  const api = make("lost_response");
  await assert.rejects(api.submit_report(report(), "r-a"), TypeError);
  const a = await api.submit_report(report(), "r-a");
  await assert.rejects(api.submit_report(report(), "r-b"), TypeError);
  const b = await api.submit_report(report(), "r-b");
  assert.notEqual(a.report.report_id, b.report.report_id);
  assert.equal((await api.get_home()).reports.length, 2);
});

test("upload_failure: first upload 503s, retry with the same key succeeds", async () => {
  const api = make("upload_failure");
  await assert.rejects(api.upload_image(photo(), "u-x"), (e) => e.status === 503 && e.body.error.retryable === true);
  const up = await api.upload_image(photo(), "u-x");
  assert.ok(up.upload_id);
  const again = await api.upload_image(photo(), "u-x");
  assert.equal(again.upload_id, up.upload_id);
});

test("a report naming an unknown upload is rejected with 422", async () => {
  const api = make();
  await assert.rejects(api.submit_report(report({ upload_ids: ["upl_999"] }), "r-u"), (e) => e.status === 422 && e.body.error.code === "unknown_upload");
  assert.equal((await api.get_home()).reports.length, 0);
});

test("a representative_layout location never binds to the dwelling", async () => {
  const api = make();
  const home = await api.get_home();
  const model = home.selectable_locations.find((l) => l.binding === "representative_layout");
  assert.ok(model, "fixture should include a model-unit location");
  await assert.rejects(api.submit_report(report({ selected_location_id: model.location_id }), "r-m"), (e) => e.status === 422);
  await assert.rejects(api.submit_report(report({ selected_location_id: "nope" }), "r-n"), (e) => e.status === 422);
  assert.equal((await api.get_home()).reports.length, 0);
});

test("non-image uploads and empty text are rejected", async () => {
  const api = make();
  await assert.rejects(api.upload_image(new File(["x"], "a.pdf", { type: "application/pdf" }), "u-pdf"), (e) => e.status === 422);
  await assert.rejects(api.submit_report(report({ text: "   " }), "r-e"), (e) => e.status === 422);
});

test("expire(): later calls reject with 401", async () => {
  const api = make();
  api.expire();
  await assert.rejects(api.get_home(), (e) => e.status === 401 && e.body.error.code === "session_expired");
  await assert.rejects(api.submit_report(report(), "r-x"), (e) => e.status === 401);
});

test("expired_on_submit: send returns 401", async () => {
  const api = make("expired_on_submit");
  await assert.rejects(api.submit_report(report(), "r-x"), (e) => e.status === 401);
  await assert.rejects(api.request_support({ category: "housing", description: "Need a room" }, "s-x"), (e) => e.status === 401);
});

test("support: lost response retries idempotently", async () => {
  const api = make("lost_response");
  await assert.rejects(api.request_support({ category: "access", description: "Lift is out" }, "s-1"), TypeError);
  const r = await api.request_support({ category: "access", description: "Lift is out" }, "s-1");
  assert.equal(r.duplicate, true);
  assert.equal((await api.get_home()).support_requests.length, 1);
});

test("advanceTask walks proposed → verified, schedule only from accepted", async () => {
  const api = make("empty");
  const seen = [];
  for (let i = 0; i < 6; i++) {
    api.advanceTask();
    const [task] = (await api.get_home()).tasks;
    seen.push(task.status);
    const before = ["proposed", "approved"].includes(task.status);
    assert.equal(task.confirmed_schedule === null, before, `${task.status} schedule=${task.confirmed_schedule}`);
  }
  assert.deepEqual(seen, ["proposed", "approved", "accepted", "in_progress", "completion_submitted", "verified"]);
  api.advanceTask();
  const tasks = (await api.get_home()).tasks;
  assert.equal(tasks.length, 2, "a verified task is closed; the next advance opens a new one");
  assert.equal(tasks[0].status, "proposed");
});

test("subscribe delivers only events after the cursor; dropConnection replays a duplicate", async () => {
  const api = make();
  const start = (await api.get_home()).event_cursor;
  api.publishNotice(); // start + 1, before subscribing
  const ids = [];
  const states = [];
  const unsubscribe = api.subscribe({ after: start + 1, on_event: (e) => ids.push(e.event_id), on_connection: (s) => states.push(s) });
  await waitFor(() => states.includes("connected"));
  assert.deepEqual(ids, [], "events at or before `after` are not delivered");
  api.advanceTask(); // start + 2
  assert.deepEqual(ids, [start + 2]);
  api.dropConnection(0.02);
  assert.equal(states.at(-1), "reconnecting");
  await waitFor(() => states.filter((s) => s === "connected").length === 2);
  assert.ok(ids.length >= 2, "reconnect replays at least one event");
  assert.ok(new Set(ids).size < ids.length, "replay includes a duplicate event ID");
  unsubscribe();
  api.advanceTask();
  const count = ids.length;
  await new Promise((r) => setTimeout(r, 20));
  assert.equal(ids.length, count, "no delivery after unsubscribe");
});

test("subscribe on an expired session reports expired", async () => {
  const api = make();
  api.expire();
  const states = [];
  api.subscribe({ after: 0, on_event: () => {}, on_connection: (s) => states.push(s) });
  await waitFor(() => states.includes("expired"));
});
