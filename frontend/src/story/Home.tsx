import { useCallback, useEffect, useRef, useState } from "react";
import * as THREE from "three";
import { api } from "../api";
import type { SiteScene } from "../types";
import { CabinWindow } from "./Cabin";
import { gsap, ScrollTrigger } from "./gsap";
import "./story.css";

/**
 * The way in. A window and a sky, no words. Scrolling flies through the window, the cloud rises and clears, and
 * the first thing on the ground is the flood: one real Houston site standing up from its aerial, the water, what
 * it costs, and what the plan buys. Nothing is clicked.
 */
const SITE = 4303509, HOME = "S19";      // The Parker at Ellington, and the roof the scanned home is under
const WATER_FT = 4, BUDGET = 500_000, HOURS = 48;

/** The fly-through from the plane project, with nothing written on it. */
export function QuietHero() {
  const section = useRef<HTMLElement>(null), stage = useRef<HTMLDivElement>(null), zoom = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const el = section.current, pinned = stage.current;
    if (!el || !pinned) return;
    const skyZoom = document.querySelector<HTMLElement>('[data-sky="zoom"]'), sweep = document.querySelector<HTMLElement>('[data-sky="sweep"]');
    const mm = gsap.matchMedia();
    mm.add({ motion: "(prefers-reduced-motion: no-preference)", reduce: "(prefers-reduced-motion: reduce)" }, (context) => {
      const { motion } = context.conditions as { motion: boolean };
      const timeline = gsap.timeline({
        defaults: { ease: "none" },
        scrollTrigger: { trigger: el, start: "top top", end: () => `+=${Math.round(window.innerHeight * 2)}`, scrub: 1, pin: pinned, anticipatePin: 1, invalidateOnRefresh: true, refreshPriority: 10 },
      });
      if (motion) {
        timeline
          .to(zoom.current, { scale: 5.4, ease: "power2.in", duration: 6.2 }, 0)
          .to(zoom.current, { autoAlpha: 0, duration: 0.6 }, 5.8)
          .to(skyZoom, { scale: 1.15, duration: 7 }, 0)
          .fromTo(sweep, { xPercent: 30, autoAlpha: 0 }, { xPercent: -10, autoAlpha: 0.95, ease: "power1.in", duration: 2.6 }, 2.6)
          .to(sweep, { xPercent: -45, autoAlpha: 0, ease: "power1.out", duration: 2 }, 5.2);
      } else {
        timeline.to(zoom.current, { autoAlpha: 0, duration: 2 }, 0);
      }
    });
    return () => mm.revert();
  }, []);
  return (
    <section ref={section} className="st-hero" aria-label="Brace">
      <div ref={stage} className="st-stage"><CabinWindow zoom={zoom} /></div>
    </section>
  );
}

interface Row { id: string; polygon: [number, number][]; depth_ft: number; loss: number | null; fix: { cost: number; saves: number } | null }
interface Flood {
  name: string; homes: number | null; bounds: [number, number, number, number]; buildings: Row[];
  do_nothing: { loss: number | null; buildings_wet: number };
  plan: null | { spent: number; saved: number; loss: number; buildings_protected: number };
}
const short = (n: number) => (n >= 1e6 ? `$${(n / 1e6).toFixed(1)}M` : `$${Math.round(n / 1e3)}K`);
const clamp = (v: number) => Math.min(1, Math.max(0, v));
const span = (p: number, a: number, b: number) => clamp((p - a) / (b - a));
const ease = (t: number) => (t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2);

/**
 * The flood on the ground, pinned while the scroll plays it:
 *   the cloud clears and the site stands up from its aerial; the water comes in and the loss runs up;
 *   the barriers rise round the buildings the plan protects and the loss falls; the view goes down to one home.
 */
