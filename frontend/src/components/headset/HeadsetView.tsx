/**
 * The headset beat (PRD R10 / J-1): stand in the scanned home and see what the owner would have to put back.
 *
 * A phone in a cardboard-style viewer shows the leasing scan's own 360° pictures, one standpoint at a time,
 * with each line the inventory agent read pinned where the thing is: "Base cabinet ×2 · $672–$1,015".
 * Turn your head to look round (iPhone asks once for motion access). Standpoints change by themselves
 * every few seconds with a slow fade, or on a tap. Everything comes from GET /api/schedule/{property}.
 *
 * Laptop: drag to look, Space or → for the next standpoint, V for one view or two.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import * as THREE from "three";
import { buildTour, direction, label, range, type Schedule, type Stop } from "./lib/tour";
import { askForMotion, createOrientationReader, motionSupport, yawOf, type MotionState } from "./lib/motion";
import "./headset.css";

const DWELL_S = 16;        // time at each standpoint before moving on
const FADE_S = 1.4;        // fade out and in between standpoints, slow for comfort
const TAG_STAGGER_S = 0.7; // tags appear one after another on arrival
const FACE_M = 40;         // the panorama box; far enough that the two eyes see it alike
const TAG_M = 4.5;         // tags float this far away
const EYES_M = 0.064;

const rad = (d: number) => (d * Math.PI) / 180;
const clamp = (x: number) => Math.min(1, Math.max(0, x));
const smooth = (x: number) => x * x * (3 - 2 * x);

type Phase =
  | { kind: "loading" }
  | { kind: "signin"; error: string | null; busy: boolean }
  | { kind: "error"; message: string }
  | { kind: "ready"; schedule: Schedule; stops: Stop[] }
  | { kind: "running"; schedule: Schedule; stops: Stop[] };

async function loadSchedule(site: number, scan: string): Promise<{ schedule: Schedule; stops: Stop[] } | "signin"> {
  const r = await fetch(`/api/schedule/${site}`, { credentials: "same-origin" });
  if (r.status === 401 || r.status === 403) return "signin";
  if (!r.ok) throw new Error((await r.json().catch(() => null))?.detail || `The schedule could not be loaded (${r.status}).`);
  const schedule = (await r.json()) as Schedule;
  let stops = buildTour(schedule, scan);
  const missing = schedule.buildings.some((b) => (b.units ?? []).some((u) => u.rooms.some((rm) => rm.items.some((i) => i.at && i.at.heading_deg == null))));
  if (missing) {
    // Older schedules do not carry the panorama heading; read it from the building's scan record instead.
    const headings: Record<string, number> = {};
    try {
      const sc = await (await fetch("/api/scenarios", { credentials: "same-origin" })).json();
      const id = (Array.isArray(sc) ? sc : sc.scenarios ?? [])[0]?.id;
      const b = await (await fetch(`/api/buildings/${site}?scenario=${encodeURIComponent(id)}`, { credentials: "same-origin" })).json();
      for (const s of b.scans ?? []) if (s.id === scan) for (const w of s.sweeps ?? []) if (typeof w.heading === "number") headings[w.id] = w.heading;
    } catch {
      /* stops without a heading are left out */
    }
    stops = buildTour(schedule, scan, headings);
  }
  return { schedule, stops };
}

function canvasSprite(draw: (g: CanvasRenderingContext2D, w: number, h: number) => void, w: number, h: number, worldH: number): THREE.Sprite {
  const c = document.createElement("canvas");
  c.width = w;
  c.height = h;
  const g = c.getContext("2d")!;
  draw(g, w, h);
  const tex = new THREE.CanvasTexture(c);
  tex.colorSpace = THREE.SRGBColorSpace;
  const mat = new THREE.SpriteMaterial({ map: tex, transparent: true, depthTest: false, depthWrite: false, opacity: 0 });
  const s = new THREE.Sprite(mat);
  s.scale.set((worldH * w) / h, worldH, 1);
  s.renderOrder = 5;
  return s;
}

