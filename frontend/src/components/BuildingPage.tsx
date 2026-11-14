import QRCode from "qrcode";
import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../api";
import { conversation } from "../conversation";
import { costRange, exposureLine, hours, money, num, standingLine, when } from "../format";
import { BEARING, nearestScanView, structureAt } from "../geo";
import type { Action, AgentEvent, Building, Direction, Facing, Lead, LonLat, Measured, Message, Plan, Scenario, Selection } from "../types";
import { modelHash, prepareHash, walkHash } from "../recovery/routes";
import { ReportsFeed } from "./ReportsFeed";
import { ConversationPanel } from "./ConversationPanel";
import { PlanPanel, type RunState } from "./PlanPanel";
import { SitePane } from "./SitePane";
import { TourPane, type TourHandle } from "./TourPane";

interface Props { id: number; scenario: Scenario; step: string | null; sdkKey: string; agentReady: boolean; voiceReady: boolean; onBack: () => void }

/**
 * A notice waiting for the owner's approval. It is never approved by the clock: when `left` (seconds) runs
 * out Brace asks aloud once, and after that it simply waits. Silence leaves it pending.
 */
interface Pending { actionId: string; label: string; seconds: number; left: number; asked: boolean }
const ASK_AFTER_SECONDS = 12;

/** A saved plan for one forecast step, as the server lists them. */
interface SavedPlan {
  step: string; label: string; hours_left: number | null; headline: string | null;
  actions: { id: string; title: string; timing: string; hours_of_work: number; cost_low: number; cost_high: number }[];
}

/** How many hours before the event a forecast step is, read from its label ("36 hours before landfall"). */
const hoursOf = (p: SavedPlan): number | null => {
  const m = /(\d+(?:\.\d+)?)\s*hours?/i.exec(p.label);
  return m ? Number(m[1]) : p.hours_left;
};

/** A saved plan in the few words the voice needs to compare it with another. */
const inBrief = (p: SavedPlan) => {
  const list = (timing: string) => p.actions.filter((a) => a.timing === timing).map((a) => ({ id: a.id, what: a.title, cost: costRange(a.cost_low, a.cost_high) }));
  const before = p.actions.filter((a) => a.timing === "before_arrival");
  return {
    forecast_step: p.label, hours_left_at_this_site: p.hours_left == null ? null : Math.round(p.hours_left), in_one_line: p.headline,
    before_it_arrives: list("before_arrival"), after_the_event: list("after_event"),
    cost_before_it_arrives: costRange(before.reduce((s, a) => s + a.cost_low, 0), before.reduce((s, a) => s + a.cost_high, 0)),
  };
};

