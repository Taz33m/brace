import type { FacingHit, ScanPlan } from "../types";

/** How far beyond the walls the drawing extends, in metres: room for the arrow, its label and the north mark. */
const MARGIN = 3.4;
const ARROW = 2.6;

/**
 * A scanned space drawn to scale from its own wall measurements, north up, with the windows and outside
 * doors that face one of the plan's outside actions picked out, and an arrow toward that action.
 *
 * Nothing here is a fixed picture: every wall, opening, direction and distance comes from the data.
 */
export function FacingDiagram({ plan, hit, label }: { plan: ScanPlan; hit: FacingHit; label: string }) {
  const points = plan.rooms.flatMap((r) => r.walls.flat());
  if (points.length === 0) return null;
  const east = points.map((p) => p[0]), north = points.map((p) => p[1]);
  const minE = Math.min(...east) - MARGIN, maxE = Math.max(...east) + MARGIN;
  const minN = Math.min(...north) - MARGIN, maxN = Math.max(...north) + MARGIN;
  // The page's y runs down and north runs up, so north is drawn negated.
  const x = (e: number) => e, y = (n: number) => -n;
  const facing = new Set(hit.facing.map((f) => f.id));

  // The arrow starts at the largest facing opening, or at the middle of the space when none faces the action.
  const first = plan.openings.find((o) => o.id === hit.facing[0]?.id);
  const from = first ? first.at : [(Math.min(...east) + Math.max(...east)) / 2, (Math.min(...north) + Math.max(...north)) / 2];
  const away = Math.hypot(hit.target.east - from[0], hit.target.north - from[1]) || 1;
  const ue = (hit.target.east - from[0]) / away, un = (hit.target.north - from[1]) / away;
  const tip = [from[0] + ue * ARROW, from[1] + un * ARROW];
  const head = (back: number, side: number) => `${x(tip[0] - ue * back - un * side)},${y(tip[1] - un * back + ue * side)}`;
  const right = ue >= 0;

  const named = plan.rooms.filter((r) => r.name && r.name !== "Void").map((r) => {
    const ps = r.walls.flat();
    const es = ps.map((p) => p[0]), ns = ps.map((p) => p[1]);
    return { id: r.id, name: r.name!, e: (Math.min(...es) + Math.max(...es)) / 2, n: (Math.min(...ns) + Math.max(...ns)) / 2,
             wide: Math.max(...es) - Math.min(...es), deep: Math.max(...ns) - Math.min(...ns) };
  }).filter((r) => r.wide > 1.9 && r.deep > 1.2);   // a name only where there is room to read it

  return (
    <svg className="facing-diagram" viewBox={`${x(minE)} ${y(maxN)} ${maxE - minE} ${maxN - minN}`} role="img" aria-label={label}>
      {plan.rooms.filter((r) => r.outdoor).map((r) => {
        // Walls come in no particular order, so the corners are walked round the room's middle to tint it.
        const corners = r.walls.flat();
        const ce = corners.reduce((s, p) => s + p[0], 0) / corners.length, cn = corners.reduce((s, p) => s + p[1], 0) / corners.length;
        const round = [...corners].sort((p, q) => Math.atan2(p[1] - cn, p[0] - ce) - Math.atan2(q[1] - cn, q[0] - ce));
        return <polygon key={r.id} className="fd-outdoor" points={round.map((p) => `${x(p[0])},${y(p[1])}`).join(" ")} />;
      })}
      {plan.rooms.map((r) => r.walls.map((w, i) => (
        <line key={`${r.id}-${i}`} className="fd-wall" x1={x(w[0][0])} y1={y(w[0][1])} x2={x(w[1][0])} y2={y(w[1][1])} />
      )))}
      {named.map((r) => <text key={r.id} className="fd-room" x={x(r.e)} y={y(r.n)}>{r.name}</text>)}
      {plan.openings.filter((o) => o.outside).map((o) => (
        <line key={o.id} className={facing.has(o.id) ? "fd-open fd-faces" : "fd-open"}
              x1={x(o.ends[0][0])} y1={y(o.ends[0][1])} x2={x(o.ends[1][0])} y2={y(o.ends[1][1])} />
      ))}

      <line className="fd-arrow" x1={x(from[0])} y1={y(from[1])} x2={x(tip[0] - ue * 0.3)} y2={y(tip[1] - un * 0.3)} />
      <polygon className="fd-head" points={`${x(tip[0])},${y(tip[1])} ${head(0.55, 0.26)} ${head(0.55, -0.26)}`} />
      <text className="fd-far" x={x(tip[0] + ue * 0.25)} y={y(tip[1] + un * 0.25) + (un < -0.5 ? 0.45 : un > 0.5 ? -0.15 : 0.13)} textAnchor={right ? "start" : "end"}>
        about {Math.round(hit.facing[0]?.metres ?? hit.metres)} m
      </text>

      <g className="fd-north" transform={`translate(${x(maxE - 0.8)} ${y(maxN - 1.9)})`}>
        <line x1={0} y1={0.9} x2={0} y2={0} /><polygon points="0,-0.35 0.22,0.1 -0.22,0.1" /><text x={0} y={-0.5}>N</text>
      </g>
      <g className="fd-scale" transform={`translate(${x(minE + 0.6)} ${y(minN + 0.7)})`}>
        <line x1={0} y1={0} x2={2} y2={0} /><line x1={0} y1={-0.12} x2={0} y2={0.12} /><line x1={2} y1={-0.12} x2={2} y2={0.12} />
        <text x={1} y={-0.25}>2 m</text>
      </g>
    </svg>
  );
}
