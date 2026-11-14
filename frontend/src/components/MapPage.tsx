import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import { conversation } from "../conversation";
import { exposureLine, hours, money, num, when } from "../format";
import type { Portfolio, Scenario, ScenarioMap } from "../types";
import { ThreatMap } from "./ThreatMap";

interface Props {
  scenarios: Scenario[];
  scenario: Scenario;
  step: string | null;
  onScenario: (id: string) => void;
  onStep: (id: string) => void;
  onOpen: (id: number) => void;
}

export function MapPage({ scenarios, scenario, step, onScenario, onStep, onOpen }: Props) {
  const [map, setMap] = useState<ScenarioMap | null>(null);
  const [data, setData] = useState<Portfolio | null>(null);
  const [manager, setManager] = useState("");
  const [kind, setKind] = useState("");
  const [hover, setHover] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const list = useRef<HTMLElement>(null);

  // The conversation belongs to a building; leaving for the map ends it.
  useEffect(() => { conversation.stop(); }, []);
  useEffect(() => { setManager(""); setKind(""); }, [scenario.id]);
  useEffect(() => { if (list.current) list.current.scrollTop = 0; }, [scenario.id, step, manager, kind]);
  useEffect(() => {
    let live = true;
    setError(null);
    api.scenario(scenario.id, step).then((s) => live && setMap(s.map)).catch((e) => live && setError(e.message));
    return () => { live = false; };
  }, [scenario.id, step]);
  useEffect(() => {
    let live = true;
    api.portfolio(scenario.id, step, manager, kind).then((p) => live && setData(p)).catch((e) => live && setError(e.message));
    return () => { live = false; };
  }, [scenario.id, step, manager, kind]);

  const at = Math.max(0, scenario.steps.findIndex((s) => s.id === step));
  const current = scenario.steps[at];
  const what = scenario.kind === "hurricane" ? "in the forecast wind field" : "inside the warning area";

  return (
    <div className="map-page">
      <header className="mast">
        <div className="brand">Brace</div>
        <nav className="scenarios" aria-label="Forecast">
          {scenarios.map((s) => (
            <button key={s.id} className={s.id === scenario.id ? "on" : ""} onClick={() => onScenario(s.id)}>
              {s.name}<small>{s.live ? "Live" : "Replay"}, {s.city}</small>
            </button>
          ))}
        </nav>
        <a className="recover-link" href="#/recovery">Recover</a>
      </header>

      <section className="briefing">
        <div>
          <h1>{scenario.name}</h1>
          <p>{scenario.summary}</p>
        </div>
        {scenario.steps.length > 1 && (
          <div className="stepper">
            <label htmlFor="step">Forecast issued</label>
            <input id="step" type="range" min={0} max={scenario.steps.length - 1} step={1} value={at}
                   onChange={(e) => onStep(scenario.steps[Number(e.target.value)].id)} aria-valuetext={current?.label} />
            <output><strong>{current?.label}</strong><small>{when(current?.issued)}</small></output>
          </div>
        )}
      </section>

      <main className="map-body">
        <ThreatMap map={map} points={data?.points ?? []} highlight={hover} onOpen={onOpen} />
        <aside className="ranked" ref={list} aria-label="Buildings to act on first">
          {error && <p className="notice bad">{error}</p>}
          {!data && !error && <p className="notice">Working out which buildings this forecast touches…</p>}
          {data && (
            <>
              <div className="tally">
                <h2>{num(data.shown)} buildings {what}</h2>
                <p>{num(data.homes)} apartment homes and {num(data.tenants)} business tenants in them.
                  {scenario.live ? "" : " This is a replay of a real forecast."}</p>
                {data.value.buildings_with_sale > 0 && (
                  <p className="value">
                    <strong>{money(data.value.last_sale_total)}</strong> is what {num(data.value.buildings_with_sale)} of these buildings last sold for.
                    <small> Last recorded sale prices going back to {data.value.oldest_sale?.slice(0, 4)}, not today's value and not a loss estimate
                      {data.value.allocated_share ? `; ${num(data.value.allocated_share)} are estimated shares of portfolio sales` : ""}.</small>
                  </p>
                )}
              </div>
              <div className="filters">
                <select value={manager} onChange={(e) => setManager(e.target.value)} aria-label="Property manager">
                  <option value="">Every property manager</option>
                  {data.managers.map((m) => <option key={m.name} value={m.name}>{m.name} ({m.buildings})</option>)}
                </select>
                <select value={kind} onChange={(e) => setKind(e.target.value)} aria-label="Building type">
                  <option value="">Every building type</option>
                  {data.types.map((t) => <option key={t.name} value={t.name}>{t.name} ({t.buildings})</option>)}
                </select>
              </div>
              {data.shown === 0 && <p className="notice">Nothing in this portfolio is touched at this point in the forecast. Move the slider or clear the filters.</p>}
              <ol className="rows">
                {data.buildings.map((b) => (
                  <li key={b.id}>
                    <button onClick={() => onOpen(b.id)} onMouseEnter={() => setHover(b.id)} onMouseLeave={() => setHover(null)}
                            onFocus={() => setHover(b.id)} onBlur={() => setHover(null)}>
                      <span className="rank">{b.rank}</span>
                      <span className="who">
                        <strong>{b.name}</strong>
                        <small>{b.type_label}{b.units ? `, ${num(b.units)} homes` : b.tenant_count ? `, ${b.tenant_count} tenants` : ""}{b.manager ? `. Managed by ${b.manager}` : ""}</small>
                        <span className="clock">{exposureLine(b.exposure)}{b.hours_left == null ? "" : b.hours_left <= 0 ? ", already here" : `, arriving in ${hours(b.hours_left)}`}</span>
                        {b.reasons.length > 0 && (
                          <span className="reasons">{b.reasons.slice(0, 4).map((r) => <span key={r}>{r}</span>)}</span>
                        )}
                        {b.plan && <span className="planned">Plan ready: {b.plan.actions} actions</span>}
                      </span>
                    </button>
                  </li>
                ))}
              </ol>
              {data.shown > data.buildings.length && <p className="more">Showing the first {data.buildings.length} of {num(data.shown)}. Filter by manager to see a portfolio.</p>}
            </>
          )}
        </aside>
      </main>
    </div>
  );
}
