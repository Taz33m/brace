import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api";
import { conversation } from "../conversation";
import { costRange, monthYear, when } from "../format";
import { prepareHash, walkHash } from "../recovery/routes";
import type { Action, Approval, Building, ClockChange, Facing, Message, SavedStep, Scenario } from "../types";
import { ConversationPanel } from "./ConversationPanel";
import { FacingDiagram } from "./FacingDiagram";
import "./walk.css";

interface Props { id: number; scenario: Scenario; step: string | null; voiceReady: boolean }

/**
 * One thing to look at and one thing to decide. The walk-through is a short run of these, in the order
 * the evidence makes sense: the site from above, each finding outside, the scanned space that goes with
 * it, and the notice to approve. Brace moves between them; the person decides.
 */
type Moment =
  | { kind: "overview" }
  | { kind: "outside"; action: Action }
  | { kind: "inside"; action: Action }
  | { kind: "change"; diff: ClockChange }
  | { kind: "notice"; message: Message; actionId: string }
  | { kind: "approved"; message: Message };

const CHANGE: Record<ClockChange["rows"][number]["change"], string> = {
  deferred: "Deferred until after the event", still_fits: "Still fits before arrival", new: "New at this step",
  dropped: "No longer in the plan", brought_forward: "Now fits before arrival",
};

/** The first sentence of a paragraph, which is as much as fits under a headline. */
const firstSentence = (text: string) => (text.match(/^.*?[.!?](?=\s|$)/)?.[0] ?? text).trim();
const hoursOf = (label: string) => { const m = /(\d+)\s*hours?/i.exec(label); return m ? Number(m[1]) : null; };

