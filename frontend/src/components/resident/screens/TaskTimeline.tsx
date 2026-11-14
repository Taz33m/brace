/**
 * Vertical progress for one repair task, using the shared TASK_STEPS wording.
 *
 * - A cancelled task has no progress to show; the caller shows the Cancelled pill instead.
 * - A proposed task shows "Planned" as the current step and nothing after it as done or booked.
 * - Each step carries a screen-reader prefix so "done / now / not yet" is not colour-only.
 */
import type { ResidentTask } from "../contract";
import { TASK_STEPS, taskStepStates } from "../lib/status";
import { IconCheck } from "../icons";

const SR_PREFIX = { done: "Done: ", current: "Now: ", todo: "Not yet: " } as const;

export function TaskTimeline({ task }: { task: Pick<ResidentTask, "status"> }) {
  if (task.status === "cancelled") return null;
  const states = taskStepStates(task.status);
  return (
    <ol className="r-steps" aria-label="Repair progress">
      {TASK_STEPS.map((step, i) => {
        const state = states[i];
        return (
          <li
            key={step.status}
            className={`r-step${state === "todo" ? "" : ` ${state}`}`}
            aria-current={state === "current" ? "step" : undefined}
          >
            <span className="r-step-dot" aria-hidden="true">
              {state === "done" ? <IconCheck size={14} strokeWidth={2.75} /> : null}
            </span>
            <span className="r-step-text">
              <span className="r-sr">{SR_PREFIX[state]}</span>
              {step.label}
            </span>
          </li>
        );
      })}
    </ol>
  );
}