export function BuildingPage({ id, scenario, step, sdkKey, agentReady, voiceReady, onBack }: Props) {
  const [b, setB] = useState<Building | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [selection, setSelection] = useState<Selection | null>(null);
  const [at, setAt] = useState<{ scanId: string; sweepId: string } | null>(null);
  const [bearing, setBearing] = useState<number | null>(null);
  const [run, setRun] = useState<RunState>("idle");
  const [events, setEvents] = useState<AgentEvent[]>([]);
  const [leads, setLeads] = useState<Lead[]>([]);
  const [actions, setActions] = useState<Action[]>([]);
  const [messages, setMessages] = useState<Message[]>([]);
  const [plan, setPlan] = useState<Plan | null>(null);
  const [runError, setRunError] = useState<string | null>(null);
  const [active, setActive] = useState<string | null>(null);
  const [zoom, setZoom] = useState<string | null>(null);
  const [headset, setHeadset] = useState<{ url: string; qr: string } | null>(null);
  const [worn, setWorn] = useState<{ scan_id: string; sweep_id: string; bearing: number | null; action_id: string | null } | null>(null);
  const [approved, setApproved] = useState<string[]>([]);
  const [facing, setFacing] = useState<Facing | null>(null);
  const [measured, setMeasured] = useState<Record<string, Measured[]> | null>(null);
  const [pending, setPending] = useState<Pending | null>(null);
  const tour = useRef<TourHandle>(null);
  const stream = useRef<EventSource | null>(null);

  // The phone in the headset reports where it is standing and looking; show that on the site photo.
  useEffect(() => {
    const t = window.setInterval(() => {
      fetch("/api/vr/pose").then((r) => r.json()).then((p) => {
        const on = p.building === id && p.age < 4;
        setWorn(on ? p : null);
        if (on && p.action_id) setActive(p.action_id);
      }).catch(() => {});
      fetch(`/api/vr/approvals?building=${id}`).then((r) => r.json()).then((a) => setApproved(a.action_ids ?? [])).catch(() => {});
    }, 800);
    return () => window.clearInterval(t);
  }, [id]);

  const openHeadset = async () => {
    const { ip, vr_port } = await fetch("/api/lan").then((r) => r.json()).catch(() => ({ ip: null, vr_port: 5175 }));
    const url = `https://${ip ?? "<this-computer's-address>"}:${vr_port ?? 5175}/#/vr/${encodeURIComponent(scenario.id)}/${step ? encodeURIComponent(step) : "-"}/b/${id}`;
    setHeadset({ url, qr: await QRCode.toDataURL(url, { margin: 1, width: 260 }) });
  };

  useEffect(() => {
    api.building(id, scenario.id, step).then((d) => {
      setB(d);
      if (d.plan) { setPlan(d.plan); setLeads(d.plan.leads); setActions(d.plan.actions); setMessages(d.plan.messages); setEvents(d.plan.events); setRun("done"); }
    }).catch((e) => setLoadError(e.message));
    return () => stream.current?.close();
  }, [id, scenario.id, step]);

  // Once there is a finished plan, measure which windows and outside doors of the nearest scan face each outside action.
  useEffect(() => {
    if (!plan || run !== "done") { setFacing(null); setMeasured(null); return; }
    let current = true;
    api.facing(id, scenario.id, step).then((f) => { if (current) setFacing(f); }).catch(() => { if (current) setFacing(null); });
    api.measured(id, scenario.id, step).then((m) => { if (current) setMeasured(m); }).catch(() => { if (current) setMeasured(null); });
    return () => { current = false; };
  }, [plan, run, id, scenario.id, step]);

  /** Tell the headset where to attend: a scan position, a point outside, an action, and the line to say if there is one. */
  const tell = useCallback((target: Record<string, unknown>) => {
    fetch("/api/vr/target", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ building: id, ...target }) }).catch(() => {});
  }, [id]);

  const point = useCallback((lon: number, lat: number, label: string, scanId: string | null, sweepId: string | null, direction: Direction, tag?: string) => {
    if (!b) return;
    const st = structureAt(b, [lon, lat]);
    setSelection({ lon, lat, label, structure: st?.id ?? null, scanId, sweepId, direction });
    if (scanId) {
      tour.current?.lookFrom(scanId, sweepId, direction, tag);
      // Bring the headset along to the same spot, facing the same way.
      tell({ scan_id: scanId, sweep_id: sweepId, bearing: direction in BEARING ? BEARING[direction as keyof typeof BEARING] : null });
    }
  }, [b, tell]);

  const pick = useCallback((p: LonLat) => {
    if (!b) return;
    const st = structureAt(b, p);
    const near = nearestScanView(b, p, 25);
    setActive(null);
    point(p[0], p[1], st ? `${st.id}: ${st.roof_material ?? "roof"}, condition ${st.roof_condition ?? "unknown"} of 5${near ? `. Nearest scanned space: ${near.scan.name}` : ""}` : "Grounds",
          near?.scan.id ?? null, near?.sweepId ?? null, "north");
  }, [b, point]);

  const show = useCallback((a: Action) => {
    setActive(a.id);
    const lon = a.site?.lon ?? a.interior?.lon, lat = a.site?.lat ?? a.interior?.lat;
    const tag = a.interior ? `${a.id.replace("A", "")}. ${a.title}` : undefined;
    if (lon == null || lat == null) { if (a.interior) tour.current?.lookFrom(a.interior.scan_id, a.interior.sweep_id, a.interior.direction, tag); return; }
    point(lon, lat, a.title, a.interior?.scan_id ?? null, a.interior?.sweep_id ?? null, a.interior?.direction ?? "north", tag);
    // An outside action has no scan to stand in: the headset turns its wearer toward it through the wall.
    if (!a.interior) tell({ action_id: a.id, lon, lat });
  }, [point, tell]);

  const follow = useRef({ point, show });
  follow.current = { point, show };

  // --- the conversation: what the voice may do on this screen -------------------------------------
  // Kept in a ref so the tools always act on the page as it is now, not as it was when the talk began.
  const stageNow = useRef({ actions, active, approved, show, scanName: null as string | null, pending: null as Pending | null,
                            settle: (_how: "approve" | "hold") => {} });
  const finding = useRef(-1);

  /** Move the clock to the saved plan closest to a number of hours, and say what differs. It is a replay, not a new run. */
  const moveClock = useCallback(async (wanted: number): Promise<unknown> => {
    const { plans } = (await fetch(`/api/buildings/${id}/plans?scenario=${encodeURIComponent(scenario.id)}`).then((r) => r.json())) as { plans: SavedPlan[] };
    if (!plans.length) return { ok: false, say: "No plan has been saved for this building, so there is nothing to compare." };
    if (!Number.isFinite(wanted)) return { ok: false, say: "Tell me how many hours are left." };
    const gap = (p: SavedPlan) => Math.abs((hoursOf(p) ?? 1e9) - wanted);
    const nearest = plans.reduce((best, p) => (gap(p) < gap(best) ? p : best));
    const here = plans.find((p) => p.step === step) ?? null;
    const saved = plans.map((p) => p.label);
    if (nearest.step === step) return { ok: true, changed: false, note: "The screen is already on the plan made for the closest saved forecast step.", plan: inBrief(nearest), saved_steps: saved };
    // Let the answer go back first; then the page is rebuilt for the other step under the same conversation.
    window.setTimeout(() => { window.location.hash = prepareHash(scenario.id, nearest.step, id); }, 60);
    return { ok: true, changed: true, saved_steps: saved,
             note: "This is a replay: the plan the agent made for that forecast step, not a new inspection. Action ids are numbered afresh in each plan, so compare by what the action is. Say what moved to after the event and why the cost changed.",
             was: here ? inBrief(here) : null, now: inBrief(nearest) };
  }, [id, scenario.id, step]);

  const runTool = useCallback(async (name: string, args: Record<string, unknown>): Promise<unknown> => {
    const now = stageNow.current;
    const wanted = typeof args.action_id === "string" ? now.actions.find((a) => a.id.toLowerCase() === (args.action_id as string).toLowerCase()) : undefined;
    const unknown = { ok: false, say: "That is not an action in this plan." };
    const shown = (a: Action) => {
      now.show(a);
      finding.current = now.actions.indexOf(a);
      return { ok: true, id: a.id, title: a.title, approved: now.approved.includes(a.id),
               where: a.interior ? `inside, in ${a.interior.scan_name}` : `outside${a.structure ? `, on ${a.structure}` : ""}` };
    };
    if (name === "go_to_action") return wanted ? shown(wanted) : unknown;
    if (name === "next_finding") return now.actions.length ? shown(now.actions[(finding.current + 1) % now.actions.length]) : { ok: false, say: "There are no actions in this plan." };
    if (name === "approve_action") {
      if (!wanted) return unknown;
      if (now.pending?.actionId === wanted.id) setPending(null);
      return fetch("/api/vr/approve", { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ building: id, scenario: scenario.id, step, action_id: wanted.id }) })
        .then((r) => r.json()).catch(() => ({ ok: false, say: "The approval could not be saved." }));
    }
    if (name === "where_am_i") return { on_screen_action: now.active, scanned_space_shown: now.scanName, forecast_step: scenario.steps.find((s) => s.id === step)?.label ?? null };
    if (name === "hold_approval") {
      if (!now.pending) return { ok: false, say: "There is no countdown running." };
      now.settle("hold");
      return { ok: true, say: "Set aside. The resident notice is not approved." };
    }
    if (name === "set_hours_left") return moveClock(Number(args.hours));
    return { ok: false, say: "I cannot do that from here." };
  }, [id, scenario, step, moveClock]);

  useEffect(() => {
    if (!b) return;
    const about = `building=${id}&scenario=${encodeURIComponent(scenario.id)}${step ? `&step=${encodeURIComponent(step)}` : ""}&view=screen`;
    conversation.setStage({
      key: `${id}:${scenario.id}:${step}`, sessionUrl: `/api/voice/session?${about}`, notesUrl: `/api/voice/notes?${about}`, run: runTool,
      greeting: `Greet the owner in one sentence: name the building, say how long is left before ${b.threat.name} reaches it, and say they can ask what to fix first.`,
    });
    return () => conversation.setStage(null);
  }, [b, id, scenario.id, step, runTool]);

  /** Settle the waiting notice: approve the action it is about, or set it aside. Either way Brace says what happened. */
  const settle = useCallback((how: "approve" | "hold") => {
    const waiting = stageNow.current.pending;
    if (!waiting) return;
    setPending(null);
    if (how === "hold") { conversation.cue("say", "Set aside. The resident notice is not approved."); return; }
    fetch("/api/vr/approve", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ building: id, scenario: scenario.id, step, action_id: waiting.actionId }) })
      .then((r) => r.json()).then((result: { say?: string }) => { if (result.say) conversation.cue("say", result.say); }).catch(() => {});
  }, [id, scenario.id, step]);

  // If nobody has answered after a few seconds Brace asks once, aloud. The clock never approves anything.
  const counting = pending !== null && !pending.asked;
  useEffect(() => {
    if (!counting) return;
    const started = performance.now();
    const tick = window.setInterval(() => {
      const left = ASK_AFTER_SECONDS - (performance.now() - started) / 1000;
      if (left > 0) { setPending((p) => (p ? { ...p, left } : p)); return; }
      window.clearInterval(tick);
      setPending((p) => (p ? { ...p, left: 0, asked: true } : p));
      conversation.cue("say", "The resident notice is ready. Shall I approve it?");
    }, 100);
    return () => window.clearInterval(tick);
  }, [counting]);

  // Tell the voice what is on screen, so "approve that one" means the action being looked at.
  useEffect(() => {
    const a = stageNow.current.actions.find((x) => x.id === active);
    if (a) conversation.note(`The owner is now looking at ${a.id}: ${a.title}.`);
  }, [active]);

  const listen = (url: string, mode: RunState) => {
    stream.current?.close();
    setEvents([]); setLeads([]); setActions([]); setMessages([]); setRunError(null); setActive(null); setRun(mode);
    const es = new EventSource(url);
    stream.current = es;
    es.onmessage = (m) => {
      const e = JSON.parse(m.data) as AgentEvent;
      setEvents((prev) => [...prev, e]);
      if (e.type === "lead") setLeads((prev) => [...prev, e.lead]);
      else if (e.type === "lead_closed") setLeads((prev) => prev.map((l) => (l.id === e.lead.id ? e.lead : l)));
      else if (e.type === "action") {
        setActions((prev) => [...prev, e.action]);
        follow.current.show(e.action);
        const a = e.action, inside = a.interior;
        tell({ kind: "action", action_id: a.id, label: a.title, scan_id: inside?.scan_id ?? null, sweep_id: inside?.sweep_id ?? null,
               bearing: inside ? inside.bearing ?? BEARING[inside.direction as keyof typeof BEARING] ?? null : null,
               lon: a.site?.lon ?? inside?.lon ?? null, lat: a.site?.lat ?? inside?.lat ?? null, image: a.site?.oblique_image ?? a.site?.image ?? null });
        conversation.cue("finding", `${a.id} ${a.title}`, `Added to the plan: ${a.title}`);
      }
      else if (e.type === "message") setMessages((prev) => [...prev, e.message]);
      else if (e.type === "step" && e.focus) {
        const f = e.focus;
        if (f.lon != null && f.lat != null) follow.current.point(f.lon, f.lat, e.label, f.scan_id ?? null, f.sweep_id ?? null, f.direction ?? "north");
        else if (f.scan_id) tour.current?.lookFrom(f.scan_id, f.sweep_id ?? null, f.direction ?? "north");
        const facing = f.direction && f.direction in BEARING ? BEARING[f.direction as keyof typeof BEARING] : null;
        tell({ kind: "step", label: e.label, scan_id: f.scan_id ?? null, sweep_id: f.sweep_id ?? null, bearing: f.scan_id ? facing : null,
               lon: f.lon ?? null, lat: f.lat ?? null, image: f.scan_id ? null : e.image });
        conversation.cue("inspection", e.label);
      } else if (e.type === "step") { tell({ kind: "step", label: e.label }); conversation.cue("inspection", e.label); }
      else if (e.type === "error") setRunError(e.message);
      else if (e.type === "done") {
        es.close();
        if (e.plan) setPlan(e.plan);
        // The inspection has just finished in front of someone: put the resident notice up for approval.
        // Opening a saved plan never does this.
        const notice = e.plan?.complete ? e.plan.messages.find((m) => m.kind === "notice") : undefined;
        const first = notice?.action_ids.find((aid) => e.plan!.actions.some((a) => a.id === aid));
        if (notice && first && !stageNow.current.approved.includes(first)) {
          setPending({ actionId: first, label: notice.subject, seconds: ASK_AFTER_SECONDS, left: ASK_AFTER_SECONDS, asked: false });
          conversation.note(`The resident notice is waiting for the owner's approval, action ${first}. It is not approved until the owner says yes, nods or presses Approve.`);
        }
        setRun(e.stop === "error" ? "error" : "done");
      }
    };
    es.onerror = () => { es.close(); setRun((r) => (r === "running" || r === "replaying" ? "error" : r)); setRunError((x) => x ?? "Lost the connection to the run. Build the plan again."); };
  };
  const start = async () => {
    try { await api.startPlan(id, scenario.id, step); listen(api.streamUrl(id, scenario.id, step, false), "running"); }
    catch { setRunError("Could not start. Check that the server is running."); }
  };

  if (loadError) return <div className="fatal"><p>This building could not be prepared: {loadError}.</p><button onClick={onBack}>Back to the map</button></div>;
  if (!b) return <div className="fatal quiet">Pulling the site photo, roof analysis and scans…</div>;

  const r = b.record, t = b.threat;
  const scan = at ? b.scans.find((s) => s.id === at.scanId) : null;
  stageNow.current = { actions, active, approved, show, scanName: scan?.name ?? null, pending, settle };
  const sweep = scan?.sweeps.find((s) => s.id === at?.sweepId);
  const standing = standingLine(t);
  const busy = run === "running" || run === "replaying";
  const marks = actions.filter((a) => a.site).map((a) => ({ id: a.id, lon: a.site!.lon, lat: a.site!.lat }));
  // When someone is wearing the headset, the "you are here" mark follows them instead of the on-screen tour.
  const wornSweep = worn ? b.scans.find((s) => s.id === worn.scan_id)?.sweeps.find((s) => s.id === worn.sweep_id) : null;
  const here = wornSweep?.lon != null && wornSweep.lat != null ? { lon: wornSweep.lon, lat: wornSweep.lat, bearing: worn!.bearing }
    : sweep?.lon != null && sweep.lat != null ? { lon: sweep.lon, lat: sweep.lat, bearing } : null;

  return (
    <div className="building-page">
      <header className="topbar">
        <button className="back" onClick={onBack}>Map</button>
        <a className="recover-link" href="#/recovery">Recover</a>
        {plan && <a className="recover-link" href={walkHash(scenario.id, step, id)}>Walk-through</a>}
        <a className="recover-link" href={modelHash(id)}>Site model</a>
        {b.scans.length > 0 && <button className="headset" onClick={openHeadset}>{worn ? "Headset connected" : "Open in headset"}</button>}
        <div className="title">
          <h1>{r.name}</h1>
          <span>{r.address}, {r.city}, {r.state} {r.zip}</span>
        </div>
        <dl className="facts">
          <div><dt>Type</dt><dd>{r.type_label}{r.style ? `, ${r.style.replace(/([a-z])([A-Z])/g, "$1-$2").toLowerCase()}` : ""}</dd></div>
          <div><dt>Built</dt><dd>{r.year_built ?? "–"}</dd></div>
          <div><dt>Size</dt><dd>{r.units ? `${num(r.units)} homes` : r.gba_sqft ? `${num(r.gba_sqft)} sq ft` : "–"}{r.stories ? `, ${r.stories} ${r.stories === 1 ? "storey" : "storeys"}` : ""}</dd></div>
          <div><dt>Construction</dt><dd>{r.construction ? r.construction.replace(/([a-z])([A-Z])/g, "$1 $2").toLowerCase() : "–"}</dd></div>
          <div><dt>Managed by</dt><dd>{r.contacts.manager ?? r.contacts.owner ?? "Not on record"}</dd></div>
          <div><dt>Tenants on record</dt><dd>{num(r.tenant_count)}</dd></div>
          {b.last_sale && (
            <div title={`How CoStar established this price: ${b.last_sale.basis.toLowerCase()}${b.last_sale.portfolio ? " (an estimated share of a portfolio sale)" : ""}`}>
              <dt>Last sold, {b.last_sale.date.slice(0, 4)}</dt><dd>{money(b.last_sale.price)}{b.last_sale.portfolio ? " (share)" : ""}</dd>
            </div>
          )}
        </dl>
      </header>

      <div className={`threat-strip ${t.kind}`}>
        <strong>{t.name}</strong>
        <span>{t.label}{t.replay ? " (replay)" : ""}</span>
        <span className="clock">{t.hours_left == null ? "No arrival time for this site" : t.hours_left <= 0 ? "Damaging conditions are here now" : `Damaging conditions here in about ${hours(t.hours_left)}`}</span>
        <span>{exposureLine(t.at_this_site)}</span>
        {standing && <span>{standing}</span>}
        {b.observed_rain && (
          <span title={`${b.observed_rain.source}. Peak rate ${b.observed_rain.peak_mm_per_h} mm an hour${b.observed_rain.capped ? "; the data caps rates at 75 mm an hour, so the heaviest bursts are understated" : ""}.`}>
            What then fell here: {b.observed_rain.inches} in of rain ({Math.round(b.observed_rain.mm)} mm), measured afterwards
          </span>
        )}
        <span className="issued">Forecast issued {when(t.forecast_issued)}</span>
      </div>

      <main className="stage">
        <SitePane b={b} selection={selection} marks={marks} onPick={pick}
                  onMark={(aid) => { const a = actions.find((x) => x.id === aid); if (a) show(a); }}
                  tour={here} />
        <TourPane ref={tour} scans={b.scans} sdkKey={sdkKey} onMove={(scanId, sweepId) => setAt({ scanId, sweepId })} onTurn={setBearing} />
        {b.reasons.length > 0 && <p className="why">Flagged by the aerial analysis and the record, before anyone has looked: {b.reasons.join("; ")}.</p>}
      </main>

      <PlanPanel id={id} run={run} agentReady={agentReady} hasSaved={!!b.plan || (run === "done" && !!plan)}
                 events={events} leads={leads} actions={actions} messages={messages} plan={busy ? null : plan}
                 error={runError} active={active} approved={approved} facing={facing} measured={measured}
                 pending={pending} onApproveNow={() => settle("approve")} onHold={() => settle("hold")} onRun={start}
                 onReplay={() => listen(api.streamUrl(id, scenario.id, step, true, worn || conversation.get().on ? 2 : 5), "replaying")} onShow={show} onZoom={setZoom} />

      <ConversationPanel ready={voiceReady} />
      <ReportsFeed id={id} />
      {headset && (
        <div className="lightbox" role="dialog" aria-label="Open in a phone headset" onClick={() => setHeadset(null)}>
          <div className="headset-card" onClick={(e) => e.stopPropagation()}>
            <h2>Stand inside this building</h2>
            <img src={headset.qr} alt="QR code for the headset view" width={260} height={260} />
            <ol>
              <li>Put the phone on the same Wi-Fi as this computer and scan the code.</li>
              <li>The phone warns about the connection because the certificate is self-made. Choose to continue.</li>
              <li>Press Start, then slide the phone into the headset.</li>
            </ol>
            <code>{headset.url}</code>
            <p>What you pick here, the headset shows. Where the wearer looks appears on the site photo.</p>
            <button onClick={() => setHeadset(null)}>Close</button>
          </div>
        </div>
      )}
      {zoom && (
        <div className="lightbox" role="dialog" aria-label="Enlarged image" onClick={() => setZoom(null)}>
          <img src={zoom} alt="" />
          <button onClick={() => setZoom(null)}>Close</button>
        </div>
      )}
    </div>
  );
}