export function WalkPage({ id, scenario, step, voiceReady }: Props) {
  const [b, setB] = useState<Building | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [facing, setFacing] = useState<Facing | null>(null);
  const [saved, setSaved] = useState<SavedStep[]>([]);
  const [diff, setDiff] = useState<ClockChange | null>(null);
  const [at, setAt] = useState(0);
  const [approved, setApproved] = useState<string[]>([]);
  const [decision, setDecision] = useState<{ context: string; actionId: string; result: Approval } | null>(null);
  const approvalContext = JSON.stringify([id, scenario.id, step]);
  const currentApprovalContext = useRef(approvalContext);
  currentApprovalContext.current = approvalContext;
  const cameFrom = useRef<string | null>(null);   // the forecast step being left when the clock is moved

  // The building and its plan for this forecast step. The previous step's stay on screen until the new one arrives.
  useEffect(() => {
    let current = true;
    api.building(id, scenario.id, step).then((d) => { if (current) { setB(d); setError(null); } }).catch((e) => { if (current) setError(e.message); });
    api.facing(id, scenario.id, step).then((f) => { if (current) setFacing(f); }).catch(() => { if (current) setFacing(null); });
    return () => { current = false; };
  }, [id, scenario.id, step]);
  useEffect(() => { api.savedSteps(id, scenario.id).then(setSaved).catch(() => setSaved([])); }, [id, scenario.id]);
  useEffect(() => {
    let current = true;
    setApproved([]);
    const query = new URLSearchParams({ building: String(id), scenario: scenario.id, step: step ?? "" });
    const poll = () => fetch(`/api/vr/approvals?${query}`).then((r) => r.json()).then((a) => {
      if (current) setApproved(a.action_ids ?? []);
    }).catch(() => {});
    poll();
    const t = window.setInterval(poll, 1500);
    return () => { current = false; window.clearInterval(t); };
  }, [id, scenario.id, step]);

  // When the clock has just been moved, the first thing to show is what changed.
  useEffect(() => {
    const earlier = cameFrom.current;
    cameFrom.current = null;
    if (!earlier || !step || earlier === step) { setDiff(null); return; }
    let current = true;
    api.clock(id, scenario.id, earlier, step).then((d) => { if (current) { setDiff(d); setAt(0); } }).catch(() => { if (current) setDiff(null); });
    return () => { current = false; };
  }, [id, scenario.id, step]);

  const plan = b?.plan ?? null;
  const moments = useMemo<Moment[]>(() => {
    if (!plan) return [{ kind: "overview" }];
    const list: Moment[] = diff ? [{ kind: "change", diff }] : [];
    list.push({ kind: "overview" });
    for (const action of plan.actions.filter((a) => a.timing === "before_arrival")) {
      if (action.site) list.push({ kind: "outside", action });
      if (action.interior || facing?.actions[action.id]) list.push({ kind: "inside", action });
    }
    const notice = plan.messages.find((m) => m.kind === "notice");
    const first = notice?.action_ids.find((aid) => plan.actions.some((a) => a.id === aid));
    if (notice && first) list.push(approved.includes(first) ? { kind: "approved", message: notice } : { kind: "notice", message: notice, actionId: first });
    return list;
  }, [plan, facing, diff, approved]);
  const moment = moments[Math.min(at, moments.length - 1)];
  const approvalMessage = decision?.context === approvalContext && (
    moment.kind === "approved" || (moment.kind === "notice" && moment.actionId === decision.actionId)
  ) ? decision.result : null;
  const go = useCallback((to: number) => setAt(Math.max(0, Math.min(moments.length - 1, to))), [moments.length]);

  const approve = useCallback(async (actionId: string): Promise<{ ok: boolean; say: string }> => {
    const result = await api.approve(id, scenario.id, step, actionId);
    if (currentApprovalContext.current === approvalContext) {
      setDecision({ context: approvalContext, actionId, result });
      if (result.ok) setApproved((list) => (list.includes(actionId) ? list : [...list, actionId]));
    }
    return result;
  }, [id, scenario.id, step, approvalContext]);

  /** Move the forecast clock to another step that has a saved plan. The page stays; what changed is shown first. */
  const moveClock = useCallback((to: string) => {
    if (to === step) return;
    cameFrom.current = step;
    window.location.hash = walkHash(scenario.id, to, id);
  }, [id, scenario.id, step]);

  // --- the conversation: what the voice may do here ---------------------------------------------------
  const now = useRef({ moments, at, saved, step, go, approve, moveClock });
  now.current = { moments, at, saved, step, go, approve, moveClock };
  const runTool = useCallback(async (name: string, args: Record<string, unknown>): Promise<unknown> => {
    const s = now.current;
    const here = s.moments[Math.min(s.at, s.moments.length - 1)];
    const wanted = typeof args.action_id === "string" ? (args.action_id as string).toUpperCase() : null;
    if (name === "go_to_action") {
      const to = s.moments.findIndex((m) => (m.kind === "outside" || m.kind === "inside") && m.action.id === wanted);
      if (to < 0) return { ok: false, say: "That is not an action in the part of the plan on screen." };
      s.go(to);
      const m = s.moments[to] as Extract<Moment, { kind: "outside" | "inside" }>;
      return { ok: true, id: m.action.id, title: m.action.title, on_screen: m.kind === "outside" ? "the aerial evidence for it" : "the related scanned space" };
    }
    if (name === "next_finding") {
      if (s.at >= s.moments.length - 1) return { ok: false, say: "That was the last one." };
      s.go(s.at + 1);
      const m = s.moments[s.at + 1];
      return { ok: true, on_screen: m.kind, id: "action" in m ? m.action.id : null, title: "action" in m ? m.action.title : m.kind === "notice" ? m.message.subject : null };
    }
    if (name === "approve_action") {
      const target = here.kind === "notice" && (!wanted || wanted === here.actionId) ? here.actionId : wanted;
      return target ? s.approve(target) : { ok: false, say: "Tell me which action to approve." };
    }
    if (name === "hold_approval") return { ok: true, say: "Set aside. The resident notice is not approved." };
    if (name === "where_am_i") return { on_screen: here.kind, action: "action" in here ? here.action.id : null, forecast_step: s.saved.find((p) => p.step === s.step)?.label ?? null };
    if (name === "set_hours_left") {
      const hours = Number(args.hours);
      const options = s.saved.filter((p) => hoursOf(p.label) !== null);
      if (!Number.isFinite(hours) || options.length === 0) return { ok: false, say: "There is no other saved plan to move the clock to." };
      const nearest = options.reduce((best, p) => (Math.abs(hoursOf(p.label)! - hours) < Math.abs(hoursOf(best.label)! - hours) ? p : best));
      if (nearest.step === s.step) return { ok: true, changed: false, note: "The screen is already on the plan made for the closest saved forecast step." };
      const change = await api.clock(id, scenario.id, s.step ?? nearest.step, nearest.step).catch(() => null);
      window.setTimeout(() => s.moveClock(nearest.step), 60);
      return { ok: true, changed: true, note: "This is a replay: the plan made for that forecast step, not a new inspection. Say what was deferred and why, and what the cost became.",
               moved_to: nearest.label, what_changed: change?.rows.map((r) => ({ what: (r.before ?? r.after)!.title, change: CHANGE[r.change], why: r.reason })),
               cost_before_it_arrives: change ? { was: costRange(change.from.before_arrival.cost_low, change.from.before_arrival.cost_high), now: costRange(change.to.before_arrival.cost_low, change.to.before_arrival.cost_high) } : null };
    }
    return { ok: false, say: "I cannot do that from here." };
  }, [id, scenario.id]);

  useEffect(() => {
    if (!b) return;
    const about = `building=${id}&scenario=${encodeURIComponent(scenario.id)}${step ? `&step=${encodeURIComponent(step)}` : ""}&view=screen`;
    conversation.setStage({
      key: `${id}:${scenario.id}:${step}`, sessionUrl: `/api/voice/session?${about}`, notesUrl: `/api/voice/notes?${about}`, run: runTool,
      greeting: `Greet the owner in one sentence: name the building, say how long is left before ${b.threat.name} reaches it, and say they can ask what to fix first.`,
    });
    return () => conversation.setStage(null);
  }, [b, id, scenario.id, step, runTool]);

  // Tell the voice what is on screen, so "this" and "approve it" mean something.
  const seen = moment.kind + ("action" in moment ? moment.action.id : "");
  useEffect(() => {
    if (moment.kind === "outside") conversation.note(`The owner is looking at the aerial evidence for ${moment.action.id}: ${moment.action.title}.`);
    else if (moment.kind === "inside") conversation.note(`The owner is looking at the scanned space related to ${moment.action.id}.`);
    else if (moment.kind === "notice") conversation.note(`The resident notice is waiting for the owner's approval, action ${moment.actionId}. It is not approved until the owner says yes, nods or presses Approve.`);
    else if (moment.kind === "change") conversation.note("The owner is looking at what changed in the plan when the forecast clock moved.");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [seen]);

  // Arrow keys step through, so the presenter never has to find a button.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const el = e.target as HTMLElement | null;
      if (el && /^(INPUT|TEXTAREA|SELECT)$/.test(el.tagName)) return;
      if (e.key === "ArrowRight") go(at + 1); else if (e.key === "ArrowLeft") go(at - 1);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [at, go]);

  if (error) return <div className="fatal"><p>This building could not be opened: {error}.</p></div>;
  if (!b) return <div className="fatal quiet">Opening the building…</div>;
  if (!plan) {
    return <div className="fatal"><p>No inspection has been saved for this building at this forecast step.</p>
      <a href={prepareHash(scenario.id, step, id)}>Open the building page to run one</a></div>;
  }

  const t = b.threat;
  const hit = "action" in moment ? facing?.actions[moment.action.id] : undefined;
  const drawn = hit ? facing?.plans[hit.scan_id] : undefined;
  const aerialDate = monthYear(b.aerial.captured);
  const last = at >= moments.length - 1;
  const deferred = moment.kind === "change" ? moment.diff.rows.filter((r) => r.change === "deferred").length : 0;
  const forward = moment.kind === "change" ? moment.diff.rows.filter((r) => r.change === "brought_forward").length : 0;

  // What fills the screen, and the line that says where it came from and when.
  let picture: string | null = null, source = "";
  if (moment.kind === "overview") { picture = api.aerial(id); source = `Vexcel aerial photo, ${aerialDate}`; }
  else if (moment.kind === "outside") {
    const image = moment.action.site?.oblique_image ?? moment.action.site?.image;
    picture = image ? api.file(id, image) : api.aerial(id);
    source = `Vexcel aerial photo, ${aerialDate}${moment.action.structure ? `, ${moment.action.structure}` : ""}`;
  } else if (moment.kind === "inside" && moment.action.interior) {
    picture = api.file(id, moment.action.interior.image);
    source = `Matterport scan: ${moment.action.interior.scan_name}`;
  }

  return (
    <div className={`walk walk-${moment.kind}`}>
      {picture && <img className="walk-backdrop" src={picture} alt="" aria-hidden="true" />}
      {picture && <img className="walk-picture" key={picture} src={picture} alt="" />}

      <header className="walk-top">
        <div className="walk-place">
          <strong>{b.record.name}</strong>
          <span>{b.record.units ? `${b.record.units.toLocaleString("en-US")} homes` : b.record.type_label}, {b.record.city}</span>
        </div>
        <div className="walk-clock">
          <strong>{t.hours_left == null ? "No arrival time for this site" : t.hours_left <= 0 ? "Damaging conditions are here" : `About ${Math.round(t.hours_left)} hours until damaging conditions here`}</strong>
          <span>{t.name}{t.replay ? `. Replay of the forecast issued ${when(t.forecast_issued)}` : ""}</span>
          {saved.length > 1 && (
            <div className="walk-steps" role="group" aria-label="Forecast step">
              {saved.map((p) => (
                <button key={p.step} type="button" aria-pressed={p.step === step} onClick={() => moveClock(p.step)}>{p.label.replace(/ before .*/, "")}</button>
              ))}
            </div>
          )}
        </div>
      </header>

      {moment.kind === "inside" && !moment.action.interior && hit && drawn && (
        <section className="walk-card walk-related">
          <p className="walk-eyebrow">Related scanned space</p>
          <h2>{drawn.scan_name}</h2>
          <FacingDiagram plan={drawn} hit={hit} label={hit.line} />
          <p className="walk-note">Drawn from the scan's own wall measurements. Direction and distance depend on where the scan sits on the aerial, so treat them as approximate. One scanned unit, not the whole building.</p>
        </section>
      )}

      {moment.kind === "change" && (
        <section className="walk-card walk-change">
          <p className="walk-eyebrow">The forecast moved: {moment.diff.from.label} to {moment.diff.to.label}</p>
          <h2>{costRange(moment.diff.from.before_arrival.cost_low, moment.diff.from.before_arrival.cost_high)} of work before arrival
            becomes {costRange(moment.diff.to.before_arrival.cost_low, moment.diff.to.before_arrival.cost_high).toLowerCase()}</h2>
          <ol>
            {moment.diff.rows.map((r, i) => (
              <li key={i} className={`is-${r.change}`}>
                <span className="walk-chip">{CHANGE[r.change]}</span>
                <strong>{(r.before ?? r.after)!.title}</strong>
                {r.reason && <small>{r.reason}</small>}
              </li>
            ))}
          </ol>
          <p className="walk-note">{moment.diff.note}</p>
        </section>
      )}

      {(moment.kind === "notice" || moment.kind === "approved") && (
        <section className="walk-card walk-notice">
          <p className="walk-eyebrow">{moment.kind === "approved" ? "Resident notice approved" : "Resident notice, drafted and waiting for you"}</p>
          <h2>{moment.message.subject}</h2>
          <pre>{moment.message.body}</pre>
        </section>
      )}

      <footer className="walk-bottom">
        <div className="walk-finding">
          {moment.kind === "overview" && <><h1>{plan.headline}</h1>
            <p>{plan.actions.filter((a) => a.timing === "before_arrival").length} things to do before it arrives, {costRange(plan.totals.before_arrival.cost_low, plan.totals.before_arrival.cost_high).toLowerCase()}.</p></>}
          {moment.kind === "outside" && <><h1>{moment.action.title}</h1><p>{firstSentence(moment.action.why)}</p>
            <p className="walk-facts"><span className="walk-chip is-still_fits">Fits before arrival</span>{moment.action.crew}. {moment.action.hours_of_work} hours. {costRange(moment.action.cost_low, moment.action.cost_high)}.
              {approved.includes(moment.action.id) && <span className="walk-chip is-approved">Approved</span>}</p></>}
          {moment.kind === "inside" && <><h1>{moment.action.interior ? moment.action.title
              : hit?.facing[0] ? `The ${`${hit.facing[0].room ?? ""} ${hit.facing[0].kind}`.trim().toLowerCase()} faces it, about ${Math.round(hit.facing[0].metres)} m away`
              : "No window or outside door in the nearest scanned unit faces it"}</h1>
            <p>{moment.action.interior ? firstSentence(moment.action.why) : `${hit?.line ?? ""} This is the scanned space nearest to the finding you just saw.`}</p></>}
          {moment.kind === "change" && <><h1>{deferred > 0 ? `${deferred} ${deferred === 1 ? "job no longer fits" : "jobs no longer fit"} in the time left`
              : forward > 0 ? `${forward} ${forward === 1 ? "job fits" : "jobs fit"} before arrival again` : "The plan made for this forecast step"}</h1>
            <p>About {moment.diff.to.safe_working_hours ?? 0} hours of safe working time remain at this step. The revised resident notice is the next decision.</p></>}
          {moment.kind === "notice" && <><h1>Approve the notice to residents?</h1><p>Say yes, nod or press Approve to publish it.</p>
            {approvalMessage && !approvalMessage.ok && <p role="alert">{approvalMessage.say}</p>}</>}
          {moment.kind === "approved" && <><h1>The resident notice is approved</h1>
            <p role="status">{approvalMessage?.ok ? approvalMessage.say : "The notice is available in the residents’ private Brace updates."}</p></>}
          {source && <p className="walk-source">{source}{t.replay ? ". The forecast is a replay; the imagery is newer than it." : ""}</p>}
        </div>
        <div className="walk-acts">
          {moment.kind === "notice"
            ? <><button type="button" className="walk-primary" onClick={() => void approve(moment.actionId)}>Approve</button>
                <button type="button" onClick={() => go(at - 1)}>Not now</button></>
            : moment.kind === "change"
              ? <button type="button" className="walk-primary" onClick={() => go(moments.findIndex((m) => m.kind === "notice" || m.kind === "approved"))}>Review the revised notice</button>
              : !last && <button type="button" className="walk-primary" onClick={() => go(at + 1)}>
                  {moment.kind === "overview" ? "Show me the first one" : moments[at + 1].kind === "inside" ? "See the related scanned space" : moments[at + 1].kind === "notice" ? "Go to the decision" : "Next finding"}
                </button>}
          <div className="walk-quiet">
            <button type="button" onClick={() => go(at - 1)} disabled={at === 0}>Back</button>
            <span aria-label={`Step ${at + 1} of ${moments.length}`}>{at + 1} / {moments.length}</span>
            <a href={prepareHash(scenario.id, step, id)}>Explore yourself</a>
          </div>
        </div>
      </footer>

      <ConversationPanel ready={voiceReady} compact />
    </div>
  );
}
