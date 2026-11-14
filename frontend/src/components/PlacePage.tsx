import { useEffect, useRef, useState } from "react";
import * as THREE from "three";
import { api } from "../api";
import type { Place, PlaceAnswer, PlacePosition } from "../types";
import { openVoice } from "../voice";
import type { Voice } from "../voice";

/**
 * Standing inside a scanned building and asking the way. You look around, ask where something is, and the
 * way is drawn on the floor in front of you: follow the marks, look at the next ring or tap to walk to it. A way
 * worked out for a wheelchair walks itself. The small plan at the lower left shows the whole route and where you
 * are on it.
 */
const FACE_M = 50, EYE_M = 1.4, DWELL_S = 1.0, REACH_M = 16;
// Walking by itself: time to read the way first, then a position every STEP_S, a little longer before a lift or
// stairs so the sign over it is read before it is taken. Each step waits for its pictures, which fade in over
// FADE_S and then hold for the rest of SETTLE_S. A pointer that moves less than TAP_PX is a tap, not a drag.
const FIRST_S = 2.5, STEP_S = 1.8, LEVEL_S = 1.0, FADE_S = 0.8, SETTLE_S = 1.1, TAP_PX = 6;
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

/** What to put in front of someone's eyes: the place, then the way in as few words as carry it. The voice says the rest. */
function brief(got: PlaceAnswer): string {
  if (!got.found) return got.say;
  const way = got.route;
  if (!way) return got.no_way ? `${got.place}. No step-free way in this scan.` : `${got.event ? `${got.event} is at ${got.place}` : got.place}.`;
  const metres = `${Math.round(way.metres)} m`;
  if (got.mover === "wheelchair") {
    const how = got.changed ? `By the lift instead of the stairs` : way.lift ? "By the lift" : "Step-free";
    const tight = way.narrowest_passage_m != null ? ` Narrowest point ${way.narrowest_passage_m.toFixed(1)} m; chair ${got.chair_width_in ?? 27} in.` : "";
    return `${how}: ${metres}, no steps.${tight}`;
  }
  const down = way.legs.filter((g) => g.kind === "stairs").reduce((sum, g) => sum + g.rise_m, 0) < 0;
  const how = way.stairs ? `, ${down ? "down" : "up"} ${way.stairs.flights} flight${way.stairs.flights === 1 ? "" : "s"} of stairs` : way.lift ? ", by the lift" : "";
  return `${got.event ? `${got.event} is at ${got.place}` : got.place}. ${metres}${how}.`;
}

