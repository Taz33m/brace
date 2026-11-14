import { useEffect, useMemo, useState } from "react";
import { api } from "../api";
import { modelHash } from "../recovery/routes";
import type { Board, BoardStage, FactSource, FindHit, ResidentReport, SiteFact, SiteModel, Stage, StageKey } from "../types";
import "./site-model.css";

/** The six stages in the order a storm runs, with the one word each is known by. */
const NAME: Record<StageKey, string> = { join: "Join", classify: "Classify", inventory: "Inventory", expose: "Expose", surface: "Surface", search: "Search" };
const ORDER: StageKey[] = ["join", "classify", "inventory", "expose", "surface", "search"];

const sourceLine = (s: FactSource) =>
  [s.provider, s.what, s.name ? `"${s.name}"` : null, s.collection ? `flight ${s.collection}` : null, s.model ? `scan ${s.model}` : null,
    s.captured ? `dated ${s.captured}` : null].filter(Boolean).join(", ");

export function SiteModelPage({ id }: { id: number | null }) {
  return id == null ? <AllSites /> : <OneSite id={id} />;
}

/** One address: the six stages across the top, every fact below, and what any fact rests on beside it. */
function OneSite({ id }: { id: number }) {
  const [model, setModel] = useState<SiteModel | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [stage, setStage] = useState<StageKey | null>(null);
  const [picked, setPicked] = useState<SiteFact | null>(null);
  const [reload, setReload] = useState(0);

  useEffect(() => {
    let current = true;
    api.siteModel(id).then((m) => { if (current) { setModel(m); setError(null); } }).catch((e: Error) => { if (current) setError(e.message); });
    return () => { current = false; };
  }, [id, reload]);

  const facts = useMemo(() => (model?.facts ?? []).filter((f) => !stage || f.stage === stage), [model, stage]);
  if (error) return <div className="fatal" role="alert">{error}</div>;
  if (!model) return <div className="fatal quiet" role="status">Assembling the site model…</div>;

  return (
    <div className="sm">
      <header className="sm-head">
        <div>
          <p className="sm-eyebrow">Site model</p>
          <h1>{model.name}</h1>
          <p className="sm-sub">{model.address}. {model.structures.length} roofs, {model.scans.length} scans, {Object.keys(model.sources).length} sources.</p>
        </div>
        <a className="sm-link" href={modelHash()}>All addresses</a>
      </header>

      <ol className="sm-pipe" aria-label="The six stages">
        {model.stages.map((s, i) => (
          <li key={s.key}>
            <button className={`sm-stage is-${s.state}`} aria-pressed={stage === s.key} onClick={() => { setStage(stage === s.key ? null : s.key); setPicked(null); }}>
              <span className="sm-step">{i + 1}</span>
              <span className="sm-name">{NAME[s.key]}</span>
              <strong>{s.state === "not_run" ? "–" : s.number.toLocaleString()}</strong>
              <span className="sm-unit">{s.state === "not_run" ? "not run for this address" : s.unit}</span>
              <span className="sm-problem">{s.problem}</span>
            </button>
          </li>
        ))}
      </ol>

      <div className="sm-body">
        <section className="sm-facts" aria-label="What is known about this address">
          {ORDER.filter((k) => !stage || k === stage).map((k) => {
            const rows = facts.filter((f) => f.stage === k);
            const s = model.stages.find((x) => x.key === k) as Stage;
            return (
              <div key={k} className="sm-group">
                <h2>{NAME[k]} <span>{s.job}</span></h2>
                {s.limits && <p className="sm-limit">{s.limits}</p>}
                {rows.length === 0 && <p className="sm-none">{s.state === "not_run" ? "This stage has not run for this address, so there is nothing here." : "Nothing recorded."}</p>}
                <ul>
                  {rows.map((f, i) => (
                    <li key={i}>
                      <button className={`${picked === f ? "is-picked" : ""}${f.report ? " is-report" : ""}`} onClick={() => setPicked(f)}>
                        <strong>{f.label}</strong><span>{f.text}</span>
                      </button>
                    </li>
                  ))}
                </ul>
              </div>
            );
          })}
        </section>

        <aside className="sm-side">
          <section className="sm-trace" aria-live="polite">
            <h2>Where this comes from</h2>
            {!picked && <p className="sm-none">Pick any line. Every fact in the model names the capture, flight or scan it rests on.</p>}
            {picked && <>
              <p className="sm-quote"><strong>{picked.label}.</strong> {picked.text}</p>
              <ul className="sm-sources">
                {picked.sources.map((s) => (
                  <li key={s.id} className={`is-${(s.provider ?? "").toLowerCase()}`}>
                    <b>{s.provider ?? "Unknown"}</b>
                    <span>{sourceLine({ ...s, provider: undefined })}</span>
                    {s.note && <small>{s.note}</small>}
                  </li>
                ))}
              </ul>
              {picked.how && <p className="sm-how"><b>How</b>{picked.how}</p>}
              {picked.limits && <p className="sm-how is-limit"><b>What it cannot tell you</b>{picked.limits}</p>}
            </>}
          </section>
          <Find id={id} />
          <Report id={id} scans={model.scans} reports={model.reports} onFiled={() => setReload((n) => n + 1)} />
        </aside>
      </div>
    </div>
  );
}

