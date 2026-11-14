import "./condition-value.css";
import { useId, useState } from "react";
import type { ReactNode } from "react";
import { Button, ChangedBanner, EmptyState, InlineError, RangeList, RangeRow, StatusMark, rangeDomain } from "../recovery-ui";
import type { ToneMark } from "../recovery-ui";
import type { Assessment, Assumption, MoneyRange, OwnerCaseView, RepairLine, ValueBasis } from "../../recovery/contracts";
import type { CommandRunner } from "./commands";
import { SourceRefs, ComparablesList } from "./ComparablesList";
import {
  VALUE_BASIS_HELP,
  VALUE_BASIS_LABEL,
  describeMoneyRange,
  describeMoneyRangeCompact,
  formatSourceDate,
  formatTimestamp,
  formatUsd,
  rangeKindLabel,
} from "./format";
import {
  assessmentHistory,
  assessmentStaleness,
  assessmentStateLabel,
  assessmentStatusLabel,
  assessmentStatusTone,
  bindingLabel,
  commandKey,
  currentAssessment,
  humanizeCode,
  isSupersededAssessment,
  labelOr,
  lookupKnown,
} from "./model";
import type { AssessmentStaleness } from "./model";

export type ValueTabProps = {
  view: OwnerCaseView;
  busy: boolean;
  runner: CommandRunner;
  on_select_evidence: (evidence_id: string) => void;
  value_slot?: ReactNode;
};

const BASIS_TONE: Record<ValueBasis, ToneMark> = {
  market_supported: { tone: "info", shape: "filled" },
  conditional: { tone: "pending", shape: "hollow" },
  insufficient_evidence: { tone: "muted", shape: "hatched" },
};

const ASSUMPTION_BASIS_LABEL: Record<Assumption["basis"], string> = {
  source: "From a source",
  user_supplied: "Owner supplied",
  scenario: "Scenario assumption",
};

/** For a valuation basis this screen does not recognise: neutral, never the market-supported look. */
const UNKNOWN_BASIS_TONE: ToneMark = { tone: "neutral", shape: "hollow" };

const basisLabel = (b: string) => labelOr(VALUE_BASIS_LABEL, b, "basis");

const RANGE_KINDS: Readonly<Record<string, true>> = {
  source_range: true,
  scenario: true,
  comparable_dispersion: true,
  calibrated_confidence: true,
};

/** The range-kind label; a kind this screen does not know is never presented as a confidence interval. */
function rangeKindText(kind: MoneyRange["range_kind"]): string {
  if (lookupKnown(RANGE_KINDS, kind)) return rangeKindLabel(kind);
  return `${humanizeCode(kind) || "Unknown"} range (unrecognised kind), not a confidence interval`;
}

/** Why Run assessment is available although runs are in progress: they were started on inputs that have since changed. */
function outdatedRunsText(view: OwnerCaseView, runs: Assessment[]): string {
  const latest = runs[0];
  const started = formatTimestamp(latest.created_at);
  const now = view.case.analysis_revision;
  const lead =
    runs.length === 1
      ? `A run started ${started} is still in progress on analysis revision ${latest.base_analysis_revision}, but the case is now at revision ${now}, so it will finish stale.`
      : `${runs.length} runs on older inputs are still in progress (latest started ${started}, on analysis revision ${latest.base_analysis_revision}); the case is now at revision ${now}, so they will finish stale.`;
  return `${lead} You can run a new assessment on the latest inputs.`;
}

/** True when the assessment was built on the case's latest analysis inputs. */
const isUpToDate = (view: OwnerCaseView, a: Assessment) => a.status !== "stale" && a.base_analysis_revision >= view.case.analysis_revision;

/** A draft can be published only while its inputs are still the case's current inputs. The server checks again. */
const canPublish = (view: OwnerCaseView, a: Assessment) => a.status === "draft" && isUpToDate(view, a);

/** Banner titles. Only a draft or a never-published stale run is ever called unpublishable; a published one never is. */
const STALE_TITLE: Record<AssessmentStaleness, string> = {
  published: "Inputs changed after this assessment was published; its figures may be out of date. Run a new assessment.",
  draft: "Inputs changed after this draft was built; it can't be published until it's re-run.",
  stale_run: "This run finished after its inputs changed. It's kept as history; it can't be published.",
  outdated: "Inputs changed after this assessment was built; its figures may be out of date. Run a new assessment.",
};