const USES_A_CHAIR = /wheel\s*chair|can(?:'|no)?t (?:take|use|do|climb) (?:the )?stairs|step[- ]free|no stairs/i;

export function PlacePage({ model, watch = false }: { model: string; watch?: boolean }) {
  const [place, setPlace] = useState<Place | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [started, setStarted] = useState(watch);
  const [stereo, setStereo] = useState(() => !watch && window.matchMedia("(pointer: coarse)").matches);
  const [mover, setMover] = useState<"walking" | "wheelchair">("walking");
  const [voiceReady, setVoiceReady] = useState(false);
  const [typed, setTyped] = useState("");
  const [last, setLast] = useState<PlaceAnswer | null>(null);
  const mount = useRef<HTMLDivElement>(null);
  const live = useRef({ stereo });
  live.current.stereo = stereo;
  const control = useRef<{ ask: (query: string) => Promise<PlaceAnswer | { say: string }>; moveBy: (mover: "walking" | "wheelchair", chairIn?: number) => Promise<PlaceAnswer | { say: string }> } | null>(null);
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
    const marks = new THREE.Group();
    scene.add(marks);
    // The pictures around you. On a step the old ones stay up until the new ones have come, then fade into them, so
    // a step reads as a glide rather than a flash of black; the marks for the new place wait with them.
    let faces = new THREE.Group(), leaving: THREE.Group | null = null, shown = "", ready = true, readyBy = 0, fadeAt = -1e9;
    scene.add(faces);
    const drop = (g: THREE.Group | null) => {
      if (!g) return;
      scene.remove(g);
      g.traverse((o) => { if (o instanceof THREE.Mesh) { const m = o.material as THREE.MeshBasicMaterial; m.map?.dispose(); m.dispose(); o.geometry.dispose(); } });
    };
    const reveal = () => {
      if (ready) return;
      ready = true; faces.visible = marks.visible = true; fadeAt = performance.now();
    };
    const loader = new THREE.TextureLoader();
    const reticle = new THREE.Mesh(new THREE.CircleGeometry(0.012, 24), new THREE.MeshBasicMaterial({ color: WHITE, depthTest: false, transparent: true, opacity: 0.95 }));
    reticle.position.z = -1; reticle.renderOrder = 9;
    const progress = new THREE.Mesh(new THREE.RingGeometry(0.016, 0.021, 40, 1, 0, 0.001), new THREE.MeshBasicMaterial({ color: BLUE, depthTest: false, transparent: true }));
    progress.position.z = -1; progress.renderOrder = 9;
    camera.add(reticle, progress);

    // You start upstairs if there is an upstairs: the top level's first position.
    const top = Math.max(...place.levels.map((l) => l.level));
    let here = place.positions.find((p) => p.level === top) ?? place.positions[0];
    let way: string[] = [], before: string[] = [];     // the way now, and the walking way it replaced
    let answer: PlaceAnswer | null = null;
    let moving: "walking" | "wheelchair" = "walking", chair = 27, asked = "";
    let targets: { object: THREE.Object3D; go: string }[] = [];
    let caption: THREE.Sprite | null = null, captionUntil = 0, plan: THREE.Sprite | null = null;
    // Walking by itself along the way: when the next step is due, and whether a tap has paused it.
    let walk: { at: number; paused: boolean } | null = null;

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
      if (before.length > 1) {
        ctx.strokeStyle = "rgba(255,255,255,0.45)"; ctx.lineWidth = 3; ctx.setLineDash([7, 7]); ctx.beginPath();
        before.forEach((id, i) => { const p = at.get(id); if (!p) return; const [x, y] = px(p); if (i) ctx.lineTo(x, y); else ctx.moveTo(x, y); });
        ctx.stroke(); ctx.setLineDash([]);
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

    /** The six pictures of where you stand, built only when you have moved: redrawing the way keeps the ones up. */
    const picture = () => {
      shown = here.id;
      // Pictures that never came in time are dropped, and the ones on screen stay up until the next ones do.
      if (ready) { drop(leaving); leaving = faces; leaving.traverse((o) => { o.renderOrder = 1; }); } else drop(faces);
      faces = new THREE.Group(); faces.visible = marks.visible = false; ready = false; readyBy = performance.now() + 3000;
      scene.add(faces);
      const these = faces;
      let waiting = 6;
      const came = () => { if (these === faces && --waiting === 0) reveal(); };
      const heading = here.heading ?? 0, size = FACE_M * 2.002;
      const face = (n: number) => {
        const tex = loader.load(api.placePano(model, here.id, n), came, undefined, came);
        tex.colorSpace = THREE.SRGBColorSpace;
        // Transparent from the start, so fading out later needs no new shader halfway through a step.
        const mesh = new THREE.Mesh(new THREE.PlaneGeometry(size, size), new THREE.MeshBasicMaterial({ map: tex, depthTest: false, transparent: true }));
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
    };

    const draw = () => {
      marks.clear(); targets = [];
      if (here.id !== shown) picture();

      const i = way.indexOf(here.id), next = i >= 0 && i < way.length - 1 ? at.get(way[i + 1])! : null;
      // The way: marks on the floor to the next position, and a ring there to look at.
      const leg = next ? answer?.route?.legs.find((g) => g.from === here.id && g.to === next.id) ?? null : null;
      if (next) {
        // A lift is reached at its doors, a few steps from here; everything else is walked to where it is.
        const end = leg?.kind === "lift" && leg.bearing != null ? toward(leg.bearing, 3.2, -EYE_M) : spot(next);
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
          const down = leg ? leg.rise_m < 0 : (next.level ?? 0) < (here.level ?? 0);
          const change = leg?.kind === "lift" ? `Lift, ${down ? "down" : "up"} one level` : leg?.kind === "stairs" ? `Stairs ${down ? "down" : "up"}` : next.level !== here.level ? (down ? "Down one level" : "Up one level") : null;
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
      if (captionUntil === Infinity) captionUntil = 0;   // a caption left up goes once you move on
      draw();
      tell();
      const i = way.indexOf(id);
      // Arriving on a walk that walked itself, the caption stays up for whoever is watching.
      if (answer?.room && i === way.length - 1 && way.length > 1) say(`You are at ${answer.place ?? answer.room.type}.`, walk ? Infinity : 7);
    };
    /** The next position along the way from where you stand, if you are on it and not there yet. */
    const ahead = () => { const i = way.indexOf(here.id); return i >= 0 && i < way.length - 1 ? way[i + 1] : null; };
    /** Which way the next mark lies, by compass: a lift's doors, or the next position. */
    const onward = (): number | null => {
      const id = ahead(), next = id ? at.get(id) : null;
      if (!next) return null;
      const leg = answer?.route?.legs.find((g) => g.from === here.id && g.to === next.id);
      return leg?.kind === "lift" && leg.bearing != null ? leg.bearing : bearing(here, next);
    };
    // The second screen only follows: it never sets off on a walk of its own.
    const walkOn = (afterS: number) => { if (!watch && ahead()) walk = { at: performance.now() + afterS * 1000, paused: false }; };
    /** A tap, a click or a clicker's button. While the way walks itself it pauses or carries on; otherwise it is one
     *  step, along the way when there is one, else to the ring that was picked out. */
    const tap = (picked: string | null) => {
      if (watch) return;
      if (walk) {
        walk.paused = !walk.paused;
        if (walk.paused) say("Paused.", Infinity);
        else { walk.at = performance.now(); captionUntil = 0; }
        return;
      }
      const next = ahead() ?? picked;
      if (next) go(next);
    };
    /** Stops a walk that walks itself, and takes down its "Paused." if it was paused. */
    const halt = () => { if (walk?.paused) captionUntil = 0; walk = null; };

    const tell = () => { void api.placeTell(model, { position: here.id, yaw: lookBearing(), pitch: lookPitch(), mover: moving, chair_in: chair, answer }); };
    const take = (got: PlaceAnswer) => {
      answer = got.found ? got : null;
      way = got.route?.positions ?? [];
      before = got.changed?.walking_positions ?? [];
      halt();
      setLast(got); setMover(moving);
      say(brief(got), 12);
      draw();
      tell();
      // A way worked out for a wheelchair walks itself, once there has been time to read what it is.
      if (moving === "wheelchair") walkOn(FIRST_S);
      return got;
    };
    const lookBearing = () => { const f = new THREE.Vector3(0, 0, -1).applyQuaternion(camera.quaternion); return ((THREE.MathUtils.radToDeg(Math.atan2(f.x, -f.z)) % 360) + 360) % 360; };
    const lookPitch = () => THREE.MathUtils.radToDeg(Math.asin(Math.max(-1, Math.min(1, new THREE.Vector3(0, 0, -1).applyQuaternion(camera.quaternion).y))));
    control.current = {
      ask: async (query: string) => {
        // "I'm in a wheelchair" is not a place to find: it changes how the way to the last place is worked out.
        if (USES_A_CHAIR.test(query)) return control.current!.moveBy("wheelchair");
        // A new question stops any walk under way, so the way is asked from where you stand.
        halt();
        asked = query;
        return take(await api.placeFind(model, query, here.id, moving, chair));
      },
      moveBy: async (how, chairIn) => {
        halt();
        moving = how;
        if (chairIn && chairIn >= 18 && chairIn <= 40) chair = chairIn;
        setMover(how);
        if (!asked) { tell(); return { say: how === "wheelchair" ? "Understood. I will keep every way step-free." : "Understood." }; }
        return take(await api.placeFind(model, asked, here.id, moving, chair));
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
      if (!drag) return;
      moved += Math.abs(e.clientX - drag.x) + Math.abs(e.clientY - drag.y);
      // With the phone's own sense of direction a drag turns nothing, but it still is not a tap.
      if (!sensor) {
        yaw += (e.clientX - drag.x) * 0.25; pitch = Math.max(-85, Math.min(85, pitch + (e.clientY - drag.y) * 0.25));
        camera.rotation.set(rad(pitch), rad(yaw), 0);
      }
      drag = { x: e.clientX, y: e.clientY };
    };
    let gazed: THREE.Object3D | null = null, held = 0;
    /** The ring at the middle of the view, the one being looked at. */
    const looked = () => targets.find((t) => t.object === gazed)?.go ?? null;
    const ray = new THREE.Raycaster();
    const up = (e: PointerEvent) => {
      // A tap or click, not a drag, anywhere on the picture. Flat on a screen it can pick out a ring; in the split
      // headset view where it lands means nothing, so it is the ring being looked at.
      if (drag && moved < TAP_PX && e.button === 0) {
        let picked: string | null = null;
        if (live.current.stereo) picked = looked();
        else if (ready) {
          const box = renderer.domElement.getBoundingClientRect();
          ray.setFromCamera(new THREE.Vector2(((e.clientX - box.left) / box.width) * 2 - 1, -((e.clientY - box.top) / box.height) * 2 + 1), camera);
          const hit = ray.intersectObjects(targets.map((t) => t.object), false)[0]?.object;
          picked = (hit && targets.find((x) => x.object === hit)?.go) || null;
        }
        tap(picked);
      }
      drag = null;
    };
    const lift = () => { drag = null; };
    // Space, Enter and the up arrow are a tap too: cheap clickers and some headsets' buttons send them.
    const key = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement | null;
      // Not keys typed into the question box, nor ones meant for a button that has the focus; and a held key is one tap.
      if (e.repeat || e.metaKey || e.ctrlKey || e.altKey || (t && (t.isContentEditable || /^(INPUT|TEXTAREA|SELECT|BUTTON)$/.test(t.tagName)))) return;
      if (e.key === " " || e.key === "Enter" || e.key === "ArrowUp") { e.preventDefault(); tap(looked()); }
      // G plays any way through by itself, or carries on with one that was paused.
      else if (e.key === "g" || e.key === "G") { if (!walk) walkOn(0); else if (walk.paused) tap(null); }
    };
    window.addEventListener("deviceorientation", onOrient);
    renderer.domElement.addEventListener("pointerdown", down);
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
    window.addEventListener("pointercancel", lift);
    if (!watch) window.addEventListener("keydown", key);
    const resize = () => renderer.setSize(el.clientWidth, el.clientHeight);
    window.addEventListener("resize", resize);

    draw();
    let rev = -1, lastTold = 0;
    const follow = watch ? window.setInterval(() => {
      api.placeLive(model).then((live) => {
        if (live.rev === rev) { if (live.yaw != null) camera.rotation.set(rad(live.pitch ?? 0), -rad(live.yaw), 0); return; }
        rev = live.rev;
        const to = live.position ? at.get(live.position) : null;
        if (to) here = to;
        moving = live.mover ?? "walking";
        answer = live.answer?.found ? live.answer : null;
        way = live.answer?.route?.positions ?? [];
        before = live.answer?.changed?.walking_positions ?? [];
        setLast(live.answer ?? null); setMover(moving);
        if (live.yaw != null) camera.rotation.set(rad(live.pitch ?? 0), -rad(live.yaw), 0);
        draw();
      }).catch(() => {});
    }, 250) : 0;
    const clock = new THREE.Clock();
    let raf = 0;
    const frame = () => {
      raf = requestAnimationFrame(frame);
      const dt = clock.getDelta(), now = performance.now();
      // The new pictures fade in over the old; if they are slow to come, show what has come after a while.
      if (!ready && now > readyBy) reveal();
      if (leaving && ready) {
        const k = (now - fadeAt) / (FADE_S * 1000);
        if (k >= 1) { drop(leaving); leaving = null; }
        else { const o = 1 - k * k * (3 - 2 * k); leaving.traverse((m) => { if (m instanceof THREE.Mesh) (m.material as THREE.MeshBasicMaterial).opacity = o; }); }
      }
      // Walking by itself: the next step once it is due and the last one's pictures have come and settled.
      if (walk) {
        const next = ahead();
        if (!next) walk = null;   // arrived, or stepped off the way
        else if (!walk.paused && ready && now >= walk.at && now - fadeAt >= SETTLE_S * 1000) {
          go(next);
          const then = ahead(), leg = then ? answer?.route?.legs.find((g) => g.from === here.id && g.to === then) : null;
          walk.at = now + (STEP_S + (leg && (leg.kind === "lift" || leg.kind === "stairs" || leg.level_change) ? LEVEL_S : 0)) * 1000;
        }
      }
      // With no sense of direction to follow (a desktop), a walk walking itself turns the view the way it is going.
      if (walk && !walk.paused && !sensor && !drag) {
        const b = onward();
        if (b != null) {
          const k = 1 - Math.exp(-2 * dt);
          yaw += (((((-b - yaw) % 360) + 540) % 360) - 180) * k;
          pitch += (-8 - pitch) * k;
          camera.rotation.set(rad(pitch), rad(yaw), 0);
        }
      }
      scene.updateMatrixWorld();
      ray.setFromCamera(new THREE.Vector2(0, 0), camera);
      const hit = ready ? ray.intersectObjects(targets.map((t) => t.object), false)[0]?.object ?? null : null;
      // The second screen only follows, and a walk walking itself needs no looking at; a paused one does.
      const dwell = !watch && !(walk && !walk.paused);
      if (hit !== gazed || !dwell) { gazed = hit; held = 0; }
      else if (hit) {
        held += dt;
        if (held >= DWELL_S) { held = -1e6; const t = targets.find((x) => x.object === hit); if (t) go(t.go); }
      }
      progress.geometry.dispose();
      progress.geometry = new THREE.RingGeometry(0.016, 0.021, 40, 1, 0, hit && held > 0 ? Math.min(1, held / DWELL_S) * Math.PI * 2 : 0.001);
      if (caption && now > captionUntil) { camera.remove(caption); caption = null; }
      // The headset says which way it is looking a few times a second, so the second screen can turn with it.
      if (!watch && now - lastTold > 300) { lastTold = now; void api.placeTell(model, { position: here.id, yaw: lookBearing(), pitch: lookPitch(), mover: moving, chair_in: chair, answer }); }
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
      if (follow) window.clearInterval(follow);
      window.removeEventListener("deviceorientation", onOrient);
      renderer.domElement.removeEventListener("pointerdown", down);
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
      window.removeEventListener("pointercancel", lift);
      window.removeEventListener("keydown", key);
      window.removeEventListener("resize", resize);
      walk = null;
      drop(leaving); drop(faces);
      control.current = null;
      renderer.dispose();
      el.removeChild(renderer.domElement);
    };
  }, [place, model, watch]);

  const start = async () => {
    // iOS only hands over motion data after a tap and an explicit yes.
    const ask = (DeviceOrientationEvent as unknown as { requestPermission?: () => Promise<string> }).requestPermission;
    if (ask) { try { await ask(); } catch { /* denied: drag-to-look still works */ } }
    try { await document.documentElement.requestFullscreen?.(); } catch { /* not available on iPhone */ }
    setStarted(true);
    if (voice.current || !voiceReady) return;
    voice.current = await openVoice({
      sessionUrl: `/api/places/${model}/voice`,
      run: async (name, args) => {
        if (name === "find_place" && control.current) return control.current.ask(String(args.query ?? ""));
        if (name === "i_move_by" && control.current) return control.current.moveBy(args.mover === "wheelchair" ? "wheelchair" : "walking", Number(args.chair_width_in) || undefined);
        return { found: false, say: "I cannot do that here." };
      },
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
          <p>Turn the phone sideways, press Start, then put it in the headset. Ask where something is. The way is drawn on the floor: look at the blue ring, or tap, to walk to it.</p>
          <button className="primary" onClick={start}>Start</button>
          <label><input type="checkbox" checked={stereo} onChange={(e) => setStereo(e.target.checked)} /> Split the screen for a headset</label>
        </div>
      )}
      {place && started && !stereo && !watch && (
        <form className="vr-bar" onSubmit={(e) => { e.preventDefault(); if (typed.trim()) { void control.current?.ask(typed.trim()); setTyped(""); } }}>
          <input value={typed} onChange={(e) => setTyped(e.target.value)} placeholder="Where is the git push-up challenge?" aria-label="Ask where something is" />
          {/* A button clicked with the mouse lets go of the focus, so a clicker's Space or Enter then steps rather than pressing it again. */}
          <button onClick={(e) => { if (e.detail) e.currentTarget.blur(); }}>Ask</button>
          <span>{last ? (last.found && last.route ? `${last.route.metres} m` : "") : voiceReady ? "Or just ask aloud" : ""}</span>
          <button type="button" aria-pressed={mover === "wheelchair"} onClick={(e) => { if (e.detail) e.currentTarget.blur(); void control.current?.moveBy(mover === "wheelchair" ? "walking" : "wheelchair"); }}>
            {mover === "wheelchair" ? "In a wheelchair" : "Walking"}
          </button>
          <button type="button" onClick={() => setStereo(true)}>Headset view</button>
        </form>
      )}
      {place && watch && (
        <aside className="place-watch" aria-live="polite">
          <p className="place-watch-name">{place.name}</p>
          {!last && <p className="place-watch-say">Waiting for the headset.</p>}
          {last && <p className="place-watch-say">{last.event ? `${last.event}: ` : ""}<strong>{last.found ? last.place : "not found"}</strong></p>}
          {last?.route && (
            <dl>
              <div><dt>{last.route.lift ? "By the lift" : last.route.stairs ? `Stairs, ${last.route.stairs.flights} flights` : "On the level"}</dt><dd>{Math.round(last.route.metres)} m</dd></div>
              {last.changed && <div><dt>Stairs avoided</dt><dd>{last.changed.flights_avoided} flights, {last.changed.rise_avoided_m.toFixed(1)} m</dd></div>}
              {mover === "wheelchair" && last.route.narrowest_passage_m != null && <div><dt>Narrowest point</dt><dd>{last.route.narrowest_passage_m.toFixed(2)} m</dd></div>}
              {mover === "wheelchair" && <div><dt>Chair</dt><dd>{last.chair_width_in ?? 27} in</dd></div>}
            </dl>
          )}
          {last?.no_way && <p className="place-watch-note">No step-free way in this scan.</p>}
          {last?.route?.lift && <p className="place-watch-note">The lift was seen in the scan, not ridden.</p>}
        </aside>
      )}
    </div>
  );
}
