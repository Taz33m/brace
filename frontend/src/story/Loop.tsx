import { useEffect, useMemo, useRef, useState } from "react";
import * as THREE from "three";
import { api } from "../api";
import type { SiteScene } from "../types";
import { ScrollTrigger, smooth } from "./gsap";
import "./story.css";

/**
 * The loop, played by the scroll on one pinned stage. One move at three scales:
 *   outside     Los Angeles from above, falling to one community standing up from its aerial, its buildings
 *               shaded by how much fuel stands at their walls;
 *   inside      the scanned home's floor plan slides under its roof, then the view goes in: the scan turns, and
 *               each thing the agent named gets a tag and a line;
 *   multiplied  that home times the homes like it, the property's figure, and what it is for.
 * The scroll stops once, over the site: a home is chosen there, and the choice carries the view inside it.
 * No model runs while it plays: every figure is read from the saved schedule.
 */
const SITE = 9519837;

interface At { sweep_id: string; yaw_deg: number; pitch_deg: number; heading_deg: number | null }
interface Line { what: string; quantity: number; low: number | null; high: number | null; at: At | null }
/** A total: its two ends, and the middle with the likely band about it that the screen leads with. */
interface Sum { low: number | null; high: number | null; middle?: number | null; likely_low?: number | null; likely_high?: number | null }
interface Schedule {
  property: { name: string; homes: number };
  total: Sum;
  home: { name: string; total: Sum };
  kinds_of_home: ({ name: string; homes: number; per_home: Sum; scanned: boolean } & Sum)[];
  lost_rent_per_month: { low: number; high: number } | null;
  numbers: { rooms_read: number; views_looked_at: number; items_named: number; prices_confirmed: number };
  buildings: { id: string; exposure_rank: number; brush_within_5ft_percent: number | null; polygon: [number, number][]; units: { scan_id: string; decisions?: { left_out: number; merged: number; doubts: number };
                                                                                              rooms: { name: string; items: Line[]; left_out?: { saw: string; why: string }[] }[] }[] }[];
}
interface Descent { levels: { level: number; url: string; bounds: [number, number, number, number] }[] }
interface Stand { scan: string; room: string; sweep: string; heading: number; items: (Line & { at: At })[]; from: number; to: number; left: { saw: string; why: string } | null }

const short = (n: number) => (n >= 1e6 ? `$${(n / 1e6).toFixed(1)}M` : n >= 1e4 ? `$${Math.round(n / 1e3)}K` : `$${Math.round(n).toLocaleString("en-US")}`);
const range = (m: { low: number | null; high: number | null }) => (m.low == null || m.high == null ? "no price confirmed" : m.low === m.high ? short(m.low) : `${short(m.low)} to ${short(m.high)}`);
const figure = (m: Sum) => (m.middle != null ? short(m.middle) : range(m));
const likely = (m: Sum) => (m.likely_low != null && m.likely_high != null && m.likely_low !== m.likely_high ? `${short(m.likely_low)} to ${short(m.likely_high)}` : null);
const clamp = (v: number) => Math.min(1, Math.max(0, v));
const span = (p: number, a: number, b: number) => clamp((p - a) / (b - a));
const ease = (t: number) => (t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2);
const rad = (deg: number) => (deg * Math.PI) / 180;
/** Up through a, held, and down again through b. */
const window_ = (p: number, a0: number, a1: number, b0: number, b1: number) => span(p, a0, a1) * (1 - span(p, b0, b1));

/** For checking a beat without scrolling: setting window.__loopAt to a number from 0 to 1 holds the loop there. */
const held = (): number | null => { const v = (window as unknown as { __loopAt?: number }).__loopAt; return typeof v === "number" ? v : null; };

// Where each beat sits on the scroll.
const T = { wide: [0.0, 0.07], site: [0.07, 0.27], fit: [0.27, 0.39], inside: [0.39, 0.76], tree: [0.77, 0.9], close: [0.91, 1] } as const;
/** The scroll goes no further than this until a home has been chosen. */
const GATE = 0.25;
/** How far the wide aerials have been scaled up when the standing site takes over: the last one fills a little over half the view. */
const Z_END = 1.6;
/** The site seen at an angle, a little turned: the pose it settles in. Distance in metres, tilt from straight down, turn from north-up. */
const SETTLED = { r: 300, tilt: 38, turn: -0.38 }, CLOSE = { r: 183, tilt: 35, turn: -0.62 };

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

