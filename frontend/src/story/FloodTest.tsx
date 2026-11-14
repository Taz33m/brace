import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import "./story.css";

/**
 * The flood test. One real site from above, water standing where the ground is low, one number for what
 * it costs if nothing is done, and one button that spends a budget inside the hours left and shows what
 * that buys. Three steps, one key: Space or Enter moves on.
 */
const LEAD = 4303509;      // The Parker at Ellington: the Houston site that also has a scan of the inside
let started = false;       // once the flood has been run, another site opens straight on its flood
const WATER = [2, 4, 6], BUDGETS = [250_000, 500_000, 1_000_000], HOURS = [24, 48, 72];

interface Fix { measure: string; name: string; cost: number; crew_hours: number; saves: number }
interface Found { name: string; type: "quick" | "long-term"; price: number; price_high: number | null; price_unit: string; source: { title: string; url: string } | null; checked: boolean; planned: boolean; why_not: string | null }
interface Step { kind: "search" | "found"; text: string; checked?: boolean }
interface SiteRow { property_id: number; name: string; loss: number | null }
interface Row { id: string; polygon: [number, number][]; ground_m: number; perimeter_ft: number; value: number | null; depth_ft: number; loss: number | null; fix: Fix | null; left_out: string | null }
interface Result {
  name: string; homes: number | null; sale: { price: number; year: string | null } | null; bounds: [number, number, number, number]; aerial: { width: number; height: number };
  water_ft: number; buildings: Row[]; do_nothing: { loss: number | null; buildings_wet: number };
  plan: null | { budget: number; hours: number; crews: number; spent: number; buildings_protected: number; saved: number; loss: number; work_order: string; notice: string;
                 fixes: (Fix & { building: string })[]; tradeoffs: string[] };
  why: { text: string; source: string }[];
  research: { by: "agent" | "hand"; made_at: string | null; searches: number; found: Found[]; steps: Step[] };
  assumptions: string[]; measures: { id: string; name: string; type: string; source: { title: string; url: string } | null }[];
}
type Stage = "warning" | "flood" | "plan";

const short = (n: number) => (n >= 1e6 ? `$${(n / 1e6).toFixed(1)}M` : `$${Math.round(n / 1e3)}K`);
const round = (n: number) => short(n).replace(".0M", "M");
const read = (site: number, water: number, budget?: number, hours?: number): Promise<Result> =>
  fetch(`/api/flood/${site}?water_ft=${water}${budget != null ? `&budget=${budget}&hours=${hours}` : ""}`).then((r) => { if (!r.ok) throw new Error("no flood test for this site"); return r.json(); });

