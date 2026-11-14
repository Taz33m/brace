import { useEffect, useMemo, useState } from "react";
import "./story.css";

/**
 * The file on one home for a property insurer. Left: the building from above and the room as the scan saw it,
 * before any water. Right: the water, and the schedule of what it would cost to put the home back, each line a
 * quantity measured from the scan times a price a page states.
 */
const WATER = [2, 4, 6];

interface Line { id: string; what: string; quantity: number; unit: string; how: string; price: number | null; price_high: number | null; low: number | null; high: number | null; source: { title: string; url: string } | null }
interface Total { low: number | null; high: number | null; lines: number; priced: number }
interface FileData {
  name: string; address: string | null; bounds: [number, number, number, number]; aerial: { width: number; height: number };
  outside: { building: string; polygon: [number, number][]; below_highest_ft: number; roof_height_ft: number | null; trees_within_5ft_percent: number | null };
  inside: { name: string; model_made: string | null; rooms: { type: string; area_sqft: number; ceiling_ft: number }[]; floor_sqft: number; ceiling_ft: number; wall_ft: number;
            inner_doors: number; windows: number; contents: { name: string }[]; contents_room: string | null; has_photo: boolean };
  water: { set_ft: number; at_this_building_ft: number; drywall_cut_ft: number };
  schedule: { work: Line[]; contents: Line[]; contents_spared: string[]; work_total: Total; contents_total: Total; total: { low: number; high: number } | null };
  limits: { building: number; contents: number; what: string; source: { title: string; url: string } };
  prices: { made_at: string | null; found: number; confirmed: number; searches: number };
  not_counted: string[]; assumptions: string[];
}

const usd = (n: number) => `$${Math.round(n).toLocaleString("en-US")}`;
const range = (low: number | null, high: number | null) => (low == null || high == null ? "no price confirmed" : low === high ? usd(low) : `${usd(low)} to ${usd(high)}`);
const each = (l: Line) => (l.price == null ? "" : l.price_high ? `$${l.price.toLocaleString("en-US")} to $${l.price_high.toLocaleString("en-US")}` : `$${l.price.toLocaleString("en-US")}`);

