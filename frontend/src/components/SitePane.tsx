import { useState } from "react";
import { api } from "../api";
import { monthYear } from "../format";
import { fromFrac, structureAt, toFrac } from "../geo";
import type { Building, LonLat, Selection } from "../types";

const VIEWS = [
  { id: "overhead", label: "Overhead", oblique: null },
  { id: "from-north", label: "From north", oblique: "oblique-south" },
  { id: "from-east", label: "From east", oblique: "oblique-west" },
  { id: "from-south", label: "From south", oblique: "oblique-north" },
  { id: "from-west", label: "From west", oblique: "oblique-east" },
];

interface Props {
  b: Building;
  selection: Selection | null;
  /** Where the 3D tour stands, when the open scan has a GPS fix. */
  tour: { lon: number; lat: number; bearing: number | null } | null;
  marks: { id: string; lon: number; lat: number }[];
  onPick: (p: LonLat) => void;
  onMark: (id: string) => void;
}

export function SitePane({ b, selection, tour, marks, onPick, onMark }: Props) {
  const [view, setView] = useState("overhead");
  const [hover, setHover] = useState<string | null>(null);
  const W = b.aerial.width, H = b.aerial.height;
  const px = (lon: number, lat: number): [number, number] => { const [fx, fy] = toFrac(b, lon, lat); return [fx * W, fy * H]; };
  const pts = (ring: LonLat[]) => ring.map(([lon, lat]) => px(lon, lat).join(",")).join(" ");
  const views = VIEWS.filter((v) => !v.oblique || b.aerial.obliques.includes(v.oblique));
  const overhead = view === "overhead";
  const k = Math.max(W, H) / 600; // keep marks a constant size on screen whatever the photo's resolution
  const fracOf = (e: React.MouseEvent<SVGSVGElement>): LonLat => {
    const box = e.currentTarget.getBoundingClientRect();
    return fromFrac(b, (e.clientX - box.left) / box.width, (e.clientY - box.top) / box.height);
  };
  const sel = selection ? px(selection.lon, selection.lat) : null;
  const here = tour ? px(tour.lon, tour.lat) : null;
  const cone = (bearing: number, r: number) => {
    const a1 = ((bearing - 28 - 90) * Math.PI) / 180, a2 = ((bearing + 28 - 90) * Math.PI) / 180;
    return `M0,0 L${Math.cos(a1) * r},${Math.sin(a1) * r} A${r},${r} 0 0 1 ${Math.cos(a2) * r},${Math.sin(a2) * r} Z`;
  };

  return (
    <section className="pane site-pane" aria-label="Outside: the site from the air">
      <header className="pane-head">
        <h2>Outside</h2>
        <div className="pane-tools">
          <select value={view} onChange={(e) => setView(e.target.value)} aria-label="Aerial view">
            {views.map((v) => <option key={v.id} value={v.id}>{v.label}</option>)}
          </select>
          <span className="pane-note">Photo from {monthYear(b.aerial.captured)}</span>
        </div>
      </header>
      <div className="pane-body">
        {overhead ? (
          <div className="aerial-fit" style={{ "--ar": W / H } as React.CSSProperties}>
            <img src={api.aerial(b.id)} alt="Aerial photo of the site" draggable={false} />
            <svg viewBox={`0 0 ${W} ${H}`} onClick={(e) => onPick(fracOf(e))}
                 onMouseMove={(e) => { const s = structureAt(b, fracOf(e)); setHover(s ? `${s.id}: ${s.roof_material ?? "roof"}, condition ${s.roof_condition ?? "unknown"} of 5` : null); }}
                 onMouseLeave={() => setHover(null)}>
              {b.structures.map((s) => (
                <g key={s.id}>
                  <polygon points={pts(s.polygon)} className={`structure ${selection?.structure === s.id ? "active" : ""}`} />
                  <text x={px(...s.centroid)[0]} y={px(...s.centroid)[1]} fontSize={13 * k} className="structure-label">{s.id}</text>
                </g>
              ))}
              {marks.map((m) => {
                const [x, y] = px(m.lon, m.lat);
                return (
                  <g key={m.id} className="mark" onClick={(e) => { e.stopPropagation(); onMark(m.id); }}>
                    <circle cx={x} cy={y} r={9 * k} />
                    <text x={x} y={y + 3.5 * k} fontSize={9.5 * k}>{m.id.replace("A", "")}</text>
                  </g>
                );
              })}
              {here && (
                <g transform={`translate(${here[0]},${here[1]})`} className="here">
                  {tour!.bearing != null && <path d={cone(tour!.bearing, 30 * k)} />}
                  <circle r={4.5 * k} />
                </g>
              )}
              {sel && <circle cx={sel[0]} cy={sel[1]} r={13 * k} className="pick" />}
            </svg>
          </div>
        ) : (
          <img className="oblique" src={api.oblique(b.id, view, selection?.structure)} alt={`Angled aerial photo, ${view.replace("-", " ")}`} />
        )}
      </div>
      <footer className="pane-foot">
        {overhead ? (hover ?? selection?.label ?? "Numbered marks are actions in the plan. Click a mark or anywhere on the site.")
          : `Angled view of ${selection?.structure ?? b.structures[0].id}. Switch to Overhead to pick a spot.`}
      </footer>
    </section>
  );
}