export function FloodTest({ site }: { site: number | null }) {
  const SITE = site ?? LEAD;
  const [water, setWater] = useState(4), [budget, setBudget] = useState(500_000), [hours, setHours] = useState(48);
  const [stage, setStage] = useState<Stage>(started ? "flood" : "warning");
  const [sites, setSites] = useState<SiteRow[]>([]);
  const [base, setBase] = useState<Result | null>(null);          // if nothing is done
  const [plan, setPlan] = useState<Result | null>(null);          // with the budget and the hours spent
  const [shown, setShown] = useState(0);                          // the number on the counter, as it runs
  const [panel, setPanel] = useState<null | "order" | "how">(null);
  const [steps, setSteps] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const counter = useRef(0);

  useEffect(() => { document.documentElement.classList.add("st-on"); return () => document.documentElement.classList.remove("st-on"); }, []);
  useEffect(() => { let on = true; setPlan(null); setSteps(0); read(SITE, water).then((r) => { if (on) setBase(r); }).catch((e) => { if (on) setError(e.message); }); return () => { on = false; }; }, [SITE, water]);
  useEffect(() => { let on = true; fetch(`/api/flood?water_ft=${water}`).then((r) => (r.ok ? r.json() : { sites: [] })).then((d) => { if (on) setSites(d.sites); }).catch(() => undefined); return () => { on = false; }; }, [water]);
  useEffect(() => { setStage((st) => (st === "plan" ? "flood" : st)); setPanel(null); }, [SITE]);

  // The counter runs to its number rather than jumping.
  const target = stage === "warning" ? 0 : stage === "plan" && plan?.plan ? plan.plan.loss : base?.do_nothing.loss ?? 0;
  useEffect(() => {
    const from = counter.current, t0 = performance.now(), ms = stage === "flood" ? 2400 : 1500;
    let raf = 0;
    const tick = (now: number) => {
      const k = Math.min(1, (now - t0) / ms), eased = 1 - Math.pow(1 - k, 3);
      counter.current = from + (target - from) * eased;
      setShown(counter.current);
      if (k < 1) raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [target, stage]);

  const protect = useCallback(() => {
    setSteps(0);
    read(SITE, water, budget, hours).then((r) => {
      setPlan(r); setStage("plan");
      Array.from({ length: 9 }, (_, i) => i + 1).forEach((n) => window.setTimeout(() => setSteps((s) => Math.max(s, n)), 420 * n));
    }).catch((e) => setError(e.message));
  }, [SITE, water, budget, hours]);
  const next = useCallback(() => {
    if (stage === "warning") { started = true; setStage("flood"); }
    else if (stage === "flood") protect();
    else setPanel((p) => (p === "order" ? null : "order"));
  }, [stage, protect]);
  useEffect(() => {
    const key = (e: KeyboardEvent) => {
      if (e.key === " " || e.key === "Enter") { e.preventDefault(); next(); }
      else if (e.key === "Escape") { if (panel) setPanel(null); else window.location.hash = "#/"; }
    };
    window.addEventListener("keydown", key);
    return () => window.removeEventListener("keydown", key);
  }, [next, panel]);
  // Changing a limit after the plan is made makes it again.
  useEffect(() => { if (stage === "plan") protect(); }, [budget, hours]);   // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { if (stage === "plan") setStage("flood"); }, [water]);    // eslint-disable-line react-hooks/exhaustive-deps

  const view = stage === "plan" && plan ? plan : base;
  const shapes = useMemo(() => {
    if (!view) return [];
    const [w, s, e, n] = view.bounds, W = view.aerial.width, H = view.aerial.height;
    return view.buildings.map((b) => ({ ...b, points: b.polygon.map(([lon, lat]) => `${(((lon - w) / (e - w)) * W).toFixed(1)},${(((n - lat) / (n - s)) * H).toFixed(1)}`).join(" ") }));
  }, [view]);

  if (error) return <div className="fatal" role="alert">{error}</div>;
  if (!base) return <div className="st-wait" />;
  const done = stage === "plan" && plan?.plan ? plan.plan : null;
  const wet = base.do_nothing.buildings_wet;
  const tooDeep = done && done.buildings_protected === 0 && plan!.buildings.some((b) => b.left_out?.startsWith("no barrier"));
  // What the agent did, in the order it did it: its searches, what it found, then why the plan is this plan.
  const research = base.research, confirmed = research.found.filter((f) => f.checked).length;
  const lines: { text: string; tag?: string }[] = !done ? [] : research.by === "agent"
    ? [...[...new Set(research.steps.filter((x) => x.kind === "search").map((x) => x.text))].slice(0, 3).map((text) => ({ text, tag: "Searched" })),
       { text: `${research.found.length} fixes found in ${research.searches} searches. ${confirmed} prices confirmed on the page`, tag: "Agent" },
       ...done.tradeoffs.slice(0, 4).map((text) => ({ text }))]
    : [{ text: `Ground level under ${base.buildings.length} buildings`, tag: "Vexcel" }, { text: `${wet} in the water, valued from the sale`, tag: "CoStar" },
       ...done.tradeoffs.slice(0, 4).map((text) => ({ text }))];

  return (
    <div className={`st ft is-${stage}`}>
      {/* A photo taller than it is wide is turned on its side, so the whole site fills a wide screen. */}
      <div className="ft-map" style={base.aerial.height > base.aerial.width
        ? { aspectRatio: `${base.aerial.width} / ${base.aerial.height}`, height: `max(100vw, calc(100vh * ${base.aerial.height / base.aerial.width}))`, transform: "translate(-50%, -50%) rotate(-90deg)" }
        : { aspectRatio: `${base.aerial.width} / ${base.aerial.height}`, width: `max(100vw, calc(100vh * ${base.aerial.width / base.aerial.height}))` }}>
        <img src={`/api/buildings/${SITE}/aerial.jpg`} alt="" draggable={false} />
        {WATER.map((ft) => <img key={ft} className="ft-water" src={`/api/flood/${SITE}/water.png?water_ft=${ft}`} alt="" draggable={false} style={{ opacity: stage !== "warning" && ft === water ? 1 : 0 }} />)}
        <svg viewBox={`0 0 ${base.aerial.width} ${base.aerial.height}`} aria-hidden="true">
          {stage !== "warning" && shapes.map((b) => (
            <polygon key={b.id} points={b.points} className={b.fix ? "is-safe" : b.depth_ft > 0 ? "is-wet" : ""} style={{ fillOpacity: b.fix ? 0.16 : Math.min(0.55, 0.12 + b.depth_ft * 0.07) }} />
          ))}
        </svg>
      </div>

      <a className="st-home" href="#/">Brace</a>
      <header className="ft-place">
        <h1>{base.name}</h1>
        <p>{[base.homes ? `${base.homes.toLocaleString("en-US")} homes` : "", base.sale ? `Last sold for ${short(base.sale.price)}` : ""].filter(Boolean).join(". ")}</p>
        {stage !== "warning" && sites.length > 1 && (
          <nav className="ft-sites" aria-label="Other sites">
            {sites.filter((x) => x.property_id !== SITE).map((x) => <a key={x.property_id} href={`#/flood/${x.property_id}`}>{x.name}{x.loss ? <small>−{short(x.loss)}</small> : null}</a>)}
          </nav>
        )}
      </header>

      {stage === "warning" ? (
        <div className="ft-warning">
          <h2>Flood incoming</h2>
          <p>{water} ft of water</p>
          <button type="button" onClick={next}>Run it</button>
        </div>
      ) : (
        <div className={`ft-counter${done ? " is-after" : ""}`} aria-live="polite">
          <span>{done ? "With the plan" : "If nothing is done"}</span>
          <strong>−{short(shown)}</strong>
          {done && done.buildings_protected > 0 && <em>{short(done.spent)} spent. {short(done.saved)} saved.</em>}
          {tooDeep && <em>No barrier holds {water} ft. Nothing can be bought in {hours} hours.</em>}
          {!done && stage === "flood" && <ul className="ft-why">{base.why.slice(0, 3).map((w) => <li key={w.text}>{w.text}<small>{w.source}</small></li>)}</ul>}
        </div>
      )}

      {stage === "plan" && done && done.buildings_protected > 0 && (
        <ol className="ft-steps">
          {lines.map((l, i) => <li key={l.text} className={steps > i ? "is-on" : ""}>{l.text}{l.tag && <small>{l.tag}</small>}</li>)}
        </ol>
      )}

      {stage !== "warning" && (
        <div className="ft-bar">
          <div role="group" aria-label="Water">{WATER.map((v) => <button key={v} type="button" aria-pressed={v === water} onClick={() => setWater(v)}>{v} ft</button>)}</div>
          <div role="group" aria-label="Budget">{BUDGETS.map((v) => <button key={v} type="button" aria-pressed={v === budget} onClick={() => setBudget(v)}>{round(v)}</button>)}</div>
          <div role="group" aria-label="Time left">{HOURS.map((v) => <button key={v} type="button" aria-pressed={v === hours} onClick={() => setHours(v)}>{v} h</button>)}</div>
          {stage === "flood" ? <button type="button" className="ft-go" onClick={protect}>Protect</button>
            : <button type="button" className="ft-go" onClick={() => setPanel(panel === "order" ? null : "order")} disabled={!done?.work_order}>Work order</button>}
        </div>
      )}
      <button type="button" className="ft-how" onClick={() => setPanel(panel === "how" ? null : "how")}>How this is worked out</button>

      {panel === "order" && done?.work_order && (
        <aside className="ft-panel">
          <table className="ft-plan"><tbody>
            {done.fixes.map((f) => <tr key={f.building}><th>{f.building}</th><td>{f.name}</td><td>{short(f.cost)}</td><td>saves {short(f.saves)}</td></tr>)}
          </tbody></table>
          <pre>{done.work_order}</pre>
          <pre>{done.notice}</pre>
        </aside>
      )}
      {panel === "how" && (
        <aside className="ft-panel">
          <ul>{base.assumptions.map((a) => <li key={a}>{a}</li>)}</ul>
          {research.found.length > 0 && (
            <ul className="ft-found">
              {research.found.map((f) => (
                <li key={f.name + f.price} className={f.planned ? "is-used" : ""}>
                  {f.source ? <a href={f.source.url} target="_blank" rel="noreferrer">{f.name}</a> : f.name}: ${f.price.toLocaleString("en-US")}{f.price_high ? ` to $${f.price_high.toLocaleString("en-US")}` : ""} {f.price_unit}
                  <small>{f.planned ? "used in the plan" : f.why_not}</small>
                </li>
              ))}
            </ul>
          )}
        </aside>
      )}
    </div>
  );
}
