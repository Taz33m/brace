import { useEffect, useMemo, useRef, useState } from "react";
import * as THREE from "three";
import { api } from "../api";
import type { SiteScene } from "../types";
import { ScrollTrigger } from "./gsap";
import "./story.css";

/**
 * The loop, played by the scroll on one pinned stage. One move at three scales:
 *   outside     Los Angeles from above, falling to one community standing up from its aerial, its buildings
 *               shaded by how much fuel stands at their walls;
 *   inside      the scanned home's floor plan slides under its roof, then the view goes in: the scan turns, and
 *               each thing the agent named gets a tag and a line;
 *   multiplied  that home times the homes like it, the property's figure, and what it is for.
 * Nothing is clicked and no model runs while it plays: every figure is read from the saved schedule.
 */
const SITE = 9519837;

interface At { sweep_id: string; yaw_deg: number; pitch_deg: number; heading_deg: number | null }
interface Line { what: string; quantity: number; low: number | null; high: number | null; at: At | null }
interface Schedule {
  property: { name: string; homes: number };
  total: { low: number | null; high: number | null };
  home: { name: string; total: { low: number | null; high: number | null } };
  kinds_of_home: { name: string; homes: number; per_home: { low: number | null; high: number | null }; low: number | null; high: number | null; scanned: boolean }[];
  lost_rent_per_month: { low: number; high: number } | null;
  numbers: { rooms_read: number; views_looked_at: number; items_named: number; prices_confirmed: number };
  buildings: { id: string; exposure_rank: number; brush_within_5ft_percent: number | null; polygon: [number, number][]; units: { scan_id: string; decisions?: { left_out: number; merged: number; doubts: number };
                                                                                              rooms: { name: string; items: Line[]; left_out?: { saw: string; why: string }[] }[] }[] }[];
}
interface Descent { levels: { level: number; url: string }[] }
interface Stand { scan: string; room: string; sweep: string; heading: number; items: (Line & { at: At })[]; from: number; to: number; left: { saw: string; why: string } | null }

const short = (n: number) => (n >= 1e6 ? `$${(n / 1e6).toFixed(1)}M` : n >= 1e4 ? `$${Math.round(n / 1e3)}K` : `$${Math.round(n).toLocaleString("en-US")}`);
const range = (m: { low: number | null; high: number | null }) => (m.low == null || m.high == null ? "no price confirmed" : m.low === m.high ? short(m.low) : `${short(m.low)} to ${short(m.high)}`);
const clamp = (v: number) => Math.min(1, Math.max(0, v));
const span = (p: number, a: number, b: number) => clamp((p - a) / (b - a));
const ease = (t: number) => (t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2);
const rad = (deg: number) => (deg * Math.PI) / 180;
/** Up through a, held, and down again through b. */
const window_ = (p: number, a0: number, a1: number, b0: number, b1: number) => span(p, a0, a1) * (1 - span(p, b0, b1));

/** For checking a beat without scrolling: setting window.__loopAt to a number from 0 to 1 holds the loop there. */
const held = (): number | null => { const v = (window as unknown as { __loopAt?: number }).__loopAt; return typeof v === "number" ? v : null; };

// Where each beat sits on the scroll.
const T = { wide: [0.0, 0.13], site: [0.12, 0.34], fit: [0.34, 0.46], inside: [0.46, 0.76], tree: [0.77, 0.9], close: [0.91, 1] } as const;

/** A tag hung in the scan where the agent saw the thing: its name and what it costs. */
function tag(line: Line): THREE.Sprite {
  const c = document.createElement("canvas");
  c.width = 640; c.height = 150;
  const g = c.getContext("2d")!;
  g.fillStyle = "rgba(11, 11, 12, 0.82)";
  g.beginPath(); g.roundRect(0, 0, 640, 150, 22); g.fill();
  g.fillStyle = "#ffc20e"; g.fillRect(0, 0, 10, 150);
  g.fillStyle = "#f3ece0"; g.font = "500 44px Helvetica, Arial, sans-serif";
  g.fillText(`${line.quantity > 1 ? `${line.quantity} x ` : ""}${line.what}`.slice(0, 26), 34, 62);
  g.fillStyle = "#ff8a70"; g.font = "400 40px Helvetica, Arial, sans-serif";
  g.fillText(range(line), 34, 118);
  const tex = new THREE.CanvasTexture(c);
  tex.colorSpace = THREE.SRGBColorSpace;
  const sprite = new THREE.Sprite(new THREE.SpriteMaterial({ map: tex, transparent: true, opacity: 0, depthTest: false }));
  sprite.scale.set(3.2, 0.75, 1);
  sprite.renderOrder = 3;
  return sprite;
}

