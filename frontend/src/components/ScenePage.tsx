import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import { api } from "../api";
import { costRange } from "../format";
import { prepareHash, sceneHash } from "../recovery/routes";
import type { Action, Approval, Building, Measured, ResidentReport, SavedStep, Scenario, SiteScene } from "../types";
import "./scene.css";

interface Props { id: number; scenario: Scenario; step: string | null }

/**
 * The site, standing up. One screen: the ground is the aerial photo, and every roof and tree rises to the
 * height the surface model measured. The plan's jobs are placed on it, crews move to the ones that still
 * fit the clock, and the one decision sits beside it.
 */
const AMBER = 0xffc20e, QUIET = 0x8a8f98, SKY = 0x00b0e6, PAPER = 0xf4f1ea, EMBER = 0xff7a3c;
const RISE_MS = 2600, HOLD_MS = 700, PIN_M = 15;
const ease = (t: number) => (t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2);
const hoursText = (h: number | null | undefined) => (h == null ? "" : h <= 0 ? "Now" : `${h >= 20 ? Math.round(h) : Math.round(h * 2) / 2} hours`);
const short = (a: Action) => a.title.replace(/^(After the storm, |Have the tree crew |Tree crew: )/i, "").replace(/\s*\(.*$/, "").replace(/^./, (c) => c.toUpperCase());
/** Metres to one decimal, halves rounded up, as a person would write 15.45. */
const metres = (m: number) => (Math.round(m * 10 + 1e-6) / 10).toFixed(1);

interface World {
  renderer: THREE.WebGLRenderer; scene: THREE.Scene; camera: THREE.PerspectiveCamera; controls: OrbitControls;
  terrain: THREE.Mesh | null; marks: THREE.Group; heights: Float32Array | null; started: number; ready: boolean;
  fly: null | { t0: number; ms: number; fromP: THREE.Vector3; toP: THREE.Vector3; fromT: THREE.Vector3; toT: THREE.Vector3 };
  movers: { mesh: THREE.Mesh; from: THREE.Vector3; to: THREE.Vector3; t0: number; ms: number; ring: THREE.Mesh }[];
}

export function ScenePage({ id, scenario, step }: Props) {
  const [b, setB] = useState<Building | null>(null);
  const [site, setSite] = useState<SiteScene | null>(null);
  const [measured, setMeasured] = useState<Record<string, Measured[]>>({});
  const [saved, setSaved] = useState<SavedStep[]>([]);
  const [reports, setReports] = useState<ResidentReport[]>([]);
  const [picked, setPicked] = useState<string | null>(null);
  const [stood, setStood] = useState(false);
  const [said, setSaid] = useState<Approval | null>(null);
  const [error, setError] = useState<string | null>(null);
  const mount = useRef<HTMLDivElement>(null);
  const world = useRef<World | null>(null);
  const anchors = useRef(new Map<string, THREE.Vector3>());
  const labels = useRef(new Map<string, HTMLElement>());
  const dispatched = useRef<string | null>(null);

  useEffect(() => {
    let current = true;
    setSaid(null);
    api.building(id, scenario.id, step).then((d) => { if (current) { setB(d); setError(null); } }).catch((e) => { if (current) setError(e.message); });
    api.measured(id, scenario.id, step).then((m) => { if (current) setMeasured(m); }).catch(() => { if (current) setMeasured({}); });
    return () => { current = false; };
  }, [id, scenario.id, step]);
  useEffect(() => { api.scene(id).then(setSite).catch((e) => setError(e.message)); }, [id]);
  useEffect(() => { api.savedSteps(id, scenario.id).then(setSaved).catch(() => setSaved([])); }, [id, scenario.id]);
  useEffect(() => {
    let current = true;
    const read = () => api.siteModel(id).then((m) => { if (current) setReports(m.reports); }).catch(() => {});
    read();
    const t = window.setInterval(read, 5000);
    return () => { current = false; window.clearInterval(t); };
  }, [id]);

  // Longitude and latitude to metres on the ground: x east, z south, with the site's centre at the origin.
  const place = useMemo(() => {
    if (!site) return null;
    const [w, s, e, n] = site.bounds;
    const width = site.cols * site.cell_m[0], depth = site.rows * site.cell_m[1];
    return {
      width, depth,
      xz: (lon: number, lat: number) => [(lon - w) / (e - w) * width - width / 2, (n - lat) / (n - s) * depth - depth / 2] as [number, number],
      cell: (lon: number, lat: number) => [Math.round((n - lat) / (n - s) * (site.rows - 1)), Math.round((lon - w) / (e - w) * (site.cols - 1))] as [number, number],
    };
  }, [site]);

  const heightAt = useCallback((lon: number, lat: number) => {
    const h = world.current?.heights;
    if (!h || !site || !place) return 0;
    const [row, col] = place.cell(lon, lat);
    if (row < 0 || col < 0 || row >= site.rows || col >= site.cols) return 0;
    return h[row * site.cols + col];
  }, [site, place]);

  // --- the world: built once per site ---------------------------------------------------------------
  useEffect(() => {
    const el = mount.current;
    if (!el || !site || !place) return;
    const renderer = new THREE.WebGLRenderer({ antialias: true, powerPreference: "high-performance" });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.setSize(el.clientWidth, el.clientHeight);
    renderer.outputColorSpace = THREE.SRGBColorSpace;
    el.appendChild(renderer.domElement);
    const scene = new THREE.Scene();
    scene.background = new THREE.Color(0x0b0f14);
    scene.fog = new THREE.Fog(0x0b0f14, 520, 1300);
    const camera = new THREE.PerspectiveCamera(38, el.clientWidth / el.clientHeight, 1, 4000);
    const above = new THREE.Vector3(0, 560, 0.01), settled = new THREE.Vector3(place.width * 0.72, 235, place.depth * 0.98);
    camera.position.copy(above);
    const controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true; controls.maxPolarAngle = Math.PI * 0.47; controls.minDistance = 40; controls.maxDistance = 700;
    controls.autoRotateSpeed = 0.35; controls.enabled = false;
    controls.addEventListener("start", () => { controls.autoRotate = false; });
    scene.add(new THREE.HemisphereLight(0xffffff, 0x2a2f3a, 1.25));
    const sun = new THREE.DirectionalLight(0xfff2dc, 1.5);
    sun.position.set(-260, 320, -180);
    scene.add(sun);
    // The land beyond the photo: dark and quiet, so the site reads as an island of light.
    const beyond = new THREE.Mesh(new THREE.PlaneGeometry(6000, 6000).rotateX(-Math.PI / 2), new THREE.MeshBasicMaterial({ color: 0x0e131a }));
    beyond.position.y = -0.4;
    scene.add(beyond);
    const marks = new THREE.Group();
    marks.visible = false;
    scene.add(marks);
    const w: World = { renderer, scene, camera, controls, terrain: null, marks, heights: null, started: 0, ready: false, fly: null, movers: [] };
    world.current = w;

    // The height grid is a picture: two bytes a cell, centimetres above the ground.
    const grid = new Image();
    grid.onload = () => {
      const c = document.createElement("canvas");
      c.width = site.cols; c.height = site.rows;
      const ctx = c.getContext("2d", { willReadFrequently: true });
      if (!ctx) return;
      ctx.drawImage(grid, 0, 0);
      const px = ctx.getImageData(0, 0, site.cols, site.rows).data;
      const h = new Float32Array(site.cols * site.rows);
      for (let i = 0; i < h.length; i++) h[i] = px[i * 4 + 2] === 255 ? 0 : (px[i * 4] * 256 + px[i * 4 + 1]) * site.decode.unit_m;
      w.heights = h;
      const geo = new THREE.PlaneGeometry(place.width, place.depth, site.cols - 1, site.rows - 1).rotateX(-Math.PI / 2);
      const pos = geo.attributes.position;
      for (let i = 0; i < pos.count; i++) pos.setY(i, h[i]);
      geo.computeVertexNormals();
      new THREE.TextureLoader().load(site.texture_url, (tex) => {
        tex.colorSpace = THREE.SRGBColorSpace; tex.anisotropy = renderer.capabilities.getMaxAnisotropy();
        const terrain = new THREE.Mesh(geo, new THREE.MeshStandardMaterial({ map: tex, roughness: 1, metalness: 0 }));
        terrain.scale.y = 0.001;
        scene.add(terrain);
        w.terrain = terrain;
        w.started = performance.now();
      });
    };
    grid.src = site.heights_url;

    const size = () => { renderer.setSize(el.clientWidth, el.clientHeight); camera.aspect = el.clientWidth / el.clientHeight; camera.updateProjectionMatrix(); };
    window.addEventListener("resize", size);
    const v = new THREE.Vector3();
    let frame = 0;
    const tick = () => {
      frame = requestAnimationFrame(tick);
      const now = performance.now();
      if (w.terrain && !w.ready) {
        // The photo lies flat for a moment, then the site stands up while the camera comes down to meet it.
        const t = Math.min(1, Math.max(0, (now - w.started - HOLD_MS) / RISE_MS)), k = ease(t);
        w.terrain.scale.y = Math.max(0.001, k);
        camera.position.lerpVectors(above, settled, k);
        camera.lookAt(0, 6 * k, 0);
        if (t >= 1) { w.ready = true; controls.enabled = true; controls.target.set(0, 6, 0); controls.autoRotate = true; marks.visible = true; setStood(true); }
      } else if (w.ready) {
        if (w.fly) {
          const t = Math.min(1, (now - w.fly.t0) / w.fly.ms), k = ease(t);
          camera.position.lerpVectors(w.fly.fromP, w.fly.toP, k);
          controls.target.lerpVectors(w.fly.fromT, w.fly.toT, k);
          if (t >= 1) w.fly = null;
        }
        controls.update();
      }
      for (const m of w.movers) {
        const t = Math.min(1, Math.max(0, (now - m.t0) / m.ms));
        m.mesh.position.lerpVectors(m.from, m.to, ease(t));
        m.mesh.visible = now >= m.t0;
        const pulse = t >= 1 ? 1 + 0.35 * Math.sin((now - m.t0) / 380) : 0.001;
        m.ring.scale.set(pulse, pulse, pulse);
      }
      renderer.render(scene, camera);
      // Words follow the things they name.
      const wpx = el.clientWidth, hpx = el.clientHeight;
      labels.current.forEach((node, key) => {
        const at = anchors.current.get(key);
        if (!at || !w.ready) { node.style.opacity = "0"; return; }
        v.copy(at).project(camera);
        const off = v.z > 1 || Math.abs(v.x) > 1.15 || Math.abs(v.y) > 1.15;
        node.style.opacity = off ? "0" : "1";
        // A measurement sits beside its rule; everything else sits on top of its pin.
        node.style.transform = `translate(${((v.x + 1) / 2) * wpx}px, ${((1 - v.y) / 2) * hpx}px) ${node.dataset.side === "left" ? "translate(-100%, -50%) translateX(-12px)" : "translate(-50%, -100%)"}`;
      });
    };
    tick();
    return () => {
      cancelAnimationFrame(frame);
      window.removeEventListener("resize", size);
      controls.dispose(); renderer.dispose();
      renderer.domElement.remove();
      world.current = null;
    };
  }, [site, place]);

  // --- what is measured: the tall things someone looked at, each with a rule beside it ---------------
  const tall = useMemo(() => {
    const seen = new Map<string, { key: string; lon: number; lat: number; height: number; wall: number; roof: string; what: string }>();
    for (const st of site?.structures ?? []) {
      const t = st.tallest;
      if (!t || !t.what || !/tree|pine/i.test(t.what)) continue;
      const key = `${t.lon.toFixed(5)},${t.lat.toFixed(5)}`, had = seen.get(key);
      if (!had || t.from_wall_m < had.wall) seen.set(key, { key, lon: t.lon, lat: t.lat, height: t.height_m, wall: t.from_wall_m, roof: st.id, what: t.what });
    }
    return [...seen.values()];
  }, [site]);

  const actions = useMemo(() => (b?.plan?.actions ?? []).filter((a) => a.site), [b]);
  const placed = useMemo(() => reports.filter((r) => r.where?.position_id && site?.positions[r.where.position_id]), [reports, site]);

  // --- what is planned: a pin for every job, and a crew on its way to each one that still fits -------
  useEffect(() => {
    const w = world.current;
    if (!w || !stood || !place) return;
    w.marks.clear();
    w.movers = [];
    for (const key of [...anchors.current.keys()]) anchors.current.delete(key);
    const line = (from: THREE.Vector3, to: THREE.Vector3, color: number, opacity = 1) =>
      w.marks.add(new THREE.Line(new THREE.BufferGeometry().setFromPoints([from, to]), new THREE.LineBasicMaterial({ color, transparent: opacity < 1, opacity })));

    for (const t of tall) {
      const [x, z] = place.xz(t.lon, t.lat);
      line(new THREE.Vector3(x, 0, z), new THREE.Vector3(x, t.height, z), PAPER);
      for (let m = 5; m < t.height; m += 5) line(new THREE.Vector3(x - 1.2, m, z), new THREE.Vector3(x + 1.2, m, z), PAPER, 0.7);
      anchors.current.set(`m:${t.key}`, new THREE.Vector3(x, t.height * 0.45, z));   // beside the rule, below the pin
    }
    // Crews travel in when the plan changes (first sight, or the clock moving), not every time a job is chosen.
    const planKey = `${step}:${actions.map((a) => a.id + a.timing).join(",")}`;
    const arriving = dispatched.current !== planKey;
    dispatched.current = planKey;
    const now = performance.now();
    actions.forEach((a, i) => {
      const [x, z] = place.xz(a.site!.lon, a.site!.lat), ground = heightAt(a.site!.lon, a.site!.lat);
      const live = a.timing === "before_arrival", color = a.id === picked ? SKY : live ? AMBER : QUIET;
      const base = new THREE.Vector3(x, ground + 0.3, z), top = new THREE.Vector3(x, ground + PIN_M, z);
      line(base, top, color, live ? 1 : 0.6);
      anchors.current.set(`a:${a.id}`, top);
      const ring = new THREE.Mesh(new THREE.RingGeometry(3.2, 4.1, 40).rotateX(-Math.PI / 2), new THREE.MeshBasicMaterial({ color, transparent: true, opacity: live ? 0.95 : 0.5, side: THREE.DoubleSide, depthTest: false }));
      ring.position.copy(base);
      w.marks.add(ring);
      if (!live) return;
      // A crew comes in from the nearest edge of the site and stays on the job.
      const edge = Math.abs(x) / place.width > Math.abs(z) / place.depth ? new THREE.Vector3(Math.sign(x || 1) * place.width / 2, 1.5, z) : new THREE.Vector3(x, 1.5, Math.sign(z || 1) * place.depth / 2);
      const mesh = new THREE.Mesh(new THREE.SphereGeometry(1.7, 20, 14), new THREE.MeshBasicMaterial({ color }));
      mesh.visible = false;
      w.marks.add(mesh);
      line(edge, new THREE.Vector3(x, 1.5, z), color, 0.35);
      w.movers.push({ mesh, from: edge, to: new THREE.Vector3(x, ground + 1.7, z), t0: arriving ? now + 500 + i * 450 : now - 60000, ms: 2600, ring });
    });
    for (const r of placed) {
      const p = site!.positions[r.where!.position_id as string];
      const [x, z] = place.xz(p.lon, p.lat), ground = heightAt(p.lon, p.lat);
      line(new THREE.Vector3(x, ground, z), new THREE.Vector3(x, ground + PIN_M + 6, z), EMBER);
      anchors.current.set(`r:${r.id}`, new THREE.Vector3(x, ground + PIN_M + 6, z));
    }
  }, [stood, place, tall, actions, placed, picked, heightAt, site, step]);

  // Choosing a job brings the camera round to it.
  const look = useCallback((a: Action | null) => {
    setPicked(a?.id ?? null);
    setSaid(null);
    const w = world.current;
    if (!w || !a?.site || !place) return;
    const [x, z] = place.xz(a.site.lon, a.site.lat);
    const to = new THREE.Vector3(x, heightAt(a.site.lon, a.site.lat) * 0.5, z);
    const away = w.camera.position.clone().sub(w.controls.target).setY(0).normalize().multiplyScalar(105);
    w.controls.autoRotate = false;
    w.fly = { t0: performance.now(), ms: 1400, fromP: w.camera.position.clone(), toP: to.clone().add(away).setY(to.y + 70), fromT: w.controls.target.clone(), toT: to };
  }, [place, heightAt]);

  if (error) return <div className="fatal" role="alert">{error}</div>;
  const chosen = actions.find((a) => a.id === picked) ?? null;
  const notice = b?.plan?.messages.find((m) => m.kind === "notice" && chosen && m.action_ids.includes(chosen.id)) ?? null;
  const left = b?.threat.hours_left ?? null;
  const steps = saved.filter((s) => s.step);

  return (
    <div className={`scene${stood ? " is-standing" : ""}`}>
      <div className="scene-stage" ref={mount} />

      <div className="scene-labels" aria-hidden={!stood}>
        {tall.map((t) => (
          <div key={t.key} className="scene-rule" data-side="left" ref={(n) => { if (n) labels.current.set(`m:${t.key}`, n); else labels.current.delete(`m:${t.key}`); }}>
            <strong>{metres(t.height)} m</strong>
            <span>{t.what.replace(/^an? /, "")}, {metres(t.wall)} m from the wall of {t.roof}</span>
          </div>
        ))}
        {actions.map((a) => (
          <button key={a.id} className={`scene-pin is-${a.timing}${a.id === picked ? " is-picked" : ""}`} onClick={() => look(a.id === picked ? null : a)}
                  ref={(n) => { if (n) labels.current.set(`a:${a.id}`, n); else labels.current.delete(`a:${a.id}`); }}>
            <b>{a.id.replace("A", "")}</b><span>{a.timing === "before_arrival" ? a.crew.split(/[(;,]/)[0].trim() : "after the storm"}</span>
          </button>
        ))}
        {placed.map((r) => (
          <div key={r.id} className="scene-report" ref={(n) => { if (n) labels.current.set(`r:${r.id}`, n); else labels.current.delete(`r:${r.id}`); }}>
            <strong>{r.where!.room}{r.where!.thing ? `, at the ${r.where!.thing}` : ""}</strong>
            <span>“{r.text.replace(/^Support request \([^)]*\):\s*/, "")}”</span>
          </div>
        ))}
      </div>

      <header className="scene-place">
        <a href={prepareHash(scenario.id, step, id)} aria-label="Back to the building">Brace</a>
        <h1>{site?.name ?? b?.record.name ?? ""}</h1>
        <p>{site?.homes ? `${site.homes} homes` : ""}{b ? `. ${b.threat.name}` : ""}</p>
      </header>

      <div className="scene-clock">
        <strong>{hoursText(left)}</strong>
        <span>{left == null ? "" : left <= 0 ? "conditions are here" : "until the wind arrives"}{left != null && left > 0 ? `. ${hoursText(Math.max(0, left - 6))} of safe working time` : ""}</span>
        {steps.length > 1 && (
          <div className="scene-steps" role="group" aria-label="Forecast step">
            {steps.map((s) => (
              <button key={s.step} aria-pressed={s.step === step} onClick={() => { window.location.hash = sceneHash(scenario.id, s.step, id); }}>{s.label.replace(/ before landfall$/, "")}</button>
            ))}
          </div>
        )}
      </div>

      {chosen && (
        <aside className={`scene-card is-${chosen.timing}`}>
          <p className="scene-when">{chosen.timing === "before_arrival" ? "Before the storm" : chosen.timing === "after_event" ? "After the storm" : "Later"}</p>
          <h2>{chosen.title}</h2>
          <p className="scene-who">{chosen.crew.split(/[(;]/)[0].trim()}, {chosen.hours_of_work} hours, {costRange(chosen.cost_low, chosen.cost_high)}</p>
          {(measured[chosen.id] ?? []).length > 0 && (
            <ul className="scene-measured">
              {measured[chosen.id].map((m, i) => <li key={i}><strong>{m.label}</strong>{m.text}</li>)}
            </ul>
          )}
          {notice && !said && <button className="scene-approve" onClick={() => api.approve(id, scenario.id, step, chosen.id).then(setSaid)}>Approve the notice to residents</button>}
          {said && <p className={`scene-said${said.ok ? "" : " is-refused"}`}>{said.say}</p>}
        </aside>
      )}

      <nav className="scene-jobs" aria-label="The plan">
        {actions.map((a) => (
          <button key={a.id} className={`is-${a.timing}`} aria-pressed={a.id === picked} onClick={() => look(a.id === picked ? null : a)}>
            <b>{a.id.replace("A", "")}</b>{short(a)}
          </button>
        ))}
      </nav>

      {site && <p className="scene-source">Heights: {site.sources.heights}. Photo: {site.sources.photo}. A height model, not a photograph of the walls.</p>}
      {!stood && <p className="scene-wait" role="status">{site ? "" : "Reading the site…"}</p>}
    </div>
  );
}
