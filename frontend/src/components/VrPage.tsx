import { useEffect, useRef, useState } from "react";
import * as THREE from "three";
import { api } from "../api";
import { costRange, hours } from "../format";
import type { Action, Building, Direction, Scan, Scenario } from "../types";

const BEARING: Record<string, number> = { north: 0, east: 90, south: 180, west: 270 };
const FACE_DISTANCE = 50;
const DWELL_SECONDS = 1.3;
const rad = (deg: number) => (deg * Math.PI) / 180;
/** Unit vector for a compass bearing in scene space: north is -Z, east is +X. */
const toward = (bearing: number, y = 0) => new THREE.Vector3(Math.sin(rad(bearing)), y, -Math.cos(rad(bearing)));

interface Props { id: number; scenario: Scenario; step: string | null }

/** Text drawn onto a canvas and shown as a flat card that always faces the viewer. */
function card(lines: { text: string; size: number; bold?: boolean; color?: string }[], width: number, fill: string): THREE.Sprite {
  const pad = 26, W = 768;
  const canvas = document.createElement("canvas");
  const ctx = canvas.getContext("2d")!;
  const wrapped: { text: string; size: number; bold?: boolean; color?: string }[] = [];
  for (const l of lines) {
    ctx.font = `${l.bold ? 700 : 500} ${l.size}px Barlow, Arial, sans-serif`;
    let row = "";
    for (const word of l.text.split(" ")) {
      if (ctx.measureText(`${row} ${word}`).width > W - 2 * pad && row) { wrapped.push({ ...l, text: row }); row = word; }
      else row = row ? `${row} ${word}` : word;
    }
    if (row) wrapped.push({ ...l, text: row });
  }
  const H = pad * 2 + wrapped.reduce((s, l) => s + l.size * 1.3, 0);
  canvas.width = W; canvas.height = Math.ceil(H);
  ctx.fillStyle = fill; ctx.fillRect(0, 0, W, H);
  let y = pad;
  for (const l of wrapped) {
    ctx.font = `${l.bold ? 700 : 500} ${l.size}px Barlow, Arial, sans-serif`;
    ctx.fillStyle = l.color ?? "#ffffff"; ctx.textBaseline = "top";
    ctx.fillText(l.text, pad, y);
    y += l.size * 1.3;
  }
  const tex = new THREE.CanvasTexture(canvas);
  tex.colorSpace = THREE.SRGBColorSpace;
  const sprite = new THREE.Sprite(new THREE.SpriteMaterial({ map: tex, depthTest: false, transparent: true }));
  sprite.scale.set(width, (width * canvas.height) / W, 1);
  sprite.renderOrder = 5;
  return sprite;
}

/** A round numbered badge marking one action in the space. */
function badge(n: string): THREE.Sprite {
  const canvas = document.createElement("canvas");
  canvas.width = canvas.height = 256;
  const ctx = canvas.getContext("2d")!;
  ctx.fillStyle = "#cf4a1a"; ctx.beginPath(); ctx.arc(128, 128, 116, 0, Math.PI * 2); ctx.fill();
  ctx.lineWidth = 12; ctx.strokeStyle = "#ffffff"; ctx.stroke();
  ctx.fillStyle = "#ffffff"; ctx.font = "700 150px Barlow Condensed, Arial, sans-serif";
  ctx.textAlign = "center"; ctx.textBaseline = "middle"; ctx.fillText(n, 128, 138);
  const tex = new THREE.CanvasTexture(canvas);
  tex.colorSpace = THREE.SRGBColorSpace;
  const sprite = new THREE.Sprite(new THREE.SpriteMaterial({ map: tex, depthTest: false, transparent: true }));
  sprite.scale.set(0.55, 0.55, 1);
  sprite.renderOrder = 5;
  return sprite;
}

function disc(color: number, radius: number, opacity = 0.9): THREE.Mesh {
  const m = new THREE.Mesh(new THREE.RingGeometry(radius * 0.55, radius, 40),
    new THREE.MeshBasicMaterial({ color, transparent: true, opacity, depthTest: false, side: THREE.DoubleSide }));
  m.renderOrder = 4;
  return m;
}