function revisionNote(view: OwnerCaseView, a: Assessment): string {
  return a.base_analysis_revision < view.case.analysis_revision
    ? `Built on analysis revision ${a.base_analysis_revision}; the case is now at revision ${view.case.analysis_revision}.`
    : "The server marked it stale: its inputs changed while it ran.";
}

const newestFirst = (a: Assessment, b: Assessment) => (Date.parse(b.created_at) || 0) - (Date.parse(a.created_at) || 0);

export function ValueTab({ view, busy, runner, on_select_evidence, value_slot }: ValueTabProps) {
  const current = currentAssessment(view);
  const staleness = current ? assessmentStaleness(view, current) : null;
  const stale = staleness != null;
  const history = assessmentHistory(view);
  const locked = busy || runner.anyPending;
  const uid = useId();

  // A run on the current inputs blocks a new one (the server would hand back the same run). A run whose inputs are
  // already out of date will finish stale, so it does not block a run on the latest inputs.
  const active = view.assessments.filter((a) => a.status === "running").sort(newestFirst);
  const blockingRun = active.find((a) => a.base_analysis_revision >= view.case.analysis_revision) ?? null;
  const outdatedRuns = active.filter((a) => a.base_analysis_revision < view.case.analysis_revision);

  const startKey = commandKey.startAssessment(view.case.case_id);
  const start = runner.status(startKey);

  return (
    <div className="rv-tab">
      {value_slot}
      {current && staleness && (
        <ChangedBanner tone="stale" title={STALE_TITLE[staleness]}>
          {revisionNote(view, current)}{" "}
          {staleness === "published"
            ? "The figures below are as published, on the older inputs."
            : "Run a new assessment to use the latest inputs. The figures below are kept for reference only."}
        </ChangedBanner>
      )}

      <div className="rv-controls">
        <Button
          variant={current == null || stale ? "primary" : "default"}
          onClick={() => void runner.run(startKey, { type: "start_assessment" })}
          disabled={locked || blockingRun != null}
          pending={start.pending}
          pendingLabel="Starting…"
        >
          Run assessment
        </Button>
        {blockingRun ? (
          <p className="rv-hint">
            Run assessment is unavailable: a run on the current inputs (analysis revision {blockingRun.base_analysis_revision}) is already in
            progress, started {formatTimestamp(blockingRun.created_at)}. Its results appear here when the server reports them.
          </p>
        ) : (
          outdatedRuns.length > 0 && <p className="rv-hint">{outdatedRunsText(view, outdatedRuns)}</p>
        )}
      </div>
      {start.error && (
        <InlineError
          message={`Could not start the assessment. ${start.error}`}
          onRetry={() => void runner.retry(startKey)}
          retrying={start.pending}
          onDismiss={() => runner.dismiss(startKey)}
        />
      )}

      {current == null ? (
        <EmptyState title="No assessment yet">
          Run an assessment to estimate value, repair cost and downtime from the evidence in this case.
        </EmptyState>
      ) : (
        <>
          <AssessmentHeader view={view} a={current} stale={stale} locked={locked} runner={runner} />
          <section className="rv-section" aria-labelledby={`${uid}-valuation`}>
            <h3 id={`${uid}-valuation`} className="rv-h">
              Valuation
              {stale && <span className="rv-h-note">from a stale assessment</span>}
            </h3>
            {current.valuation == null ? (
              <EmptyState title="No valuation yet">
                {current.status === "running"
                  ? "This assessment is still running."
                  : current.status === "failed"
                    ? "This assessment failed before producing a valuation."
                    : "This assessment did not include a valuation."}
              </EmptyState>
            ) : (
              <Valuation view={view} a={current} on_select_evidence={on_select_evidence} />
            )}
          </section>
          {current.unresolved_questions.length > 0 && (
            <section className="rv-section" aria-labelledby={`${uid}-questions`}>
              <h3 id={`${uid}-questions`} className="rv-h">
                Unresolved questions
              </h3>
              <ul className="rv-list">
                {current.unresolved_questions.map((q, i) => (
                  <li key={i}>{q}</li>
                ))}
              </ul>
            </section>
          )}
        </>
      )}

      {history.length > 0 && (
        <section className="rv-section rv-history" aria-labelledby={`${uid}-history`}>
          <h3 id={`${uid}-history`} className="rv-h">
            Assessment history
            <span className="rv-h-count">{history.length}</span>
          </h3>
          <ol className="rv-history-list">
            {history.map((a) => (
              <HistoryItem key={a.assessment_id} view={view} a={a} locked={locked} runner={runner} on_select_evidence={on_select_evidence} />
            ))}
          </ol>
        </section>
      )}
    </div>
  );
}