function roundRect(g: CanvasRenderingContext2D, x: number, y: number, w: number, h: number, r: number) {
  g.beginPath();
  g.moveTo(x + r, y);
  g.arcTo(x + w, y, x + w, y + h, r);
  g.arcTo(x + w, y + h, x, y + h, r);
  g.arcTo(x, y + h, x, y, r);
  g.arcTo(x, y, x + w, y, r);
  g.closePath();
}

const FONT = '"Barlow", "Helvetica Neue", Arial, sans-serif';

/** A pinned line: a dot on the thing, the name above, the figure below. */
function tagSprite(name: string, figure: string, priced: boolean): THREE.Sprite {
  return canvasSprite((g, w, h) => {
    g.font = `600 44px ${FONT}`;
    const nameW = g.measureText(name).width;
    g.font = `500 38px ${FONT}`;
    const figW = g.measureText(figure).width;
    const boxW = Math.min(w - 8, Math.max(nameW, figW) + 56), boxH = 118, x = (w - boxW) / 2, y = 8;
    g.fillStyle = "rgba(11, 21, 34, 0.86)";
    roundRect(g, x, y, boxW, boxH, 18);
    g.fill();
    g.strokeStyle = "rgba(255, 255, 255, 0.28)";
    g.lineWidth = 2;
    g.stroke();
    g.textAlign = "center";
    g.fillStyle = "#ffffff";
    g.font = `600 44px ${FONT}`;
    g.fillText(name, w / 2, y + 52, boxW - 32);
    g.fillStyle = priced ? "#f6d58b" : "#b9c4d2";
    g.font = `500 38px ${FONT}`;
    g.fillText(figure, w / 2, y + 100, boxW - 32);
    // Leader and dot: the dot sits on the thing itself, at the sprite's bottom centre.
    g.strokeStyle = "rgba(255, 255, 255, 0.7)";
    g.lineWidth = 3;
    g.beginPath();
    g.moveTo(w / 2, y + boxH);
    g.lineTo(w / 2, h - 18);
    g.stroke();
    g.fillStyle = "#ffffff";
    g.beginPath();
    g.arc(w / 2, h - 12, 10, 0, Math.PI * 2);
    g.fill();
  }, 640, 230, 0.86);
}

/** The strip that stays below the gaze: the room, its figure, and the home's. */
function hudSprite(top: string, bottom: string): THREE.Sprite {
  return canvasSprite((g, w, h) => {
    g.fillStyle = "rgba(11, 21, 34, 0.8)";
    roundRect(g, 4, 4, w - 8, h - 8, 22);
    g.fill();
    g.textAlign = "center";
    g.fillStyle = "#ffffff";
    g.font = `700 46px ${FONT}`;
    g.fillText(top, w / 2, 66, w - 48);
    g.fillStyle = "#c4cfdc";
    g.font = `500 34px ${FONT}`;
    g.fillText(bottom, w / 2, 120, w - 48);
  }, 1100, 150, 0.36);
}

