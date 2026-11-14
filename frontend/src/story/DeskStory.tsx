import { useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api";
import type { Desk, DeskJob, DeskSchedule } from "../types";
import { gsap } from "./gsap";

/**
 * The storm desk, told by scrolling. Houston draws itself from every building in the storm's wind field;
 * the buildings with a plan light up, each with a ring that is its safe working time; and as the scroll runs
 * the clock, the crews the desk scheduled move between them until the time runs out. What did not fit is
 * shown, then what a second crew would buy, which is the question the desk put to the owner.
 *
 * Every figure is the desk's own: the saved run for the step, and the schedule worked out from the saved plans.
 */
const SCENARIO = "beryl-2024", STEP = "adv33", LATER = "adv37";
const COLOUR: Record<string, string> = { roofer: "#00b0e6", "tree crew": "#7fe0b0" };
const DAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
const WORDS = ["no", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten"];
const word = (n: number) => WORDS[n] ?? String(n);
const cap = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);
const money = (n: number) => `$${Math.round(n).toLocaleString("en-US")}`;
const clamp = (v: number) => Math.max(0, Math.min(1, v));
const ease = (t: number) => (t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2);

/** "Sat 06 Jul 16:00" plus some hours, as "Sun 10:00". */
function clockAt(issued: string, hours: number): string {
  const m = /^(\w{3}) \d+ \w+ (\d+):(\d+)/.exec(issued);
  if (!m) return "";
  const total = Number(m[2]) * 60 + Number(m[3]) + Math.round(hours * 60);
  const day = (DAYS.indexOf(m[1]) + Math.floor(total / 1440) + 7) % 7, mins = ((total % 1440) + 1440) % 1440;
  return `${DAYS[day]} ${String(Math.floor(mins / 60)).padStart(2, "0")}:${String(mins % 60).padStart(2, "0")}`;
}

interface Crew { trade: string; crew: number; jobs: DeskJob[] }
const crewsOf = (schedule: DeskSchedule): Crew[] => schedule.trades.flatMap((t) => {
  const byCrew = new Map<number, DeskJob[]>();
  for (const j of t.scheduled) byCrew.set(j.crew ?? 1, [...(byCrew.get(j.crew ?? 1) ?? []), j]);
  return [...byCrew.entries()].map(([crew, jobs]) => ({ trade: t.trade, crew, jobs: jobs.sort((a, b) => (a.start_h ?? 0) - (b.start_h ?? 0)) }));
});

export function DeskStory() {
  const section = useRef<HTMLElement>(null), canvas = useRef<HTMLCanvasElement>(null);
  const hud = useRef<HTMLDivElement>(null), hours = useRef<HTMLElement>(null), time = useRef<HTMLSpanElement>(null);
  const [desk, setDesk] = useState<Desk | null>(null);
  const [later, setLater] = useState<Desk | null>(null);
  const [city, setCity] = useState<[number, number][]>([]);
  const live = useRef({ city: 0, five: 0, t: 0, after: 0, second: 0 });

  useEffect(() => {
    let current = true;
    api.desk(SCENARIO, STEP).then((d) => { if (current) setDesk(d); }).catch(() => {});
    api.desk(SCENARIO, LATER).then((d) => { if (current) setLater(d); }).catch(() => {});
    api.portfolio(SCENARIO, STEP, "", "").then((p) => { if (current) setCity(p.points.map((pt) => [pt[2], pt[1]])); }).catch(() => {});
    return () => { current = false; };
  }, []);

  const view = useMemo(() => {
    if (!desk) return null;
    const placed = desk.buildings.filter((b) => b.lat != null && b.lon != null);
    const crews = crewsOf(desk.schedule);
    const deferred = desk.schedule.trades.flatMap((t) => t.deferred);
    // What a second crew of each trade would add: the jobs its schedule has that the standing one does not.
    const more = (desk.run?.what_more_crews_buy ?? []).flatMap((option) => option.trades.filter((t) => (option.crews?.[t.trade] ?? 1) > 1).map((t) => {
      const base = desk.schedule.trades.find((b) => b.trade === t.trade);
      const had = new Set((base?.scheduled ?? []).map((j) => `${j.building_id}:${j.job_id}`));
      return { trade: t.trade, people: t.people_covered - (base?.people_covered ?? 0), low: t.cost_low, high: t.cost_high, jobs: t.scheduled.filter((j) => !had.has(`${j.building_id}:${j.job_id}`)) };
    }));
    const end = Math.max(...placed.map((b) => b.safe_crew_hours), 1) + 1.5;
    const first = Math.min(...placed.map((b) => b.hours_left));
    const worst = [...deferred].sort((a, b) => b.people - a.people)[0] ?? null;
    return { placed, crews, deferred, more, end, first, worst };
  }, [desk]);
  const now = useRef({ view, desk, city });
  now.current = { view, desk, city };

  // The scroll is the clock.
  useEffect(() => {
    const el = section.current;
    if (!el) return;
    const q = (name: string) => el.querySelector<HTMLElement>(`[data-d="${name}"]`);
    const s = live.current, show = { autoAlpha: 1, y: 0, filter: "blur(0px)", duration: 0.8 }, hide = { autoAlpha: 0, y: 24, filter: "blur(8px)" };
    const ctx = gsap.context(() => {
      gsap.timeline({ defaults: { ease: "none" }, scrollTrigger: { trigger: el, start: "top top", end: "bottom bottom", scrub: 1 } })
        .fromTo(s, { city: 0 }, { city: 1, duration: 1.6 }, 0)
        .fromTo(q("title"), hide, show, 1)
        .fromTo(s, { five: 0 }, { five: 1, duration: 1 }, 1.4)
        .to(q("title"), { autoAlpha: 0, y: -20, duration: 0.6 }, 3.2)
        .fromTo(q("agent"), hide, show, 3.6)
        .fromTo(hud.current, { autoAlpha: 0 }, { autoAlpha: 1, duration: 0.6 }, 3.8)
        .fromTo(s, { t: 0 }, { t: 1, duration: 8 }, 4)
        .to(q("agent"), { autoAlpha: 0, duration: 0.5 }, 11.4)
        .fromTo(s, { after: 0 }, { after: 1, duration: 0.8 }, 12)
        .fromTo(q("after"), hide, show, 12)
        .to(q("after"), { autoAlpha: 0, y: -20, duration: 0.5 }, 14)
        .fromTo(s, { second: 0 }, { second: 1, duration: 2 }, 14.3)
        .fromTo(q("more"), hide, show, 14.4)
        .to(q("more"), { autoAlpha: 0, y: -20, duration: 0.5 }, 17)
        .fromTo(q("close"), hide, show, 17.3)
        .to(q("close"), { autoAlpha: 0, y: -20, duration: 0.5 }, 19.2)
        .fromTo(q("late"), hide, show, 19.5)
        .to({}, { duration: 1.6 }, 20.3);
    }, el);
    return () => ctx.revert();
  }, [desk, later]);

  // The picture: redrawn every frame from where the scroll has put the clock.
  useEffect(() => {
    const el = canvas.current;
    if (!el) return;
    const ctx = el.getContext("2d");
    if (!ctx) return;
    let raf = 0;
    const draw = () => {
      raf = requestAnimationFrame(draw);
      const { view: v, desk: d, city: dots } = now.current, s = live.current;
      const dpr = Math.min(window.devicePixelRatio, 2), W = el.clientWidth, H = el.clientHeight;
      if (el.width !== W * dpr || el.height !== H * dpr) { el.width = W * dpr; el.height = H * dpr; }
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.clearRect(0, 0, W, H);
      if (!v || !d || !v.placed.length) return;

      // The buildings with a plan decide the frame; the rest of the city falls where it falls.
      const k = Math.cos((v.placed.reduce((sum, b) => sum + b.lat!, 0) / v.placed.length) * Math.PI / 180);
      const xs = v.placed.map((b) => b.lon! * k), ys = v.placed.map((b) => b.lat!);
      const mx = (Math.min(...xs) + Math.max(...xs)) / 2, my = (Math.min(...ys) + Math.max(...ys)) / 2;
      const scale = Math.min((W * 0.5) / Math.max(Math.max(...xs) - Math.min(...xs), 0.01), (H * 0.56) / Math.max(Math.max(...ys) - Math.min(...ys), 0.01));
      const at = (lon: number, lat: number): [number, number] => [W * 0.54 + (lon * k - mx) * scale, H * 0.47 - (lat - my) * scale];
      const where = new Map(v.placed.map((b) => [b.building_id, at(b.lon!, b.lat!)]));
      // Two buildings close together would write over each other: the one further west puts its words on its left.
      const leftward = new Set<number>();
      v.placed.forEach((a, i) => v.placed.slice(i + 1).forEach((b) => {
        const [ax, ay] = where.get(a.building_id)!, [bx, by] = where.get(b.building_id)!;
        if (Math.abs(ay - by) < 64 && Math.abs(ax - bx) < 280) leftward.add(ax < bx ? a.building_id : b.building_id);
      }));
      const clock = s.t * v.end;

      ctx.fillStyle = `rgba(255, 194, 14, ${0.34 * s.city})`;
      for (const [lon, lat] of dots) { const [x, y] = at(lon, lat); if (x > -4 && x < W + 4 && y > -4 && y < H + 4) { ctx.beginPath(); ctx.arc(x, y, 1.5, 0, Math.PI * 2); ctx.fill(); } }

      // Where each crew is on the clock, and the ground it has covered.
      const crewAt = (jobs: DeskJob[]): { x: number; y: number; path: [number, number][] } => {
        const stops = jobs.map((j) => where.get(j.building_id)).filter(Boolean) as [number, number][];
        if (!stops.length) return { x: -99, y: -99, path: [] };
        let x = stops[0][0], y = stops[0][1];
        const path: [number, number][] = [stops[0]];
        for (let i = 1; i < jobs.length; i++) {
          const left = jobs[i - 1].end_h ?? 0, arrive = jobs[i].start_h ?? left;
          if (clock <= left) break;
          const f = arrive > left ? ease(clamp((clock - left) / (arrive - left))) : 1;
          x = stops[i - 1][0] + (stops[i][0] - stops[i - 1][0]) * f; y = stops[i - 1][1] + (stops[i][1] - stops[i - 1][1]) * f;
          path.push([x, y]);
        }
        return { x, y, path };
      };
      v.crews.forEach((c, n) => {
        const p = crewAt(c.jobs), colour = COLOUR[c.trade] ?? "#f3ece0", lift = n % 2 ? 30 : -30;
        ctx.globalAlpha = s.five;
        if (p.path.length > 1) { ctx.strokeStyle = colour; ctx.lineWidth = 1.5; ctx.setLineDash([2, 6]); ctx.beginPath(); p.path.forEach(([x, y], i) => (i ? ctx.lineTo(x, y) : ctx.moveTo(x, y))); ctx.stroke(); ctx.setLineDash([]); }
        ctx.fillStyle = colour; ctx.beginPath(); ctx.arc(p.x + lift, p.y - 30, 8, 0, Math.PI * 2); ctx.fill();
        ctx.strokeStyle = "#0b0b0c"; ctx.lineWidth = 2; ctx.stroke();
        ctx.font = '600 11px "Manrope", sans-serif'; ctx.textAlign = n % 2 ? "left" : "right"; ctx.fillText(c.trade, p.x + lift + (n % 2 ? 13 : -13), p.y - 26);
        ctx.globalAlpha = 1;
      });
      // A second crew of a trade comes in from the edge to the job it would add.
      if (s.second > 0) v.more.forEach((m, n) => m.jobs.forEach((j) => {
        const to = where.get(j.building_id);
        if (!to) return;
        const f = ease(s.second), x = W + 40 + (to[0] + (n % 2 ? 30 : -30) - W - 40) * f, y = to[1] + 74;
        ctx.strokeStyle = COLOUR[m.trade] ?? "#f3ece0"; ctx.lineWidth = 2.5; ctx.beginPath(); ctx.arc(x, y, 8, 0, Math.PI * 2); ctx.stroke();
        ctx.fillStyle = COLOUR[m.trade] ?? "#f3ece0"; ctx.font = '600 11px "Manrope", sans-serif'; ctx.textAlign = "center"; ctx.textAlign = n % 2 ? "left" : "right"; ctx.fillText(`second ${m.trade}`, x + (n % 2 ? 14 : -14), y + 4);
      }));

      // Each building: its ring is the safe working time it has left.
      for (const b of v.placed) {
        const [x, y] = where.get(b.building_id)!, left = Math.max(0, b.safe_crew_hours - clock), share = left / b.safe_crew_hours;
        ctx.globalAlpha = s.five;
        ctx.strokeStyle = "rgba(243, 236, 224, 0.2)"; ctx.lineWidth = 3; ctx.beginPath(); ctx.arc(x, y, 18, 0, Math.PI * 2); ctx.stroke();
        if (share > 0) { ctx.strokeStyle = "#ffc20e"; ctx.beginPath(); ctx.arc(x, y, 18, -Math.PI / 2, -Math.PI / 2 + Math.PI * 2 * share); ctx.stroke(); }
        ctx.fillStyle = share > 0 ? "#f3ece0" : "#8a8f98"; ctx.beginPath(); ctx.arc(x, y, 5, 0, Math.PI * 2); ctx.fill();
        const side = x > W * 0.72 || leftward.has(b.building_id) ? -1 : 1, tx = x + side * 32;
        ctx.textAlign = side > 0 ? "left" : "right";
        ctx.fillStyle = "#f3ece0"; ctx.font = '400 22px "Cormorant Garamond", Georgia, serif'; ctx.fillText(b.name, tx, y - 2);
        ctx.font = '400 12px "Manrope", sans-serif'; ctx.fillStyle = "rgba(243, 236, 224, 0.72)";
        const who = b.homes ? `${b.homes.toLocaleString("en-US")} homes` : `${b.tenants} businesses`;
        ctx.fillText(b.rent ? `${who}, ${money(b.rent.low)} to ${money(b.rent.high)} a month` : who, tx, y + 16);
        ctx.fillStyle = share > 0 ? "#ffc20e" : "#8a8f98";
        ctx.fillText(share > 0 ? `${left.toFixed(1)} h of safe working time` : "out of safe working time", tx, y + 32);
        const waiting = v.deferred.filter((j) => j.building_id === b.building_id), saved = v.more.flatMap((m) => m.jobs).filter((j) => j.building_id === b.building_id).length;
        if (waiting.length && s.after > 0) {
          ctx.globalAlpha = s.five * s.after;
          ctx.fillStyle = saved && s.second > 0.6 ? "#7fe0b0" : "#ff7a3c";
          ctx.fillText(saved && s.second > 0.6 ? `${word(saved)} of them fits with a second crew` : `${word(waiting.length)} job${waiting.length === 1 ? "" : "s"} moved to after the storm`, tx, y + 48);
        }
        ctx.globalAlpha = 1;
      }

      // The clock, and what each crew is doing on it.
      if (hours.current) hours.current.textContent = String(Math.max(0, Math.round(v.first - clock)));
      if (time.current) time.current.textContent = clockAt(d.schedule.forecast_issued_local, clock);
      v.crews.forEach((c, n) => {
        const line = hud.current?.querySelector<HTMLElement>(`[data-crew="${n}"]`);
        if (!line) return;
        const job = c.jobs.find((j) => clock >= (j.start_h ?? 0) && clock < (j.end_h ?? 0)), done = c.jobs.filter((j) => clock >= (j.end_h ?? 0));
        const people = [...new Map(done.map((j) => [j.building_id, j.people])).values()].reduce((sum, p) => sum + p, 0);
        const text = job ? `${job.building}: ${job.title}` : done.length === c.jobs.length ? "Out of safe working time" : "On the road";
        const last = line.lastElementChild as HTMLElement, mid = line.children[1] as HTMLElement;
        if (mid.textContent !== text) mid.textContent = text;
        const count = people ? `${people.toLocaleString("en-US")} people protected` : "";
        if (last.textContent !== count) last.textContent = count;
      });
    };
    draw();
    return () => cancelAnimationFrame(raf);
  }, []);

  const trades = desk?.schedule.trades ?? [];
  const sentences = desk?.run?.statement.split("\n")[0].match(/[^.]+\./g)?.slice(0, 2).join("").trim() ?? null;
  const nothingFits = later && later.schedule.trades.every((t) => t.scheduled.length === 0);
  return (
    <>
      <section ref={section} className="st-desk-section" aria-label="Five buildings and the crews there are">
        <div className="st-stage st-sticky st-desk">
          <canvas ref={canvas} className="st-desk-canvas" />
          <div data-d="title" className="st-desk-say">
            <p className="st-kicker">Houston{desk ? `. ${desk.schedule.forecast_issued_local}` : ""}</p>
            <h2>{view ? `${cap(word(view.placed.length))} buildings.` : ""}<br />{trades.map((t) => `${cap(word(t.crews))} ${t.trade}.`).join(" ")}</h2>
          </div>
          <div data-d="agent" className="st-desk-note">
            <p className="st-kicker">The storm desk</p>
            {desk?.run && view && <p>One agent read {desk.run.buildings_touched.toLocaleString("en-US")} buildings, took the {word(view.placed.length)} with a plan, and put the crews in order by people protected per crew hour. {Math.round(desk.run.seconds)} seconds.</p>}
          </div>
          <div data-d="after" className="st-desk-say">
            {view && <h2>{cap(word(view.deferred.length))} jobs run out of time.</h2>}
            {view?.worst && <p>{view.worst.building}: {view.worst.reason}</p>}
          </div>
          <div data-d="more" className="st-desk-say">
            <p className="st-kicker">The desk asks the owner</p>
            {view?.more.map((m) => <h2 key={m.trade}>A second {m.trade}: {m.people.toLocaleString("en-US")} more people.<small>{money(m.low)} to {money(m.high)}</small></h2>)}
          </div>
          <div data-d="close" className="st-desk-say">
            <p className="st-kicker">The desk, to the owner</p>
            {sentences && <h2>{sentences}</h2>}
          </div>
          <div data-d="late" className="st-desk-say">
            {later && nothingFits && <>
              <p className="st-kicker">The same desk, twelve hours out</p>
              <h2>No outside crew fits now.</h2>
              <p>{later.buildings.map((b) => `${b.name} has ${b.safe_crew_hours} hours of safe working time`).join("; ")}. The notices to residents are what is left, and they wait for the owner.</p>
            </>}
          </div>
          <div ref={hud} className="st-desk-hud">
            <div className="st-desk-crews">
              {view?.crews.map((c, n) => <p key={n} data-crew={n}><i style={{ background: COLOUR[c.trade] ?? "#f3ece0" }} /><span /><em /></p>)}
            </div>
            <div className="st-desk-clock"><strong ref={hours} /><span>hours until the wind arrives<small ref={time} /></span></div>
          </div>
          <p className="st-credit">Buildings, homes and rents: CoStar. The storm: National Hurricane Center advisories, replayed.</p>
        </div>
      </section>
      <section className="st-end"><h2>Brace</h2><a href="#/">All scenarios</a></section>
    </>
  );
}