export function InsurerFile({ site, scan }: { site: number; scan: string }) {
  const [water, setWater] = useState(4);
  const [data, setData] = useState<FileData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [how, setHow] = useState(false);

  useEffect(() => { document.documentElement.classList.add("st-on"); return () => document.documentElement.classList.remove("st-on"); }, []);
  useEffect(() => {
    let on = true;
    fetch(`/api/file/${site}/${scan}?water_ft=${water}`).then(async (r) => { if (!r.ok) throw new Error((await r.json().catch(() => null))?.detail || "no file for this home"); return r.json(); })
      .then((d) => { if (on) setData(d); }).catch((e) => { if (on) setError(e.message); });
    return () => { on = false; };
  }, [site, scan, water]);
  useEffect(() => {
    const key = (e: KeyboardEvent) => { if (e.key === "Escape") { if (how) setHow(false); else window.location.hash = "#/"; } };
    window.addEventListener("keydown", key);
    return () => window.removeEventListener("keydown", key);
  }, [how]);

  // The aerial, cut down to this building and a little around it.
  const view = useMemo(() => {
    if (!data) return null;
    const [w, s, e, n] = data.bounds, W = data.aerial.width, H = data.aerial.height;
    const pts = data.outside.polygon.map(([lon, lat]) => [((lon - w) / (e - w)) * W, ((n - lat) / (n - s)) * H]);
    const xs = pts.map((p) => p[0]), ys = pts.map((p) => p[1]);
    const cx = (Math.min(...xs) + Math.max(...xs)) / 2, cy = (Math.min(...ys) + Math.max(...ys)) / 2;
    const half = Math.max(Math.max(...xs) - Math.min(...xs), Math.max(...ys) - Math.min(...ys)) * 1.25;
    return { box: `${cx - half} ${cy - half * 0.62} ${half * 2} ${half * 1.24}`, points: pts.map((p) => p.map((v) => v.toFixed(1)).join(",")).join(" "), W, H };
  }, [data]);

  if (error) return <div className="fatal" role="alert">{error}</div>;
  if (!data || !view) return <div className="st-wait" />;
  const { inside, outside, schedule } = data, depth = data.water.at_this_building_ft, wet = depth > 0;
  const lines = schedule.work_total.lines + schedule.contents_total.lines, priced = schedule.work_total.priced + schedule.contents_total.priced;

  return (
    <div className="st fi">
      <div className="fi-before">
        <figure>
          <svg viewBox={view.box} preserveAspectRatio="xMidYMid slice" aria-hidden="true">
            <image href={`/api/buildings/${site}/aerial.jpg`} width={view.W} height={view.H} />
            <polygon points={view.points} className={wet ? "is-wet" : ""} />
          </svg>
          <figcaption>
            <strong>Outside</strong>
            <span>Building {outside.building}. Ground {outside.below_highest_ft > 0 ? `${outside.below_highest_ft} ft below the highest on the site` : "the highest on the site"}{outside.roof_height_ft ? `. Roof at ${outside.roof_height_ft} ft` : ""}{outside.trees_within_5ft_percent ? `. Trees within 5 ft of ${Math.round(outside.trees_within_5ft_percent)}% of it` : ""}.</span>
            <small>Vexcel</small>
          </figcaption>
        </figure>
        <figure>
          {inside.has_photo ? <img src={`/api/file/${site}/${scan}/inside.jpg`} alt="" draggable={false} /> : <div className="fi-nophoto" />}
          <figcaption>
            <strong>Inside</strong>
            <span>{inside.floor_sqft} sq ft in {inside.rooms.length} rooms. {inside.wall_ft} ft of wall, {inside.inner_doors} interior doors, {inside.windows} windows{inside.contents.length ? `. ${inside.contents.length} pieces of furniture in the ${(inside.contents_room || "room").toLowerCase()}` : ""}.</span>
            <small>Matterport{inside.model_made ? `, ${inside.model_made}` : ""}</small>
          </figcaption>
        </figure>
      </div>

      <div className="fi-after">
        <a className="st-home fi-home" href="#/">Brace</a>
        <header>
          <h1>{inside.name}</h1>
          <p>{data.name}{data.address ? `, ${data.address}` : ""}</p>
        </header>

        <div className="fi-water">
          <div role="group" aria-label="Water">{WATER.map((v) => <button key={v} type="button" aria-pressed={v === water} onClick={() => setWater(v)}>{v} ft</button>)}</div>
          <span>{wet ? `${depth} ft of water in this building` : "This building stays dry"}</span>
        </div>

        <div className="fi-total" aria-live="polite">
          <span>To put it back</span>
          <strong>{schedule.total ? range(Math.round(schedule.total.low / 100) * 100, Math.round(schedule.total.high / 100) * 100) : wet ? "No price confirmed" : "$0"}</strong>
          {wet && priced < lines && <em>{priced} of {lines} lines have a confirmed price. The rest are not in this figure.</em>}
        </div>

        {wet && (
          <div className="fi-lines">
            <table>
              <tbody>
                {schedule.work.map((l) => (
                  <tr key={l.id} title={l.how}>
                    <th>{l.what}</th><td>{l.quantity.toLocaleString("en-US")} {l.unit}</td>
                    <td>{l.source ? <a href={l.source.url} target="_blank" rel="noreferrer">{each(l)}</a> : ""}</td><td className={l.low == null ? "is-none" : ""}>{range(l.low, l.high)}</td>
                  </tr>
                ))}
                {schedule.contents.length > 0 && <tr className="fi-gap"><th colSpan={4}>Contents</th></tr>}
                {schedule.contents.map((l, i) => (
                  <tr key={l.what + i} title={l.how}>
                    <th>{l.what}</th><td>{l.how.split(",")[0]}</td>
                    <td>{l.source ? <a href={l.source.url} target="_blank" rel="noreferrer">{each(l)}</a> : ""}</td><td className={l.low == null ? "is-none" : ""}>{range(l.low, l.high)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            {schedule.contents_spared.length > 0 && <p>Above the water: {schedule.contents_spared.join(", ")}.</p>}
          </div>
        )}

        <footer>
          <button type="button" className="ft-how fi-how" onClick={() => setHow(!how)}>How this is worked out</button>
          <a href={`#/flood/${site}`}>The whole site</a>
        </footer>

        {how && (
          <aside className="ft-panel fi-panel">
            <ul>{data.assumptions.map((a) => <li key={a}>{a}</li>)}</ul>
            <ul className="ft-found">
              <li className="is-used">Not counted: {data.not_counted.join("; ").toLowerCase()}.</li>
              <li className="is-used">Prices: {data.prices.confirmed} of {data.prices.found} found were confirmed on their page{data.prices.made_at ? `, ${data.prices.made_at.slice(0, 10)}` : ""}.</li>
              <li className="is-used"><a href={data.limits.source.url} target="_blank" rel="noreferrer">Federal flood insurance</a> pays at most {usd(data.limits.building)} a building and {usd(data.limits.contents)} for contents.</li>
            </ul>
          </aside>
        )}
      </div>
    </div>
  );
}
