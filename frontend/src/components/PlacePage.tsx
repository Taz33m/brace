import { useEffect, useRef, useState } from "react";
import * as THREE from "three";
import { api } from "../api";
import type { Place, PlaceAnswer, PlacePosition } from "../types";
import { openVoice } from "../voice";
import type { Voice } from "../voice";

/**
 * Standing inside a scanned building and asking the way. You look around, ask where something is, and the
 * way is drawn on the floor in front of you: follow the marks, look at the next ring to walk to it. The
 * small plan at the lower left shows the whole route and where you are on it.
 */
const FACE_M = 50, EYE_M = 1.4, DWELL_S = 1.0, REACH_M = 16;
const BLUE = 0x00b0e6, WHITE = 0xffffff;
const rad = (deg: number) => (deg * Math.PI) / 180;
const toward = (bearing: number, flat: number, y: number) => new THREE.Vector3(Math.sin(rad(bearing)) * flat, y, -Math.cos(rad(bearing)) * flat);

/** Compass bearing from one scan position to another, from where the scan sits on the map. */
function bearing(a: PlacePosition, b: PlacePosition): number | null {
  if (a.lon == null || a.lat == null || b.lon == null || b.lat == null) return null;
  const east = (b.lon - a.lon) * Math.cos(rad(a.lat));
  return ((THREE.MathUtils.radToDeg(Math.atan2(east, b.lat - a.lat)) % 360) + 360) % 360;
}

function words(text: string, size: number, color = "#ffffff", fill = "rgba(11, 21, 34, 0.82)", width = 0.9): THREE.Sprite {
  const W = 900, pad = 28;
  const canvas = document.createElement("canvas"), ctx = canvas.getContext("2d")!;
  ctx.font = `600 ${size}px Barlow, Arial, sans-serif`;
  const rows: string[] = [];
  let row = "";
  for (const word of text.split(" ")) {
    if (ctx.measureText(`${row} ${word}`).width > W - 2 * pad && row) { rows.push(row); row = word; } else row = row ? `${row} ${word}` : word;
  }
  if (row) rows.push(row);
  canvas.width = W; canvas.height = Math.ceil(pad * 2 + rows.length * size * 1.3);
  ctx.fillStyle = fill; ctx.fillRect(0, 0, W, canvas.height);
  ctx.font = `600 ${size}px Barlow, Arial, sans-serif`; ctx.fillStyle = color; ctx.textBaseline = "top";
  rows.forEach((r, i) => ctx.fillText(r, pad, pad + i * size * 1.3));
  const tex = new THREE.CanvasTexture(canvas);
  tex.colorSpace = THREE.SRGBColorSpace;
  const sprite = new THREE.Sprite(new THREE.SpriteMaterial({ map: tex, depthTest: false, transparent: true }));
  sprite.scale.set(width, (width * canvas.height) / W, 1);
  sprite.renderOrder = 8;
  return sprite;
}

