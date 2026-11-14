import "./condition-value.css";
import { StatusMark } from "../recovery-ui";
import type { Comparable, OwnerCaseView } from "../../recovery/contracts";
import { formatSourceDate, formatUsd } from "./format";
import { evidenceForSource, evidenceKindLabel, labelOr } from "./model";

/* ---------- source references (shared with ValueTab) ---------- */

export type SourceRefsProps = {
  view: OwnerCaseView;
  source_ids: readonly string[];
  on_select_evidence: (evidence_id: string) => void;
  /** Lead-in text; defaults to "Sources". */
  label?: string;
};

/**
 * Source ids as small chips. An id that matches an evidence item's source_id becomes a button that selects that evidence;
 * an id with no matching evidence is shown as plain text, so nothing pretends to be inspectable when it is not.
 */
export function SourceRefs({ view, source_ids, on_select_evidence, label = "Sources" }: SourceRefsProps) {
  if (source_ids.length === 0) return null;
  return (
    <span className="rv-sources">
      <span className="rv-sources-label">{label}:</span>
      {[...new Set(source_ids)].map((id) => {
        const match = evidenceForSource(view, id)[0];
        if (!match) {
          return (
            <span key={id} className="rv-src rv-src--plain" title="No evidence item in this case matches this source">
              {id}
            </span>
          );
        }
        return (
          <button
            key={id}
            type="button"
            className="rv-src"
            title={`Show ${evidenceKindLabel(match.kind)}: ${match.source_label}`}
            onClick={() => on_select_evidence(match.evidence_id)}
          >
            {match.source_label}
          </button>
        );
      })}
    </span>
  );
}

/* ---------- comparable price ---------- */

/** price_status text that says the price was withheld: "Price not disclosed", "undisclosed", "not_disclosed", "Non-disclosed"... */
const SAYS_NOT_DISCLOSED = /\b(?:not disclosed|undisclosed|non ?disclosed)\b/;

const saysNotDisclosed = (status: string) => SAYS_NOT_DISCLOSED.test(status.toLowerCase().replace(/[_-]+/g, " "));

/**
 * The price shown for a comparable. A missing price is never $0 and never assumed to be "not disclosed": the reason comes
 * from price_status. `missing` is true when no dollar figure is shown.
 */
export function comparablePrice(c: Pick<Comparable, "price_usd" | "price_status">): { text: string; missing: boolean } {
  const status = typeof c.price_status === "string" ? c.price_status.trim() : "";
  if (typeof c.price_usd === "number" && Number.isFinite(c.price_usd)) return { text: formatUsd(c.price_usd), missing: false };
  if (c.price_usd != null) return { text: "Price unavailable (the source value is not a valid number)", missing: true };
  if (status !== "" && saysNotDisclosed(status)) return { text: "Price not disclosed", missing: true };
  if (status !== "") return { text: `No price on record (status: ${status})`, missing: true };
  return { text: "No price on record (no status given)", missing: true };
}

/* ---------- comparables disclosure ---------- */

const DATE_BASIS_LABEL: Record<Comparable["date_basis"], string> = {
  deed_recorded: "deed recorded",
  closed: "closed",
  unknown: "date basis unknown",
};

const ALLOCATED_LABEL = "Allocated share of a portfolio sale";

export type ComparablesListProps = {
  view: OwnerCaseView;
  comparables: readonly Comparable[];
  on_select_evidence: (evidence_id: string) => void;
};

/** "Comparables: N included, M excluded". Excluded comps stay listed (muted) with the reason they were left out. Server order is kept. */
export function ComparablesList({ view, comparables, on_select_evidence }: ComparablesListProps) {
  const included = comparables.filter((c) => c.included).length;
  const excluded = comparables.length - included;
  return (
    <details className="rv-comps">
      <summary className="rv-comps-summary">
        <span className="rv-comps-caret" aria-hidden="true" />
        Comparables: {included} included, {excluded} excluded
      </summary>
      {comparables.length === 0 ? (
        <p className="rv-comps-empty">No comparable sales were considered for this assessment.</p>
      ) : (
        <ul className="rv-comps-list">
          {comparables.map((c) => {
            const price = comparablePrice(c);
            const status = typeof c.price_status === "string" ? c.price_status.trim() : "";
            // Don't repeat a status that the price text or the allocation tag already says.
            const showStatus =
              status !== "" && !price.text.toLowerCase().includes(status.toLowerCase()) && !(c.allocated && status === ALLOCATED_LABEL);
            return (
              <li key={c.comp_id} className={c.included ? "rv-comp" : "rv-comp rv-comp--excluded"}>
                <div className="rv-comp-head">
                  <span className="rv-comp-label">{c.label}</span>
                  {c.included ? (
                    <StatusMark tone="info" shape="filled" label="Included" />
                  ) : (
                    <StatusMark tone="muted" shape="hatched" label="Excluded" />
                  )}
                </div>
                <div className="rv-comp-facts">
                  <span className={price.missing ? "rv-comp-price is-missing" : "rv-comp-price"}>{price.text}</span>
                  <span>
                    {formatSourceDate(c.transaction_date)} ({labelOr(DATE_BASIS_LABEL, c.date_basis, "date basis")})
                  </span>
                </div>
                {(showStatus || c.allocated) && (
                  <div className="rv-comp-status">
                    {showStatus && <span>Price status: {status}</span>}
                    {c.allocated && <span className="rv-tag">{ALLOCATED_LABEL}</span>}
                  </div>
                )}
                <p className="rv-comp-reason">
                  <span className="rv-comp-reason-label">{c.included ? "Why included:" : "Why excluded:"}</span> {c.reason}
                </p>
                <SourceRefs view={view} source_ids={c.source_ids} on_select_evidence={on_select_evidence} />
              </li>
            );
          })}
        </ul>
      )}
    </details>
  );
}
