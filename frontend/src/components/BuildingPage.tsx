import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../api";
import { exposureLine, hours, num, standingLine, when } from "../format";
import { nearestScanView, structureAt } from "../geo";
import type { Action, AgentEvent, Building, Direction, Lead, LonLat, Message, Plan, Scenario, Selection } from "../types";
import { PlanPanel, type RunState } from "./PlanPanel";
import { SitePane } from "./SitePane";
import { TourPane, type TourHandle } from "./TourPane";

interface Props { id: number; scenario: Scenario; step: string | null; sdkKey: string; agentReady: boolean; onBack: () => void }

export function BuildingPage({ id, scenario, step, sdkKey, agentReady, onBack }: Props) {
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
  const tour = useRef<TourHandle>(null);
  const stream = useRef<EventSource | null>(null);

  useEffect(() => {
    api.building(id, scenario.id, step).then((d) => {
      setB(d);
      if (d.plan) { setPlan(d.plan); setLeads(d.plan.leads); setActions(d.plan.actions); setMessages(d.plan.messages); setEvents(d.plan.events); setRun("done"); }
    }).catch((e) => setLoadError(e.message));
    return () => stream.current?.close();
  }, [id, scenario.id, step]);

  const point = useCallback((lon: number, lat: number, label: string, scanId: string | null, sweepId: string | null, direction: Direction) => {
    if (!b) return;
    const st = structureAt(b, [lon, lat]);
    setSelection({ lon, lat, label, structure: st?.id ?? null, scanId, sweepId, direction });
    if (scanId) tour.current?.lookFrom(scanId, sweepId, direction);
  }, [b]);

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
    if (lon == null || lat == null) { if (a.interior) tour.current?.lookFrom(a.interior.scan_id, a.interior.sweep_id, a.interior.direction); return; }
    point(lon, lat, a.title, a.interior?.scan_id ?? null, a.interior?.sweep_id ?? null, a.interior?.direction ?? "north");
  }, [point]);

  const follow = useRef({ point, show });
  follow.current = { point, show };

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
      else if (e.type === "action") { setActions((prev) => [...prev, e.action]); follow.current.show(e.action); }
      else if (e.type === "message") setMessages((prev) => [...prev, e.message]);
      else if (e.type === "step" && e.focus) {
        const f = e.focus;
        if (f.lon != null && f.lat != null) follow.current.point(f.lon, f.lat, e.label, f.scan_id ?? null, f.sweep_id ?? null, f.direction ?? "north");
        else if (f.scan_id) tour.current?.lookFrom(f.scan_id, f.sweep_id ?? null, f.direction ?? "north");
      } else if (e.type === "error") setRunError(e.message);
      else if (e.type === "done") {
        es.close();
        if (e.plan) setPlan(e.plan);
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
  const sweep = scan?.sweeps.find((s) => s.id === at?.sweepId);
  const standing = standingLine(t);
  const busy = run === "running" || run === "replaying";
  const marks = actions.filter((a) => a.site).map((a) => ({ id: a.id, lon: a.site!.lon, lat: a.site!.lat }));

  return (
    <div className="building-page">
      <header className="topbar">
        <button className="back" onClick={onBack}>Map</button>
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
        </dl>
      </header>

      <div className={`threat-strip ${t.kind}`}>
        <strong>{t.name}</strong>
        <span>{t.label}{t.replay ? " (replay)" : ""}</span>
        <span className="clock">{t.hours_left != null ? `Damaging conditions here in about ${hours(t.hours_left)}` : "No arrival time for this site"}</span>
        <span>{exposureLine(t.at_this_site)}</span>
        {standing && <span>{standing}</span>}
        <span className="issued">Forecast issued {when(t.forecast_issued)}</span>
      </div>

      <main className="stage">
        <SitePane b={b} selection={selection} marks={marks} onPick={pick}
                  onMark={(aid) => { const a = actions.find((x) => x.id === aid); if (a) show(a); }}
                  tour={sweep?.lon != null && sweep.lat != null ? { lon: sweep.lon, lat: sweep.lat, bearing } : null} />
        <TourPane ref={tour} scans={b.scans} sdkKey={sdkKey} onMove={(scanId, sweepId) => setAt({ scanId, sweepId })} onTurn={setBearing} />
        {b.reasons.length > 0 && <p className="why">On the list because: {b.reasons.join("; ")}.</p>}
      </main>

      <PlanPanel id={id} run={run} agentReady={agentReady} hasSaved={!!b.plan || (run === "done" && !!plan)}
                 events={events} leads={leads} actions={actions} messages={messages} plan={busy ? null : plan}
                 error={runError} active={active} onRun={start}
                 onReplay={() => listen(api.streamUrl(id, scenario.id, step, true), "replaying")} onShow={show} onZoom={setZoom} />

      {zoom && (
        <div className="lightbox" role="dialog" aria-label="Enlarged image" onClick={() => setZoom(null)}>
          <img src={zoom} alt="" />
          <button onClick={() => setZoom(null)}>Close</button>
        </div>
      )}
    </div>
  );
}