/** The search stage, live: describe a thing and get the rooms that show it. */
function Find({ id }: { id: number }) {
  const [query, setQuery] = useState("");
  const [found, setFound] = useState<{ said: string; hits: FindHit[] } | null>(null);
  const [busy, setBusy] = useState(false);
  const run = (e: React.FormEvent) => {
    e.preventDefault();
    if (!query.trim()) return;
    setBusy(true);
    api.find(id, query.trim()).then(setFound).catch(() => setFound({ said: "The search could not be run.", hits: [] })).finally(() => setBusy(false));
  };
  return (
    <section className="sm-tool">
      <h2>Find in the scans</h2>
      <form onSubmit={run}>
        <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="sliding door, water heater, ceiling fan" aria-label="What to find" />
        <button disabled={busy}>Find</button>
      </form>
      {found && <>
        <p className="sm-said">{found.said}</p>
        <ul className="sm-hits">
          {found.hits.map((h, i) => (
            <li key={i}><strong>{h.thing ?? h.room}</strong><span>{h.room}, {h.scan_name}{h.direction ? `, to the ${h.direction}` : ""}</span></li>
          ))}
        </ul>
      </>}
    </section>
  );
}

/** After the event: what a resident reports is filed against the room it names, in the same model. */
function Report({ id, scans, reports, onFiled }: { id: number; scans: { id: string; name: string }[]; reports: ResidentReport[]; onFiled: () => void }) {
  const [text, setText] = useState("");
  const [scan, setScan] = useState("");
  const [error, setError] = useState<string | null>(null);
  const file = (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    api.report(id, text, scan || null).then(() => { setText(""); onFiled(); }).catch((err: Error) => setError(err.message));
  };
  return (
    <section className="sm-tool">
      <h2>After the event</h2>
      <p className="sm-none">A resident's report is filed against the room and fixture it names, beside what was known before. It is recorded as reported; nothing is sent.</p>
      <form onSubmit={file} className="sm-report">
        <input value={text} onChange={(e) => setText(e.target.value)} placeholder="Water is coming in under the balcony sliding door" aria-label="What the resident reports" />
        <select value={scan} onChange={(e) => setScan(e.target.value)} aria-label="Which home">
          <option value="">Any scanned home</option>
          {scans.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
        </select>
        <button disabled={!text.trim()}>File it</button>
      </form>
      {error && <p className="sm-limit">{error}</p>}
      <ul className="sm-hits">
        {[...reports].reverse().map((r) => (
          <li key={r.id}>
            <strong>{r.where ? `${r.where.room ?? "A room"}${r.where.thing ? `, at the ${r.where.thing}` : ""}` : "Not matched to a scanned room"}</strong>
            <span>“{r.text}”{r.where ? ` ${r.where.scan_name}.` : ""} {r.status}.</span>
          </li>
        ))}
      </ul>
      {reports.length > 0 && <button className="sm-clear" onClick={() => api.clearReports(id).then(onFiled)}>Clear these reports</button>}
    </section>
  );
}

const total = (s: BoardStage): [string, string] => {
  const n = s.number.toLocaleString();
  switch (s.key) {
    case "join": return [`${n} of ${s.of}`, `scans fitted to a roof${s.median_move_m != null ? `, moved a median ${s.median_move_m.toFixed(1)} m` : ""}`];
    case "classify": return [`${n} of ${s.of}`, "scanned rooms typed"];
    case "inventory": return [n, "things counted and placed"];
    case "expose": return [`${n} of ${s.of}`, "scans with a defurnished copy found"];
    case "surface": return [n, "roofs measured for height"];
    case "search": return [`${n} of ${s.of.toLocaleString()}`, "scan positions described"];
  }
};

/** Every gathered address: how far each stage has run, with nothing filled in where it has not. */
function AllSites() {
  const [board, setBoard] = useState<Board | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => { api.board().then(setBoard).catch((e: Error) => setError(e.message)); }, []);
  if (error) return <div className="fatal" role="alert">{error}</div>;
  if (!board) return <div className="fatal quiet" role="status">Assembling the site models…</div>;
  return (
    <div className="sm">
      <header className="sm-head">
        <div>
          <p className="sm-eyebrow">Site models</p>
          <h1>{board.sites} addresses, six stages, one model each</h1>
          <p className="sm-sub">Each stage writes into the same object for an address. The planner and the voice read that object; what residents report afterwards lands in it too.</p>
        </div>
      </header>
      <ol className="sm-pipe" aria-label="The six stages across every address">
        {board.stages.map((s, i) => {
          const [big, unit] = total(s);
          return (
            <li key={s.key}>
              <div className={`sm-stage is-${s.sites_ready === board.sites ? "ready" : s.sites_ready ? "partial" : "not_run"}`}>
                <span className="sm-step">{i + 1}</span>
                <span className="sm-name">{NAME[s.key]}</span>
                <strong>{big}</strong>
                <span className="sm-unit">{unit}</span>
                <span className="sm-problem">{s.sites_ready} of {board.sites} addresses. {s.problem}</span>
              </div>
            </li>
          );
        })}
      </ol>
      <table className="sm-table">
        <thead><tr><th>Address</th>{ORDER.map((k) => <th key={k}>{NAME[k]}</th>)}</tr></thead>
        <tbody>
          {board.rows.map((r) => (
            <tr key={r.property_id} onClick={() => { window.location.hash = modelHash(r.property_id); }}>
              <th><a href={modelHash(r.property_id)}>{r.name}</a><small>{r.address}. {r.structures} roofs, {r.scans} scans</small></th>
              {ORDER.map((k) => (
                <td key={k} className={`is-${r.stages[k].state}`} title={r.stages[k].headline}>
                  {r.stages[k].state === "not_run" ? "–" : r.stages[k].number.toLocaleString()}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      <p className="sm-foot">A dash means the stage has not run for that address. Nothing is estimated in its place.</p>
    </div>
  );
}