/* ---------- current assessment header ---------- */

function AssessmentHeader({
  view,
  a,
  stale,
  locked,
  runner,
}: {
  view: OwnerCaseView;
  a: Assessment;
  stale: boolean;
  locked: boolean;
  runner: CommandRunner;
}) {
  const mark = assessmentStatusTone(a.status);
  const showStaleMark = stale && a.status !== "stale";
  const headingId = useId();
  return (
    <section className={stale ? "rv-current is-stale" : "rv-current"} aria-labelledby={headingId}>
      <div className="rv-current-marks">
        <span className="rv-eyebrow">Current assessment</span>
        <StatusMark {...mark} label={assessmentStatusLabel(a.status)} />
        {showStaleMark && <StatusMark tone="pending" shape="hatched" label="Stale: inputs changed" />}
      </div>
      <h3 id={headingId} className="rv-headline">
        {a.headline}
      </h3>
      {a.summary.trim() !== "" && <p className="rv-summary">{a.summary}</p>}
      {a.status === "failed" && (
        <p className="rv-failure">
          <strong>Run failed:</strong> {a.failure_reason ?? "No reason was given."}
        </p>
      )}
      <dl className="rv-meta">
        <div>
          <dt>Created</dt>
          <dd>{formatTimestamp(a.created_at)}</dd>
        </div>
        <div>
          <dt>Published</dt>
          <dd>{a.published_at ? formatTimestamp(a.published_at) : "Not published"}</dd>
        </div>
        <div>
          <dt>Inputs</dt>
          <dd>
            Based on analysis revision {a.base_analysis_revision} of {view.case.analysis_revision}
          </dd>
        </div>
      </dl>
      {canPublish(view, a) && <PublishControl view={view} a={a} locked={locked} runner={runner} />}
    </section>
  );
}

function PublishControl({ view, a, locked, runner }: { view: OwnerCaseView; a: Assessment; locked: boolean; runner: CommandRunner }) {
  const key = commandKey.publishAssessment(view.case.case_id, a.assessment_id);
  const s = runner.status(key);
  return (
    <div className="rv-publish">
      <Button
        variant="primary"
        onClick={() => void runner.run(key, { type: "publish_assessment", assessment_id: a.assessment_id })}
        disabled={locked}
        pending={s.pending}
        pendingLabel="Publishing…"
      >
        Publish
      </Button>
      <span className="rv-hint">Draft, not published. Publishing makes it the owner-facing assessment of record.</span>
      {s.error && (
        <InlineError
          message={`Could not publish. ${s.error}`}
          onRetry={() => void runner.retry(key)}
          retrying={s.pending}
          onDismiss={() => runner.dismiss(key)}
        />
      )}
    </div>
  );
}

/* ---------- valuation ---------- */

/** Numbers a range contributes to a shared domain. Unavailable or inconsistent ranges contribute nothing. */
function domainValues(r: MoneyRange): (number | null)[] {
  const d = describeMoneyRange(r);
  return d.state === "unavailable" || d.state === "invalid" ? [] : [r.low, r.high, r.point];
}