const FIRE_VIEWS: Record<string, string> = {
  x9aueidhw980n197tiue89t3c: "/aftermath/verdugo/fire.png",
  naaiahpb2a7bgebbitnx189gc: "/aftermath/verdugo/bathroom-fire.png",
};

export function LoopGround({ replay = 0, onAftermath }: { replay?: number; onAftermath?: () => void }) {
  const aftermath = replay > 0;
  const afterRef = useRef(aftermath); afterRef.current = aftermath;
  const wildfireLabel = useRef<HTMLDivElement>(null);
  const firePick = useRef<HTMLButtonElement>(null);
  const lastReplay = useRef(0);
  const fireLabel = useRef<HTMLDivElement>(null);
  const section = useRef<HTMLElement>(null), stage = useRef<HTMLDivElement>(null);
  const wide = useRef<HTMLDivElement>(null), mount = useRef<HTMLDivElement>(null), roomMount = useRef<HTMLDivElement>(null);
  const cap = useRef<(HTMLElement | null)[]>([]), list = useRef<HTMLOListElement>(null), sub = useRef<HTMLElement>(null);
  const progress = useRef(0);
  const trig = useRef<ScrollTrigger | null>(null), picked = useRef(false), picks = useRef<HTMLDivElement>(null);
  const pickAt = useRef(new Map<string, THREE.Vector3>());
  const [chosen, setChosen] = useState<string | null>(null);       // a building picked that has no scan under its roof
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
    const trigger = ScrollTrigger.create({ trigger: el, start: "top top", end: "bottom bottom", pin: pinned, pinSpacing: false, scrub: true, invalidateOnRefresh: true, onUpdate: (self) => {
      // Until a home is chosen the page is held at the site: scrolling further is put back.
      if (!picked.current && self.progress > GATE + 0.0001) {
        progress.current = GATE;
        const y = self.start + GATE * (self.end - self.start);
        if (smooth.lenis) smooth.lenis.scrollTo(y, { immediate: true, force: true }); else if (window.scrollY > y + 1) window.scrollTo({ top: y, behavior: "instant" as ScrollBehavior });
        return;
      }
      // Hold the community-wide fire scene until the owner chooses the same home again.
      if (!afterRef.current && self.progress > 0.8901) {
        progress.current = 0.89;
        const y = self.start + 0.89 * (self.end - self.start);
        if (smooth.lenis) smooth.lenis.scrollTo(y, { immediate: true, force: true });
        else window.scrollTo({ top: y, behavior: "instant" as ScrollBehavior });
        return;
      }
      progress.current = self.progress;
    } });
    trig.current = trigger;
    return () => { trig.current = null; trigger.kill(); };
  }, []);

  /** A home is chosen: the hold is let go and the page carries itself down to the inside of the scan. */
  const enter = () => {
    picked.current = true;
    setChosen(null);
    const t = trig.current;
    if (!t) return;
    const y = t.start + (T.inside[0] + 0.04) * (t.end - t.start), inOut = (k: number) => (k < 0.5 ? 2 * k * k : 1 - Math.pow(-2 * k + 2, 2) / 2);
    if (smooth.lenis) { smooth.lenis.scrollTo(y, { duration: 5, easing: inOut, force: true }); return; }
    const from = window.scrollY, began = performance.now();
    let stopped = false;
    const stop = () => { stopped = true; };
    window.addEventListener("wheel", stop, { once: true, passive: true });
    window.addEventListener("touchstart", stop, { once: true, passive: true });
    const step = (now: number) => {
      if (stopped) return;
      const k = Math.min(1, (now - began) / 5000);
      window.scrollTo({ top: from + (y - from) * inOut(k), behavior: "instant" as ScrollBehavior });
      if (k < 1) requestAnimationFrame(step);
    };
    requestAnimationFrame(step);
  };

  useEffect(() => {
    if (!replay || replay === lastReplay.current || !site || !sched || !trig.current) return;
    lastReplay.current = replay;
    picked.current = true;
    setChosen(null);
    const t = trig.current;
    const start = t.start + GATE * (t.end - t.start);
    progress.current = GATE;
    if (smooth.lenis) smooth.lenis.scrollTo(start, { immediate: true, force: true });
    else window.scrollTo({ top: start, behavior: "instant" as ScrollBehavior });
    // Let the same roof/floor-plan scene render before entering along the existing path.
    const frame = requestAnimationFrame(() => enter());
    return () => cancelAnimationFrame(frame);
  }, [replay, site, sched]);

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
    // The last two wide aerials lie on the ground under the site, exactly where they are on the map. Seen from straight
    // above at the right height this is the same picture the flat aerials end on, so the change from flat to standing has no seam.
    let across: number | null = null;      // metres the flat view shows across its square when it hands over
    (descent?.levels ?? []).filter((l) => l.level === 2 || l.level === 3).forEach((l) => {
      const [lw, ls, le, ln] = l.bounds, [x0, z0] = xz(lw, ln), [x1, z1] = xz(le, ls);
      if (l.level === 3) across = Math.min(x1 - x0, z1 - z0) / Math.pow(4, Z_END - 2);
      new THREE.TextureLoader().load(l.url, (tex) => {
        tex.colorSpace = THREE.SRGBColorSpace; tex.anisotropy = renderer.capabilities.getMaxAnisotropy();
        const ground = new THREE.Mesh(new THREE.PlaneGeometry(x1 - x0, z1 - z0).rotateX(-Math.PI / 2), new THREE.MeshStandardMaterial({ map: tex, roughness: 1, metalness: 0 }));
        ground.position.set((x0 + x1) / 2, l.level === 3 ? -0.15 : -0.3, (z0 + z1) / 2);
        scene.add(ground);
      });
    });

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
      pickAt.current.set(b.id, new THREE.Vector3(cx, (roof.get(b.id) ?? 8) + 3, cz));
      const mat = new THREE.MeshBasicMaterial({ color: 0xff7a3c, transparent: true, opacity: 0, depthTest: false });
      const mesh = new THREE.Mesh(new THREE.ShapeGeometry(new THREE.Shape(pts.map(([x, z]) => new THREE.Vector2(x, -z)))).rotateX(-Math.PI / 2), mat);
      mesh.position.y = (roof.get(b.id) ?? 8) + 1.5;
      mesh.renderOrder = 2;
      scene.add(mesh);
      caps.push({ mat, strength: 0.1 + 0.55 * ((b.brush_within_5ft_percent ?? 0) / 100) });
    }
    // Illustrative fire and smoke at actual building footprints; not a fire-spread model.
    const makeParticle = (smoke: boolean) => {
      const canvas = document.createElement("canvas"); canvas.width = 128; canvas.height = 256;
      const c = canvas.getContext("2d")!;
      const glow = c.createRadialGradient(64, smoke ? 128 : 193, 2, 64, 140, smoke ? 90 : 105);
      if (smoke) { glow.addColorStop(0, "rgba(55,45,40,.65)"); glow.addColorStop(.5, "rgba(80,65,55,.35)"); glow.addColorStop(1, "rgba(55,45,40,0)"); }
      else { glow.addColorStop(0, "rgba(255,245,170,1)"); glow.addColorStop(.23, "rgba(255,185,35,.95)"); glow.addColorStop(.55, "rgba(238,65,10,.75)"); glow.addColorStop(1, "rgba(160,25,5,0)"); }
      c.fillStyle = glow; c.fillRect(0, 0, 128, 256);
      const texture = new THREE.CanvasTexture(canvas); texture.colorSpace = THREE.SRGBColorSpace;
      return texture;
    };
    const flameMap = makeParticle(false), smokeMap = makeParticle(true);
    const fireParticles: { sprite: THREE.Sprite; base: THREE.Vector3; phase: number; smoke: boolean; building: number }[] = [];
    sched.buildings.forEach((b, index) => {
      const center = pickAt.current.get(b.id)!;
      for (let j = 0; j < 5; j++) {
        const smoke = j > 2;
        const material = new THREE.SpriteMaterial({ map: smoke ? smokeMap : flameMap, transparent: true, opacity: 0, depthWrite: false, depthTest: false, blending: smoke ? THREE.NormalBlending : THREE.AdditiveBlending });
        const sprite = new THREE.Sprite(material); sprite.renderOrder = smoke ? 4 : 3;
        const base = center.clone().add(new THREE.Vector3((j % 3 - 1) * 5, smoke ? 12 : 3, ((index + j) % 3 - 1) * 4));
        sprite.position.copy(base); scene.add(sprite);
        fireParticles.push({ sprite, base, phase: index * 1.71 + j * 2.3, smoke, building: index });
      }
    });
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
    const fog = scene.fog as THREE.Fog, lerp = (a: number, b: number, k: number) => a + (b - a) * k, look = new THREE.Vector3(), spot = new THREE.Vector3();
    let raf = 0;
    const tick = () => {
      raf = requestAnimationFrame(tick);
      const p = held() ?? progress.current;
      // The flat aerials hand over to this scene while both show the same picture; only then does the view tilt and the ground stand up.
      const stand = ease(span(p, T.wide[1] + 0.008, T.site[0] + 0.1)), near = ease(span(p, T.fit[0], T.fit[0] + 0.05)) * (1 - ease(span(p, T.tree[0] - 0.01, T.tree[0] + 0.05)));
      const snap = ease(span(p, T.fit[0] + 0.05, T.fit[1] - 0.03));
      el.style.opacity = String(span(p, T.wide[1], T.wide[1] + 0.006));
      if (terrain) terrain.scale.y = Math.max(0.001, stand);
      // Straight above, at the height from which this camera sees what the flat view showed. Then one move about the site's
      // centre: closer, tilted, a little turned. The view never slides sideways.
      const high = across != null ? (el.clientHeight / Math.max(el.clientWidth, el.clientHeight)) * across / (2 * Math.tan(rad(camera.fov / 2))) : 520;
      const r = lerp(high * Math.pow(SETTLED.r / high, stand), CLOSE.r, near), tilt = rad(lerp(Math.max(0.03, SETTLED.tilt * stand), CLOSE.tilt, near)), turn = lerp(SETTLED.turn * stand, CLOSE.turn, near);
      look.set(homeAt.x * near, 6 * stand, homeAt.z * near);
      camera.position.set(look.x + r * Math.sin(tilt) * Math.sin(turn), look.y + r * Math.cos(tilt), look.z + r * Math.sin(tilt) * Math.cos(turn));
      camera.lookAt(look);
      fog.near = lerp(2400, 520, stand); fog.far = lerp(5200, 1400, stand);
      // The homes that can be chosen: a ring over each, kept on its roof as the view moves.
      const offer = ease(span(p, T.site[0] + 0.105, T.site[0] + 0.13)) * (1 - span(p, GATE + 0.004, GATE + 0.02));
      if (picks.current) {
        picks.current.style.opacity = String(offer);
        picks.current.style.visibility = offer > 0.02 ? "visible" : "hidden";
        picks.current.querySelectorAll<HTMLElement>("[data-id]").forEach((node) => {
          const at = pickAt.current.get(node.dataset.id ?? "");
          if (!at) return;
          spot.copy(at).project(camera);
          node.style.transform = `translate(${((spot.x + 1) / 2) * el.clientWidth}px, ${((1 - spot.y) / 2) * el.clientHeight}px)`;
        });
      }
      const burn = afterRef.current ? 1 : span(p, 0.79, 0.875);
      const seconds = performance.now() / 1000;
      fireParticles.forEach(({ sprite, base, phase, smoke, building }) => {
        const arrive = span(burn, (building / Math.max(1, sched.buildings.length)) * 0.55, 0.55 + (building / Math.max(1, sched.buildings.length)) * 0.45);
        const flicker = 0.78 + 0.22 * Math.sin(seconds * (smoke ? 0.7 : 7) + phase);
        sprite.material.opacity = arrive * (smoke ? 0.55 : 0.85) * flicker;
        sprite.visible = arrive > 0;
        const rise = smoke ? ((seconds * 0.2 + phase) % 1) : 0;
        sprite.position.copy(base).add(new THREE.Vector3(smoke ? rise * 8 : Math.sin(seconds * 3 + phase), rise * 22, 0));
        const scale = smoke ? 24 + rise * 20 : 12 + flicker * 5;
        sprite.scale.set(scale, smoke ? scale * 1.1 : scale * 1.7, 1);
      });
      if (firePick.current) {
        const active = !afterRef.current && p >= 0.835;
        firePick.current.style.visibility = active ? "visible" : "hidden";
        spot.copy(homeAt).setY(homeTop + 6).project(camera);
        firePick.current.style.transform = `translate(${((spot.x + 1) / 2) * el.clientWidth}px, ${((1 - spot.y) / 2) * el.clientHeight}px)`;
      }
      const shade = ease(span(p, T.site[0] + 0.08, T.site[0] + 0.12)) * (1 - near * 0.7);
      for (const c of caps) { c.mat.opacity = Math.max(shade * c.strength, burn * 0.45); c.mat.color.setHex(burn > 0.1 ? 0xe54816 : 0xff7a3c); }
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
    return () => { cancelAnimationFrame(raf); watch.disconnect(); fireParticles.forEach(p => p.sprite.material.dispose()); flameMap.dispose(); smokeMap.dispose(); renderer.dispose(); el.removeChild(renderer.domElement); };
  }, [site, sched, descent]);

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
      const box = new THREE.Group(), mats: THREE.MeshBasicMaterial[] = [], fireMats: THREE.MeshBasicMaterial[] = [];
      const face = (f: number) => {
        const tex = loader.load(`/api/buildings/${SITE}/pano/${st.scan}/${st.sweep}/${f}.jpg?size=2048`);
        tex.colorSpace = THREE.SRGBColorSpace;
        const mat = new THREE.MeshBasicMaterial({ map: tex, depthTest: false, depthWrite: false, transparent: true, opacity: 0 });
        mats.push(mat);
        return new THREE.Mesh(new THREE.PlaneGeometry(side, side), mat);
      };
      if (FIRE_VIEWS[st.sweep]) {
        const texture = loader.load(FIRE_VIEWS[st.sweep]);
        texture.colorSpace = THREE.SRGBColorSpace;
        const mat = new THREE.MeshBasicMaterial({ map: texture, depthTest: false, depthWrite: false, transparent: true, opacity: 0 });
        fireMats.push(mat);
        const geometry = new THREE.SphereGeometry(FACE, 64, 40);
        geometry.scale(-1, 1, 1);
        const sphere = new THREE.Mesh(geometry, mat);
        sphere.renderOrder = 1;      // drawn over the scanned room, so the room can be seen turning into the scenario
        // Match the equirectangular reference to the original cube's compass heading.
        sphere.rotation.y = -Math.PI / 2 - rad(st.heading);
        box.add(sphere);
      }
      {
        for (let k = 0; k < 4; k++) { const pivot = new THREE.Group(), m = face(k + 1); m.position.z = -FACE; pivot.add(m); pivot.rotation.y = -rad(st.heading + 90 * k); box.add(pivot); }
        const caps = new THREE.Group(), up = face(0), down = face(5);
        up.position.y = FACE; up.rotation.x = Math.PI / 2; down.position.y = -FACE; down.rotation.x = -Math.PI / 2;
        caps.add(up, down); caps.rotation.y = -rad(st.heading); box.add(caps);
      }
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
      return { st, mats, fireMats, tags, yaws };
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
      rooms.forEach(({ st, mats, fireMats, tags, yaws }, i) => {
        // One room at a time: each fades in at its start and out at its end, the first and last holding to the edges of the beat.
        const here = (i === 0 ? 1 : span(p, st.from - 0.012, st.from + 0.012)) * (i + 1 === rooms.length ? 1 : 1 - span(p, st.to - 0.012, st.to + 0.012));
        // Returning from the wildfire starts in the aftermath immediately. Never
        // flash the original room underneath a loading or fading fire texture.
        for (const m of mats) m.opacity = afterRef.current ? 0 : here;
        for (const m of fireMats) m.opacity = afterRef.current ? here : 0;
        if (here >= 0.5) {
          const at = span(p, st.from + 0.02, st.to - 0.03) * (yaws.length - 1), a = Math.floor(at), b = Math.min(yaws.length - 1, a + 1);
          const yaw = yaws[a] + (yaws[b] - yaws[a]) * (at - a), pitch = (st.items[a].at.pitch_deg + (st.items[b].at.pitch_deg - st.items[a].at.pitch_deg) * (at - a)) * 0.45;
          camera.rotation.set(rad(pitch), -rad(yaw), 0);
        }
        const step = (st.to - st.from - 0.05) / yaws.length;
        tags.forEach((t, j) => {
          const reached = span(p, st.from + 0.02 + j * step, st.from + 0.035 + j * step);
          (t.material as THREE.SpriteMaterial).opacity = afterRef.current ? 0 : reached * here;
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
    return () => {
      cancelAnimationFrame(raf); watch.disconnect();
      scene.traverse(object => {
        if (object instanceof THREE.Mesh || object instanceof THREE.Sprite) {
          if (object instanceof THREE.Mesh) object.geometry.dispose();
          const materials = Array.isArray(object.material) ? object.material : [object.material];
          materials.forEach(material => { material.map?.dispose(); material.dispose(); });
        }
      });
      renderer.dispose(); el.removeChild(renderer.domElement);
    };
  }, [stands]);

  // ---- the words and the wide view, set straight on their elements as the scroll moves ----
  useEffect(() => {
    let raf = 0;
    const tick = () => {
      raf = requestAnimationFrame(tick);
      const p = held() ?? progress.current;
      // Three aerials on one centre, each a quarter of the last: falling is scaling them up.
      const z = span(p, 0.004, T.wide[1]) * Z_END;
      wide.current?.querySelectorAll<HTMLImageElement>("img").forEach((img, i) => {
        const k = Math.pow(4, z - i);
        img.style.transform = `scale(${k})`;
        img.style.opacity = String(k < 0.2 ? 0 : 1);
      });
      if (wide.current) wide.current.style.opacity = String(span(p, 0, 0.008) * (1 - span(p, T.wide[1] + 0.006, T.wide[1] + 0.012)));
      // The stage enters while the clouds are still whitening. Keep its dark
      // caption shade out of that handoff; blend it in only over the aerial.
      stage.current?.style.setProperty("--scene-shade", String(ease(span(p, 0.008, 0.025))));
      const shows = [
        window_(p, 0.008, 0.02, T.wide[1] - 0.012, T.wide[1]),
        window_(p, T.site[0] + 0.1, T.site[0] + 0.125, GATE + 0.004, GATE + 0.02),
        window_(p, T.fit[0] + 0.03, T.fit[0] + 0.05, T.fit[1] - 0.02, T.fit[1]),
        window_(p, T.inside[0] + 0.02, T.inside[0] + 0.04, T.inside[1] - 0.03, T.inside[1]),
        window_(p, T.tree[0], T.tree[0] + 0.03, T.tree[1], T.tree[1] + 0.02),
        span(p, T.close[0], T.close[0] + 0.03),
      ];
      if (aftermath) shows[3] = 0;
      else { shows[4] = 0; shows[5] = 0; }
      if (wildfireLabel.current) {
        const o = aftermath ? 0 : span(p, 0.80, 0.835);
        wildfireLabel.current.style.opacity = String(o);
        wildfireLabel.current.style.visibility = o > 0.01 ? "visible" : "hidden";
      }
      if (fireLabel.current) {
        const opacity = window_(p, T.inside[0], T.inside[0] + 0.03, T.inside[1] - 0.02, T.inside[1]);
        fireLabel.current.style.opacity = String(opacity);
        fireLabel.current.style.visibility = opacity > 0.01 ? "visible" : "hidden";
      }
      shows.forEach((o, i) => { const node = cap.current[i]; if (node) { node.style.opacity = String(o); node.style.visibility = o > 0.01 ? "visible" : "hidden"; } });
    };
    tick();
    return () => cancelAnimationFrame(raf);
  }, [aftermath]);

  // Four homes are offered: the one that has been scanned, and the three buildings with the most fuel at their walls.
  const offered = sched ? [...sched.buildings.filter((b) => b.units.length).slice(0, 1), ...sched.buildings.filter((b) => !b.units.length).slice(0, 3)] : [];
  const other = offered.find((b) => b.id === chosen && !b.units.length) ?? null;
  const levels = (descent?.levels ?? []).filter((l) => l.level >= 1).slice(0, 3);
  return (
    <section ref={section} className="lp-section" aria-label="What a fire would cost to put back">
      <div ref={stage} className="lp-stage">
        <div ref={wide} className="lp-wide">{levels.map((l) => <img key={l.level} src={l.url} alt="" draggable={false} />)}</div>
        <div ref={mount} className="lp-scene" />
        <div ref={roomMount} className="lp-room" />
        <div ref={wildfireLabel} className="lp-wildfire-label"><h2>A wildfire reaches the community.</h2><p>Hypothetical scenario · All buildings assumed affected</p></div>
        <button ref={firePick} type="button" className="lp-pick is-scanned lp-fire-pick" onClick={onAftermath} aria-label="Return to this home after the wildfire"><i /><span>Return to this home</span></button>

        <div ref={(n) => { cap.current[0] = n; }} className="lp-cap lp-cap-mid">
          <h2>Los Angeles</h2>
          {count && <p>{count.communities_scanned.toLocaleString("en-US")} apartment communities, each one scanned inside.</p>}
        </div>
        <div ref={picks} className="lp-picks">
          {offered.map((b) => (
            <button key={b.id} type="button" data-id={b.id} className={`lp-pick${b.units.length ? " is-scanned" : ""}${b.id === chosen ? " is-on" : ""}`}
                    onClick={() => { if (b.units.length) enter(); else setChosen(b.id); }}>
              <i /><span>{b.units.length ? "Open this home" : `Building ${b.id}`}</span>
            </button>
          ))}
        </div>
        <div ref={(n) => { cap.current[1] = n; }} className="lp-cap">
          <h2>{sched?.property.name}</h2>
          <p>Its owner insures what is inside these homes without a list of it.</p>
          <p>Choose a home. Brace looks inside and reads what is there.</p>
          <small>Roofs shaded by the fuel at their walls · Vexcel</small>
          {other && (
            <div className="lp-chosen">
              <b>Building {other.id}</b>
              <span>{other.brush_within_5ft_percent != null ? `${Math.round(other.brush_within_5ft_percent)}% of its walls have fuel within 5 ft. ` : ""}No home under this roof has been scanned, so its figure is worked out from the one that has.</span>
              <button type="button" onClick={enter}>Open this home</button>
            </div>
          )}
        </div>
        <div ref={(n) => { cap.current[2] = n; }} className="lp-cap">
          <h2>{aftermath ? "The same home. After the fire." : "Inside the home"}</h2>
          <p>Its floor plan, placed under the roof it belongs to.</p>
          <small>Matterport</small>
        </div>
        {aftermath && <div ref={fireLabel} className="lp-fire-label"><h2>After the fire</h2><p>AI-generated scenario · Not observed damage</p></div>}
        <div ref={(n) => { cap.current[3] = n; }} className="lp-lines">
          <span>{sched?.home.name}</span>
          <strong ref={sub} />
          <ol ref={list}>
            {stands.flatMap((s) => [<li key={s.sweep} className="is-room">{s.room}</li>,
              ...s.items.map((l, i) => <li key={`${s.sweep}:${i}`}><b>{l.quantity > 1 ? `${l.quantity} x ` : ""}{l.what}</b><i>{range(l)}</i></li>),
              ...(s.left ? [<li key={`${s.sweep}:out`} className="is-out"><b>{s.left.saw.replace(/\s*\(.*\)$/, "")}</b><i>left out: {s.left.why.replace("furniture or a tenant's own", "not the owner's").replace("already recorded from another standpoint", "already counted")}</i></li>] : [])])}
          </ol>
          <small>{decided ? `The agent named these from the scan. It left ${decided.left_out} things out and is unsure of ${decided.doubts} counts. Each price is from a page it opened.` : "Named by an agent looking at the scan. Priced from a page it opened."}</small>
        </div>
        {sched && (
          <div ref={(n) => { cap.current[4] = n; }} className="lp-tree">
            <span>If fire reaches it</span>
            <strong>{figure(sched.total)}</strong>
            {likely(sched.total) && <em>likely {likely(sched.total)}</em>}
            <table><tbody>
              {sched.kinds_of_home.map((k) => <tr key={k.name}><th>{k.homes} x {k.name}</th><td>{figure(k.per_home)} each</td><td>{k.scanned ? "this home" : "scaled from it"}</td><td>{figure(k)}</td></tr>)}
              {sched.lost_rent_per_month && <tr><th>Rent, each month empty</th><td /><td>asking rents</td><td>{range(sched.lost_rent_per_month)}</td></tr>}
            </tbody></table>
            <small>{sched.numbers.rooms_read} rooms, {sched.numbers.views_looked_at} views, {sched.numbers.items_named} items named, {sched.numbers.prices_confirmed} prices confirmed. One home, multiplied: an extrapolation.</small>
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