export function FloodGround() {
  const section = useRef<HTMLElement>(null), stage = useRef<HTMLDivElement>(null), mount = useRef<HTMLDivElement>(null);
  const counter = useRef<HTMLElement>(null), label = useRef<HTMLSpanElement>(null), line = useRef<HTMLElement>(null), head = useRef<HTMLElement>(null);
  const progress = useRef(0);
  const [site, setSite] = useState<SiteScene | null>(null);
  const [flood, setFlood] = useState<Flood | null>(null);

  useEffect(() => { api.scene(SITE).then(setSite).catch(() => {}); }, []);
  useEffect(() => { fetch(`/api/flood/${SITE}?water_ft=${WATER_FT}&budget=${BUDGET}&hours=${HOURS}`).then((r) => (r.ok ? r.json() : null)).then((d) => d && setFlood(d)).catch(() => {}); }, []);

  useEffect(() => {
    const el = section.current, pinned = stage.current;
    if (!el || !pinned) return;
    const trigger = ScrollTrigger.create({ trigger: el, start: "top top", end: "bottom bottom", pin: pinned, pinSpacing: false, scrub: true, invalidateOnRefresh: true, onUpdate: (self) => { progress.current = self.progress; } });
    return () => trigger.kill();
  }, []);

  useEffect(() => {
    const el = mount.current;
    if (!el || !site || !flood) return;
    const [w, s, e, n] = site.bounds;
    const width = site.cols * site.cell_m[0], depth = site.rows * site.cell_m[1];
    const xz = (lon: number, lat: number) => [(lon - w) / (e - w) * width - width / 2, (n - lat) / (n - s) * depth - depth / 2] as [number, number];

    const renderer = new THREE.WebGLRenderer({ antialias: true, powerPreference: "high-performance" });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.setSize(el.clientWidth, el.clientHeight);
    renderer.outputColorSpace = THREE.SRGBColorSpace;
    el.appendChild(renderer.domElement);
    const scene = new THREE.Scene();
    scene.background = new THREE.Color(0x0b0f14);
    scene.fog = new THREE.Fog(0x0b0f14, 520, 1400);
    const camera = new THREE.PerspectiveCamera(38, el.clientWidth / el.clientHeight, 1, 4000);
    scene.add(new THREE.HemisphereLight(0xffffff, 0x2a2f3a, 1.25));
    const sun = new THREE.DirectionalLight(0xfff2dc, 1.5);
    sun.position.set(-260, 320, -180);
    scene.add(sun);
    const beyond = new THREE.Mesh(new THREE.PlaneGeometry(6000, 6000).rotateX(-Math.PI / 2), new THREE.MeshBasicMaterial({ color: 0x0e131a }));
    beyond.position.y = -0.4;
    scene.add(beyond);

    // The ground is the aerial photo; every roof and tree rises to the height the surface model measured.
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

    // The water: every cell of the terrain model below the level, laid on the ground where the photo is.
    const [fw, fs, fe, fn] = flood.bounds, [x0, z0] = xz(fw, fn), [x1, z1] = xz(fe, fs);
    const waterMat = new THREE.MeshBasicMaterial({ transparent: true, opacity: 0, depthWrite: false });
    new THREE.TextureLoader().load(`/api/flood/${SITE}/water.png?water_ft=${WATER_FT}`, (tex) => { tex.colorSpace = THREE.SRGBColorSpace; waterMat.map = tex; waterMat.needsUpdate = true; });
    const water = new THREE.Mesh(new THREE.PlaneGeometry(Math.abs(x1 - x0), Math.abs(z1 - z0)).rotateX(-Math.PI / 2), waterMat);
    water.position.set((x0 + x1) / 2, 0.3, (z0 + z1) / 2);
    water.renderOrder = 1;
    scene.add(water);

    // Each building: a wash over its roof for how wet it is, and a wall round it if the plan protects it.
    const roof = new Map(site.structures.map((st) => [st.id, st.roof_height_m ?? 8]));
    const caps: { mat: THREE.MeshBasicMaterial; row: Row }[] = [], walls = new THREE.Group();
    walls.scale.y = 0.001;
    scene.add(walls);
    let homeAt = new THREE.Vector3();
    for (const b of flood.buildings) {
      const pts = b.polygon.map(([lon, lat]) => xz(lon, lat));
      const cx = pts.reduce((a, p) => a + p[0], 0) / pts.length, cz = pts.reduce((a, p) => a + p[1], 0) / pts.length;
      if (b.id === HOME) homeAt = new THREE.Vector3(cx, 0, cz);
      const shape = new THREE.Shape(pts.map(([x, z]) => new THREE.Vector2(x, -z)));
      const mat = new THREE.MeshBasicMaterial({ color: 0xff5a3c, transparent: true, opacity: 0, depthTest: false });
      const cap = new THREE.Mesh(new THREE.ShapeGeometry(shape).rotateX(-Math.PI / 2), mat);
      cap.position.y = (roof.get(b.id) ?? 8) + 1.5;
      cap.renderOrder = 2;
      scene.add(cap);
      caps.push({ mat, row: b });
      if (b.fix) {
        const out = pts.map(([x, z]) => [cx + (x - cx) * 1.07 + Math.sign(x - cx) * 1.2, cz + (z - cz) * 1.07 + Math.sign(z - cz) * 1.2]);
        const verts: number[] = [];
        out.forEach(([x, z], i) => { const [nx, nz] = out[(i + 1) % out.length]; verts.push(x, 0, z, nx, 0, nz, nx, 1, nz, x, 0, z, nx, 1, nz, x, 1, z); });
        const g = new THREE.BufferGeometry();
        g.setAttribute("position", new THREE.Float32BufferAttribute(verts, 3));
        const wall = new THREE.Mesh(g, new THREE.MeshBasicMaterial({ color: 0x7fd4ff, transparent: true, opacity: 0.92, side: THREE.DoubleSide }));
        wall.scale.y = 4.5;      // drawn taller than a real barrier so it reads from above
        wall.renderOrder = 3;
        walls.add(wall);
      }
    }
    // The one home the file is about, ringed in amber once the view comes down to it.
    const ring = new THREE.Mesh(new THREE.RingGeometry(15, 17.5, 64).rotateX(-Math.PI / 2), new THREE.MeshBasicMaterial({ color: 0xffc20e, transparent: true, opacity: 0, depthTest: false }));
    ring.position.copy(homeAt).setY((roof.get(HOME) ?? 8) + 2);
    ring.renderOrder = 4;
    scene.add(ring);

    const above = new THREE.Vector3(0, 560, 0.01), reach = Math.max(width, depth);
    // The drawing follows its box, however the box comes to change size; the style sheet, not the renderer, sets how big it is shown.
    const size = () => { renderer.setSize(el.clientWidth, el.clientHeight, false); camera.aspect = el.clientWidth / Math.max(1, el.clientHeight); camera.updateProjectionMatrix(); };
    size();
    const watch = new ResizeObserver(size);
    watch.observe(el);
    const loss = flood.do_nothing.loss ?? 0, after = flood.plan?.loss ?? loss;
    let raf = 0;
    const tick = () => {
      raf = requestAnimationFrame(tick);
      const p = progress.current;
      const stand = ease(span(p, 0.04, 0.2)), wet = ease(span(p, 0.26, 0.46)), guard = ease(span(p, 0.56, 0.72)), down = ease(span(p, 0.82, 0.97));
      el.style.opacity = String(span(p, 0, 0.06));
      if (terrain) terrain.scale.y = Math.max(0.001, stand);
      // The view comes down from straight above, drifts round the site as the scroll goes on, then drops to the one home.
      const turn = -0.5 + p * 1.1, r = reach * 0.92, settled = new THREE.Vector3(Math.sin(turn) * r, 235, Math.cos(turn) * r);
      const near = new THREE.Vector3(homeAt.x + Math.sin(turn) * 70, 62, homeAt.z + Math.cos(turn) * 70);
      camera.position.lerpVectors(above, settled, stand).lerp(near, down);
      camera.lookAt(new THREE.Vector3(0, 6 * stand, 0).lerp(new THREE.Vector3(homeAt.x, 6, homeAt.z), down));
      waterMat.opacity = wet * 0.95;
      walls.scale.y = Math.max(0.001, guard);
      for (const { mat, row } of caps) {
        const safe = row.fix ? guard : 0;
        mat.color.setHex(safe > 0.5 ? 0x4fc3ff : 0xff5a3c);
        mat.opacity = row.depth_ft > 0 ? wet * (0.2 + Math.min(0.3, row.depth_ft * 0.07)) * (safe > 0.5 ? 0.6 : 1) * (1 - down * 0.6) : 0;
      }
      (ring.material as THREE.MeshBasicMaterial).opacity = down;
      // The number runs up with the water and falls with the barriers.
      const shown = loss * wet - (loss - after) * guard;
      if (counter.current) { counter.current.textContent = `−${short(shown)}`; counter.current.style.color = guard > 0.5 ? "var(--amber)" : "#ff5a3c"; counter.current.style.opacity = String(span(p, 0.24, 0.3) * (1 - down)); }
      if (label.current) { label.current.textContent = guard > 0.5 ? "With the plan" : "If nothing is done"; label.current.style.opacity = String(span(p, 0.24, 0.3) * (1 - down)); }
      if (line.current) line.current.style.opacity = String(span(p, 0.68, 0.74) * (1 - down));
      if (head.current) head.current.style.opacity = String(span(p, 0.12, 0.2));
      renderer.render(scene, camera);
    };
    tick();
    return () => { cancelAnimationFrame(raf); watch.disconnect(); renderer.dispose(); el.removeChild(renderer.domElement); };
  }, [site, flood]);

  const plan = flood?.plan;
  return (
    <section ref={section} className="fg-section" aria-label="The flood">
      <div ref={stage} className="fg-stage">
        <div ref={mount} className="fg-scene" />
        <header ref={head} className="fg-head">
          <h2>{flood?.name}</h2>
          <p>Houston. {WATER_FT} ft of water.</p>
        </header>
        <div className="fg-count" aria-live="off">
          <span ref={label} />
          <strong ref={counter} />
          <em ref={line}>{plan ? `${short(plan.spent)} spent. ${short(plan.saved)} saved.` : ""}</em>
        </div>
      </div>
    </section>
  );
}

/** A stretch of open scroll where the cloud bank rises and whites out the view, as in the scenarios. */
export function QuietCloud() {
  const zone = useRef<HTMLDivElement>(null);
  const run = useCallback(() => {
    const el = zone.current;
    if (!el) return () => {};
    const bank = document.querySelector<HTMLElement>('[data-sky="bank"]'), veil = document.querySelector<HTMLElement>('[data-sky="veil"]');
    const timeline = gsap.timeline({ defaults: { ease: "none" }, scrollTrigger: { trigger: el, start: "top bottom", end: "bottom bottom", scrub: 1, refreshPriority: 8 } });
    timeline.fromTo(bank, { yPercent: 105, scale: 1, autoAlpha: 1 }, { yPercent: -8, scale: 1.45, ease: "power1.out", duration: 6 }, 0)
      .fromTo(veil, { autoAlpha: 0 }, { autoAlpha: 1, duration: 1.8 }, 4.4);
    return () => { timeline.scrollTrigger?.kill(); timeline.kill(); };
  }, []);
  useEffect(() => run(), [run]);
  return <div ref={zone} aria-hidden="true" className="st-cloud-rise fg-cloud" />;
}
