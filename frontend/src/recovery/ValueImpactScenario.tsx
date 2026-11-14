import { useEffect, useId, useRef, useState } from "react";
import type { FormEvent } from "react";
import type { MoneyRange } from "../../../docs/recovery-handoffs/shared-contract";
import { createRecoveryClient, RecoveryApiError } from "./client";
import type { ImpactAssumptions, ImpactInputs, ImpactResult } from "./impact";
import "./value-impact.css";

const api = createRecoveryClient();
const usd = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 });
const quantity = new Intl.NumberFormat("en-US", { maximumFractionDigits: 1 });
const empty = { affected_percent: "", unit_cost_low: "", unit_cost_high: "", affected_units: "", monthly_income_per_unit: "", downtime_months: "" };
type Field = keyof ImpactAssumptions;
const fields: { key: Field; label: string; unit: string; max: number; step: string }[] = [
  { key: "affected_percent", label: "Affected share of footprint", unit: "%", max: 100, step: "any" },
  { key: "unit_cost_low", label: "Repair rate · low", unit: "$/sq ft", max: 1000000, step: "any" },
  { key: "unit_cost_high", label: "Repair rate · high", unit: "$/sq ft", max: 1000000, step: "any" },
  { key: "affected_units", label: "Homes with lost income", unit: "homes", max: 1000000, step: "1" },
  { key: "monthly_income_per_unit", label: "Monthly lost income per home", unit: "$/month", max: 1000000, step: "any" },
  { key: "downtime_months", label: "Income interruption", unit: "months", max: 120, step: "any" },
];
function money(range: MoneyRange) {
  if (range.low === null || range.high === null) return "Not available";
  return range.low === range.high ? usd.format(range.low) : `${usd.format(range.low)} – ${usd.format(range.high)}`;
}

