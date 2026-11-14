// The command runner's React-free core: scope reset, late settles, double runs, retry and error messages.
import type { OwnerCommand } from "../../../recovery/contracts";
import { COMMAND_FALLBACK_ERROR, commandErrorMessage, createCommandStore } from "../commands";
import type { CommandBody } from "../commands";
import { assert, assertEqual, test } from "./harness";

type Deferred = { promise: Promise<void>; resolve: () => void; reject: (e: unknown) => void };

function deferred(): Deferred {
  let resolve!: () => void;
  let reject!: (e: unknown) => void;
  const promise = new Promise<void>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

/** A stand-in for the parent's on_command: records every command and settles only when the test says so. */
function fakeServer() {
  const sent: { command: OwnerCommand; answer: Deferred }[] = [];
  const on_command = (command: OwnerCommand) => {
    const answer = deferred();
    sent.push({ command, answer });
    return answer.promise;
  };
  return { sent, on_command };
}

const NOTICE_A: CommandBody = { type: "publish_notice", title: "Case A notice", body: "Only for case A.", household_ids: null, source_ids: [] };
const NOTICE_B: CommandBody = { type: "publish_notice", title: "Case B notice", body: "Only for case B.", household_ids: null, source_ids: [] };
const IDLE = { pending: false, error: null };

test("commands/store: run injects the latest revision, is pending until the server answers, then idle", async () => {
  const srv = fakeServer();
  const store = createCommandStore({ on_command: srv.on_command, case_revision: 4, scope: "case-a" });
  store.setRevision(5);
  const before = store.getState();
  const done = store.run("notice:publish", NOTICE_A);
  assertEqual(store.status("notice:publish"), { pending: true, error: null });
  assertEqual(store.getState().anyPending, true);
  assert(store.getState() !== before, "every change produces a new state object");
  assertEqual(srv.sent.length, 1);
  assertEqual(srv.sent[0].command, { ...NOTICE_A, expected_revision: 5 } as OwnerCommand);

  srv.sent[0].answer.resolve();
  assertEqual(await done, true);
  assertEqual(store.status("notice:publish"), IDLE);
  assertEqual(store.getState().anyPending, false);
  assertEqual(await store.retry("notice:publish"), false, "nothing to retry after a success");
});

test("commands/store: a second run of a pending key is ignored (no double send)", async () => {
  const srv = fakeServer();
  const store = createCommandStore({ on_command: srv.on_command, case_revision: 1, scope: "case-a" });
  const first = store.run("assessment:start", { type: "start_assessment" });
  const second = store.run("assessment:start", { type: "start_assessment" });
  assertEqual(await second, false, "the double click resolves false at once");
  assertEqual(srv.sent.length, 1, "only one command reached the server");
  srv.sent[0].answer.resolve();
  assertEqual(await first, true);
});

test("commands/store: an uncertain failure retries the exact original revision after an SSE update", async () => {
  const srv = fakeServer();
  const store = createCommandStore({ on_command: srv.on_command, case_revision: 7, scope: "case-a" });
  const key = "task:fx-task-membrane:accepted";
  const body: CommandBody = {
    type: "transition_task",
    task_id: "fx-task-membrane",
    expected_task_revision: 3,
    status: "accepted",
    note: "",
    confirmation_source: "Signed work order (test)",
    evidence_ids: [],
  };
  const first = store.run(key, body);
  srv.sent[0].answer.reject({ error: { code: "unavailable", message: "Service unavailable (test)", retryable: true } });
  assertEqual(await first, false);
  assertEqual(store.status(key), { pending: false, error: "Service unavailable (test)" });

  store.setRevision(9);
  const again = store.retry(key);
  assertEqual(store.status(key), { pending: true, error: null }, "retry clears the error while pending");
  assertEqual(srv.sent.length, 2);
  // Same body and original case revision keep the parent's idempotency signature intact.
  assertEqual(srv.sent[1].command, { ...body, expected_revision: 7 } as OwnerCommand);
  srv.sent[1].answer.resolve();
  assertEqual(await again, true);
  assertEqual(store.status(key), IDLE);
  assertEqual(await store.retry("never-run"), false, "retry without a stored body sends nothing");
  assertEqual(srv.sent.length, 2);
});

test("commands/store: notice resubmission after a lost response preserves the original request", async () => {
  const srv = fakeServer();
  const store = createCommandStore({ on_command: srv.on_command, case_revision: 2, scope: "case-a" });
  const first = store.run("notice:publish", NOTICE_A);
  srv.sent[0].answer.reject(new Error("Response lost after commit"));
  await first;
  store.setRevision(3);
  const repeated = store.run("notice:publish", { ...NOTICE_A });
  assertEqual(srv.sent[1].command, srv.sent[0].command, "NoticeComposer calls run again; it must also preserve revision");
  srv.sent[1].answer.resolve();
  assertEqual(await repeated, true);
});

test("commands/store: a definite rejection permits a later attempt with the fresh revision", async () => {
  const srv = fakeServer();
  const store = createCommandStore({ on_command: srv.on_command, case_revision: 2, scope: "case-a" });
  const first = store.run("notice:publish", NOTICE_A);
  srv.sent[0].answer.reject({ status: 409, error: { code: "revision_conflict", message: "The case changed." } });
  await first;
  store.setRevision(3);
  const repeated = store.retry("notice:publish");
  assertEqual(srv.sent[1].command, { ...NOTICE_A, expected_revision: 3 });
  srv.sent[1].answer.resolve();
  assertEqual(await repeated, true);
});

test("commands/store: changing the scope clears every pending flag, error and stored body", async () => {
  const srv = fakeServer();
  const store = createCommandStore({ on_command: srv.on_command, case_revision: 12, scope: "case-a" });
  const failed = store.run("notice:publish", NOTICE_A);
  srv.sent[0].answer.reject(new Error("Publish failed in case A (test)"));
  await failed;
  void store.run("assessment:start", { type: "start_assessment" }); // still in flight
  assertEqual(store.getState().anyPending, true);
  assertEqual(store.status("notice:publish").error, "Publish failed in case A (test)");

  let notified = 0;
  store.subscribe(() => {
    notified += 1;
  });
  store.setScope("case-b");
  assertEqual(notified, 1, "subscribers hear about the reset");
  assertEqual(store.getState(), { scope: "case-b", statuses: {}, anyPending: false });
  assertEqual(store.status("notice:publish"), IDLE, "case A's error is not shown in case B");
  assertEqual(store.status("assessment:start"), IDLE, "case A's pending command is not shown in case B");
  assertEqual(await store.retry("notice:publish"), false, "Retry in case B cannot re-send case A's notice");
  assertEqual(srv.sent.length, 2, "nothing was re-sent");

  store.setScope("case-b");
  assertEqual(notified, 1, "the same scope again changes nothing");
});

test("commands/store: a promise that settles after the scope changed writes nothing into the new scope", async () => {
  // Late failure.
  const srv = fakeServer();
  const store = createCommandStore({ on_command: srv.on_command, case_revision: 3, scope: "case-a" });
  const lateA = store.run("notice:publish", NOTICE_A);
  store.setScope("case-b");
  const inB = store.run("notice:publish", NOTICE_B);
  assertEqual(srv.sent.length, 2, "the same key can run in the new scope right away");
  srv.sent[0].answer.reject(new Error("Case A failed late (test)"));
  assertEqual(await lateA, false);
  assertEqual(store.status("notice:publish"), { pending: true, error: null }, "case B's command is still pending, without case A's error");

  // A late success must not clear the new scope's pending flag (or let its double click through).
  const lateB = store.run("assessment:start", { type: "start_assessment" });
  store.setScope("case-c");
  const inC = store.run("assessment:start", { type: "start_assessment" });
  srv.sent[2].answer.resolve();
  assertEqual(await lateB, false, "a late answer is not reported as success to the new scope");
  assertEqual(store.status("assessment:start"), { pending: true, error: null });
  assertEqual(await store.run("assessment:start", { type: "start_assessment" }), false, "still guarded against a double run");

  srv.sent[3].answer.resolve();
  assertEqual(await inC, true);
  assertEqual(store.getState(), { scope: "case-c", statuses: {}, anyPending: false });
  srv.sent[1].answer.resolve(); // case B's command, answered after case C opened
  assertEqual(await inB, false);
  assertEqual(store.getState(), { scope: "case-c", statuses: {}, anyPending: false });
});

test("commands/store: dismiss clears an error, is ignored while pending, and drops the Retry body", async () => {
  const srv = fakeServer();
  const store = createCommandStore({ on_command: srv.on_command, case_revision: 2, scope: "case-a" });
  let notified = 0;
  const unsubscribe = store.subscribe(() => {
    notified += 1;
  });
  const run = store.run("invite:fx-hh-2b", { type: "create_invitation", household_id: "fx-hh-2b" });
  store.dismiss("invite:fx-hh-2b");
  assertEqual(store.status("invite:fx-hh-2b").pending, true, "dismiss is ignored while pending");
  srv.sent[0].answer.reject("Invitation service down (test)");
  await run;
  assertEqual(store.status("invite:fx-hh-2b"), { pending: false, error: "Invitation service down (test)" });
  store.dismiss("invite:fx-hh-2b");
  assertEqual(store.status("invite:fx-hh-2b"), IDLE);
  assertEqual(await store.retry("invite:fx-hh-2b"), false, "a dismissed command cannot be retried");
  assertEqual(notified, 3, "pending, failed, dismissed");
  unsubscribe();
  void store.run("invite:fx-hh-3c", { type: "create_invitation", household_id: "fx-hh-3c" });
  assertEqual(notified, 3, "no notifications after unsubscribe");
});

test("commands/store: a handler that throws synchronously is reported like a rejection", async () => {
  const store = createCommandStore({
    on_command: () => {
      throw new Error("Adapter misconfigured (test)");
    },
    case_revision: 1,
    scope: null,
  });
  assertEqual(await store.run("assessment:start", { type: "start_assessment" }), false);
  assertEqual(store.status("assessment:start"), { pending: false, error: "Adapter misconfigured (test)" });
});

test("commands/errors: commandErrorMessage handles Error, ApiErrorBody, strings and junk", () => {
  assertEqual(commandErrorMessage(new Error("Boom")), "Boom");
  assertEqual(commandErrorMessage({ error: { code: "revision_conflict", message: "This case changed.", retryable: true, current_revision: 12 } }), "This case changed.");
  assertEqual(commandErrorMessage({ error: { code: "x", message: "   ", retryable: false } }), COMMAND_FALLBACK_ERROR, "blank ApiErrorBody message");
  assertEqual(commandErrorMessage({ error: "not an object" }), COMMAND_FALLBACK_ERROR);
  assertEqual(commandErrorMessage("Network down"), "Network down");
  assertEqual(commandErrorMessage(null), COMMAND_FALLBACK_ERROR);
  assertEqual(commandErrorMessage(new Error("")), COMMAND_FALLBACK_ERROR);
});
