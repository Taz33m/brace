import assert from "node:assert/strict";
import { File } from "node:buffer";
import { readFile } from "node:fs/promises";
import test from "node:test";
import ts from "typescript";

const source = await readFile(new URL("../src/recovery/client.ts", import.meta.url), "utf8");
const { outputText } = ts.transpileModule(source, { compilerOptions: { target: ts.ScriptTarget.ES2020, module: ts.ModuleKind.ESNext } });
const { createRecoveryClient, RecoveryApiError } = await import(`data:text/javascript;base64,${Buffer.from(outputText).toString("base64")}`);

const json = (value, status = 200) => new Response(JSON.stringify(value), { status, headers: { "Content-Type": "application/json" } });
const event = (id, extras = {}) => ({ event_id: id, case_id: "case / 1", case_revision: id + 1,
  analysis_revision: 1, type: "case.updated", at: "2026-11-14T12:00:00Z", entity_id: null, public_summary: null, ...extras });
const frame = (e) => `id: ${e.event_id}\ndata: ${JSON.stringify(e)}\n\n`;
const encoder = new TextEncoder();

function stream(chunks, { open = false, cancelled = () => {} } = {}) {
  return new Response(new ReadableStream({
    start(controller) {
      for (const chunk of chunks) controller.enqueue(typeof chunk === "string" ? encoder.encode(chunk) : chunk);
      if (!open) controller.close();
    },
    cancel() { cancelled(); },
  }), { headers: { "Content-Type": "text/event-stream; charset=utf-8" } });
}

function abortableWait(_milliseconds, signal) {
  return new Promise((resolve) => {
    if (signal.aborted) resolve();
    else signal.addEventListener("abort", () => resolve(), { once: true });
  });
}

async function until(check) {
  for (let turn = 0; turn < 100; turn++) {
    if (check()) return;
    await new Promise((resolve) => setImmediate(resolve));
  }
  assert.fail("Condition did not become true");
}

test("owner request encodes opaque IDs and preserves caller idempotency across retry", async () => {
  const calls = [];
  const api = createRecoveryClient({ fetch: async (url, init) => {
    calls.push({ url, init });
    if (calls.length === 1) throw new Error("private transport details");
    return json({ case_revision: 7, analysis_revision: 4, run_id: "r1", invitation_token: null, invitation_expires_at: null });
  } });
  const command = { type: "start_assessment", expected_revision: 6 };
  await assert.rejects(api.command("case / 1", command, "same-request-key"), (error) => {
    assert.ok(error instanceof RecoveryApiError);
    assert.equal(error.code, "network_error");
    assert.equal(error.retryable, true);
    assert.ok(!error.message.includes("private transport"));
    return true;
  });
  assert.equal(calls.length, 1, "Mutations are not automatically replayed");
  await api.command("case / 1", command, "same-request-key");
  for (const { url, init } of calls) {
    assert.equal(url, "/api/recovery/cases/case%20%2F%201/commands");
    assert.equal(init.credentials, "same-origin");
    assert.equal(init.headers["Idempotency-Key"], "same-request-key");
    assert.deepEqual(JSON.parse(init.body), command);
  }
});

test("structured HTTP errors retain revision, status, code and retry policy", async () => {
  for (const status of [401, 403, 409, 503]) {
    const api = createRecoveryClient({ fetch: async () => json({ error: { code: "revision_conflict", message: "Reload this case.", retryable: true, current_revision: 12 } }, status) });
    await assert.rejects(api.get_case("id"), (error) => error instanceof RecoveryApiError && error.status === status
      && error.current_revision === 12 && error.code === "revision_conflict" && error.message === "Reload this case.");
  }
  const api = createRecoveryClient({ fetch: async () => new Response("<html>private stack trace</html>", { status: 503 }) });
  await assert.rejects(api.get_cases(), (error) => error.code === "request_failed" && !error.message.includes("private"));
});

test("sessions and resident writes use only scoped endpoints and multipart upload headers", async () => {
  const calls = [];
  const api = createRecoveryClient({ fetch: async (url, init) => { calls.push({ url, init }); return json({ ok: true }); } });
  await api.owner_session("owner secret");
  await api.resident_session("invitation token");
  await api.resident_api.get_home();
  const report = { category: "water", text: "Water at door", selected_location_id: null, location_description: "Entry", observed_at: null, upload_ids: [] };
  await api.resident_api.submit_report(report, "report-key");
  await api.resident_api.request_support({ category: "housing", description: "Need information" }, "support-key");
  const image = new File(["test-bytes"], "report.jpg", { type: "image/jpeg" });
  await api.resident_api.upload_image(image, "upload-key");
  assert.deepEqual(calls.map(c => c.url), ["/api/recovery/session", "/api/resident/session", "/api/resident/home", "/api/resident/reports", "/api/resident/support", "/api/resident/uploads"]);
  assert.deepEqual(JSON.parse(calls[0].init.body), { secret: "owner secret" });
  assert.deepEqual(JSON.parse(calls[1].init.body), { invitation_token: "invitation token" });
  assert.deepEqual(JSON.parse(calls[3].init.body), report);
  assert.equal(calls[5].init.headers["Idempotency-Key"], "upload-key");
  assert.equal(calls[5].init.headers["Content-Type"], undefined, "Browser supplies the multipart boundary");
  assert.equal(calls[5].init.body.get("file").name, "report.jpg");
  assert.throws(() => api.command("id", { type: "start_assessment", expected_revision: 1 }, ""), /nonempty idempotency/);
});

