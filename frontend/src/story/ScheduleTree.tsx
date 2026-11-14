import { useEffect, useMemo, useState } from "react";
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
interface Building { id: string; exposure_rank: number; brush_within_5ft_percent: number | null; in_fire_zone: boolean | null; homes_assumed: number; polygon: [number, number][]; total: Money; units: Unit[] }
interface Schedule {
  property: { id: number; name: string; address: string | null; homes: number; scenario: string; scan_date: string | null; bounds: [number, number, number, number]; aerial: { width: number; height: number } };
  total: Money; home: { name: string; total: Money; multiplied_by: number };
  lost_rent_per_month: { low: number; high: number; how: string } | null;
  numbers: { scans_read: number; rooms_read: number; views_looked_at: number; items_named: number; prices_confirmed: number; minutes: number | null };
  buildings: Building[]; assumptions: string[]; not_counted: string[];
}

const short = (n: number) => (n >= 1e6 ? `$${(n / 1e6).toFixed(1)}M` : n >= 1e4 ? `$${Math.round(n / 1e3)}K` : `$${Math.round(n).toLocaleString("en-US")}`);
const range = (m: { low: number | null; high: number | null }) => (m.low == null || m.high == null ? "no price confirmed" : m.low === m.high ? short(m.low) : `${short(m.low)} to ${short(m.high)}`);
const each = (l: Line) => (l.price_low == null ? "" : l.price_high && l.price_high !== l.price_low ? `$${l.price_low.toLocaleString("en-US")} to $${l.price_high.toLocaleString("en-US")}` : `$${l.price_low.toLocaleString("en-US")}`);

export function ScheduleTree({ site }: { site: number }) {
  const [data, setData] = useState<Schedule | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState<string | null>(null);        // the building that is open
  const [room, setRoom] = useState<string | null>(null);        // the room that is open inside it
  const [how, setHow] = useState(false);

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
        <header>
          <h1>{p.name}</h1>
          <p>If fire reaches it. {p.homes.toLocaleString("en-US")} homes.</p>
        </header>
        <div className="sc-total">
          <strong>{range(data.total)}</strong>
          <span>to put back what the owner owns inside{data.lost_rent_per_month ? `, and ${short(data.lost_rent_per_month.low)} to ${short(data.lost_rent_per_month.high)} of rent for each month empty` : ""}</span>
          <em>One scanned home, {range(data.home.total)}, times {data.home.multiplied_by.toLocaleString("en-US")} homes. An extrapolation.{partial ? ` ${data.total.lines_priced} of ${data.total.lines} lines have a confirmed price.` : ""}</em>
        </div>

        <ol className="sc-list">
          {data.buildings.map((b) => {
            const unit = b.units[0];
            return (
              <li key={b.id} className={b.id === open ? "is-open" : ""}>
                <button type="button" onClick={() => { setOpen(b.id === open ? null : b.id); setRoom(null); }}>
                  <b>{b.exposure_rank}</b><span>Building {b.id}{unit ? <small>scanned home here</small> : null}</span>
                  <span>{b.brush_within_5ft_percent != null ? `${Math.round(b.brush_within_5ft_percent)}% of walls` : ""}</span>
                  <span>{b.homes_assumed} homes</span><strong>{range(b.total)}</strong>
                </button>
                {b.id === open && unit && (
                  <div className="sc-home-rows">
                    <p>{unit.name}. Scanned by Matterport{unit.scan_date ? `, model dated ${unit.scan_date}` : ""}. {range(unit.total)}.</p>
                    {unit.rooms.map((r) => (
                      <div key={r.name} className={r.name === room ? "is-open" : ""}>
                        <button type="button" onClick={() => setRoom(r.name === room ? null : r.name)}>
                          <span>{r.name}{!r.read && <small>not seen by the camera: measured only</small>}</span><span>{r.items.length} lines</span><strong>{range(r.total)}</strong>
                        </button>
                        {r.name === room && (
                          <table><tbody>
                            {r.items.map((l, i) => (
                              <tr key={l.what + i} title={l.seen ?? undefined}>
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
          <span>{n.scans_read} scan, {n.rooms_read} rooms, {n.views_looked_at} views, {n.items_named} items named, {n.prices_confirmed} prices confirmed{n.minutes ? `, ${n.minutes} minutes` : ""}</span>
        </footer>
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
