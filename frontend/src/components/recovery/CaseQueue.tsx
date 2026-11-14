// Left queue: recovery cases in exactly the order the server sent them. No ranking, no risk score.
import type { RecoveryCaseSummary } from "../../recovery/contracts";
import { EmptyState, Panel } from "../recovery-ui";
import { formatSourceDate } from "./format";
import { CASE_MODE_LABEL, labelOr, lookupKnown } from "./model";

export type CaseQueueProps = {
  cases: RecoveryCaseSummary[];
  selected_case_id: string | null;
  on_open_case: (case_id: string) => void;
};

function count(n: number, one: string, many: string) {
  return `${n} ${n === 1 ? one : many}`;
}

export function CaseQueue({ cases, selected_case_id, on_open_case }: CaseQueueProps) {
  return (
    <Panel title="Recovery cases" aside={<span>{cases.length}</span>} className="rq-panel">
      {cases.length === 0 ? (
        <EmptyState title="No recovery cases yet">When a recovery case is opened for a property, it appears here.</EmptyState>
      ) : (
        <>
          <p className="rq-order-note">In the order the server lists them. Not ranked.</p>
          <ul className="rq-list">
            {cases.map((c) => {
              const selected = c.case_id === selected_case_id;
              return (
                <li key={c.case_id}>
                  <button
                    type="button"
                    className={["rq-row", selected && "is-selected"].filter(Boolean).join(" ")}
                    aria-current={selected ? "true" : undefined}
                    onClick={() => on_open_case(c.case_id)}
                  >
                    <span className="rq-name">{c.property_name}</span>
                    <span className="rq-city">{c.city}</span>
                    <span className="rq-incident">
                      {c.incident_name} · {formatSourceDate(c.incident_at)}
                    </span>
                    <span className={`rq-mode rq-mode--${lookupKnown(CASE_MODE_LABEL, c.mode) !== undefined ? c.mode : "unknown"}`}>
                      {labelOr(CASE_MODE_LABEL, c.mode, "mode")}
                    </span>
                    <span className="rq-counts">
                      <span className={c.pending_reports > 0 ? "rq-count is-open" : "rq-count"}>{count(c.pending_reports, "pending report", "pending reports")}</span>
                      <span className={c.pending_tasks > 0 ? "rq-count is-open" : "rq-count"}>{count(c.pending_tasks, "pending task", "pending tasks")}</span>
                    </span>
                    <span className="rq-next">
                      <span className="rq-next-label">Next</span> {c.next_action}
                    </span>
                  </button>
                </li>
              );
            })}
          </ul>
        </>
      )}
    </Panel>
  );
}