export function VrPage({ id, scenario, step }: Props) {
  const mount = useRef<HTMLDivElement>(null);
  const [b, setB] = useState<Building | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [started, setStarted] = useState(false);
  const [stereo, setStereo] = useState(() => window.matchMedia("(pointer: coarse)").matches);
  const [where, setWhere] = useState("");
  const live = useRef({ stereo, started });
  live.current = { stereo, started };
  const control = useRef<{ recenter: () => void } | null>(null);

  useEffect(() => { api.building(id, scenario.id, step).then(setB).catch((e) => setError(e.message)); }, [id, scenario.id, step]);

  useEffect(() => {
    const el = mount.current;
    if (!el || !b) return;
    const actions: Action[] = (b.plan?.actions ?? []).filter((a) => a.interior);
    const scans = b.scans.filter((s) => s.sweeps.length > 0);
    if (scans.length === 0) { setError("No space in this building has been scanned, so there is nothing to stand in."); return; }

    const renderer = new THREE.WebGLRenderer({ antialias: true });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.autoClear = false;
    el.appendChild(renderer.domElement);
    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(88, 1, 0.05, 200);
    camera.rotation.order = "YXZ";
    scene.add(camera);
    const world = new THREE.Group();   // everything that belongs to the space; turning it re-centres the view
    scene.add(world);
    const faces = new THREE.Group();
    const things = new THREE.Group();  // markers, cards and stepping spots for the current position
    world.add(faces, things);

    const reticle = disc(0xffffff, 0.012, 0.95);
    reticle.position.z = -1;
    const progress = new THREE.Mesh(new THREE.RingGeometry(0.016, 0.021, 40, 1, 0, 0.001),
      new THREE.MeshBasicMaterial({ color: 0xff8a4d, depthTest: false, transparent: true }));
    progress.position.z = -1; progress.renderOrder = 6;
    camera.add(reticle, progress);
    let hud: THREE.Sprite | null = null;
    const setHud = (scan: Scan) => {
      if (hud) camera.remove(hud);
      const t = b.threat;
      hud = card([{ text: `${t.name}: ${t.hours_left != null ? `about ${hours(t.hours_left)} left` : t.label ?? ""}`, size: 34, bold: true, color: "#ffb38f" },
        { text: `${b.record.name}, ${scan.name}`, size: 28 }], 0.9, "rgba(11,21,34,0.78)");
      hud.position.set(0, -0.62, -1.4);
      camera.add(hud);
    };

    const loader = new THREE.TextureLoader();
    let current: { scan: Scan; sweepId: string; heading: number } | null = null;
    let targets: { object: THREE.Object3D; act: () => void }[] = [];
    let openCard: THREE.Sprite | null = null;
    let selectedAction: string | null = null;

    const buildFaces = (scan: Scan, sweepId: string, heading: number) => {
      const size = FACE_DISTANCE * 2.002;
      const next = new THREE.Group();
      const plane = (face: number) => {
        const tex = loader.load(`/api/buildings/${id}/pano/${scan.id}/${sweepId}/${face}.jpg?size=1024`);
        tex.colorSpace = THREE.SRGBColorSpace;
        const mesh = new THREE.Mesh(new THREE.PlaneGeometry(size, size), new THREE.MeshBasicMaterial({ map: tex, depthTest: false }));
        mesh.renderOrder = 0;
        return mesh;
      };
      // Sides: face 1 looks along the sweep's heading; 2, 3 and 4 each turn a further 90 degrees clockwise.
      for (let k = 0; k < 4; k++) {
        const pivot = new THREE.Group();
        const m = plane(k + 1);
        m.position.z = -FACE_DISTANCE;
        pivot.add(m);
        pivot.rotation.y = -rad(heading + 90 * k);
        next.add(pivot);
      }
      // Up (face 0): its bottom edge joins the top of face 1. Down (face 5): its top edge joins the bottom of face 1.
      const caps = new THREE.Group();
      const up = plane(0); up.position.y = FACE_DISTANCE; up.rotation.x = Math.PI / 2;
      const down = plane(5); down.position.y = -FACE_DISTANCE; down.rotation.x = -Math.PI / 2;
      caps.add(up, down);
      caps.rotation.y = -rad(heading);
      next.add(caps);
      faces.clear();
      faces.add(next);
    };

    const lookBearing = () => {
      const f = new THREE.Vector3(0, 0, -1).applyQuaternion(camera.quaternion);
      return (((THREE.MathUtils.radToDeg(Math.atan2(f.x, -f.z) + world.rotation.y)) % 360) + 360) % 360;
    };
    /** Turn the space so the given compass bearing is straight ahead of wherever the viewer is facing. */
    const faceBearing = (bearing: number) => {
      const f = new THREE.Vector3(0, 0, -1).applyQuaternion(camera.quaternion);
      world.rotation.y = rad(bearing) - Math.atan2(f.x, -f.z);
    };

    const go = (scan: Scan, sweepId: string, bearing?: number | null) => {
      const sweep = scan.sweeps.find((s) => s.id === sweepId) ?? scan.sweeps[0];
      const heading = sweep.heading ?? 0;
      current = { scan, sweepId: sweep.id, heading };
      buildFaces(scan, sweep.id, heading);
      setHud(scan);
      setWhere(scan.name);
      things.clear();
      targets = [];
      openCard = null;
      // Actions the plan pinned to this position.
      for (const a of actions.filter((x) => x.interior!.scan_id === scan.id && x.interior!.sweep_id === sweep.id)) {
        const d: Direction = a.interior!.direction;
        const at = d === "up" ? new THREE.Vector3(0.3, 2.2, -0.6) : d === "down" ? new THREE.Vector3(0.3, -1.3, -0.9)
          : toward(a.interior!.bearing ?? BEARING[d] ?? heading).multiplyScalar(3.2);
        const pin = badge(a.id.replace("A", ""));
        pin.position.copy(at);
        things.add(pin);
        targets.push({ object: pin, act: () => {
          if (openCard) things.remove(openCard);
          openCard = card([
            { text: a.title, size: 40, bold: true },
            { text: a.why, size: 30, color: "#d5dde7" },
            { text: `${a.crew}. ${a.hours_of_work} h. ${costRange(a.cost_low, a.cost_high)}.`, size: 30, bold: true, color: "#ffb38f" },
          ], 2.4, "rgba(11,21,34,0.9)");
          openCard.position.copy(at).add(new THREE.Vector3(0, 1.05, 0));
          things.add(openCard);
          selectedAction = a.id;
        } });
      }
      // Stepping spots: nearby scan positions, drawn on the floor in their true direction.
      if (sweep.lon != null && sweep.lat != null) {
        const kx = 111_320 * Math.cos(rad(sweep.lat));
        const near = scan.sweeps.filter((s) => s.id !== sweep.id && s.lon != null && s.lat != null)
          .map((s) => ({ s, e: (s.lon! - sweep.lon!) * kx, n: (s.lat! - sweep.lat!) * 111_320 }))
          .map((x) => ({ ...x, d: Math.hypot(x.e, x.n) })).filter((x) => x.d > 0.7 && x.d < 7).sort((p, q) => p.d - q.d).slice(0, 6);
        for (const x of near) {
          const spot = disc(0x7fb4ff, 0.3, 0.85);
          spot.position.set(x.e, -1.35, -x.n);
          spot.rotation.x = -Math.PI / 2;
          things.add(spot);
          targets.push({ object: spot, act: () => go(scan, x.s.id) });
        }
      }
      if (bearing != null) faceBearing(bearing);
    };
    control.current = { recenter: () => { if (current) faceBearing(current.heading); } };

    // Head tracking from the phone's motion sensors, with drag-to-look as the desktop fallback.
    let drag: { x: number; y: number } | null = null;
    let yaw = 0, pitch = 0, sensor = false;
    const zee = new THREE.Vector3(0, 0, 1), euler = new THREE.Euler(), q0 = new THREE.Quaternion();
    const q1 = new THREE.Quaternion(-Math.sqrt(0.5), 0, 0, Math.sqrt(0.5));
    const onOrient = (e: DeviceOrientationEvent) => {
      if (e.alpha == null || e.beta == null || e.gamma == null) return;
      sensor = true;
      const orient = rad((screen.orientation?.angle ?? (window as unknown as { orientation?: number }).orientation ?? 0) as number);
      euler.set(rad(e.beta), rad(e.alpha), -rad(e.gamma), "YXZ");
      camera.quaternion.setFromEuler(euler).multiply(q1).multiply(q0.setFromAxisAngle(zee, -orient));
    };
    const down = (e: PointerEvent) => { drag = { x: e.clientX, y: e.clientY }; };
    const move = (e: PointerEvent) => {
      if (!drag || sensor) return;
      yaw += (e.clientX - drag.x) * 0.25; pitch = Math.max(-85, Math.min(85, pitch + (e.clientY - drag.y) * 0.25));
      drag = { x: e.clientX, y: e.clientY };
      camera.rotation.set(rad(pitch), rad(yaw), 0);
    };
    const upPtr = () => { drag = null; };
    window.addEventListener("deviceorientation", onOrient);
    renderer.domElement.addEventListener("pointerdown", down);
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", upPtr);

    const resize = () => renderer.setSize(el.clientWidth, el.clientHeight);
    resize();
    window.addEventListener("resize", resize);

    // Start where the plan has something to show, otherwise in the first scanned space.
    const first = actions[0]?.interior;
    const startScan = (first && scans.find((s) => s.id === first.scan_id)) || scans[0];
    go(startScan, first?.sweep_id ?? startScan.sweeps[0].id, first?.bearing ?? null);

    // Follow the laptop, and tell it where the headset is looking.
    let rev = -1;
    const link = window.setInterval(async () => {
      try {
        const t = await fetch("/api/vr/target").then((r) => r.json());
        if (rev === -1) rev = t.rev;
        else if (t.rev !== rev) {
          rev = t.rev;
          const scan = scans.find((s) => s.id === t.scan_id);
          if (t.building === id && scan) go(scan, t.sweep_id ?? scan.sweeps[0].id, t.bearing ?? null);
        }
        if (current && live.current.started) {
          fetch("/api/vr/pose", { method: "POST", headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ building: id, scan_id: current.scan.id, sweep_id: current.sweepId, bearing: lookBearing(), action_id: selectedAction }) }).catch(() => {});
        }
      } catch { /* the laptop is unreachable for a moment; keep showing the space */ }
    }, 600);

    const ray = new THREE.Raycaster();
    const clock = new THREE.Clock();
    let gazed: THREE.Object3D | null = null, held = 0, raf = 0;
    const frame = () => {
      raf = requestAnimationFrame(frame);
      const dt = clock.getDelta();
      ray.setFromCamera(new THREE.Vector2(0, 0), camera);
      const hit = ray.intersectObjects(targets.map((t) => t.object), false)[0]?.object ?? null;
      if (hit !== gazed) { gazed = hit; held = 0; }
      else if (hit) {
        held += dt;
        if (held >= DWELL_SECONDS) { held = -1e6; targets.find((t) => t.object === hit)?.act(); }
      }
      const arc = hit && held > 0 ? Math.min(1, held / DWELL_SECONDS) * Math.PI * 2 : 0.001;
      progress.geometry.dispose();
      progress.geometry = new THREE.RingGeometry(0.016, 0.021, 40, 1, 0, arc);

      const w = el.clientWidth, h = el.clientHeight;
      renderer.setScissorTest(true);
      const eyes = live.current.stereo ? [[0, w / 2], [w / 2, w / 2]] : [[0, w]];
      camera.aspect = eyes[0][1] / h;
      camera.updateProjectionMatrix();
      for (const [x, ww] of eyes) {
        renderer.setViewport(x, 0, ww, h);
        renderer.setScissor(x, 0, ww, h);
        renderer.clear();
        renderer.render(scene, camera);
      }
    };
    frame();

    return () => {
      cancelAnimationFrame(raf);
      window.clearInterval(link);
      window.removeEventListener("deviceorientation", onOrient);
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", upPtr);
      window.removeEventListener("resize", resize);
      renderer.dispose();
      el.removeChild(renderer.domElement);
    };
  }, [b, id]);

  const start = async () => {
    // iOS only hands over motion data after a tap and an explicit yes.
    const ask = (DeviceOrientationEvent as unknown as { requestPermission?: () => Promise<string> }).requestPermission;
    if (ask) { try { await ask(); } catch { /* denied: drag-to-look still works */ } }
    try { await document.documentElement.requestFullscreen?.(); } catch { /* not available on iPhone */ }
    try { await (navigator as unknown as { wakeLock?: { request: (t: string) => Promise<unknown> } }).wakeLock?.request("screen"); } catch { /* optional */ }
    setStarted(true);
  };

  if (error) return <div className="fatal">{error}</div>;
  return (
    <div className="vr">
      <div className="vr-canvas" ref={mount} />
      {!b && <div className="vr-gate"><p>Loading the scanned space…</p></div>}
      {b && !started && (
        <div className="vr-gate">
          <h1>{b.record.name}</h1>
          <p>Turn the phone sideways, press Start, then put it in the headset. Look at a blue spot on the floor to walk there. Look at an orange number to read that action.</p>
          <button className="primary" onClick={start}>Start</button>
          <label><input type="checkbox" checked={stereo} onChange={(e) => setStereo(e.target.checked)} /> Split the screen for a headset</label>
        </div>
      )}
      {b && started && !stereo && (
        <div className="vr-bar">
          <span>{where}</span>
          <button onClick={() => control.current?.recenter()}>Face the scan's front</button>
          <button onClick={() => setStereo(true)}>Headset view</button>
        </div>
      )}
    </div>
  );
}
