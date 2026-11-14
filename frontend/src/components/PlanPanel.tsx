import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import { costRange, HAZARD, TIMING } from "../format";
import type { Action, AgentEvent, Lead, Message, Plan, Timing } from "../types";

export type RunState = "idle" | "running" | "replaying" | "done" | "error";

interface Props {
  id: number;
  run: RunState;
  agentReady: boolean;
  hasSaved: boolean;
  events: AgentEvent[];
  leads: Lead[];
  actions: Action[];
  messages: Message[];
  plan: Plan | null;
  error: string | null;
  active: string | null;
  onRun: () => void;
  onReplay: () => void;
  onShow: (a: Action) => void;
  onZoom: (src: string) => void;
}

const ORDER: Timing[] = ["before_arrival", "after_event", "capital"];
const LEAD: Record<Lead["status"], string> = { open: "Checking", actions: "In the plan", not_a_concern: "Not a concern", cannot_check: "Could not check" };

export function PlanPanel(p: Props) {
  const [tab, setTab] = useState<"plan" | "messages" | "activity">(p.plan ? "plan" : "activity");
  const feed = useRef<HTMLDivElement>(null);
  const busy = p.run === "running" || p.run === "replaying";
  useEffect(() => { if (busy) setTab("activity"); }, [busy]);
  useEffect(() => { if (p.run === "done") setTab("plan"); }, [p.run]);
  useEffect(() => { if (tab === "activity" && busy && feed.current) feed.current.scrollTop = feed.current.scrollHeight; }, [p.events.length, tab, busy]);

  const steps = p.events.filter((e) => ["step", "thinking", "note", "action", "status", "message"].includes(e.type));
  const fine = p.leads.filter((l) => l.status === "not_a_concern");
  const unknown = p.leads.filter((l) => l.status === "cannot_check");
  const sum = (t: Timing) => {
    const xs = p.actions.filter((a) => a.timing === t);
    return { n: xs.length, low: xs.reduce((s, a) => s + a.cost_low, 0), high: xs.reduce((s, a) => s + a.cost_high, 0), hours: xs.reduce((s, a) => s + a.hours_of_work, 0) };
  };

  return (
    <aside className="panel" aria-label="Preparation plan">
      <div className="panel-top">
        {p.run === "idle" && !p.plan && (
          <>
            <h2>Build the plan for this building</h2>
            <p>The agent reads the forecast for this site, studies the roof and grounds from the air, walks the scanned spaces, and writes what to fix in the time left, with costs and the messages to send.</p>
          </>
        )}
        {busy && (
          <>
            <h2>{p.run === "replaying" ? "Replaying the plan" : "Working on the plan"}<span className="pulse" aria-hidden="true" /></h2>
            <p>{p.leads.filter((l) => l.status === "open").length} leads open, {p.actions.length} actions so far. The viewers follow where the agent looks.</p>
          </>
        )}
        {!busy && p.plan && (
          <>
            <h2 className="headline">{p.plan.headline ?? "The plan stopped before it was finished"}</h2>
            {p.plan.summary && <p>{p.plan.summary}</p>}
            {!p.plan.complete && <p className="warn">This run ended early ({p.plan.stop.replace("_", " ")}). What it had so far is below.</p>}
          </>
        )}
        {p.error && <p className="warn">{p.error}</p>}
        <div className="panel-actions">
          {!busy && <button className="primary" onClick={p.onRun} disabled={!p.agentReady}
                            title={p.agentReady ? "" : "Add ANTHROPIC_API_KEY to .env and restart the server"}>{p.plan ? "Build it again" : "Build the plan"}</button>}
          {!busy && p.hasSaved && <button onClick={p.onReplay}>Replay how it was built</button>}
        </div>
        {!p.agentReady && !busy && <p className="hint">Building a plan needs an Anthropic API key in <code>.env</code>. Saved plans can still be replayed.</p>}
      </div>

      <div className="tabs" role="tablist">
        <button role="tab" aria-selected={tab === "plan"} onClick={() => setTab("plan")}>Plan{p.actions.length ? ` (${p.actions.length})` : ""}</button>
        <button role="tab" aria-selected={tab === "messages"} onClick={() => setTab("messages")}>Messages{p.messages.length ? ` (${p.messages.length})` : ""}</button>
        <button role="tab" aria-selected={tab === "activity"} onClick={() => setTab("activity")}>Activity</button>
      </div>

      {tab === "plan" && (
        <div className="panel-scroll">
          {p.actions.length === 0 && <p className="empty">{p.plan ? "Nothing needs doing for this threat. See what was checked below." : "No actions yet."}</p>}
          {ORDER.map((t) => {
            const s = sum(t);
            if (!s.n) return null;
            return (
              <section key={t} className={`group ${t}`}>
                <header>
                  <h3>{TIMING[t]}</h3>
                  <span>{s.n} {s.n === 1 ? "action" : "actions"}, {costRange(s.low, s.high)}{t === "before_arrival" ? `, about ${Math.round(s.hours)} crew hours` : ""}</span>
                </header>
                {p.actions.filter((a) => a.timing === t).map((a) => (
                  <article key={a.id} className={`action ${p.active === a.id ? "active" : ""}`}>
                    <div className="action-head">
                      <span className="num">{a.id.replace("A", "")}</span>
                      <h4>{a.title}</h4>
                    </div>
                    <p>{a.why}</p>
                    <div className="evidence">
                      {a.site?.image && <Thumb src={api.file(p.id, a.site.image)} label={`From the air${a.structure ? `, ${a.structure}` : ""}`} onZoom={p.onZoom} />}
                      {a.site?.oblique_image && <Thumb src={api.file(p.id, a.site.oblique_image)} label={(a.site.oblique_view ?? "").replace("-", " ")} onZoom={p.onZoom} />}
                      {a.interior && <Thumb src={api.file(p.id, a.interior.image)} label={`Inside: ${a.interior.scan_name}`} onZoom={p.onZoom} />}
                    </div>
                    <dl>
                      <dt>Who</dt><dd>{a.crew}</dd>
                      <dt>Time</dt><dd>{a.hours_of_work} {a.hours_of_work === 1 ? "hour" : "hours"} of work</dd>
                      <dt>Cost</dt><dd>{costRange(a.cost_low, a.cost_high)}</dd>
                      <dt>Basis</dt><dd>{HAZARD[a.hazard]}. {a.basis === "seen" ? "Seen in the imagery" : "From the record and forecast"}</dd>
                    </dl>
                    {(a.site || a.interior) && <button className="show" onClick={() => p.onShow(a)}>Show me</button>}
                  </article>
                ))}
              </section>
            );
          })}
          {fine.length > 0 && <section className="tally-list"><h3>Checked, not a concern</h3><ul>{fine.map((l) => <li key={l.id}><strong>{l.title}.</strong> {l.note}</li>)}</ul></section>}
          {unknown.length > 0 && <section className="tally-list"><h3>Could not check</h3><ul>{unknown.map((l) => <li key={l.id}><strong>{l.title}.</strong> {l.note}</li>)}</ul></section>}
          {p.plan && <p className="disclaimer">Brace works from imagery, the building record and public forecasts. It cannot see structure, drainage or plant rooms, and it is not an engineering assessment.</p>}
        </div>
      )}

      {tab === "messages" && (
        <div className="panel-scroll">
          {p.messages.length === 0 && <p className="empty">Notices and work orders appear here once the plan has actions.</p>}
          {p.messages.map((m) => <Draft key={m.id} m={m} />)}
        </div>
      )}

      {tab === "activity" && (
        <div className="panel-scroll" ref={feed}>
          {p.leads.length > 0 && (
            <ul className="leads">
              {p.leads.map((l) => (
                <li key={l.id} className={`lead is-${l.status}`}>
                  <span className="lead-mark" aria-hidden="true" />
                  <span className="lead-body"><strong>{l.title}</strong><small>{HAZARD[l.hazard]} / {LEAD[l.status]}{l.note ? `: ${l.note}` : ""}</small></span>
                </li>
              ))}
            </ul>
          )}
          {steps.length === 0 && <p className="empty">Nothing yet. Build the plan to watch the agent work.</p>}
          <ol className="feed">
            {steps.map((e, i) => {
              if (e.type === "thinking" || e.type === "note") return <li key={i} className="thought">{e.text}</li>;
              if (e.type === "status") return <li key={i} className="step"><span>{e.label}</span></li>;
              if (e.type === "action") return <li key={i} className="step added"><span>Added to the plan: {e.action.title}</span></li>;
              if (e.type === "message") return <li key={i} className="step"><span>Drafted {e.message.kind === "notice" ? "a notice" : "a work order"} for {e.message.to}</span></li>;
              if (e.type === "step") return (
                <li key={i} className="step">
                  <span>{e.label}</span>
                  {e.image && <button className="thumb" onClick={() => p.onZoom(api.file(p.id, e.image!))} aria-label="Enlarge what the agent saw"><img src={api.file(p.id, e.image)} alt="" loading="lazy" /></button>}
                </li>
              );
              return null;
            })}
          </ol>
        </div>
      )}
    </aside>
  );
}

function Thumb({ src, label, onZoom }: { src: string; label: string; onZoom: (s: string) => void }) {
  return <button onClick={() => onZoom(src)}><img src={src} alt="" loading="lazy" /><span>{label}</span></button>;
}

function Draft({ m }: { m: Message }) {
  const [copied, setCopied] = useState(false);
  const text = `To: ${m.to}\nSubject: ${m.subject}\n\n${m.body}`;
  return (
    <article className="draft">
      <header><span>{m.kind === "notice" ? "Notice" : "Work order"}</span><span>To: {m.to}</span></header>
      <h3>{m.subject}</h3>
      <pre>{m.body}</pre>
      <button onClick={() => navigator.clipboard.writeText(text).then(() => { setCopied(true); setTimeout(() => setCopied(false), 1600); })}>{copied ? "Copied" : "Copy message"}</button>
    </article>
  );
}
