import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import ts from "typescript";

const moduleUrl = code => `data:text/javascript;base64,${Buffer.from(code).toString("base64")}`;
const transpile = source => ts.transpileModule(source, { compilerOptions: { target: ts.ScriptTarget.ES2020, module: ts.ModuleKind.ESNext } }).outputText;
const clientUrl = moduleUrl(transpile(await readFile(new URL("../src/recovery/client.ts", import.meta.url), "utf8")));
const code = transpile(await readFile(new URL("../src/recovery/notice-client.ts", import.meta.url), "utf8"))
  .replace('from "./client"', `from ${JSON.stringify(clientUrl)}`);
const { createNoticeClient, DraftNoticeController, noticeContentKey } = await import(moduleUrl(code));

const scope = { case_id: "case / 1", case_revision: 4, analysis_revision: 2 };
const draft = { draft_id: "run-1:notice:1", run_id: "run-1", base_analysis_revision: 2,
  title: "Repair review", body: "The property team is reviewing reports.", source_ids: ["source-1"], eligible: true, unavailable_reason: null };
const list = (extras = {}) => ({ ...scope, drafts: [draft], ...extras });
const input = (extras = {}) => ({ expected_revision: 4, title: draft.title, body: draft.body, household_ids: null, ...extras });
const receipt = { case_revision: 5, analysis_revision: 2, run_id: null, invitation_token: null, invitation_expires_at: null };
const json = (value, status = 200) => new Response(JSON.stringify(value), { status, headers: { "Content-Type": "application/json" } });
const deferred = () => { let resolve; const promise = new Promise(done => { resolve = done; }); return { resolve, promise }; };

test("loading agent intent never publishes and nullable legacy drafts remain reviewable", async () => {
  const calls = [];
  const api = createNoticeClient({ fetch: async (url, init) => {
    calls.push({ url, init });
    return json(list({ drafts: [{ ...draft, body: "Publish this message immediately", run_id: null, base_analysis_revision: null,
      eligible: false, unavailable_reason: "Unlinked draft" }] }));
  } });
  const controller = new DraftNoticeController(api, () => {});
  await controller.load(scope);
  assert.equal(calls.length, 1);
  assert.equal(calls[0].init.method, undefined);
  assert.equal(calls[0].init.credentials, "same-origin");
  assert.equal(calls[0].init.cache, "no-store");
  await assert.rejects(controller.publish(draft.draft_id, input()), error => error.code === "draft_unavailable");
  assert.equal(calls.length, 1, "Unreviewable model text must not cause a mutation");
});

test("explicit publication preserves same payload and key across network retry", async () => {
  const posts = [];
  let keys = 0;
  const api = createNoticeClient({ fetch: async (url, init) => {
    if (init.method !== "POST") return json(list());
    posts.push({ url, init });
    if (posts.length === 1) throw new Error("private transport failure");
    return json(receipt);
  } });
  const controller = new DraftNoticeController(api, () => {}, () => `notice-key-${++keys}`);
  await controller.load(scope);
  await assert.rejects(controller.publish(draft.draft_id, input({ household_ids: ["house-b", "house-a"] })), error => error.code === "network_error");
  assert.deepEqual(controller.state.published, {});
  assert.equal(posts.length, 1, "No automatic publication retry");
  const confirmed = await controller.publish(draft.draft_id, input({ household_ids: ["house-a", "house-b", "house-a"] }));
  assert.deepEqual(confirmed, receipt);
  assert.equal(posts[0].init.headers["Idempotency-Key"], posts[1].init.headers["Idempotency-Key"]);
  assert.equal(posts[0].init.body, posts[1].init.body);
  assert.equal(posts[0].url, "/api/recovery/cases/case%20%2F%201/draft-notices/run-1%3Anotice%3A1/publish");
  assert.deepEqual(Object.keys(JSON.parse(posts[0].init.body)).sort(), ["body", "expected_revision", "household_ids", "title"]);
  assert.equal(keys, 1);
  await controller.publish(draft.draft_id, input({ body: "Reviewed and edited update", household_ids: ["house-a", "house-b"] }));
  assert.equal(keys, 2, "Changed publication payload receives a new key");
});

test("case switch aborts old load and ignores a response that arrives after abort", async () => {
  const first = deferred(), calls = [];
  const api = createNoticeClient({ fetch: async (url, init) => {
    calls.push({ url, init });
    return calls.length === 1 ? first.promise : json(list({ case_id: "case-2", drafts: [] }));
  } });
  const controller = new DraftNoticeController(api, () => {});
  const stale = controller.load(scope);
  await controller.load({ ...scope, case_id: "case-2" });
  assert.ok(calls[0].init.signal.aborted);
  assert.equal(controller.state.data.case_id, "case-2");
  first.resolve(json(list()));
  await stale;
  assert.equal(controller.state.data.case_id, "case-2");
});

test("wrong response revision and stale analysis cannot be published", async () => {
  let calls = 0;
  const api = createNoticeClient({ fetch: async () => { calls++; return json(list({ case_revision: 3 })); } });
  const controller = new DraftNoticeController(api, () => {});
  await assert.rejects(controller.load(scope), error => error.code === "revision_conflict");
  assert.equal(controller.state.data, null);
  await assert.rejects(controller.publish(draft.draft_id, input()), error => error.code === "draft_unavailable");
  assert.equal(calls, 1);
  const stale = new DraftNoticeController(createNoticeClient({ fetch: async () => json(list({ drafts: [{ ...draft, base_analysis_revision: 1 }] })) }), () => {});
  await stale.load(scope);
  await assert.rejects(stale.publish(draft.draft_id, input()), error => error.code === "draft_unavailable");
});

