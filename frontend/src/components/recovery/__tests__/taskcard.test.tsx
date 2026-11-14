import type { OwnerCaseView, RecoveryTask, TaskStatus } from "../../../recovery/contracts";
import { fixtureSnapshot } from "../fixtures/preview-fixture";
import { TASK_NEXT, TASK_STATUS_LABEL } from "../model";
import { TaskCard } from "../TaskCard";
import { assert, assertEqual, assertIncludes, assertNotIncludes, render, test } from "./harness";
import { fakeRunner, noop, textOf } from "./test-utils";

/** Every action label TaskCard might show for some target. Used to check only TASK_NEXT targets appear. */
const ACTION_LABEL: Record<TaskStatus, string> = {
  proposed: "Mark proposed",
  approved: "Approve",
  accepted: "Record acceptance",
  in_progress: "Mark in progress",
  completion_submitted: "Submit completion",
  verified: "Verify completion",
  cancelled: "Cancel task",
};

function card(view: OwnerCaseView, task: RecoveryTask, opts: { busy?: boolean; anyPending?: boolean } = {}): string {
  return render(
    <TaskCard
      task={task}
      view={view}
      busy={opts.busy ?? false}
      runner={fakeRunner({}, opts.anyPending ?? false)}
      on_focus={noop}
      on_select_evidence={noop}
    />,
  );
}

function taskWith(status: TaskStatus): { view: OwnerCaseView; task: RecoveryTask } {
  const view = fixtureSnapshot("full");
  const task = view.tasks.find((t) => t.status === status);
  assert(task, `fixture has a ${status} task`);
  return { view, task };
}

/** Buttons rendered by the card, as their visible text. */
function buttonTexts(html: string): string[] {
  return [...html.matchAll(/<button\b[^>]*>([\s\S]*?)<\/button>/g)].map((m) => textOf(m[1]));
}

test("TaskCard: proposed task never reads as accepted or booked", () => {
  const { view, task } = taskWith("proposed");
  const text = textOf(card(view, task));
  assertIncludes(text, TASK_STATUS_LABEL.proposed);
  assertNotIncludes(text, "Accepted", "no accepted wording on a proposed task");
  assertNotIncludes(text.toLowerCase(), "contractor on the way");
  // "booked" may only appear negated ("not booked").
  for (const m of text.toLowerCase().matchAll(/booked/g)) {
    const before = text.toLowerCase().slice(Math.max(0, (m.index ?? 0) - 6), m.index);
    assertIncludes(before, "not", `"booked" must be negated, got "...${before}booked"`);
  }
  assertIncludes(text, "Schedule not confirmed");
});

test("TaskCard: null confirmed_schedule reads 'Schedule not confirmed' for every status", () => {
  const view = fixtureSnapshot("full");
  for (const status of Object.keys(TASK_NEXT) as TaskStatus[]) {
    const task = { ...view.tasks[0], status, confirmed_schedule: null };
    const text = textOf(card(view, task));
    assertIncludes(text, "Schedule not confirmed", status);
  }
});

test("TaskCard: a schedule on an approved (unaccepted) task is still not shown as confirmed", () => {
  const { view, task } = taskWith("approved");
  const text = textOf(card(view, { ...task, confirmed_schedule: "2024-07-20" }));
  assertIncludes(text, "Schedule not confirmed");
});

test("TaskCard: superseded_scope shows the changed-scope banner with the previous scope struck through", () => {
  const { view, task } = taskWith("approved");
  assert(task.superseded_scope, "fixture approved task has superseded_scope");
  const html = card(view, task);
  assertIncludes(html, 'role="status"', "ChangedBanner rendered");
  assertIncludes(textOf(html), "Scope changed");
  assertIncludes(html, `<s>${task.superseded_scope}</s>`);
  assertIncludes(textOf(html), task.scope, "current scope is shown");

  const plain = card(view, { ...task, superseded_scope: null });
  assertNotIncludes(textOf(plain), "Scope changed", "no banner without superseded_scope");
});

test("TaskCard: only TASK_NEXT targets are offered as actions", () => {
  const view = fixtureSnapshot("full");
  for (const status of Object.keys(TASK_NEXT) as TaskStatus[]) {
    const task = view.tasks.find((t) => t.status === status);
    assert(task, `fixture has a ${status} task`);
    const buttons = buttonTexts(card(view, task));
    const allowed = new Set(TASK_NEXT[status].map((t) => ACTION_LABEL[t]));
    const offered = buttons.filter((b) => Object.values(ACTION_LABEL).includes(b));
    assertEqual([...offered].sort(), [...allowed].sort(), `${status} actions`);
  }
});

test("TaskCard: actions are disabled while busy or any command is pending", () => {
  const { view, task } = taskWith("proposed");
  for (const opts of [{ busy: true }, { anyPending: true }]) {
    const html = card(view, task, opts);
    const approve = [...html.matchAll(/<button\b([^>]*)>([\s\S]*?)<\/button>/g)].find((m) => textOf(m[2]) === "Approve");
    assert(approve, "Approve button present");
    assertIncludes(approve[1], "disabled", JSON.stringify(opts));
  }
});