export function HeadsetView({ site, scan }: { site: number; scan: string }) {
  const [phase, setPhase] = useState<Phase>({ kind: "loading" });
  const [motion, setMotion] = useState<MotionState>(() => motionSupport());
  const [stereo, setStereo] = useState(() => window.matchMedia("(pointer: coarse)").matches);
  const [secret, setSecret] = useState("");
  const mount = useRef<HTMLDivElement>(null);
  const live = useRef({ stereo, next: 0 });
  live.current.stereo = stereo;

  const load = useCallback(() => {
    setPhase({ kind: "loading" });
    loadSchedule(site, scan)
      .then((r) => {
        if (r === "signin") setPhase({ kind: "signin", error: null, busy: false });
        else if (!r.stops.length) setPhase({ kind: "error", message: "No line in this home's schedule has a place in the scan yet. Read the scan first (scripts.inventory)." });
        else setPhase({ kind: "ready", ...r });
      })
      .catch((e: Error) => setPhase({ kind: "error", message: e.message }));
  }, [site, scan]);

  useEffect(load, [load]);

  const signIn = async (e: React.FormEvent) => {
    e.preventDefault();
    setPhase({ kind: "signin", error: null, busy: true });
    try {
      const r = await fetch("/api/recovery/session", {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ secret }),
      });
      if (!r.ok) throw new Error((await r.json().catch(() => null))?.error?.message || "That password was not accepted.");
      setSecret("");
      load();
    } catch (err) {
      setPhase({ kind: "signin", error: (err as Error).message, busy: false });
    }
  };

  const start = async () => {
    if (phase.kind !== "ready") return;
    if (motion === "needs-tap") setMotion(await askForMotion()); // must run inside this tap on iPhone
    (navigator as Navigator & { wakeLock?: { request(kind: string): Promise<unknown> } }).wakeLock?.request("screen").catch(() => {});
    document.documentElement.requestFullscreen?.().catch(() => {});
    setPhase({ kind: "running", schedule: phase.schedule, stops: phase.stops });
  };

  useEffect(() => {
    const key = (e: KeyboardEvent) => {
      if (e.key === "v" || e.key === "V") setStereo((s) => !s);
      else if (e.key === " " || e.key === "ArrowRight") { e.preventDefault(); live.current.next++; }
    };
    window.addEventListener("keydown", key);
    return () => window.removeEventListener("keydown", key);
  }, []);

  // The scene: one standpoint's panorama and its tags at a time.
  useEffect(() => {
    const el = mount.current;
    if (!el || phase.kind !== "running") return;
    const { schedule, stops } = phase;
    const coarse = window.matchMedia("(pointer: coarse)").matches;
    const faceSize = coarse ? 1024 : 2048;

    const renderer = new THREE.WebGLRenderer({ antialias: true });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.outputColorSpace = THREE.SRGBColorSpace;
    renderer.autoClear = false;
    renderer.setClearColor(0x05080c, 1);
    el.appendChild(renderer.domElement);
    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(80, 1, 0.05, 300);
    camera.rotation.order = "YXZ";
    const world = new THREE.Group();
    scene.add(world);
    const loader = new THREE.TextureLoader();
    const reader = createOrientationReader();

    type Built = { group: THREE.Group; mats: THREE.Material[]; tags: THREE.Sprite[]; textures: THREE.Texture[] };
    const build = (st: Stop): Built => {
      const group = new THREE.Group(), mats: THREE.Material[] = [], textures: THREE.Texture[] = [], side = FACE_M * 2.002;
      const face = (f: number) => {
        const tex = loader.load(`/api/buildings/${site}/pano/${scan}/${st.sweepId}/${f}.jpg?size=${faceSize}`);
        tex.colorSpace = THREE.SRGBColorSpace;
        textures.push(tex);
        const mat = new THREE.MeshBasicMaterial({ map: tex, depthTest: false, depthWrite: false, transparent: true, opacity: 0 });
        mats.push(mat);
        const m = new THREE.Mesh(new THREE.PlaneGeometry(side, side), mat);
        m.renderOrder = 0;
        return m;
      };
      // Faces 1-4 run clockwise from the panorama's heading; 0 is up and 5 is down (same as the home page).
      for (let k = 0; k < 4; k++) {
        const pivot = new THREE.Group(), m = face(k + 1);
        m.position.z = -FACE_M;
        pivot.add(m);
        pivot.rotation.y = -rad(st.heading + 90 * k);
        group.add(pivot);
      }
      const caps = new THREE.Group(), up = face(0), down = face(5);
      up.position.y = FACE_M;
      up.rotation.x = Math.PI / 2;
      down.position.y = -FACE_M;
      down.rotation.x = -Math.PI / 2;
      caps.add(up, down);
      caps.rotation.y = -rad(st.heading);
      group.add(caps);
      const tags = st.tags.map((t) => {
        const s = tagSprite(label(t), range(t.low, t.high), t.low != null && t.high != null);
        const [x, y, z] = direction(t.yaw, t.pitch);
        // The sprite's dot is at its bottom centre; anchor there so the dot lands on the thing.
        s.center.set(0.5, 0.04);
        s.position.set(x * TAG_M, y * TAG_M, z * TAG_M);
        group.add(s);
        mats.push(s.material);
        return s;
      });
      return { group, mats, tags, textures };
    };
    const dispose = (b: Built) => {
      world.remove(b.group);
      b.textures.forEach((t) => t.dispose());
      b.mats.forEach((m) => { (m as THREE.SpriteMaterial).map?.dispose?.(); m.dispose(); });
      b.group.traverse((o) => (o as THREE.Mesh).geometry?.dispose?.());
    };

    const homeLine = `This home: ${range(schedule.home.total.low, schedule.home.total.high)} · ${schedule.home.total.lines_priced} of ${schedule.home.total.lines} lines priced`;
    let hud: THREE.Sprite | null = null;
    const setHud = (st: Stop) => {
      if (hud) { scene.remove(hud); (hud.material as THREE.SpriteMaterial).map?.dispose(); hud.material.dispose(); }
      hud = hudSprite(`${st.room} · ${range(st.roomTotal.low, st.roomTotal.high)}`, homeLine);
      scene.add(hud);
    };

    let index = -1, current: Built | null = null, arrived = 0, fadeOutFrom = 0, seenNext = live.current.next;
    let drag = 0, dragPitch = 0, lastX = 0, lastY = 0, dragging = false;
    const devQ = new THREE.Quaternion();

    const go = (i: number) => {
      if (current) dispose(current);
      index = ((i % stops.length) + stops.length) % stops.length;
      const st = stops[index];
      current = build(st);
      world.add(current.group);
      setHud(st);
      // Face the middle of what there is to see: with motion, turn the room to the head; without, the head to the room.
      if (reader.read(devQ)) world.rotation.y = rad(st.facing) + yawOf(devQ);
      else { world.rotation.y = 0; drag = 0; dragPitch = -8; }
      arrived = performance.now();
      fadeOutFrom = 0;
    };
    go(0);

    const down = (e: PointerEvent) => { dragging = true; lastX = e.clientX; lastY = e.clientY; };
    const move = (e: PointerEvent) => {
      if (!dragging) return;
      drag -= (e.clientX - lastX) * 0.18;
      dragPitch = Math.max(-80, Math.min(80, dragPitch + (e.clientY - lastY) * 0.18));
      lastX = e.clientX;
      lastY = e.clientY;
    };
    const upH = () => { dragging = false; };
    el.addEventListener("pointerdown", down);
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", upH);

    const left = new THREE.PerspectiveCamera(), right = new THREE.PerspectiveCamera();
    const resize = () => renderer.setSize(el.clientWidth, el.clientHeight, false);
    resize();
    const watch = new ResizeObserver(resize);
    watch.observe(el);

    let raf = 0;
    const frame = () => {
      raf = requestAnimationFrame(frame);
      const now = performance.now(), here = (now - arrived) / 1000;
      // Next standpoint: by time, or on a tap / key.
      if (live.current.next !== seenNext && !fadeOutFrom) { seenNext = live.current.next; fadeOutFrom = now; }
      if (!fadeOutFrom && here > DWELL_S) fadeOutFrom = now;
      const out = fadeOutFrom ? smooth(clamp((now - fadeOutFrom) / 1000 / FADE_S)) : 0;
      if (fadeOutFrom && out >= 1) { go(index + 1); return; }
      const inn = smooth(clamp(here / FADE_S)) * (1 - out);
      if (current) {
        const n = current.tags.length, first = current.mats.length - n;
        current.mats.forEach((m, i) => {
          const tagIdx = i - first;
          (m as THREE.Material & { opacity: number }).opacity =
            tagIdx < 0 ? inn : inn * smooth(clamp((here - FADE_S - tagIdx * TAG_STAGGER_S) / 0.8));
        });
      }

      if (reader.read(devQ)) camera.quaternion.copy(devQ);
      else camera.rotation.set(rad(dragPitch), rad(-(stops[index].facing + drag)), 0);
      camera.updateMatrixWorld();

      // The strip sits low in the view (about 32 degrees below level), turning with the head but not tilting
      // with it, so it never covers what the tags point at; glance down to read it.
      if (hud) {
        const yaw = yawOf(camera.quaternion);
        hud.position.copy(new THREE.Vector3(0, -1.0, -1.6).applyEuler(new THREE.Euler(0, yaw, 0)));
        (hud.material as THREE.SpriteMaterial).opacity = inn * 0.95;
      }

      const W = el.clientWidth, H = el.clientHeight;
      renderer.setScissorTest(true);
      renderer.setViewport(0, 0, W, H);
      renderer.setScissor(0, 0, W, H);
      renderer.clear();
      if (!live.current.stereo) {
        camera.aspect = W / H;
        camera.fov = 75;
        camera.updateProjectionMatrix();
        renderer.render(scene, camera);
      } else {
        const off = new THREE.Vector3(1, 0, 0).applyQuaternion(camera.quaternion).multiplyScalar(EYES_M / 2);
        [left, right].forEach((eye, i) => {
          eye.fov = 84;
          eye.aspect = W / 2 / H;
          eye.near = 0.05;
          eye.far = 300;
          eye.updateProjectionMatrix();
          eye.quaternion.copy(camera.quaternion);
          eye.position.copy(off).multiplyScalar(i ? 1 : -1);
          eye.updateMatrixWorld();
          renderer.setViewport((i * W) / 2, 0, W / 2, H);
          renderer.setScissor((i * W) / 2, 0, W / 2, H);
          renderer.render(scene, eye);
        });
      }
    };
    frame();

    return () => {
      cancelAnimationFrame(raf);
      watch.disconnect();
      reader.stop();
      el.removeEventListener("pointerdown", down);
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", upH);
      if (current) dispose(current);
      renderer.dispose();
      el.removeChild(renderer.domElement);
    };
  }, [phase, site, scan]);

  if (phase.kind === "loading") return <div className="hs-panel"><p className="hs-quiet">Loading the home…</p></div>;
  if (phase.kind === "error") {
    return (
      <div className="hs-panel" role="alert">
        <h1>This home can't be shown yet</h1>
        <p>{phase.message}</p>
        <button type="button" className="hs-btn" onClick={load}>Try again</button>
      </div>
    );
  }
  if (phase.kind === "signin") {
    return (
      <form className="hs-panel" onSubmit={signIn}>
        <h1>Sign in on this phone</h1>
        <p>This phone needs the owner password once. It stays signed in after that.</p>
        <label className="hs-field">
          <span>Owner password</span>
          <input type="password" autoComplete="current-password" value={secret} onChange={(e) => setSecret(e.target.value)} required />
        </label>
        {phase.error ? <p className="hs-error" role="alert">{phase.error}</p> : null}
        <button type="submit" className="hs-btn" disabled={phase.busy || !secret}>{phase.busy ? "Signing in…" : "Sign in"}</button>
      </form>
    );
  }
  if (phase.kind === "ready") {
    const h = phase.schedule.home;
    return (
      <div className="hs-panel">
        <h1>{phase.schedule.property.name}</h1>
        <p className="hs-sub">{h.name} · {range(h.total.low, h.total.high)} to put back · {phase.stops.reduce((n, s) => n + s.tags.length, 0)} things pinned in {phase.stops.length} places</p>
        <ol className="hs-steps">
          <li>Turn the phone sideways.</li>
          <li>Tap Start{motion === "needs-tap" ? " and allow motion" : ""}.</li>
          <li>Put the phone in the viewer and look around.</li>
        </ol>
        <button type="button" className="hs-btn hs-start" onClick={start}>Start</button>
        <p className="hs-quiet">Each place changes by itself every {DWELL_S} seconds; tap to skip. Scan dated {phase.schedule.property.scan_date ?? "unknown"}. Multiplying this home by the {h.multiplied_by} like it is an extrapolation.</p>
      </div>
    );
  }
  return (
    <div className={`hs-stage${stereo ? " is-stereo" : ""}`} onClick={() => { live.current.next++; }}>
      <div ref={mount} className="hs-canvas" />
      {stereo ? <i className="hs-split" aria-hidden="true" /> : null}
      {motion === "denied" ? <p className="hs-note">Motion is off, so drag to look round. To turn it on, reload and allow motion.</p> : null}
    </div>
  );
}

export default HeadsetView;