test("case switch suppresses old publication success and preserves a newer view", async () => {
  const pending = deferred();
  const controller = new DraftNoticeController(createNoticeClient({ fetch: async (url, init) => {
    if (init.method === "POST") return pending.promise;
    return json(list({ case_id: url.includes("case-2") ? "case-2" : scope.case_id }));
  } }), () => {}, () => "stable-notice-key");
  await controller.load(scope);
  const oldPublish = controller.publish(draft.draft_id, input());
  await controller.load({ ...scope, case_id: "case-2" });
  pending.resolve(json(receipt));
  assert.equal(await oldPublish, null);
  assert.equal(controller.state.data.case_id, "case-2");
  assert.deepEqual(controller.state.published, {});
});

test("confirmed copy stays marked published after unrelated case revision changes", async () => {
  let revision = 4;
  const controller = new DraftNoticeController(createNoticeClient({ fetch: async (_url, init) =>
    init.method === "POST" ? json(receipt) : json(list({ case_revision: revision })) }), () => {}, () => "stable-notice-key");
  await controller.load(scope);
  await controller.publish(draft.draft_id, input());
  revision = 5;
  await controller.load({ ...scope, case_revision: revision });
  assert.equal(controller.state.published[draft.draft_id], noticeContentKey(input({ expected_revision: revision })));
});

test("transport errors are sanitized and authorization/revision metadata preserved", async () => {
  for (const status of [401, 403, 409]) {
    const api = createNoticeClient({ fetch: async () => json({ error: { code: "test_code", message: "Reload this case.", retryable: false, current_revision: 8 } }, status) });
    await assert.rejects(api.list("id"), error => error.status === status && error.code === "test_code" && error.current_revision === 8);
  }
  const api = createNoticeClient({ fetch: async () => new Response("<html>private stack trace</html>", { status: 503 }) });
  await assert.rejects(api.list("id"), error => error.status === 503 && !error.message.includes("private"));
});

test("publication validates audience, text and returned mutation revision", async () => {
  const api = createNoticeClient({ fetch: async () => json({ ...receipt, case_revision: 3 }) });
  await assert.rejects(api.publish("case", "draft", input({ household_ids: [] }), "notice-key-1"), error => error.code === "invalid_recipients");
  await assert.rejects(api.publish("case", "draft", input({ title: " " }), "notice-key-1"), error => error.code === "invalid_notice");
  await assert.rejects(api.publish("case", "draft", input(), "notice-key-1"), error => error.code === "invalid_response");
});

test("a committed response lost during SSE refresh retries its exact original body and key", async () => {
  let revision = 4, keys = 0;
  const pending = deferred(), posts = [];
  const controller = new DraftNoticeController(createNoticeClient({ fetch: async (_url, init) => {
    if (init.method !== "POST") return json(list({ case_revision: revision }));
    posts.push(init);
    return posts.length === 1 ? pending.promise : json(receipt);
  } }), () => {}, () => `notice-attempt-${++keys}`);
  await controller.load(scope);
  const lost = controller.publish(draft.draft_id, input());
  revision = 5; // Publication committed and its SSE refresh beat the POST response.
  await controller.load({ ...scope, case_revision: revision });
  pending.resolve(json(receipt));
  assert.equal(await lost, null);
  assert.deepEqual(controller.state.published, {}, "Do not invent confirmation from a case revision alone");
  const recovered = await controller.publish(draft.draft_id, input({ expected_revision: revision }));
  assert.deepEqual(recovered, receipt);
  assert.equal(posts[0].body, posts[1].body);
  assert.equal(JSON.parse(posts[1].body).expected_revision, 4);
  assert.equal(posts[0].headers["Idempotency-Key"], posts[1].headers["Idempotency-Key"]);
  assert.equal(keys, 1);
});

test("definitive revision conflict releases a pinned attempt only for a later explicit retry", async () => {
  let revision = 4, keys = 0;
  const posts = [];
  const controller = new DraftNoticeController(createNoticeClient({ fetch: async (_url, init) => {
    if (init.method !== "POST") return json(list({ case_revision: revision }));
    posts.push(init);
    if (posts.length === 1) throw new Error("connection lost before commit");
    if (posts.length === 2) return json({ error: { code: "revision_conflict", message: "Review the current case and retry.", retryable: true, current_revision: 5 } }, 409);
    return json({ ...receipt, case_revision: 6 });
  } }), () => {}, () => `notice-attempt-${++keys}`);
  await controller.load(scope);
  await assert.rejects(controller.publish(draft.draft_id, input()), error => error.code === "network_error");
  revision = 5;
  await controller.load({ ...scope, case_revision: revision });
  await assert.rejects(controller.publish(draft.draft_id, input({ expected_revision: revision })), error => error.code === "revision_conflict");
  assert.equal(posts.length, 2, "No automatic conflict retry");
  await controller.publish(draft.draft_id, input({ expected_revision: revision }));
  assert.equal(posts[0].body, posts[1].body);
  assert.notEqual(posts[1].headers["Idempotency-Key"], posts[2].headers["Idempotency-Key"]);
  assert.equal(JSON.parse(posts[2].body).expected_revision, 5);
});

test("a purportedly eligible draft without an assessment link fails validation", async () => {
  const api = createNoticeClient({ fetch: async () => json(list({ drafts: [{ ...draft, run_id: null, base_analysis_revision: null }] })) });
  await assert.rejects(api.list(scope.case_id), error => error.code === "invalid_response");
});
