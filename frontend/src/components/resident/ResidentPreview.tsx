/**
 * Explicit, opt-in preview of the resident experience against an injected fake API.
 * Visible fixture banner; synthetic data; never mounted by the production path.
 *
 * Open in dev: http://localhost:5174/src/components/resident/preview.html
 * (add ?scenario=<id> to start in a scenario; see SCENARIOS in fixtures/fakeApi.ts).
 */
import { useMemo, useState } from "react";
import { ResidentExperience } from "./ResidentExperience";
import { FakeResidentApi, SCENARIOS, type Scenario } from "./fixtures/fakeApi";
import "./preview.css";

function initialScenario(): Scenario {
  const q = new URLSearchParams(window.location.search).get("scenario");
  return (SCENARIOS.find((s) => s.value === q)?.value ?? "happy") as Scenario;
}

export function ResidentPreview() {
  const [scenario, setScenario] = useState<Scenario>(initialScenario);
  const [run, setRun] = useState(0);
  const [log, setLog] = useState<string[]>([]);
  const [expiredCalls, setExpiredCalls] = useState(0);
  const api = useMemo(() => new FakeResidentApi(scenario), [scenario, run]);

  const act = (label: string, f: () => string) => {
    const result = f();
    setLog((l) => [`${new Date().toLocaleTimeString()} · ${label}: ${result}`, ...l].slice(0, 8));
  };

  const restart = (s: Scenario) => {
    setScenario(s);
    setRun((r) => r + 1);
    setLog([]);
    setExpiredCalls(0);
    const url = new URL(window.location.href);
    url.searchParams.set("scenario", s);
    window.history.replaceState(null, "", url);
  };

  const controls = (
    <div className="rp-controls">
      <label className="rp-field">
        <span>Scenario</span>
        <select value={scenario} onChange={(e) => restart(e.target.value as Scenario)}>
          {SCENARIOS.map((s) => (
            <option key={s.value} value={s.value}>{s.label}</option>
          ))}
        </select>
      </label>
      <p className="rp-detail">{SCENARIOS.find((s) => s.value === scenario)?.detail}</p>
      <div className="rp-buttons">
        <button type="button" onClick={() => act("Owner reviews report", () => api.reviewLatestReport())}>Owner reviews latest report</button>
        <button type="button" onClick={() => act("Advance task", () => api.advanceTask())}>Owner/crew advance task</button>
        <button type="button" onClick={() => act("Publish notice", () => api.publishNotice())}>Owner publishes notice</button>
        <button type="button" onClick={() => act("Drop connection", () => api.dropConnection())}>Drop connection 4s</button>
        <button type="button" onClick={() => act("Expire session", () => api.expire())}>Expire session</button>
        <button type="button" onClick={() => restart(scenario)}>Reset fixture</button>
      </div>
      <p className="rp-detail">on_session_expired called: <strong>{expiredCalls}</strong></p>
      {log.length ? (
        <ol className="rp-log" aria-label="Fixture actions">
          {log.map((l, i) => <li key={i}>{l}</li>)}
        </ol>
      ) : null}
    </div>
  );

  return (
    <div className="rp-page">
      <div className="rp-banner" role="note">
        <strong>UI fixture</strong> — synthetic data, not a property assessment. Nothing here is sent anywhere.
        <details className="rp-mobile-controls">
          <summary>Fixture controls</summary>
          {controls}
        </details>
      </div>
      <div className="rp-stage">
        <div className="rp-frame">
          <div className="rp-scroll">
            <ResidentExperience key={`${scenario}-${run}`} api={api} on_session_expired={() => setExpiredCalls((n) => n + 1)} />
          </div>
        </div>
        <aside className="rp-side">{controls}</aside>
      </div>
    </div>
  );
}

export default ResidentPreview;