/** Owner-entered what-if only. Never writes an assessment or asserts detected damage. */
export function ValueImpactScenario({ case_id, analysis_revision, on_session_expired }: {
  case_id: string; analysis_revision: number; on_session_expired: () => void;
}) {
  const uid = useId();
  const [inputs, setInputs] = useState<ImpactInputs | null>(null);
  const [structureId, setStructureId] = useState("");
  const [values, setValues] = useState(empty);
  const [result, setResult] = useState<ImpactResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [reload, setReload] = useState(0);
  const pending = useRef<AbortController | null>(null);
  const expired = useRef(on_session_expired);
  expired.current = on_session_expired;

  useEffect(() => {
    const controller = new AbortController();
    setInputs(null); setResult(null); setError(null);
    api.get_value_impact(case_id, controller.signal).then(data => {
      if (controller.signal.aborted) return;
      if (data.case_id !== case_id || data.analysis_revision !== analysis_revision) {
        throw new Error("Case inputs changed. Reload the case to use the latest evidence.");
      }
      setInputs(data); setStructureId(data.structures.find(row => row.footprint_sqft !== null)?.structure_id ?? "");
    }).catch(problem => {
      if (controller.signal.aborted) return;
      if (problem instanceof RecoveryApiError && [401, 403].includes(problem.status)) expired.current();
      else setError(problem instanceof Error ? problem.message : "Could not load source quantities.");
    });
    return () => { controller.abort(); pending.current?.abort(); };
  }, [case_id, analysis_revision, reload]);

  const structure = inputs?.structures.find(row => row.structure_id === structureId);
  const ready = !!structure && structure.footprint_sqft !== null && Object.values(values).every(value => value.trim() !== "" && Number.isFinite(Number(value)) && Number(value) >= 0);
  function invalidate() { pending.current?.abort(); pending.current = null; setBusy(false); setResult(null); setError(null); }
  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!ready || !inputs || busy) return;
    if (Number(values.unit_cost_low) > Number(values.unit_cost_high)) { setError("The high repair rate must be at least the low repair rate."); return; }
    const controller = new AbortController();
    pending.current?.abort(); pending.current = controller;
    setBusy(true); setError(null); setResult(null);
    try {
      const assumptions = Object.fromEntries(Object.entries(values).map(([key, value]) => [key, Number(value)])) as unknown as ImpactAssumptions;
      const next = await api.preview_value_impact(case_id, { ...assumptions, structure_id: structureId, expected_analysis_revision: inputs.analysis_revision }, controller.signal);
      if (!controller.signal.aborted && next.case_id === case_id && next.analysis_revision === analysis_revision) setResult(next);
    } catch (problem) {
      if (!controller.signal.aborted) {
        if (problem instanceof RecoveryApiError && [401, 403].includes(problem.status)) expired.current();
        else setError(problem instanceof Error ? problem.message : "Could not calculate this scenario.");
      }
    } finally { if (!controller.signal.aborted) { setBusy(false); pending.current = null; } }
  }
  return <section className="brace-impact" aria-labelledby={`${uid}-title`}>
    <header className="brace-impact-header"><div><span className="brace-impact-eyebrow">Vexcel quantities × CoStar market data</span>
      <h3 id={`${uid}-title`}>What could recovery cost?</h3></div><span className="brace-impact-badge">Owner scenario</span></header>
    <p className="brace-impact-intro">Connect the building’s measured footprint to your repair and income assumptions. Preview the potential impact before requesting an inspection or quote.</p>
    {!inputs && !error && <p role="status">Loading building quantities and comparable benchmark…</p>}
    {inputs && <>
      <div className="brace-impact-source-row"><div><span>CoStar comparable benchmark</span><strong>{inputs.benchmark.point === null ? "Not available" : usd.format(inputs.benchmark.point)}</strong>
        <small>Unadjusted market proxy · not pre-disaster appraised value</small></div><div><span>Vexcel footprint</span><strong>{structure?.footprint_sqft == null ? "Not available" : `${quantity.format(structure.footprint_sqft)} sq ft`}</strong>
        <small>{structure?.analysis_date ? `Source analysis · ${structure.analysis_date}` : "Source analysis date unknown"}</small></div></div>
      <form onSubmit={submit}>
        <label className="brace-impact-structure" htmlFor={`${uid}-structure`}>Structure
          <select id={`${uid}-structure`} value={structureId} onChange={event => { invalidate(); setStructureId(event.target.value); }}>
            {inputs.structures.map(row => <option key={row.structure_id} value={row.structure_id}>{row.label} · {row.footprint_sqft === null ? "area unavailable" : `${quantity.format(row.footprint_sqft)} sq ft`}</option>)}
          </select></label>
        <p className="brace-impact-hint">Enter your assumptions below. Footprint is a plan-area proxy, not measured roof surface or detected damage. Use 0 only when you intend no impact for that input.</p>
        <div className="brace-impact-inputs">{fields.map(field => <label key={field.key} htmlFor={`${uid}-${field.key}`}>{field.label}<div>
          <input id={`${uid}-${field.key}`} type="number" min="0" max={field.key === "affected_units" ? inputs.subject_units ?? field.max : field.max}
            step={field.step} value={values[field.key]} placeholder="Enter assumption" required
            onChange={event => { invalidate(); setValues(current => ({ ...current, [field.key]: event.target.value })); }} />
          <span>{field.unit}</span></div></label>)}</div>
        <button className="brace-impact-calculate" type="submit" disabled={!ready || busy}>{busy ? "Calculating…" : "Preview value impact"}<span aria-hidden="true">↗</span></button>
      </form>
    </>}
    {error && <p className="brace-impact-error" role="alert">{error}{!inputs && <button type="button" onClick={() => setReload(n => n + 1)}>Retry</button>}</p>}
    {result && <div className="brace-impact-result" aria-live="polite">
      <div className="brace-impact-result-title"><span>Conditional cost exposure</span><strong>{money(result.total_cost)}</strong><p>Under your assumptions · not observed market-value loss</p></div>
      <div className="brace-impact-breakdown"><div><span>Repair proxy</span><strong>{money(result.repair_cost)}</strong><small>{result.quantity_sqft === null ? "Quantity unavailable" : `${quantity.format(result.quantity_sqft)} sq ft affected under your scenario`}</small></div>
        <div><span>Income interruption</span><strong>{money(result.disruption_cost)}</strong><small>{result.assumptions.affected_units} homes × {result.assumptions.downtime_months} months</small></div></div>
      <div className="brace-impact-remainder"><span>Comparable benchmark less scenario costs</span><strong>{money(result.current_range)}</strong><small>Uses the benchmark’s comparable dispersion. This is a scenario remainder, not an as-is appraisal.</small></div>
      <p className="brace-impact-hint">{result.summary}</p>
      <p className="brace-impact-hint">Preview only. Your assessment and resident updates have not changed.</p>
    </div>}
    {inputs && <details className="brace-impact-details"><summary>Sources, method &amp; limitations</summary>
      <p>Affected area = footprint × your affected share. Repair proxy = affected area × your rate range. Income interruption = homes × monthly lost income × months.</p>
      <p>{inputs.benchmark.method}</p>
      {structure?.source_id && <p>Footprint source: {structure.source_id}</p>}
      <ul>{Array.from(new Set([...(inputs.limitations ?? []), ...(result?.limitations ?? [])])).map(item => <li key={item}>{item}</li>)}</ul>
    </details>}
  </section>;
}
