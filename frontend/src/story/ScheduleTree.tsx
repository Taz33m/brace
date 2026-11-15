import QRCode from "qrcode";
import { useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api";
import { ConversationPanel } from "../components/ConversationPanel";
import { conversation } from "../conversation";
import "./story.css";
import { ScheduleReview } from "./ScheduleReview";
import { FireAftermath } from "./FireAftermath";
import { smooth } from "./gsap";

/**
 * The schedule as a tree. The property's total at the top; under it the buildings, ranked by how much fuel stands
 * at their walls; under the building that holds the scanned home, the home, its rooms, and each line: a quantity
 * from the scan times a price a page states. Every figure opens down to where it came from.
 */
interface Money { low: number | null; high: number | null; lines?: number; lines_priced?: number }
interface Line { what: string; quantity: number; unit: string; from: string; price_low: number | null; price_high: number | null; low: number | null; high: number | null;
                 source_url: string | null; seen: string | null; at: { standpoint: string; direction: string } | null;
                 key?: string | null; match?: Match | null; guide_low?: number | null; guide_high?: number | null }
/** The products one item most likely is: found by looking at it in the scan, each price confirmed on its page. Never an identification. */
interface Match { label: string; make: string; model: string | null; name: string; low: number; high: number; seen: string[]; brand_read: string | null;
                  candidates: { make: string; model: string | null; name: string; price: number; url: string; store: string; why: string }[] }
interface Room { name: string; area_sqft: number | null; read: boolean; room_id: string | null; items: Line[]; total: Money;
                 doubts: { id: string; about: string | null; doubt: string }[]; left_out: { saw: string; why: string }[] }
interface Unit { scan_id: string; name: string; scan_date: string | null; rooms: Room[]; total: Money; multiplied_by: number; statement: string | null;
                 decisions: { left_out: number; merged: number; doubts: number }; rechecks: { room_name: string; changed: string[] }[] }
interface Cover { check: { cover: number; verdict: string; say: string; example: { loss: number; low: number; high: number } }; note: string }
interface Again { room: string; state: "looking" | "done" | "failed"; changed: string[]; statement: string | null; before?: Money; after?: Money }
interface Building { id: string; exposure_rank: number; brush_within_5ft_percent: number | null; in_fire_zone: boolean | null; homes_assumed: number; polygon: [number, number][]; total: Money; units: Unit[] }
export interface Schedule {
  property: { id: number; name: string; address: string | null; homes: number; homes_on_record: number; scenario: string; scan_date: string | null; bounds: [number, number, number, number]; aerial: { width: number; height: number } };
  total: Money; home: { name: string; total: Money; multiplied_by: number };
  kinds_of_home: { name: string; homes: number; per_home: Money; low: number | null; high: number | null; basis: string; scanned: boolean }[];
  lost_rent_per_month: { low: number; high: number; how: string } | null;
  numbers: { scans_read: number; rooms_read: number; views_looked_at: number; items_named: number; prices_confirmed: number; minutes: number | null };
  buildings: Building[]; assumptions: string[]; not_counted: string[];
}

const short = (n: number) => (n >= 1e6 ? `$${(n / 1e6).toFixed(1)}M` : n >= 1e4 ? `$${Math.round(n / 1e3)}K` : `$${Math.round(n).toLocaleString("en-US")}`);
const range = (m: { low: number | null; high: number | null }) => (m.low == null || m.high == null ? "no price confirmed" : m.low === m.high ? short(m.low) : `${short(m.low)} to ${short(m.high)}`);
const dollars = (m: { low: number | null; high: number | null }) => (m.low == null || m.high == null ? "no price confirmed" : m.low === m.high ? `$${Math.round(m.low).toLocaleString("en-US")}` : `$${Math.round(m.low).toLocaleString("en-US")} to $${Math.round(m.high).toLocaleString("en-US")}`);
const each = (l: Line) => (l.price_low == null ? "" : l.price_high && l.price_high !== l.price_low ? `$${l.price_low.toLocaleString("en-US")} to $${l.price_high.toLocaleString("en-US")}` : `$${l.price_low.toLocaleString("en-US")}`);

export function ScheduleTree({ site, controller = false, inline = false }: { site: number; controller?: boolean; inline?: boolean }) {
  const [review, setReview] = useState<{ data: Schedule; captured: string } | null>(null);
  const [data, setData] = useState<Schedule | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState<string | null>(null);        // the building that is open
  const [room, setRoom] = useState<string | null>(null);        // the room that is open inside it
  const [how, setHow] = useState(false);
  const [pointed, setPointed] = useState<string | null>(null);  // the line the voice is pointing at
  const [voiceReady, setVoiceReady] = useState(false);
  const [phone, setPhone] = useState<{ url: string; qr: string } | null>(null);   // the code that opens the controller on a phone
  const seen = useRef(0);
  const latest = useRef<Schedule | null>(null);
  latest.current = data;
  const [cover, setCover] = useState<Cover | null>(null);         // the owner's cover checked against the schedule
  const [asking, setAsking] = useState(false);                    // the cover field is open
  const [amount, setAmount] = useState("");
  const [again, setAgain] = useState<Again | null>(null);         // a second look at one room: under way, or what it found
  const [version, setVersion] = useState(0);                      // goes up when the schedule is rebuilt, so the voice is told again
  const [card, setCard] = useState<{ room: string; what: string } | null>(null);     // the line whose likely make and model is shown
  const [finding, setFinding] = useState<{ key: string; state: "looking" | "none" | "failed" } | null>(null);

  const load = () => fetch(`/api/schedule/${site}`).then(async (r) => { if (!r.ok) throw new Error((await r.json().catch(() => null))?.detail || "no schedule for this property"); return r.json() as Promise<Schedule>; });
  // The two things the owner can ask the agent to do. Both go to the server; neither sends anything to anyone.
  const checkCover = async (dollars: number): Promise<Cover | null> => {
    const r = await fetch(`/api/schedule/${site}/cover?amount=${encodeURIComponent(dollars)}`, { method: "POST" });
    if (!r.ok) return null;
    const got = (await r.json()) as Cover;
    setCover(got); setAsking(false); setHow(false);
    return got;
  };
  const lookAgain = (roomName: string) => {
    if (again?.state === "looking") return;
    setAgain({ room: roomName, state: "looking", changed: [], statement: null });
    fetch(`/api/schedule/${site}/recheck?room=${encodeURIComponent(roomName)}`, { method: "POST" })
      .then(async (r) => { if (!r.ok) throw new Error(String(r.status)); return r.json(); })
      .then(async (got: { stop: string; changed: string[]; statement: string | null; home_before: Money; home_after: Money }) => {
        const ok = got.stop === "finished";
        setAgain({ room: roomName, state: ok ? "done" : "failed", changed: got.changed, statement: got.statement, before: got.home_before, after: got.home_after });
        if (ok) { setData(await load()); setVersion((v) => v + 1); }
        conversation.cue("finding", ok ? `The second look at the ${roomName} is back. ${got.changed.length ? got.changed.join(". ") : "Nothing changed"}. The scanned home is now ${range(got.home_after)}.`
                                       : `The second look at the ${roomName} could not be finished. Nothing was changed.`);
      })
      .catch(() => setAgain({ room: roomName, state: "failed", changed: [], statement: null }));
  };
  // Look at one item in the scan and find the products it most likely is. A real agent run of about a minute.
  const findModel = (roomName: string, what: string) => {
    const key = `${roomName}:${what}`;
    if (finding?.state === "looking") return;
    setFinding({ key, state: "looking" });
    fetch(`/api/schedule/${site}/match?room=${encodeURIComponent(roomName)}&item=${encodeURIComponent(what)}`, { method: "POST" })
      .then(async (r) => { if (!r.ok) throw new Error(String(r.status)); return r.json(); })
      .then(async (got: { match: Match | null }) => {
        setFinding(got.match ? null : { key, state: "none" });
        if (got.match) { setData(await load()); setVersion((v) => v + 1); }
        conversation.cue("finding", got.match
          ? `The search for the ${what} in the ${roomName} is back. ${got.match.label}: ${got.match.make} ${got.match.model ?? got.match.name}, ${dollars(got.match)}, from ${got.match.candidates.length} product ${got.match.candidates.length === 1 ? "page" : "pages"}. It is a match by appearance, not an identification.`
          : `The search for the ${what} in the ${roomName} found no product whose price could be confirmed. The line keeps its cost guide price.`);
      })
      .catch(() => setFinding({ key, state: "failed" }));
  };
  const act = useRef({ checkCover, lookAgain, findModel });
  act.current = { checkCover, lookAgain, findModel };

  useEffect(() => { api.config().then((c) => setVoiceReady(c.voice_ready)).catch(() => setVoiceReady(false)); }, []);
  // The schedule can be talked to. What the voice may do here: open a building, open a room, point at a line, show the working.
  // Each tool moves the screen and hands back only what the schedule holds, so the voice has nothing else to say.
  useEffect(() => {
    const like = (a: string, b: string) => a.toLowerCase().replace(/[^a-z0-9]/g, "").includes(b.toLowerCase().replace(/[^a-z0-9]/g, ""));
    const money = (m: { low: number | null; high: number | null }) => range(m);      // rounded as on the screen, so what is said matches what is shown
    const told = (m: Match) => ({ label: m.label, make: m.make, model: m.model, name: m.name, price_each: dollars(m), product_pages: m.candidates.map((c) => c.store),
                                  seen_in_the_scan: m.seen, note: "A match by appearance, not an identification, unless a brand was read in the scan." });
    const run = (name: string, args: Record<string, unknown>) => {
      const d = latest.current;
      if (!d) return { ok: false, say: "The schedule is still loading." };
      const scanned = d.buildings.find((b) => b.units.length);
      const findRoom = (words: string) => scanned?.units[0].rooms.find((r) => like(r.name, words)) ?? scanned?.units[0].rooms.find((r) => like(words, r.name));
      if (name === "open_building") {
        const want = String(args.building ?? "").trim();
        const b = /scan/i.test(want) ? scanned : d.buildings.find((x) => x.id.toLowerCase() === want.toLowerCase()) ?? d.buildings.find((x) => String(x.exposure_rank) === want.replace(/\D/g, ""));
        if (!b) return { ok: false, say: "There is no such building on this schedule." };
        setHow(false); setOpen(b.id); setRoom(null); setPointed(null);
        return { ok: true, building: b.id, rank: b.exposure_rank, of: d.buildings.length, walls_with_vegetation_within_5ft_percent: b.brush_within_5ft_percent, homes: b.homes_assumed,
                 figure: money(b.total), holds_the_scanned_home: b.units.length > 0, note: "Homes are shared among buildings by roof area; the figure is that share times the average home." };
      }
      if (name === "open_room" || name === "explain_line") {
        const r = findRoom(String(args.room ?? ""));
        if (!scanned || !r) return { ok: false, say: "That room is not in the scanned home." };
        setHow(false); setOpen(scanned.id); setRoom(r.name);
        if (name === "open_room") {
          setPointed(null);
          return { ok: true, room: r.name, seen_by_the_camera: r.read, figure: money(r.total), lines: r.items.map((l) => ({ what: l.what, quantity: l.quantity, unit: l.unit, amount: money(l) })) };
        }
        const l = r.items.find((x) => like(x.what, String(args.item ?? ""))) ?? r.items.find((x) => like(String(args.item ?? ""), x.what.split(" ")[0]));
        if (!l) return { ok: false, say: "That line is not in this room." };
        setPointed(`${r.name}:${l.what}`);
        setCard(l.key ? { room: r.name, what: l.what } : null);
        return { ok: true, room: r.name, line: l.what, closest_match: l.match ? told(l.match) : "not looked for yet; find_model can look", quantity: l.quantity, unit: l.unit, quantity_from: l.from, what_the_agent_saw: l.seen,
                 price_each: l.price_low == null ? "no confirmed price" : money({ low: l.price_low, high: l.price_high }), amount: money(l),
                 price_from: l.source_url ? `a page on ${new URL(l.source_url).hostname.replace(/^www\./, "")}, fetched and found to state this price` : "no page" };
      }
      if (name === "show_working") {
        setHow(true);
        return { ok: true, how_it_is_worked_out: d.assumptions, not_counted: d.not_counted };
      }
      if (name === "find_model") {
        const r = findRoom(String(args.room ?? ""));
        const l = r?.items.find((x) => like(x.what, String(args.item ?? ""))) ?? r?.items.find((x) => like(String(args.item ?? ""), x.what.split(" ")[0]));
        if (!scanned || !r || !l || !l.key) return { ok: false, say: "That is not something the camera saw in that room, so it cannot be looked at." };
        setHow(false); setOpen(scanned.id); setRoom(r.name); setPointed(`${r.name}:${l.what}`); setCard({ room: r.name, what: l.what });
        if (l.match) return { ok: true, already_found: true, ...told(l.match) };
        act.current.findModel(r.name, l.what);
        return { ok: true, started: true, line: l.what, room: r.name, price_now: money({ low: l.price_low, high: l.price_high }),
                 say: "The agent is looking at it in the scan and searching for products that match. It takes about a minute. Say so, and that you will tell them what it finds." };
      }
      if (name === "look_again") {
        const r = findRoom(String(args.room ?? ""));
        if (!scanned || !r || !r.room_id) return { ok: false, say: "The camera did not stand in that room, so it cannot be read again." };
        setHow(false); setOpen(scanned.id); setRoom(r.name); setPointed(null);
        act.current.lookAgain(r.name);
        return { ok: true, started: true, room: r.name, doubts: r.doubts.map((x) => x.doubt), say: "The agent is reading that room again. It takes about a minute. Say so, and that you will tell them what changed." };
      }
      if (name === "check_cover") {
        const dollars = Number(args.amount);
        if (!Number.isFinite(dollars) || dollars <= 0) return { ok: false, say: "Ask the owner how much cover they carry for the fit-out, in dollars." };
        return act.current.checkCover(dollars).then((got) => (got ? { ok: true, verdict: got.check.verdict, say: got.check.say, on_a_loss_of: got.check.example.loss,
          paid_at_the_low_end: got.check.example.low, paid_at_the_high_end: got.check.example.high, note: "A note to the broker has been drafted on the screen. Nothing is sent." } : { ok: false, say: "The cover could not be checked." }));
      }
      return { ok: false, say: "That cannot be done on this screen." };
    };
    conversation.setStage({ key: `schedule:${site}:${version}`, sessionUrl: `/api/schedule/${site}/voice`, notesUrl: `/api/schedule/${site}/voice/notes`,
                            greeting: "Greet the owner in one short sentence and give the property's figure, saying it is an extrapolation from one scanned home.", run, nods: false, hint: "Ask what a room would cost to put back, or whether your cover is enough." });
  }, [site, version]);
  useEffect(() => () => { conversation.setStage(null); conversation.stop(); }, []);

  // Two devices, one schedule. The phone tells the server what it has opened; the big screen follows.
  useEffect(() => {
    if (!controller) return;
    void fetch(`/api/schedule/${site}/live`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ open, room, pointed, how }) }).catch(() => {});
  }, [controller, site, open, room, pointed, how]);
  useEffect(() => {
    if (controller) return;
    const t = window.setInterval(() => {
      fetch(`/api/schedule/${site}/live`).then((r) => r.json()).then((live: { rev: number; open?: string | null; room?: string | null; pointed?: string | null; how?: boolean }) => {
        if (!live.rev || live.rev === seen.current) return;
        const first = seen.current === 0;
        seen.current = live.rev;
        if (first) return;                    // what was open before this screen loaded is not replayed
        setOpen(live.open ?? null); setRoom(live.room ?? null); setPointed(live.pointed ?? null); setHow(!!live.how);
      }).catch(() => {});
    }, 600);
    return () => window.clearInterval(t);
  }, [controller, site]);
  const showPhone = async () => {
    if (phone) { setPhone(null); return; }
    const { ip, vr_port } = await fetch("/api/lan").then((r) => r.json()).catch(() => ({ ip: null, vr_port: 5185 }));
    const url = `https://${ip ?? "this-computer"}:${vr_port ?? 5185}/#/ctl/${site}`;
    setPhone({ url, qr: await QRCode.toDataURL(url, { margin: 1, width: 240 }) });
  };

  useEffect(() => { document.documentElement.classList.add("st-on"); return () => document.documentElement.classList.remove("st-on"); }, []);
  useEffect(() => {
    load().then((d) => { setData(d); setOpen(d.buildings.find((b) => b.units.length)?.id ?? null); }).catch((e) => setError(e.message));
  }, [site]);
  useEffect(() => {
    const key = (e: KeyboardEvent) => { if (review) return; if (e.key === "Escape") { if (card) setCard(null); else if (how) setHow(false); else if (room) setRoom(null); else if (!inline) window.location.hash = "#/"; } };
    window.addEventListener("keydown", key);
    return () => window.removeEventListener("keydown", key);
  }, [how, room, inline, review, card]);

  // Whatever was opened, by a click or by the voice, is brought into view.
  useEffect(() => {
    const el = document.querySelector(room ? ".sc-home-rows > div.is-open" : ".sc-list > li.is-open");
    // Inside its own list only: at the foot of the home page the page itself must not be dragged to it.
    const box = el?.closest(".sc-list");
    if (el && box) box.scrollTo({ top: (el as HTMLElement).offsetTop - (box as HTMLElement).offsetTop - (room ? 0 : 40), behavior: "smooth" });
  }, [open, room]);

  const shapes = useMemo(() => {
    if (!data) return [];
    const [w, s, e, n] = data.property.bounds, W = data.property.aerial.width, H = data.property.aerial.height;
    return data.buildings.map((b) => ({ id: b.id, rank: b.exposure_rank, scanned: b.units.length > 0,
      points: b.polygon.map(([lon, lat]) => `${(((lon - w) / (e - w)) * W).toFixed(1)},${(((n - lat) / (n - s)) * H).toFixed(1)}`).join(" ") }));
  }, [data]);

  if (error) return <div className="fatal" role="alert">{error}</div>;
  if (!data) return <div className={inline ? "sc is-inline" : "st-wait"} />;
  const p = data.property, n = data.numbers, count = data.buildings.length;
  const partial = (data.total.lines_priced ?? 0) < (data.total.lines ?? 0);
  const carded = card ? data.buildings.flatMap((b) => b.units).flatMap((u) => u.rooms).find((r) => r.name === card.room)?.items.find((l) => l.what === card.what) ?? null : null;
  const looking = !!card && finding?.key === `${card.room}:${card.what}` ? finding.state : null;

  // On the phone there is no list to read: the name, the figure, the voice, and what the big screen is showing.
  if (controller) {
    return (
      <div className="st ctl">
        <ConversationPanel ready={voiceReady} />
        <h1>{p.name}</h1>
        <strong>{range(data.total)}</strong>
        <p>{pointed ? pointed.replace(":", ", ") : room ? room : open ? `Building ${open}` : how ? "How this is worked out" : "Ask about a building, a room or a line."}</p>
        <small>The big screen follows.</small>
      </div>
    );
  }

  const returnHome = () => {
    setReview(null);
    requestAnimationFrame(() => {
      const target = document.getElementById("home-after-fire");
      if (target) {
        if (smooth.lenis) smooth.lenis.scrollTo(target, { immediate: true, force: true });
        else target.scrollIntoView({ behavior: "instant" as ScrollBehavior });
        target.querySelector<HTMLElement>("[tabindex]")?.focus({ preventScroll: true });
      }
    });
  };

  return (<>
    <div className={`st sc${inline ? " is-inline" : ""}`}>
      {review && <ScheduleReview data={review.data} captured={review.captured} onClose={() => setReview(null)} onContinue={site === 9519837 ? returnHome : undefined} />}
      <div className="sc-map">
        <svg viewBox={`0 0 ${p.aerial.width} ${p.aerial.height}`} preserveAspectRatio="xMidYMid slice" aria-hidden="true">
          <image href={`/api/buildings/${site}/aerial.jpg`} width={p.aerial.width} height={p.aerial.height} />
          {shapes.map((b) => (
            <polygon key={b.id} points={b.points} className={`${b.id === open ? "is-open" : ""}${b.scanned ? " is-scanned" : ""}`}
              style={{ fillOpacity: 0.12 + 0.5 * (1 - (b.rank - 1) / Math.max(1, count - 1)) }} onClick={() => { setOpen(b.id); setRoom(null); }} />
          ))}
        </svg>
        <p className="sc-key"><i />More fuel at the walls<small>Vexcel</small></p>
        {card && carded && (
          <aside className="sc-card" aria-label={`${carded.what}: likely make and model`}>
            <button type="button" className="sc-card-x" aria-label="Close" onClick={() => setCard(null)}>×</button>
            <img src={`/api/schedule/${site}/view.jpg?room=${encodeURIComponent(card.room)}&item=${encodeURIComponent(card.what)}`} alt="" onError={(e) => { e.currentTarget.style.display = "none"; }} />
            <span>{carded.what}, {card.room}</span>
            {carded.match ? (<>
              <strong>{dollars(carded.match)}</strong>
              <p className="sc-card-name"><em>{carded.match.label}</em>{carded.match.make} {carded.match.model ?? carded.match.name}</p>
              <ul>
                {carded.match.candidates.map((c) => (
                  <li key={c.url}><a href={c.url} target="_blank" rel="noreferrer" title={c.why}>
                    <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M14 4h6v6M20 4l-9 9M18 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5" /></svg>
                    <b>{c.make} {c.model ?? c.name}</b><i>${Math.round(c.price).toLocaleString("en-US")}</i><small>{c.store}</small>
                  </a></li>
                ))}
              </ul>
              <small>{carded.guide_low != null && carded.guide_high != null ? `Was ${dollars({ low: carded.guide_low, high: carded.guide_high })} for any ${carded.what.toLowerCase()}. ` : ""}Matched by how it looks in the scan{carded.match.seen.length ? `: ${carded.match.seen.slice(0, 4).join(", ")}` : ""}. Not an identification.</small>
            </>) : (<>
              <strong className="is-wide">{dollars({ low: carded.price_low, high: carded.price_high })}</strong>
              <p className="sc-card-name"><em>Any {carded.what.toLowerCase()}</em>from a cost guide</p>
              {looking === "none" && <small>No product's price could be confirmed on its page, so the line keeps this price.</small>}
              {looking === "failed" && <small>The search could not be finished. Nothing was changed.</small>}
              <button type="button" disabled={finding?.state === "looking"} onClick={() => findModel(card.room, card.what)}>{looking === "looking" ? "Looking at it in the scan" : "Find the make and model"}</button>
            </>)}
          </aside>
        )}
      </div>

      <div className="sc-tree">
        {!inline && <a className="st-home sc-home" href="#/">Brace</a>}
        <ConversationPanel ready={voiceReady} compact />
        <header>
          <h1>{p.name}</h1>
          <p>If fire reaches it. {p.homes.toLocaleString("en-US")} homes.</p>
        </header>
        <div className="sc-total">
          <strong>{range(data.total)}</strong>
          <span>to put back what the owner owns inside{data.lost_rent_per_month ? `, and ${short(data.lost_rent_per_month.low)} to ${short(data.lost_rent_per_month.high)} of rent for each month empty` : ""}</span>
          {partial && <em>{data.total.lines_priced} of {data.total.lines} lines have a confirmed price.</em>}
        </div>
        <button className="sr-open" onClick={() => setReview({ data: structuredClone(data), captured: new Date().toISOString() })}>Review &amp; export the evidence</button>
        <table className="sc-kinds"><tbody>
          {data.kinds_of_home.map((k) => (
            <tr key={k.name} title={k.basis}>
              <th>{k.homes} x {k.name}</th><td>{range(k.per_home)} each</td><td>{k.scanned ? "this home" : "scaled from this home"}</td><td>{range(k)}</td>
            </tr>
          ))}
        </tbody></table>

        <ol className="sc-list">
          {data.buildings.map((b) => {
            const unit = b.units[0];
            return (
              <li key={b.id} className={b.id === open ? "is-open" : ""}>
                <button type="button" onClick={() => { setOpen(b.id === open ? null : b.id); setRoom(null); }}>
                  <b>{b.exposure_rank}</b><span>Building {b.id}{unit ? <small>this home</small> : null}</span>
                  <span>{b.brush_within_5ft_percent != null ? `${Math.round(b.brush_within_5ft_percent)}% of walls` : ""}</span>
                  <span>{b.homes_assumed} {b.homes_assumed === 1 ? "home" : "homes"}</span><strong>{range(b.total)}</strong>
                </button>
                {b.id === open && unit && (
                  <div className="sc-home-rows">
                    <p>{unit.name}. Matterport{unit.scan_date ? `, scan dated ${unit.scan_date}` : ""}. {range(unit.total)}.</p>
                    {unit.rooms.map((r) => (
                      <div key={r.name} className={r.name === room ? "is-open" : ""}>
                        <button type="button" onClick={() => { setRoom(r.name === room ? null : r.name); setPointed(null); }}>
                          <span>{r.name}{!r.read && <small>not seen by the camera: measured only</small>}{r.doubts.length > 0 && <small className="sc-unsure">unsure of {r.doubts.length}</small>}</span><span>{r.items.length} lines</span><strong>{range(r.total)}</strong>
                        </button>
                        {r.name === room && (
                          <table><tbody>
                            {r.items.map((l, i) => (
                              <tr key={l.what + i} title={l.seen ?? undefined} className={`${pointed === `${r.name}:${l.what}` ? "is-pointed" : ""}${l.key ? " is-seen" : ""}`}
                                  onClick={l.key ? (e) => { if ((e.target as HTMLElement).closest("a")) return; setPointed(`${r.name}:${l.what}`); setCard({ room: r.name, what: l.what }); } : undefined}
                                  ref={pointed === `${r.name}:${l.what}` ? (el) => el?.scrollIntoView({ block: "center", behavior: "smooth" }) : undefined}>
                                <th>{l.what}{l.match ? <small className="sc-matched">{l.match.make} {l.match.model ?? ""}</small> : l.seen && <small>{l.seen}</small>}</th>
                                <td>{l.quantity.toLocaleString("en-US")} {l.unit}<small>{l.from.replace(" from the scan", "")}</small></td>
                                <td>{l.match?.candidates[0] ? <a href={l.match.candidates[0].url} target="_blank" rel="noreferrer">{each(l)}</a> : l.source_url ? <a href={l.source_url} target="_blank" rel="noreferrer">{each(l)}</a> : ""}</td>
                                <td className={l.low == null ? "is-none" : ""}>{range(l)}</td>
                              </tr>
                            ))}
                          </tbody></table>
                        )}
                        {r.name === room && (r.doubts.length > 0 || r.left_out.length > 0 || r.room_id) && (
                          <div className="sc-decided">
                            {r.doubts.map((x) => <p key={x.id} className="is-doubt"><b>Unsure</b>{x.doubt}</p>)}
                            {r.left_out.length > 0 && <p><b>Left out</b>{r.left_out.map((x) => `${x.saw} (${x.why.replace("already recorded from another standpoint", "already counted")})`).join("; ")}</p>}
                            {again?.room === r.name && again.state === "done" && <p className="is-new"><b>Looked again</b>{again.changed.length ? again.changed.join(". ") : "Nothing changed"}.{again.before && again.after ? ` The home: ${range(again.before)} before, ${range(again.after)} now.` : ""}</p>}
                            {again?.room !== r.name && (() => { const c = [...unit.rechecks].reverse().find((x) => x.room_name === r.name); return c ? <p className="is-new"><b>Looked again</b>{c.changed.length ? c.changed.join(". ") : "Nothing changed"}.</p> : null; })()}
                            {again?.room === r.name && again.state === "failed" && <p><b>Looked again</b>The second look could not be finished. Nothing was changed.</p>}
                            {r.room_id && <button type="button" disabled={again?.state === "looking"} onClick={() => lookAgain(r.name)}>{again?.room === r.name && again.state === "looking" ? "Reading the room again" : "Look again"}</button>}
                          </div>
                        )}
                      </div>
                    ))}
                  </div>
                )}
                {b.id === open && !unit && <div className="sc-home-rows"><p>No home under this roof has been scanned. Its figure is {b.homes_assumed} {b.homes_assumed === 1 ? "home" : "homes"} at the average home's figure.</p></div>}
              </li>
            );
          })}
        </ol>

        <footer>
          <button type="button" className="ft-how sc-how" onClick={() => setHow(!how)}>How this is worked out</button>
          <button type="button" className="ft-how sc-how" onClick={() => { setAsking(!asking); setCover(null); }}>Check my cover</button>
          <button type="button" className="ft-how sc-how" onClick={() => void showPhone()}>Phone</button>
          <span>{n.scans_read} scan, {n.rooms_read} rooms, {n.views_looked_at} views, {n.items_named} items named, {n.prices_confirmed} prices confirmed{n.minutes ? `, ${n.minutes} minutes` : ""}</span>
        </footer>
        {asking && (
          <form className="ft-panel sc-panel sc-cover" onSubmit={(e) => { e.preventDefault(); const n = Number(amount.replace(/[^0-9.]/g, "")); if (n > 0) void checkCover(n); }}>
            <label htmlFor="sc-amount">Cover you carry for the fit-out, in dollars</label>
            <div><input id="sc-amount" inputMode="numeric" autoFocus value={amount} onChange={(e) => setAmount(e.target.value)} placeholder="4,000,000" /><button type="submit">Check</button></div>
          </form>
        )}
        {cover && (
          <aside className="ft-panel sc-panel sc-cover">
            <strong>{cover.check.verdict}</strong>
            <p>{cover.check.say}</p>
            <p>On a loss of {short(cover.check.example.loss)}: {short(cover.check.example.low)} paid at the low end of the range, {short(cover.check.example.high)} at the high end.</p>
            <pre>{cover.note}</pre>
            <button type="button" onClick={() => setCover(null)}>Close</button>
          </aside>
        )}
        {phone && <aside className="sc-phone"><img src={phone.qr} alt="" /><span>{phone.url}</span></aside>}
        {how && (
          <aside className="ft-panel sc-panel">
            <ul>{data.assumptions.map((a) => <li key={a}>{a}</li>)}</ul>
            <ul className="ft-found"><li className="is-used">Not counted: {data.not_counted.join("; ").toLowerCase()}.</li></ul>
          </aside>
        )}
      </div>
    </div>
    {site === 9519837 && <FireAftermath />}
  </>);
}