export function LoopGround() {
  const section = useRef<HTMLElement>(null), stage = useRef<HTMLDivElement>(null);
  const wide = useRef<HTMLDivElement>(null), mount = useRef<HTMLDivElement>(null), roomMount = useRef<HTMLDivElement>(null);
  const cap = useRef<(HTMLElement | null)[]>([]), list = useRef<HTMLOListElement>(null), sub = useRef<HTMLElement>(null);
  const progress = useRef(0);
  const [site, setSite] = useState<SiteScene | null>(null);
  const [sched, setSched] = useState<Schedule | null>(null);
  const [descent, setDescent] = useState<Descent | null>(null);
  const [count, setCount] = useState<{ communities_scanned: number } | null>(null);

  useEffect(() => { api.scene(SITE).then(setSite).catch(() => {}); }, []);
  useEffect(() => {
    const get = (url: string) => fetch(url).then((r) => (r.ok ? r.json() : null)).catch(() => null);
    get(`/api/schedule/${SITE}`).then((d) => d && setSched(d));
    get(`/api/buildings/${SITE}/descent`).then((d) => d && setDescent(d));
    get("/api/schedule").then((d) => d && setCount(d));
  }, []);

  useEffect(() => {
    const el = section.current, pinned = stage.current;
    if (!el || !pinned) return;
    const trigger = ScrollTrigger.create({ trigger: el, start: "top top", end: "bottom bottom", pin: pinned, pinSpacing: false, scrub: true, invalidateOnRefresh: true, onUpdate: (self) => { progress.current = self.progress; } });
    return () => trigger.kill();
  }, []);

  const decided = sched?.buildings.find((b) => b.units.length)?.units[0].decisions ?? null;
  // The two standpoints that saw the most, in the order the view visits them, each with its share of the inside beat.
  const stands = useMemo<Stand[]>(() => {
    const unit = sched?.buildings.find((b) => b.units.length)?.units[0];
    if (!unit) return [];
    const by = new Map<string, Stand>();
    for (const r of unit.rooms) for (const l of r.items) {
      if (!l.at || l.at.heading_deg == null) continue;
      // One thing the agent saw in this room and chose to leave out: its own judgement first, a thing that is another room's last.
      const out = r.left_out ?? [];
      const s = by.get(l.at.sweep_id) ?? { scan: unit.scan_id, room: r.name, sweep: l.at.sweep_id, heading: l.at.heading_deg, items: [], from: 0, to: 0,
                                           left: out.find((x) => x.why !== "belongs to another room") ?? out[0] ?? null };
      s.items.push(l as Line & { at: At });
      by.set(l.at.sweep_id, s);
    }
    const best = [...by.values()].sort((a, b) => b.items.length - a.items.length).slice(0, 2);
    const [t0, t1] = T.inside, each = (t1 - t0) / Math.max(1, best.length);
    best.forEach((s, i) => {
      s.from = t0 + i * each; s.to = s.from + each;
      // Seen in the order the head would turn: start after the widest empty stretch and go round clockwise.
      const ys = s.items.map((x) => x.at.yaw_deg).sort((a, b) => a - b);
      let start = ys[0], gap = -1;
      ys.forEach((y, k) => { const next = ys[(k + 1) % ys.length] + (k + 1 === ys.length ? 360 : 0); if (next - y > gap) { gap = next - y; start = ys[(k + 1) % ys.length]; } });
      s.items.sort((a, b) => ((a.at.yaw_deg - start + 360) % 360) - ((b.at.yaw_deg - start + 360) % 360));
    });
    return best;
  }, [sched]);

  // ---- outside: the site standing up, its buildings shaded by fuel at the walls, and the floor plan sliding under its roof ----
  useEffect(() => {
    const el = mount.current;
    if (!el || !site || !sched) return;
    const [w, s, e, n] = site.bounds;
    const width = site.cols * site.cell_m[0], depth = site.rows * site.cell_m[1];
    const xz = (lon: number, lat: number) => [(lon - w) / (e - w) * width - width / 2, (n - lat) / (n - s) * depth - depth / 2] as [number, number];
    const renderer = new THREE.WebGLRenderer({ antialias: true, powerPreference: "high-performance" });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.outputColorSpace = THREE.SRGBColorSpace;
    el.appendChild(renderer.domElement);
    const scene = new THREE.Scene();
    scene.background = new THREE.Color(0x0b0f14);
    scene.fog = new THREE.Fog(0x0b0f14, 520, 1400);
    const camera = new THREE.PerspectiveCamera(38, 1, 1, 4000);
    scene.add(new THREE.HemisphereLight(0xffffff, 0x2a2f3a, 1.25));
    const sun = new THREE.DirectionalLight(0xfff2dc, 1.5);
    sun.position.set(-260, 320, -180);
    scene.add(sun);
    const beyond = new THREE.Mesh(new THREE.PlaneGeometry(6000, 6000).rotateX(-Math.PI / 2), new THREE.MeshBasicMaterial({ color: 0x0e131a }));
    beyond.position.y = -0.4;
    scene.add(beyond);

    let terrain: THREE.Mesh | null = null;
    const grid = new Image();
    grid.onload = () => {
      const c = document.createElement("canvas");
      c.width = site.cols; c.height = site.rows;
      const ctx = c.getContext("2d", { willReadFrequently: true });
      if (!ctx) return;
      ctx.drawImage(grid, 0, 0);
      const px = ctx.getImageData(0, 0, site.cols, site.rows).data;
      const geo = new THREE.PlaneGeometry(width, depth, site.cols - 1, site.rows - 1).rotateX(-Math.PI / 2);
      const pos = geo.attributes.position;
      for (let i = 0; i < pos.count; i++) pos.setY(i, px[i * 4 + 2] === 255 ? 0 : (px[i * 4] * 256 + px[i * 4 + 1]) * site.decode.unit_m);
      geo.computeVertexNormals();
      new THREE.TextureLoader().load(site.texture_url, (tex) => {
        tex.colorSpace = THREE.SRGBColorSpace; tex.anisotropy = renderer.capabilities.getMaxAnisotropy();
        terrain = new THREE.Mesh(geo, new THREE.MeshStandardMaterial({ map: tex, roughness: 1, metalness: 0 }));
        terrain.scale.y = 0.001;
        scene.add(terrain);
      });
    };
    grid.src = site.heights_url;

    // A wash over each roof: the more of its walls have vegetation within 5 ft, the stronger.
    const roof = new Map(site.structures.map((st) => [st.id, st.roof_height_m ?? 8]));
    const caps: { mat: THREE.MeshBasicMaterial; strength: number }[] = [];
    let homeAt = new THREE.Vector3(), homeTop = 8;
    for (const b of sched.buildings) {
      const pts = b.polygon.map(([lon, lat]) => xz(lon, lat));
      const cx = pts.reduce((a, q) => a + q[0], 0) / pts.length, cz = pts.reduce((a, q) => a + q[1], 0) / pts.length;
      if (b.units.length) { homeAt = new THREE.Vector3(cx, 0, cz); homeTop = roof.get(b.id) ?? 8; }
      const mat = new THREE.MeshBasicMaterial({ color: 0xff7a3c, transparent: true, opacity: 0, depthTest: false });
      const mesh = new THREE.Mesh(new THREE.ShapeGeometry(new THREE.Shape(pts.map(([x, z]) => new THREE.Vector2(x, -z)))).rotateX(-Math.PI / 2), mat);
      mesh.position.y = (roof.get(b.id) ?? 8) + 1.5;
      mesh.renderOrder = 2;
      scene.add(mesh);
      caps.push({ mat, strength: 0.1 + 0.55 * ((b.brush_within_5ft_percent ?? 0) / 100) });
    }
    // The scanned home's floor plan: where its own GPS put it, and where it sits once fitted under the roof.
    const fit = site.fits[0];
    let outline: THREE.LineLoop | null = null, raw: Float32Array | null = null, fitted: Float32Array | null = null;
    let plan: THREE.Mesh | null = null;
    const slide = new THREE.Vector3();
    if (fit && fit.raw.length === fit.fitted.length) {
      const flat = (ring: [number, number][]) => new Float32Array(ring.flatMap(([lon, lat]) => { const [x, z] = xz(lon, lat); return [x, homeTop + 3, z]; }));
      raw = flat(fit.raw); fitted = flat(fit.fitted);
      // GPS is off by about a metre here. Drawn at ten times that, so the slide can be seen from above; it ends where the fit put it.
      const far = new Float32Array(raw.length);
      for (let i = 0; i < raw.length; i += 3) { far[i] = fitted[i] + (raw[i] - fitted[i]) * 10; far[i + 1] = raw[i + 1]; far[i + 2] = fitted[i + 2] + (raw[i + 2] - fitted[i + 2]) * 10; }
      raw = far;
      const g = new THREE.BufferGeometry();
      g.setAttribute("position", new THREE.BufferAttribute(raw.slice(), 3));
      outline = new THREE.LineLoop(g, new THREE.LineBasicMaterial({ color: 0xff7a3c, transparent: true, opacity: 0, depthTest: false }));
      outline.renderOrder = 5;
      scene.add(outline);
      // The plan itself, filled so it can be seen from the air, starting as far off as the outline does.
      const ring = fit.fitted.map(([lon, lat]) => xz(lon, lat));
      plan = new THREE.Mesh(new THREE.ShapeGeometry(new THREE.Shape(ring.map(([x, z]) => new THREE.Vector2(x, -z)))).rotateX(-Math.PI / 2),
                            new THREE.MeshBasicMaterial({ color: 0xff7a3c, transparent: true, opacity: 0, depthTest: false }));
      plan.position.y = homeTop + 2.8;
      plan.renderOrder = 4;
      scene.add(plan);
      let dx = 0, dz = 0;
      for (let i = 0; i < raw.length; i += 3) { dx += raw[i] - fitted[i]; dz += raw[i + 2] - fitted[i + 2]; }
      slide.set(dx / (raw.length / 3), 0, dz / (raw.length / 3));
    }

    const size = () => { renderer.setSize(el.clientWidth, el.clientHeight, false); camera.aspect = el.clientWidth / Math.max(1, el.clientHeight); camera.updateProjectionMatrix(); };
    size();
    const watch = new ResizeObserver(size);
    watch.observe(el);
    const above = new THREE.Vector3(0, 560, 0.01), reach = Math.max(width, depth);
    let raf = 0;
    const tick = () => {
      raf = requestAnimationFrame(tick);
      const p = held() ?? progress.current;
      const stand = ease(span(p, T.site[0], T.site[0] + 0.12)), near = ease(span(p, T.fit[0], T.fit[0] + 0.05)) * (1 - ease(span(p, T.tree[0] - 0.01, T.tree[0] + 0.05)));
      const snap = ease(span(p, T.fit[0] + 0.05, T.fit[1] - 0.03));
      el.style.opacity = String(span(p, T.wide[1] - 0.02, T.wide[1] + 0.02));
      if (terrain) terrain.scale.y = Math.max(0.001, stand);
      const turn = -0.5 + p * 1.0, r = reach * 0.92, settled = new THREE.Vector3(Math.sin(turn) * r, 235, Math.cos(turn) * r);
      const close = new THREE.Vector3(homeAt.x + Math.sin(turn) * 105, 150, homeAt.z + Math.cos(turn) * 105);
      camera.position.lerpVectors(above, settled, stand).lerp(close, near);
      camera.lookAt(new THREE.Vector3(0, 6 * stand, 0).lerp(new THREE.Vector3(homeAt.x, 6, homeAt.z), near));
      const shade = ease(span(p, T.site[0] + 0.1, T.site[0] + 0.17)) * (1 - near * 0.7);
      for (const c of caps) c.mat.opacity = shade * c.strength;
      if (outline && raw && fitted) {
        const pos = outline.geometry.attributes.position as THREE.BufferAttribute;
        for (let i = 0; i < raw.length; i++) (pos.array as Float32Array)[i] = raw[i] + (fitted[i] - raw[i]) * snap;
        pos.needsUpdate = true;
        const m = outline.material as THREE.LineBasicMaterial;
        m.opacity = window_(p, T.fit[0] + 0.02, T.fit[0] + 0.05, T.fit[1], T.fit[1] + 0.02);
        m.color.setHex(snap >= 1 ? 0xf4f1ea : 0xff7a3c);
        if (plan) {
          plan.position.x = slide.x * (1 - snap); plan.position.z = slide.z * (1 - snap);
          const pm = plan.material as THREE.MeshBasicMaterial;
          pm.opacity = m.opacity * 0.55;
          pm.color.setHex(snap >= 1 ? 0xffc20e : 0xff7a3c);
        }
      }
      renderer.render(scene, camera);
    };
    tick();
    return () => { cancelAnimationFrame(raf); watch.disconnect(); renderer.dispose(); el.removeChild(renderer.domElement); };
  }, [site, sched]);

  // ---- inside: the scan from the standpoints that saw the most, turning, with a tag on each thing as the view reaches it ----
  useEffect(() => {
    const el = roomMount.current;
    if (!el || !stands.length) return;
    const renderer = new THREE.WebGLRenderer({ antialias: true });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.outputColorSpace = THREE.SRGBColorSpace;
    el.appendChild(renderer.domElement);
    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(74, 1, 0.05, 300);
    camera.rotation.order = "YXZ";
    const loader = new THREE.TextureLoader(), FACE = 40, side = FACE * 2.002;
    const rooms = stands.map((st) => {
      const box = new THREE.Group(), mats: THREE.MeshBasicMaterial[] = [];
      const face = (f: number) => {
        const tex = loader.load(`/api/buildings/${SITE}/pano/${st.scan}/${st.sweep}/${f}.jpg?size=2048`);
        tex.colorSpace = THREE.SRGBColorSpace;
        const mat = new THREE.MeshBasicMaterial({ map: tex, depthTest: false, depthWrite: false, transparent: true, opacity: 0 });
        mats.push(mat);
        return new THREE.Mesh(new THREE.PlaneGeometry(side, side), mat);
      };
      for (let k = 0; k < 4; k++) { const pivot = new THREE.Group(), m = face(k + 1); m.position.z = -FACE; pivot.add(m); pivot.rotation.y = -rad(st.heading + 90 * k); box.add(pivot); }
      const caps = new THREE.Group(), up = face(0), down = face(5);
      up.position.y = FACE; up.rotation.x = Math.PI / 2; down.position.y = -FACE; down.rotation.x = -Math.PI / 2;
      caps.add(up, down); caps.rotation.y = -rad(st.heading); box.add(caps);
      scene.add(box);
      const tags = st.items.map((l) => {
        const t = tag(l), y = rad(l.at.yaw_deg), pt = rad(l.at.pitch_deg);
        t.position.set(Math.sin(y) * Math.cos(pt), Math.sin(pt), -Math.cos(y) * Math.cos(pt)).multiplyScalar(9);
        scene.add(t);
        return t;
      });
      // The head turns from the first thing to the last, the short way round.
      const yaws = st.items.map((l) => l.at.yaw_deg);
      for (let i = 1; i < yaws.length; i++) { while (yaws[i] - yaws[i - 1] > 180) yaws[i] -= 360; while (yaws[i] - yaws[i - 1] < -180) yaws[i] += 360; }
      return { st, mats, tags, yaws };
    });
    const size = () => { renderer.setSize(el.clientWidth, el.clientHeight, false); camera.aspect = el.clientWidth / Math.max(1, el.clientHeight); camera.updateProjectionMatrix(); };
    size();
    const watch = new ResizeObserver(size);
    watch.observe(el);
    let raf = 0, shown = -1;
    const lines = stands.flatMap((s) => s.items);
    const tick = () => {
      raf = requestAnimationFrame(tick);
      const p = held() ?? progress.current;
      const on = window_(p, T.inside[0], T.inside[0] + 0.03, T.inside[1] - 0.02, T.inside[1] + 0.01);
      el.style.opacity = String(on);
      if (on <= 0) return;
      let seen = 0;
      rooms.forEach(({ st, mats, tags, yaws }, i) => {
        // One room at a time: each fades in at its start and out at its end, the first and last holding to the edges of the beat.
        const here = (i === 0 ? 1 : span(p, st.from - 0.012, st.from + 0.012)) * (i + 1 === rooms.length ? 1 : 1 - span(p, st.to - 0.012, st.to + 0.012));
        for (const m of mats) m.opacity = here;
        if (here >= 0.5) {
          const at = span(p, st.from + 0.02, st.to - 0.03) * (yaws.length - 1), a = Math.floor(at), b = Math.min(yaws.length - 1, a + 1);
          const yaw = yaws[a] + (yaws[b] - yaws[a]) * (at - a), pitch = (st.items[a].at.pitch_deg + (st.items[b].at.pitch_deg - st.items[a].at.pitch_deg) * (at - a)) * 0.45;
          camera.rotation.set(rad(pitch), -rad(yaw), 0);
        }
        const step = (st.to - st.from - 0.05) / yaws.length;
        tags.forEach((t, j) => {
          const reached = span(p, st.from + 0.02 + j * step, st.from + 0.035 + j * step);
          (t.material as THREE.SpriteMaterial).opacity = reached * here;
          if (reached > 0.5) seen += 1;
        });
      });
      // The schedule fills beside the room, one line for each thing the view has reached.
      if (seen !== shown && list.current) {
        shown = seen;
        let nth = 0;      // a room's name comes on with its first line
        // What was left out comes on once everything in its room has been reached.
        [...list.current.children].forEach((li) => { const on = li.classList.contains("is-room") ? nth < seen : li.classList.contains("is-out") ? nth > 0 && nth <= seen : nth++ < seen; li.classList.toggle("is-on", on); });
        const got = lines.slice(0, seen).filter((l) => l.low != null);
        const hundreds = (v: number) => `$${(Math.round(v / 100) * 100).toLocaleString("en-US")}`;      // the tally in one style all the way up
        if (sub.current) sub.current.textContent = got.length ? `${hundreds(got.reduce((nn, l) => nn + (l.low ?? 0), 0))} to ${hundreds(got.reduce((nn, l) => nn + (l.high ?? 0), 0))}` : "";
      }
      renderer.render(scene, camera);
    };
    tick();
    return () => { cancelAnimationFrame(raf); watch.disconnect(); renderer.dispose(); el.removeChild(renderer.domElement); };
  }, [stands]);

  // ---- the words and the wide view, set straight on their elements as the scroll moves ----
  useEffect(() => {
    let raf = 0;
    const tick = () => {
      raf = requestAnimationFrame(tick);
      const p = held() ?? progress.current;
      // Three aerials on one centre, each a quarter of the last: falling is scaling them up.
      const z = span(p, 0.015, T.wide[1]) * 2;
      wide.current?.querySelectorAll<HTMLImageElement>("img").forEach((img, i) => {
        const k = Math.pow(4, z - i);
        img.style.transform = `scale(${k})`;
        img.style.opacity = String(k < 0.2 ? 0 : 1);
      });
      if (wide.current) wide.current.style.opacity = String(span(p, 0, 0.02) * (1 - span(p, T.wide[1] - 0.005, T.wide[1] + 0.025)));
      const shows = [
        window_(p, 0.02, 0.04, T.wide[1] - 0.03, T.wide[1]),
        window_(p, T.site[0] + 0.08, T.site[0] + 0.11, T.site[1] - 0.02, T.site[1]),
        window_(p, T.fit[0] + 0.03, T.fit[0] + 0.05, T.fit[1] - 0.02, T.fit[1]),
        window_(p, T.inside[0] + 0.02, T.inside[0] + 0.04, T.inside[1] - 0.03, T.inside[1]),
        window_(p, T.tree[0], T.tree[0] + 0.03, T.tree[1], T.tree[1] + 0.02),
        span(p, T.close[0], T.close[0] + 0.03),
      ];
      shows.forEach((o, i) => { const node = cap.current[i]; if (node) { node.style.opacity = String(o); node.style.visibility = o > 0.01 ? "visible" : "hidden"; } });
    };
    tick();
    return () => cancelAnimationFrame(raf);
  }, []);

  const ranked = sched?.buildings.length ?? 0, first = sched?.buildings[0];
  const levels = (descent?.levels ?? []).filter((l) => l.level >= 1).slice(0, 3);
  return (
    <section ref={section} className="lp-section" aria-label="What a fire would cost to put back">
      <div ref={stage} className="lp-stage">
        <div ref={wide} className="lp-wide">{levels.map((l) => <img key={l.level} src={l.url} alt="" draggable={false} />)}</div>
        <div ref={mount} className="lp-scene" />
        <div ref={roomMount} className="lp-room" />

        <div ref={(n) => { cap.current[0] = n; }} className="lp-cap lp-cap-mid">
          <h2>Los Angeles</h2>
          {count && <p>{count.communities_scanned.toLocaleString("en-US")} apartment communities, each one scanned inside.</p>}
        </div>
        <div ref={(n) => { cap.current[1] = n; }} className="lp-cap">
          <h2>{sched?.property.name}</h2>
          <p>{ranked} buildings, shaded by the fuel at their walls.{first?.brush_within_5ft_percent != null ? ` Building ${first.id}: ${Math.round(first.brush_within_5ft_percent)}% of its walls.` : ""}</p>
          <small>Vexcel</small>
        </div>
        <div ref={(n) => { cap.current[2] = n; }} className="lp-cap">
          <h2>One home, scanned for leasing</h2>
          <p>Its floor plan, placed under the roof it belongs to.</p>
          <small>Matterport</small>
        </div>
        <div ref={(n) => { cap.current[3] = n; }} className="lp-lines">
          <span>{sched?.home.name}</span>
          <strong ref={sub} />
          <ol ref={list}>
            {stands.flatMap((s) => [<li key={s.sweep} className="is-room">{s.room}</li>,
              ...s.items.map((l, i) => <li key={`${s.sweep}:${i}`}><b>{l.quantity > 1 ? `${l.quantity} x ` : ""}{l.what}</b><i>{range(l)}</i></li>),
              ...(s.left ? [<li key={`${s.sweep}:out`} className="is-out"><b>{s.left.saw.replace(/\s*\(.*\)$/, "")}</b><i>left out: {s.left.why.replace("furniture or a tenant's own", "not the owner's")}</i></li>] : [])])}
          </ol>
          <small>{decided ? `The agent named these from the scan. It left ${decided.left_out} things out and is unsure of ${decided.doubts} counts. Each price is from a page it opened.` : "Named by an agent looking at the scan. Priced from a page it opened."}</small>
        </div>
        {sched && (
          <div ref={(n) => { cap.current[4] = n; }} className="lp-tree">
            <span>If fire reaches it</span>
            <strong>{range(sched.total)}</strong>
            <table><tbody>
              {sched.kinds_of_home.map((k) => <tr key={k.name}><th>{k.homes} x {k.name}</th><td>{range(k.per_home)} each</td><td>{k.scanned ? "the scanned home" : "scaled from it"}</td><td>{range(k)}</td></tr>)}
              {sched.lost_rent_per_month && <tr><th>Rent, each month empty</th><td /><td>asking rents</td><td>{range(sched.lost_rent_per_month)}</td></tr>}
            </tbody></table>
            <small>{sched.numbers.rooms_read} rooms, {sched.numbers.views_looked_at} views, {sched.numbers.items_named} items named, {sched.numbers.prices_confirmed} prices confirmed. One scanned home, multiplied: an extrapolation.</small>
          </div>
        )}
        <div ref={(n) => { cap.current[5] = n; }} className="lp-close">
          <ul><li>At renewal</li><li>Before a fire</li><li>After a loss</li></ul>
          <p>From the scan you already have.</p>
        </div>
      </div>
    </section>
  );
}