function Valuation({ view, a, on_select_evidence }: { view: OwnerCaseView; a: Assessment; on_select_evidence: (id: string) => void }) {
  const v = a.valuation;
  if (!v) return null;
  const basisMark = lookupKnown(BASIS_TONE, v.basis) ?? UNKNOWN_BASIS_TONE;
  const valueDomain = rangeDomain([...domainValues(v.benchmark), ...domainValues(v.current_condition), ...domainValues(v.after_repair)]);
  const costDomain = rangeDomain([0, ...domainValues(v.repair_cost), ...domainValues(v.downtime_cost)]);
  const rowProps = { view, valuationBasis: v.basis, on_select_evidence };

  return (
    <div className="rv-valuation">
      <div className={`rv-basis rv-basis--${v.basis}`}>
        <div className="rv-basis-line">
          <span className="rv-basis-key">Basis</span>
          <StatusMark {...basisMark} label={basisLabel(v.basis)} />
          <span className="rv-basis-date">Effective {formatSourceDate(v.effective_at)}</span>
        </div>
        <p className="rv-basis-help">
          {lookupKnown(VALUE_BASIS_HELP, v.basis) ?? "This screen does not recognise this basis. Treat the figures below with caution."}
        </p>
      </div>

      <div className="rv-block" role="group" aria-label="Market value">
        <p className="rv-block-title">Market value</p>
        <RangeList>
          <MoneyRow label="Benchmark" r={v.benchmark} domain={valueDomain} {...rowProps} />
          <MoneyRow label="Current condition" r={v.current_condition} domain={valueDomain} emphasis {...rowProps} />
          <MoneyRow label="After repair" r={v.after_repair} domain={valueDomain} {...rowProps} />
        </RangeList>
        <p className="rv-caption">
          "After repair" assumes the repair scope is completed. It is an estimate, not a result: no work is approved or done because of it.
        </p>
      </div>

      <div className="rv-block rv-costs" role="group" aria-label="Costs (not a change in market value)">
        <p className="rv-block-title">Costs (not a change in market value)</p>
        <RangeList>
          <MoneyRow label="Repair cost" r={v.repair_cost} domain={costDomain} {...rowProps} />
          <MoneyRow label="Downtime cost" r={v.downtime_cost} domain={costDomain} {...rowProps} />
        </RangeList>
      </div>

      <RepairLines view={view} lines={v.repair_lines} on_select_evidence={on_select_evidence} />

      <ComparablesList view={view} comparables={v.comparables} on_select_evidence={on_select_evidence} />

      <div className="rv-block">
        <p className="rv-block-title">Assumptions</p>
        {v.assumptions.length === 0 ? (
          <p className="rv-none">No assumptions were recorded.</p>
        ) : (
          <ul className="rv-assumptions">
            {v.assumptions.map((as) => (
              <li key={as.assumption_id} className="rv-assumption">
                <div className="rv-assumption-line">
                  <span className="rv-assumption-label">{as.label}</span>
                  <span className={`rv-tag rv-tag--${as.basis}`}>{labelOr(ASSUMPTION_BASIS_LABEL, as.basis, "basis")}</span>
                </div>
                <p className="rv-assumption-value">{as.value}</p>
                <SourceRefs view={view} source_ids={as.source_ids} on_select_evidence={on_select_evidence} />
              </li>
            ))}
          </ul>
        )}
      </div>

      {v.limitations.length > 0 && (
        <div className="rv-block">
          <p className="rv-block-title">Limitations</p>
          <ul className="rv-list">
            {v.limitations.map((l, i) => (
              <li key={i}>{l}</li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

function MoneyRow({
  view,
  label,
  r,
  domain,
  emphasis = false,
  valuationBasis,
  on_select_evidence,
}: {
  view: OwnerCaseView;
  label: string;
  r: MoneyRange;
  domain: [number, number];
  emphasis?: boolean;
  valuationBasis: ValueBasis;
  on_select_evidence: (id: string) => void;
}) {
  const d = describeMoneyRangeCompact(r);
  const unavailable = d.state === "unavailable" || d.state === "invalid";
  const note = (
    <span className="rv-row-note">
      {d.detail && <span className={d.state === "invalid" ? "rv-row-reason is-invalid" : "rv-row-reason"}>{d.detail}</span>}
      <span>
        {r.method}
        {/* The range kind only means something when there is a range to describe. */}
        {d.state === "range" || d.state === "range_with_point" ? <> · {rangeKindText(r.range_kind)}</> : null}
        {r.basis !== valuationBasis && <> · basis: {basisLabel(r.basis)}</>}
      </span>
      <SourceRefs view={view} source_ids={r.source_ids} on_select_evidence={on_select_evidence} />
    </span>
  );
  return (
    <RangeRow
      label={label}
      readout={d.text}
      low={unavailable ? null : r.low}
      high={unavailable ? null : r.high}
      point={unavailable ? null : r.point}
      domain={domain}
      emphasis={emphasis}
      unavailable={unavailable}
      note={note}
    />
  );
}

/* ---------- repair lines ---------- */

function rateText(line: RepairLine): string {
  const { rate_low_usd: lo, rate_high_usd: hi } = line;
  const unit = line.quantity_unit.trim() === "" ? "" : ` / ${line.quantity_unit}`;
  if (lo === null && hi === null) return "Rate unknown";
  const part = (n: number | null) => (n === null ? "Rate unknown" : formatUsd(n));
  if (lo !== null && hi !== null && lo === hi) return `${formatUsd(lo)}${unit}`;
  return `${part(lo)}–${part(hi)}${unit}`;
}

function quantityText(line: RepairLine): string {
  if (line.quantity === null) return "Quantity unknown";
  return `${line.quantity.toLocaleString("en-US")} ${line.quantity_unit}`.trim();
}

function RepairLines({ view, lines, on_select_evidence }: { view: OwnerCaseView; lines: RepairLine[]; on_select_evidence: (id: string) => void }) {
  return (
    <div className="rv-block">
      <p className="rv-block-title">Repair lines</p>
      {lines.length === 0 ? (
        <p className="rv-none">No repair lines in this assessment.</p>
      ) : (
        <div className="rv-table-wrap" tabIndex={0} role="region" aria-label="Repair lines (scrolls sideways)">
          <table className="rv-table">
            <thead>
              <tr>
                <th scope="col">Item</th>
                <th scope="col">Quantity</th>
                <th scope="col">Rate</th>
                <th scope="col" className="rv-num">
                  Total
                </th>
              </tr>
            </thead>
            <tbody>
              {lines.map((l) => {
                const total = describeMoneyRangeCompact(l.total);
                const totalMissing = total.state === "unavailable" || total.state === "invalid";
                return (
                  <tr key={l.line_id}>
                    <td>
                      <span className="rv-line-desc">{l.description}</span>
                      <span className="rv-line-sub">{l.location ? `${l.location.label} (${bindingLabel(l.location.binding)})` : "No location"}</span>
                      <SourceRefs view={view} source_ids={l.source_ids} on_select_evidence={on_select_evidence} />
                    </td>
                    <td>
                      {quantityText(l)}
                      {l.quantity_basis.trim() !== "" && <span className="rv-line-sub">{l.quantity_basis}</span>}
                    </td>
                    <td className={l.rate_low_usd === null && l.rate_high_usd === null ? "rv-missing" : undefined}>{rateText(l)}</td>
                    <td className={totalMissing ? "rv-num rv-missing" : "rv-num"}>
                      {total.text}
                      {total.detail && <span className="rv-line-sub">{total.detail}</span>}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

/* ---------- history ---------- */

/** A note for a past assessment whose inputs changed. Superseded and published ones never get "can't be published". */
function historyStaleNote(view: OwnerCaseView, a: Assessment): string | null {
  if (isSupersededAssessment(view, a)) return null;
  switch (assessmentStaleness(view, a)) {
    case "draft":
      return "Inputs changed after this draft was built; it can't be published until it's re-run.";
    case "stale_run":
      return "Finished after its inputs changed. Kept as history; it can't be published.";
    case "published":
      return "Inputs changed after it was published; its figures may be out of date.";
    default:
      return null;
  }
}

function HistoryItem({ view, a, locked, runner, on_select_evidence }: {
  view: OwnerCaseView; a: Assessment; locked: boolean; runner: CommandRunner; on_select_evidence: (id: string) => void;
}) {
  const [reviewOpen, setReviewOpen] = useState(false);
  const superseded = isSupersededAssessment(view, a);
  const mark: ToneMark = superseded ? { tone: "muted", shape: "hatched" } : assessmentStatusTone(a.status);
  const outdated = superseded || a.status === "stale" || (a.status === "draft" && !isUpToDate(view, a));
  const staleNote = historyStaleNote(view, a);
  return (
    <li className={outdated ? "rv-past is-outdated" : "rv-past"}>
      <div className="rv-past-head">
        <StatusMark {...mark} label={assessmentStateLabel(view, a)} />
        <span className="rv-past-date">{formatTimestamp(a.created_at)}</span>
      </div>
      <p className="rv-past-title">{a.headline}</p>
      <p className="rv-past-meta">
        Analysis revision {a.base_analysis_revision}
        {a.published_at && <> · published {formatTimestamp(a.published_at)}</>}
        {a.valuation && <> · basis: {basisLabel(a.valuation.basis)}</>}
      </p>
      {a.status === "failed" && <p className="rv-past-meta">Failed: {a.failure_reason ?? "No reason was given."}</p>}
      {staleNote && <p className="rv-past-meta">{staleNote}</p>}
      {a.valuation && <details className="rv-draft-review" onToggle={event => setReviewOpen(event.currentTarget.open)}>
        <summary>{a.status === "draft" ? "Review draft valuation before publishing" : "Review assessment valuation"}</summary>
        {a.status === "draft" && <p className="rv-past-meta">This draft is separate from the published assessment. Reviewing it does not publish it.</p>}
        {a.summary.trim() !== "" && <p className="rv-summary">{a.summary}</p>}
        {reviewOpen && <Valuation view={view} a={a} on_select_evidence={on_select_evidence} />}
        {a.unresolved_questions.length > 0 && <><h4>Unresolved questions</h4><ul className="rv-list">
          {a.unresolved_questions.map((question, index) => <li key={index}>{question}</li>)}
        </ul></>}
      </details>}
      {canPublish(view, a) && <PublishControl view={view} a={a} locked={locked} runner={runner} />}
    </li>
  );
}