test("SSE parses split UTF-8, CRLF, multiline JSON, comments and ignores duplicate events", async () => {
  const e = event(8, { public_summary: "Réparation" });
  const serialized = JSON.stringify(e);
  const split = serialized.indexOf(',"at"');
  const payload = `: heartbeat\r\nid: 8\r\ndata: ${serialized.slice(0, split + 1)}\r\ndata: ${serialized.slice(split + 1)}\r\n\r\n${frame(e)}`;
  const bytes = encoder.encode(payload);
  const chunks = [...bytes].map((byte) => Uint8Array.of(byte));
  const events = [];
  const connections = [];
  const api = createRecoveryClient({ fetch: async () => stream(chunks), sleep: abortableWait });
  const stop = api.subscribe_case("case / 1", { after: 7, on_event: (value) => events.push(value), on_connection: (state) => connections.push(state) });
  await until(() => connections.includes("reconnecting"));
  stop();
  assert.deepEqual(events, [e]);
  assert.deepEqual(connections, ["connected", "reconnecting"]);
});

test("SSE reconnects from the latest accepted cursor and deduplicates replay", async () => {
  const calls = [];
  const delays = [];
  const received = [];
  const api = createRecoveryClient({
    reconnect_initial_ms: 10, reconnect_max_ms: 40,
    sleep: async (milliseconds) => { delays.push(milliseconds); },
    fetch: async (url, init) => {
      calls.push({ url, init });
      if (calls.length === 1) return json({ error: { code: "unavailable", message: "Retry", retryable: true } }, 503);
      if (calls.length === 2) return stream([frame(event(1))]);
      return stream([frame(event(1)), frame(event(2))], { open: true });
    },
  });
  let stop;
  stop = api.subscribe_case("case / 1", { after: 0, on_event: e => { received.push(e.event_id); if (e.event_id === 2) stop(); }, on_connection: () => {} });
  await until(() => received.length === 2);
  assert.deepEqual(received, [1, 2]);
  assert.deepEqual(calls.map(c => c.url), ["/api/recovery/cases/case%20%2F%201/events?after=0", "/api/recovery/cases/case%20%2F%201/events?after=0", "/api/recovery/cases/case%20%2F%201/events?after=1"]);
  assert.deepEqual(calls.map(c => c.init.headers["Last-Event-ID"]), ["0", "0", "1"]);
  assert.ok(delays.every(d => d >= 10 && d <= 40));
});

test("SSE network reconnect backoff is bounded and unsubscribe aborts pending sleep", async () => {
  const delays = [];
  let calls = 0;
  let signal;
  const api = createRecoveryClient({ reconnect_initial_ms: 2, reconnect_max_ms: 5,
    fetch: async () => { calls++; throw new Error("offline"); },
    sleep: async (milliseconds, currentSignal) => {
      delays.push(milliseconds);
      if (delays.length === 4) { signal = currentSignal; await abortableWait(milliseconds, currentSignal); }
    },
  });
  const stop = api.resident_api.subscribe({ after: 0, on_event: () => {}, on_connection: () => {} });
  await until(() => delays.length === 4);
  stop();
  await new Promise(resolve => setImmediate(resolve));
  assert.deepEqual(delays, [2, 4, 5, 5]);
  assert.equal(calls, 4);
  assert.equal(signal.aborted, true);
});

test("401 and 403 expire subscriptions without retry loops", async () => {
  for (const status of [401, 403]) {
    let calls = 0;
    let sleeps = 0;
    const states = [];
    const api = createRecoveryClient({ fetch: async () => { calls++; return json({ error: { code: "expired", message: "Sign in", retryable: false } }, status); }, sleep: async () => { sleeps++; } });
    const stop = api.resident_api.subscribe({ after: 0, on_event: () => assert.fail("No event expected"), on_connection: state => states.push(state) });
    await until(() => states.includes("expired"));
    stop();
    assert.equal(calls, 1);
    assert.equal(sleeps, 0);
  }
});

test("cleanup cancels the active reader and prevents later callbacks", async () => {
  let cancelled = 0;
  let signal;
  const states = [];
  const api = createRecoveryClient({ fetch: async (_url, init) => { signal = init.signal; return stream([], { open: true, cancelled: () => { cancelled++; } }); } });
  const stop = api.subscribe_case("case / 1", { after: 0, on_event: () => assert.fail("No event expected"), on_connection: state => states.push(state) });
  await until(() => states.includes("connected"));
  stop(); stop();
  await until(() => cancelled === 1);
  assert.equal(signal.aborted, true);
  assert.deepEqual(states, ["connected"]);
});

test("session.revoked event expires and closes the stream", async () => {
  const states = [];
  const received = [];
  let calls = 0;
  const api = createRecoveryClient({ fetch: async () => { calls++; return stream([frame(event(1, { type: "session.revoked" })), frame(event(2))], { open: true }); } });
  const stop = api.resident_api.subscribe({ after: 0, on_event: e => received.push(e.event_id), on_connection: state => states.push(state) });
  await until(() => states.includes("expired"));
  stop();
  assert.deepEqual(received, [1]);
  assert.equal(calls, 1);
});

test("invalid frames do not advance replay cursor", async () => {
  const calls = [];
  const errors = [];
  const api = createRecoveryClient({ fetch: async (url) => {
    calls.push(url);
    return calls.length === 1 ? stream([`id: 99\ndata: ${JSON.stringify(event(1))}\n\n`]) : stream([], { open: true });
  }, sleep: async () => {} });
  const stop = api.subscribe_case("case / 1", { after: 0, on_event: () => assert.fail("No valid event"), on_connection: () => {}, on_error: error => errors.push(error) });
  await until(() => calls.length === 2);
  stop();
  assert.ok(calls.every(url => url.endsWith("after=0")));
  assert.equal(errors[0].code, "invalid_stream");
});
