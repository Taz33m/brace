import { test } from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import ts from "typescript";

const source = await readFile(new URL("../src/recovery/owner-controller.ts", import.meta.url), "utf8");
const js = ts.transpileModule(source, { compilerOptions: { target: ts.ScriptTarget.ES2020, module: ts.ModuleKind.ESNext } }).outputText;
const { OwnerCaseController } = await import(`data:text/javascript;base64,${Buffer.from(js).toString("base64")}`);
const snapshot = (id, revision = 1) => ({ case: { case_id: id, case_revision: revision }, event_cursor: revision });
const deferred = () => { let resolve; const promise = new Promise(r => resolve = r); return { promise, resolve }; };
const flush = () => new Promise(r => setImmediate(r));

test("slow previous case cannot replace current case or subscribe after disposal", async () => {
  const slow = deferred(), subscribed = [], updates = [];
  const transport = {
    get_case: id => id === "old" ? slow.promise : Promise.resolve(snapshot(id)),
    subscribe_case: id => { subscribed.push(id); return () => {}; },
  };
  const controller = new OwnerCaseController(transport, state => updates.push(state));
  const old = controller.open("old");
  await controller.open("new");
  slow.resolve(snapshot("old")); await old;
  assert.equal(controller.state.snapshot.case.case_id, "new");
  assert.deepEqual(subscribed, ["new"]);
  controller.dispose();
});

test("lost mutation response retries with the same idempotency key", async () => {
  const keys = [], command = { type: "start_assessment", expected_revision: 1 };
  const transport = {
    get_case: async id => snapshot(id), subscribe_case: () => () => {},
    command: async (id, input, key) => { keys.push(key); if (keys.length === 1) throw new Error("Network interrupted"); return { run_id: "r1" }; },
  };
  let key = 0;
  const controller = new OwnerCaseController(transport, () => {}, () => `key-${++key}`);
  await controller.open("c1");
  await assert.rejects(controller.command(command), /Network/);
  assert.equal(controller.state.busy, false);
  assert.equal((await controller.command(command)).run_id, "r1");
  assert.deepEqual(keys, ["key-1", "key-1"]);
  controller.dispose();
});

test("confirmed mutation stays successful if the following refresh fails", async () => {
  let gets = 0;
  const transport = {
    get_case: async id => { if (++gets > 1) throw new Error("Reload unavailable"); return snapshot(id); },
    subscribe_case: () => () => {}, command: async () => ({ run_id: "r1" }),
  };
  const controller = new OwnerCaseController(transport, () => {}, () => "k1");
  await controller.open("c1");
  const receipt = await controller.command({ type: "start_assessment", expected_revision: 1 });
  assert.equal(receipt.run_id, "r1");
  assert.match(controller.state.error, /Update saved/);
  controller.dispose();
});

test("event refreshes cannot regress a newer command snapshot", async () => {
  let subscription, calls = 0;
  const older = deferred();
  const transport = {
    get_case: async id => ++calls === 2 ? older.promise : snapshot(id, calls === 1 ? 1 : 3),
    subscribe_case: (id, args) => { subscription = args; return () => {}; },
    command: async () => ({ case_revision: 3 }),
  };
  const controller = new OwnerCaseController(transport, () => {}, () => "k1");
  await controller.open("c1");
  subscription.on_event({ case_id: "c1" });
  await controller.command({ type: "publish_notice", expected_revision: 1 });
  older.resolve(snapshot("c1", 2)); await flush();
  assert.equal(controller.state.snapshot.case.case_revision, 3);
  controller.dispose();
});

test("unsubscribes and ignores late callbacks after disposal", async () => {
  let subscription, stops = 0, updates = 0;
  const transport = {
    get_case: async id => snapshot(id),
    subscribe_case: (id, args) => { subscription = args; return () => { stops++; }; },
  };
  const controller = new OwnerCaseController(transport, () => { updates++; });
  await controller.open("c1");
  controller.dispose();
  const count = updates;
  subscription.on_connection("expired"); subscription.on_event({ case_id: "c1" });
  await flush();
  assert.equal(stops, 1); assert.equal(updates, count);
});