export function PlacePage({ model }: { model: string }) {
  const [place, setPlace] = useState<Place | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [started, setStarted] = useState(false);
  const [stereo, setStereo] = useState(() => window.matchMedia("(pointer: coarse)").matches);
  const [voiceReady, setVoiceReady] = useState(false);
  const [typed, setTyped] = useState("");
  const [last, setLast] = useState<PlaceAnswer | null>(null);
  const mount = useRef<HTMLDivElement>(null);
  const live = useRef({ stereo });
  live.current.stereo = stereo;
  const control = useRef<{ ask: (query: string) => Promise<PlaceAnswer> } | null>(null);
  const voice = useRef<Voice | null>(null);

  useEffect(() => { api.place(model).then(setPlace).catch((e) => setError(e.message)); }, [model]);
  useEffect(() => { api.config().then((c) => setVoiceReady(c.voice_ready)).catch(() => setVoiceReady(false)); }, []);
  useEffect(() => () => { voice.current?.close(); voice.current = null; }, []);

  useEffect(() => {
    const el = mount.current;
    if (!el || !place) return;
    const at = new Map(place.positions.map((p) => [p.id, p]));
    const renderer = new THREE.WebGLRenderer({ antialias: true });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.setSize(el.clientWidth, el.clientHeight);
    renderer.autoClear = false;
    el.appendChild(renderer.domElement);
    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(88, 1, 0.05, 400);
    camera.rotation.order = "YXZ";
    scene.add(camera);
    const faces = new THREE.Group(), marks = new THREE.Group();
    scene.add(faces, marks);
    const loader = new THREE.TextureLoader();
    const reticle = new THREE.Mesh(new THREE.CircleGeometry(0.012, 24), new THREE.MeshBasicMaterial({ color: WHITE, depthTest: false, transparent: true, opacity: 0.95 }));
    reticle.position.z = -1; reticle.renderOrder = 9;
    const progress = new THREE.Mesh(new THREE.RingGeometry(0.016, 0.021, 40, 1, 0, 0.001), new THREE.MeshBasicMaterial({ color: BLUE, depthTest: false, transparent: true }));
    progress.position.z = -1; progress.renderOrder = 9;
    camera.add(reticle, progress);

    // You start upstairs if there is an upstairs: the top level's first position.
    const top = Math.max(...place.levels.map((l) => l.level));
    let here = place.positions.find((p) => p.level === top) ?? place.positions[0];
    let way: string[] = [];
    let answer: PlaceAnswer | null = null;
    let targets: { object: THREE.Object3D; go: string }[] = [];
    let caption: THREE.Sprite | null = null, captionUntil = 0, plan: THREE.Sprite | null = null;

    const say = (text: string, seconds = 9) => {
      if (caption) camera.remove(caption);
      caption = words(text, 40);
      caption.position.set(0, -0.36, -1);
      camera.add(caption);
      captionUntil = performance.now() + seconds * 1000;
    };

    // The plan at the lower left: the rooms of the level you are on, the route, where it ends and where you are.
    const drawPlan = () => {
      if (plan) camera.remove(plan);
      const S = 420, canvas = document.createElement("canvas"), ctx = canvas.getContext("2d")!;
      canvas.width = canvas.height = S;
      const xs = place.positions.map((p) => p.x), ys = place.positions.map((p) => p.y);
      const pad = 6, minX = Math.min(...xs) - pad, maxX = Math.max(...xs) + pad, minY = Math.min(...ys) - pad, maxY = Math.max(...ys) + pad;
      const k = (S - 40) / Math.max(maxX - minX, maxY - minY);
      const px = (p: { x: number; y: number }) => [20 + (p.x - minX) * k, S - 20 - (p.y - minY) * k] as [number, number];
      ctx.fillStyle = "rgba(11, 21, 34, 0.78)"; ctx.fillRect(0, 0, S, S);
      const goal = answer?.room ? at.get(answer.room.position_id) : null;
      for (const p of place.positions) {
        const [x, y] = px(p);
        ctx.fillStyle = p.level === here.level ? "rgba(255,255,255,0.5)" : "rgba(255,255,255,0.16)";
        ctx.beginPath(); ctx.arc(x, y, 3, 0, Math.PI * 2); ctx.fill();
      }
      if (way.length > 1) {
        ctx.strokeStyle = "#00b0e6"; ctx.lineWidth = 5; ctx.lineJoin = "round"; ctx.lineCap = "round"; ctx.beginPath();
        way.forEach((id, i) => { const [x, y] = px(at.get(id)!); if (i) ctx.lineTo(x, y); else ctx.moveTo(x, y); });
        ctx.stroke();
      }
      if (goal) { const [x, y] = px(goal); ctx.strokeStyle = "#00b0e6"; ctx.lineWidth = 4; ctx.beginPath(); ctx.arc(x, y, 13, 0, Math.PI * 2); ctx.stroke(); ctx.fillStyle = "#00b0e6"; ctx.beginPath(); ctx.arc(x, y, 5, 0, Math.PI * 2); ctx.fill(); }
      const [hx, hy] = px(here);
      ctx.fillStyle = "#ffffff"; ctx.beginPath(); ctx.arc(hx, hy, 8, 0, Math.PI * 2); ctx.fill();
      ctx.strokeStyle = "#0b1522"; ctx.lineWidth = 3; ctx.stroke();
      ctx.font = "600 22px Barlow, Arial, sans-serif"; ctx.fillStyle = "#ffffff"; ctx.textBaseline = "top";
      ctx.fillText(place.levels.find((l) => l.level === here.level)?.label ?? "", 14, 12);
      const tex = new THREE.CanvasTexture(canvas);
      tex.colorSpace = THREE.SRGBColorSpace;
      plan = new THREE.Sprite(new THREE.SpriteMaterial({ map: tex, depthTest: false, transparent: true }));
      plan.scale.set(0.34, 0.34, 1); plan.position.set(-0.52, -0.3, -1); plan.renderOrder = 8;
      camera.add(plan);
    };

    const ring = (color: number, inner: number, outer: number, opacity: number) => {
      const m = new THREE.Mesh(new THREE.RingGeometry(inner, outer, 48).rotateX(-Math.PI / 2), new THREE.MeshBasicMaterial({ color, depthTest: false, transparent: true, opacity, side: THREE.DoubleSide }));
      m.renderOrder = 4;
      return m;
    };
    /** The whole of a ring counts as looking at it, hole included: a clear disc the same size takes the gaze. */
    const catcher = (radius: number) => {
      const m = new THREE.Mesh(new THREE.CircleGeometry(radius, 32).rotateX(-Math.PI / 2), new THREE.MeshBasicMaterial({ transparent: true, opacity: 0, depthTest: false, side: THREE.DoubleSide }));
      m.renderOrder = 3;
      return m;
    };
    /** Where another position is, seen from here: straight ahead by compass, as far as it is, and as much lower or higher. */
    const spot = (to: PlacePosition): THREE.Vector3 | null => {
      const b = bearing(here, to);
      if (b == null) return null;
      const flat = Math.hypot(to.x - here.x, to.y - here.y);
      return toward(b, Math.min(flat, REACH_M), -EYE_M + (to.z - here.z) * Math.min(1, REACH_M / Math.max(flat, 0.01)));
    };

    const draw = () => {
      faces.clear(); marks.clear(); targets = [];
      const heading = here.heading ?? 0, size = FACE_M * 2.002;
      const face = (n: number) => {
        const tex = loader.load(api.placePano(model, here.id, n));
        tex.colorSpace = THREE.SRGBColorSpace;
        const mesh = new THREE.Mesh(new THREE.PlaneGeometry(size, size), new THREE.MeshBasicMaterial({ map: tex, depthTest: false }));
        mesh.renderOrder = 0;
        return mesh;
      };
      // Sides: face 1 looks along the position's heading; 2, 3 and 4 each turn a further 90 degrees clockwise.
      for (let k = 0; k < 4; k++) {
        const pivot = new THREE.Group(), m = face(k + 1);
        m.position.z = -FACE_M; pivot.add(m); pivot.rotation.y = -rad(heading + 90 * k); faces.add(pivot);
      }
      const caps = new THREE.Group(), up = face(0), down = face(5);
      up.position.y = FACE_M; up.rotation.x = Math.PI / 2; down.position.y = -FACE_M; down.rotation.x = -Math.PI / 2;
      caps.add(up, down); caps.rotation.y = -rad(heading); faces.add(caps);

      const i = way.indexOf(here.id), next = i >= 0 && i < way.length - 1 ? at.get(way[i + 1])! : null;
      // The way: marks on the floor to the next position, and a ring there to look at.
      if (next) {
        const end = spot(next);
        if (end) {
          const steps = Math.max(3, Math.round(end.length() / 0.9));
          for (let s = 2; s < steps; s++) {
            const dot = new THREE.Mesh(new THREE.CircleGeometry(0.11, 20).rotateX(-Math.PI / 2), new THREE.MeshBasicMaterial({ color: BLUE, depthTest: false, transparent: true, opacity: 0.9 }));
            dot.position.copy(end).multiplyScalar(s / steps); dot.position.y = -EYE_M + (end.y + EYE_M) * (s / steps); dot.renderOrder = 4;
            marks.add(dot);
          }
          const target = ring(BLUE, 0.34, 0.5, 1), take = catcher(0.62);
          target.position.copy(end); take.position.copy(end);
          marks.add(target, take);
          targets.push({ object: take, go: next.id });
          const change = next.level !== here.level ? ((next.level ?? 0) < (here.level ?? 0) ? "Down one level" : "Up one level") : null;
          if (change) { const tag = words(change, 44, "#ffffff", "rgba(0, 84, 166, 0.9)", 1.6); tag.position.copy(end).setY(end.y + 1.0); marks.add(tag); }
        }
      }
      // Anywhere else you can walk from here: the nearest few positions this one sees, drawn quietly.
      const near = here.sees.map((id) => at.get(id)!).filter((p) => p && p.id !== next?.id)
        .sort((a, b) => Math.hypot(a.x - here.x, a.y - here.y) - Math.hypot(b.x - here.x, b.y - here.y)).slice(0, 6);
      for (const p of near) {
        const v = spot(p);
        if (!v) continue;
        const r = ring(WHITE, 0.2, 0.28, 0.5), take = catcher(0.34);
        r.position.copy(v); take.position.copy(v);
        marks.add(r, take);
        targets.push({ object: take, go: p.id });
      }
      // You have arrived when you stand in the room that was asked for.
      if (answer?.room && here.room_id === answer.room.id && i === way.length - 1) {
        const sign = words(answer.place ?? answer.room.type, 64, "#ffffff", "rgba(0, 84, 166, 0.92)", 2.6);
        sign.position.copy(toward(here.heading ?? 0, 3.2, 0.5));
        marks.add(sign);
      }
      drawPlan();
    };

    const go = (id: string) => {
      const to = at.get(id);
      if (!to) return;
      here = to;
      draw();
      const i = way.indexOf(id);
      if (answer?.room && i === way.length - 1 && way.length > 1) say(`You are at ${answer.place ?? answer.room.type}.`, 7);
    };

    control.current = {
      ask: async (query: string) => {
        const got = await api.placeFind(model, query, here.id);
        answer = got.found ? got : null;
        way = got.route?.positions ?? [];
        setLast(got);
        say(got.say);
        draw();
        return got;
      },
    };

    // Looking around: the phone's own sense of direction in a headset, a drag anywhere else.
    let drag: { x: number; y: number } | null = null, yaw = 0, pitch = 0, sensor = false, moved = 0;
    const zee = new THREE.Vector3(0, 0, 1), euler = new THREE.Euler(), q0 = new THREE.Quaternion();
    const q1 = new THREE.Quaternion(-Math.sqrt(0.5), 0, 0, Math.sqrt(0.5));
    const onOrient = (e: DeviceOrientationEvent) => {
      if (e.alpha == null || e.beta == null || e.gamma == null) return;
      sensor = true;
      const orient = rad((screen.orientation?.angle ?? (window as unknown as { orientation?: number }).orientation ?? 0) as number);
      euler.set(rad(e.beta), rad(e.alpha), -rad(e.gamma), "YXZ");
      camera.quaternion.setFromEuler(euler).multiply(q1).multiply(q0.setFromAxisAngle(zee, -orient));
    };
    const down = (e: PointerEvent) => { drag = { x: e.clientX, y: e.clientY }; moved = 0; };
    const move = (e: PointerEvent) => {
      if (!drag || sensor) return;
      moved += Math.abs(e.clientX - drag.x) + Math.abs(e.clientY - drag.y);
      yaw += (e.clientX - drag.x) * 0.25; pitch = Math.max(-85, Math.min(85, pitch + (e.clientY - drag.y) * 0.25));
      drag = { x: e.clientX, y: e.clientY };
      camera.rotation.set(rad(pitch), rad(yaw), 0);
    };
    const ray = new THREE.Raycaster();
    const up = (e: PointerEvent) => {
      // A tap, not a drag, on a ring walks there: the same as looking at it in the headset.
      if (drag && moved < 6 && !live.current.stereo) {
        const box = renderer.domElement.getBoundingClientRect();
        ray.setFromCamera(new THREE.Vector2(((e.clientX - box.left) / box.width) * 2 - 1, -((e.clientY - box.top) / box.height) * 2 + 1), camera);
        const hit = ray.intersectObjects(targets.map((t) => t.object), false)[0]?.object;
        const t = hit && targets.find((x) => x.object === hit);
        if (t) go(t.go);
      }
      drag = null;
    };
    window.addEventListener("deviceorientation", onOrient);
    renderer.domElement.addEventListener("pointerdown", down);
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
    const resize = () => renderer.setSize(el.clientWidth, el.clientHeight);
    window.addEventListener("resize", resize);

    draw();
    const clock = new THREE.Clock();
    let gazed: THREE.Object3D | null = null, held = 0, raf = 0;
    const frame = () => {
      raf = requestAnimationFrame(frame);
      const dt = clock.getDelta(), now = performance.now();
      scene.updateMatrixWorld();
      ray.setFromCamera(new THREE.Vector2(0, 0), camera);
      const hit = ray.intersectObjects(targets.map((t) => t.object), false)[0]?.object ?? null;
      if (hit !== gazed) { gazed = hit; held = 0; }
      else if (hit) {
        held += dt;
        if (held >= DWELL_S) { held = -1e6; const t = targets.find((x) => x.object === hit); if (t) go(t.go); }
      }
      progress.geometry.dispose();
      progress.geometry = new THREE.RingGeometry(0.016, 0.021, 40, 1, 0, hit && held > 0 ? Math.min(1, held / DWELL_S) * Math.PI * 2 : 0.001);
      if (caption && now > captionUntil) { camera.remove(caption); caption = null; }
      const w = el.clientWidth, h = el.clientHeight;
      renderer.setScissorTest(true);
      const eyes = live.current.stereo ? [[0, w / 2], [w / 2, w / 2]] : [[0, w]];
      camera.aspect = eyes[0][1] / h;
      camera.updateProjectionMatrix();
      // The plan keeps to the lower left corner of whatever shape the view is.
      if (plan) { const half = Math.tan(rad(camera.fov / 2)); plan.position.set(-(half * camera.aspect - 0.25), -(half - 0.3), -1); }
      for (const [x, ww] of eyes) {
        renderer.setViewport(x, 0, ww, h); renderer.setScissor(x, 0, ww, h);
        renderer.clear(); renderer.render(scene, camera);
      }
    };
    frame();
    return () => {
      cancelAnimationFrame(raf);
      window.removeEventListener("deviceorientation", onOrient);
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
      window.removeEventListener("resize", resize);
      control.current = null;
      renderer.dispose();
      el.removeChild(renderer.domElement);
    };
  }, [place, model]);

  const start = async () => {
    // iOS only hands over motion data after a tap and an explicit yes.
    const ask = (DeviceOrientationEvent as unknown as { requestPermission?: () => Promise<string> }).requestPermission;
    if (ask) { try { await ask(); } catch { /* denied: drag-to-look still works */ } }
    try { await document.documentElement.requestFullscreen?.(); } catch { /* not available on iPhone */ }
    setStarted(true);
    if (voice.current || !voiceReady) return;
    voice.current = await openVoice({
      sessionUrl: `/api/places/${model}/voice`,
      run: async (name, args) => (name === "find_place" && control.current ? control.current.ask(String(args.query ?? "")) : { found: false, say: "I cannot do that here." }),
      onState: () => {},
      onCaption: () => {},
      greeting: `Greet the person in one short sentence and tell them they can ask where anything in ${place?.name ?? "the building"} is.`,
    }, true);
  };

  if (error) return <div className="fatal" role="alert">{error}</div>;
  return (
    <div className="vr">
      <div className="vr-canvas" ref={mount} />
      {!place && <div className="vr-gate"><p>Loading the building…</p></div>}
      {place && !started && (
        <div className="vr-gate">
          <h1>{place.name}</h1>
          <p>Turn the phone sideways, press Start, then put it in the headset. Ask where something is. The way is drawn on the floor: look at the blue ring to walk to it.</p>
          <button className="primary" onClick={start}>Start</button>
          <label><input type="checkbox" checked={stereo} onChange={(e) => setStereo(e.target.checked)} /> Split the screen for a headset</label>
        </div>
      )}
      {place && started && !stereo && (
        <form className="vr-bar" onSubmit={(e) => { e.preventDefault(); if (typed.trim()) { void control.current?.ask(typed.trim()); setTyped(""); } }}>
          <input value={typed} onChange={(e) => setTyped(e.target.value)} placeholder="Where is the git push-up challenge?" aria-label="Ask where something is" />
          <button>Ask</button>
          <span>{last ? (last.found && last.route ? `${last.route.metres} m` : "") : voiceReady ? "Or just ask aloud" : ""}</span>
          <button type="button" onClick={() => setStereo(true)}>Headset view</button>
        </form>
      )}
    </div>
  );
}
