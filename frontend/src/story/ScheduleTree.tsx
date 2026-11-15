import QRCode from "qrcode";
import { useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api";
import { ConversationPanel } from "../components/ConversationPanel";
import { conversation } from "../conversation";
import "./story.css";

/**
 * The schedule as a tree. The property's total at the top; under it the buildings, ranked by how much fuel stands
 * at their walls; under the building that holds the scanned home, the home, its rooms, and each line: a quantity
 * from the scan times a price a page states. Every figure opens down to where it came from.
 */
interface Money { low: number | null; high: number | null; lines?: number; lines_priced?: number }
interface Line { what: string; quantity: number; unit: string; from: string; price_low: number | null; price_high: number | null; low: number | null; high: number | null;
                 source_url: string | null; seen: string | null; at: { standpoint: string; direction: string } | null }
interface Room { name: string; area_sqft: number | null; read: boolean; items: Line[]; total: Money }
interface Unit { scan_id: string; name: string; scan_date: string | null; rooms: Room[]; total: Money; multiplied_by: number; statement: string | null }
interface Building { id: string; exposure_rank: number; brush_within_5ft_percent: number | null; tree_cover_over_roof_percent: number | null; fire_zone: string | null; in_fire_zone: boolean | null; homes_assumed: number; polygon: [number, number][]; total: Money; units: Unit[] }
interface Schedule {
  property: { id: number; name: string; address: string | null; homes: number; homes_on_record: number; scenario: string; scan_date: string | null; bounds: [number, number, number, number]; aerial: { width: number; height: number } };
  total: Money; home: { name: string; total: Money; multiplied_by: number };
  kinds_of_home: { name: string; homes: number; per_home: Money; low: number | null; high: number | null; basis: string; scanned: boolean }[];
  lost_rent_per_month: { low: number; high: number; how: string } | null;
  numbers: { scans_read: number; rooms_read: number; views_looked_at: number; items_named: number; prices_confirmed: number; minutes: number | null };
  buildings: Building[]; assumptions: string[]; not_counted: string[];
}

const short = (n: number) => (n >= 1e6 ? `$${(n / 1e6).toFixed(1)}M` : n >= 1e4 ? `$${Math.round(n / 1e3)}K` : `$${Math.round(n).toLocaleString("en-US")}`);
const range = (m: { low: number | null; high: number | null }) => (m.low == null || m.high == null ? "no price confirmed" : m.low === m.high ? short(m.low) : `${short(m.low)} to ${short(m.high)}`);
const each = (l: Line) => (l.price_low == null ? "" : l.price_high && l.price_high !== l.price_low ? `$${l.price_low.toLocaleString("en-US")} to $${l.price_high.toLocaleString("en-US")}` : `$${l.price_low.toLocaleString("en-US")}`);

export function ScheduleTree({ site, controller = false }: { site: number; controller?: boolean }) {
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

  useEffect(() => { api.config().then((c) => setVoiceReady(c.voice_ready)).catch(() => setVoiceReady(false)); }, []);
  // The schedule can be talked to. What the voice may do here: open a building, open a room, point at a line, show the working.
  // Each tool moves the screen and hands back only what the schedule holds, so the voice has nothing else to say.
  useEffect(() => {
    const like = (a: string, b: string) => a.toLowerCase().replace(/[^a-z0-9]/g, "").includes(b.toLowerCase().replace(/[^a-z0-9]/g, ""));
    const money = (m: { low: number | null; high: number | null }) => range(m);      // rounded as on the screen, so what is said matches what is shown
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
        return { ok: true, room: r.name, line: l.what, quantity: l.quantity, unit: l.unit, quantity_from: l.from, what_the_agent_saw: l.seen,
                 price_each: l.price_low == null ? "no confirmed price" : money({ low: l.price_low, high: l.price_high }), amount: money(l),
                 price_from: l.source_url ? `a page on ${new URL(l.source_url).hostname.replace(/^www\./, "")}, fetched and found to state this price` : "no page" };
      }
      if (name === "show_working") {
        setHow(true);
        return { ok: true, how_it_is_worked_out: d.assumptions, not_counted: d.not_counted };
      }
      return { ok: false, say: "That cannot be done on this screen." };
    };
    conversation.setStage({ key: `schedule:${site}`, sessionUrl: `/api/schedule/${site}/voice`, notesUrl: `/api/schedule/${site}/voice/notes`,
                            greeting: "Greet the owner in one short sentence and give the property's figure, saying it is an extrapolation from one scanned home.", run });
    return () => { conversation.setStage(null); conversation.stop(); };
  }, [site]);

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
    fetch(`/api/schedule/${site}`).then(async (r) => { if (!r.ok) throw new Error((await r.json().catch(() => null))?.detail || "no schedule for this property"); return r.json(); })
      .then((d: Schedule) => { setData(d); setOpen(d.buildings.find((b) => b.units.length)?.id ?? null); }).catch((e) => setError(e.message));
  }, [site]);
  useEffect(() => {
    const key = (e: KeyboardEvent) => { if (e.key === "Escape") { if (how) setHow(false); else if (room) setRoom(null); else window.location.hash = "#/"; } };
    window.addEventListener("keydown", key);
    return () => window.removeEventListener("keydown", key);
  }, [how, room]);

  // Whatever was opened, by a click or by the voice, is brought into view.
  useEffect(() => {
    const el = document.querySelector(room ? ".sc-home-rows > div.is-open" : ".sc-list > li.is-open");
    el?.scrollIntoView({ block: room ? "start" : "nearest", behavior: "smooth" });
  }, [open, room]);

  const shapes = useMemo(() => {
    if (!data) return [];
    const [w, s, e, n] = data.property.bounds, W = data.property.aerial.width, H = data.property.aerial.height;
    return data.buildings.map((b) => ({ id: b.id, rank: b.exposure_rank, scanned: b.units.length > 0,
      points: b.polygon.map(([lon, lat]) => `${(((lon - w) / (e - w)) * W).toFixed(1)},${(((n - lat) / (n - s)) * H).toFixed(1)}`).join(" ") }));
  }, [data]);

  if (error) return <div className="fatal" role="alert">{error}</div>;
  if (!data) return <div className="st-wait" />;
  const p = data.property, n = data.numbers, count = data.buildings.length;
  const partial = (data.total.lines_priced ?? 0) < (data.total.lines ?? 0);

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

  return (
    <div className="st sc">
      <div className="sc-map">
        <svg viewBox={`0 0 ${p.aerial.width} ${p.aerial.height}`} preserveAspectRatio="xMidYMid slice" aria-hidden="true">
          <image href={`/api/buildings/${site}/aerial.jpg`} width={p.aerial.width} height={p.aerial.height} />
          {shapes.map((b) => (
            <polygon key={b.id} points={b.points} className={`${b.id === open ? "is-open" : ""}${b.scanned ? " is-scanned" : ""}`}
              style={{ fillOpacity: 0.12 + 0.5 * (1 - (b.rank - 1) / Math.max(1, count - 1)) }} onClick={() => { setOpen(b.id); setRoom(null); }} />
          ))}
        </svg>
        <p className="sc-key"><i />More fuel at the walls<small>Vexcel</small></p>
      </div>

      <div className="sc-tree">
        <a className="st-home sc-home" href="#/">Brace</a>
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
        <table className="sc-kinds"><tbody>
          {data.kinds_of_home.map((k) => (
            <tr key={k.name} title={k.basis}>
              <th>{k.homes} x {k.name}</th><td>{range(k.per_home)} each</td><td>{k.scanned ? "the scanned home" : "scaled from the scanned home"}</td><td>{range(k)}</td>
            </tr>
          ))}
        </tbody></table>

        <ol className="sc-list">
          {data.buildings.map((b) => {
            const unit = b.units[0];
            return (
              <li key={b.id} className={b.id === open ? "is-open" : ""}>
                <button type="button" onClick={() => { setOpen(b.id === open ? null : b.id); setRoom(null); }}>
                  <b>{b.exposure_rank}</b><span>Building {b.id}{unit ? <small>scanned home here</small> : null}</span>
                  <span title={b.fire_zone ? `${b.fire_zone} fire hazard severity zone (CAL FIRE)` : b.in_fire_zone === false ? "Outside the mapped fire hazard severity zones (CAL FIRE)" : undefined}>{[b.brush_within_5ft_percent != null ? `${Math.round(b.brush_within_5ft_percent)}% of walls` : null, b.tree_cover_over_roof_percent != null ? `${Math.round(b.tree_cover_over_roof_percent)}% of roof` : null].filter(Boolean).join(", ")}</span>
                  <span>{b.homes_assumed} {b.homes_assumed === 1 ? "home" : "homes"}</span><strong>{range(b.total)}</strong>
                </button>
                {b.id === open && unit && (
                  <div className="sc-home-rows">
                    <p>{unit.name}. Scanned by Matterport{unit.scan_date ? `, model dated ${unit.scan_date}` : ""}. {range(unit.total)}.</p>
                    {unit.rooms.map((r) => (
                      <div key={r.name} className={r.name === room ? "is-open" : ""}>
                        <button type="button" onClick={() => { setRoom(r.name === room ? null : r.name); setPointed(null); }}>
                          <span>{r.name}{!r.read && <small>not seen by the camera: measured only</small>}</span><span>{r.items.length} lines</span><strong>{range(r.total)}</strong>
                        </button>
                        {r.name === room && (
                          <table><tbody>
                            {r.items.map((l, i) => (
                              <tr key={l.what + i} title={l.seen ?? undefined} className={pointed === `${r.name}:${l.what}` ? "is-pointed" : ""}
                                  ref={pointed === `${r.name}:${l.what}` ? (el) => el?.scrollIntoView({ block: "center", behavior: "smooth" }) : undefined}>
                                <th>{l.what}{l.seen && <small>{l.seen}</small>}</th>
                                <td>{l.quantity.toLocaleString("en-US")} {l.unit}<small>{l.from.replace(" from the scan", "")}</small></td>
                                <td>{l.source_url ? <a href={l.source_url} target="_blank" rel="noreferrer">{each(l)}</a> : ""}</td>
                                <td className={l.low == null ? "is-none" : ""}>{range(l)}</td>
                              </tr>
                            ))}
                          </tbody></table>
                        )}
                      </div>
                    ))}
                  </div>
                )}
                {b.id === open && !unit && <div className="sc-home-rows"><p>No home under this roof has been scanned. Its figure is the scanned home times {b.homes_assumed}.</p></div>}
              </li>
            );
          })}
        </ol>

        <footer>
          <button type="button" className="ft-how sc-how" onClick={() => setHow(!how)}>How this is worked out</button>
          <button type="button" className="ft-how sc-how" onClick={() => void showPhone()}>Phone</button>
          <span>{n.scans_read} scan, {n.rooms_read} rooms, {n.views_looked_at} views, {n.items_named} items named, {n.prices_confirmed} prices confirmed{n.minutes ? `, ${n.minutes} minutes` : ""}</span>
        </footer>
        {phone && <aside className="sc-phone"><img src={phone.qr} alt="" /><span>{phone.url}</span></aside>}
        {how && (
          <aside className="ft-panel sc-panel">
            <ul>{data.assumptions.map((a) => <li key={a}>{a}</li>)}</ul>
            <ul className="ft-found"><li className="is-used">Not counted: {data.not_counted.join("; ").toLowerCase()}.</li></ul>
          </aside>
        )}
      </div>
    </div>
  );
}
