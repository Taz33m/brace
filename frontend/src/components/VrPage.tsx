import { useEffect, useRef, useState } from "react";
import * as THREE from "three";
import { api } from "../api";
import { costRange, hours } from "../format";
import type { Action, Building, Direction, Scan, Scenario } from "../types";
import { openVoice, type Voice, type VoiceState } from "../voice";

const BEARING: Record<string, number> = { north: 0, east: 90, south: 180, west: 270 };
const FACE_DISTANCE = 50;
const DWELL_SECONDS = 1.3;
const PIN_DISTANCE = 3.2;
const M_PER_DEG = 111_320;
const rad = (deg: number) => (deg * Math.PI) / 180;
/** Unit vector for a compass bearing in scene space: north is -Z, east is +X. */
const toward = (bearing: number, y = 0) => new THREE.Vector3(Math.sin(rad(bearing)), y, -Math.cos(rad(bearing)));

interface Props { id: number; scenario: Scenario; step: string | null }
type Line = { text: string; size: number; bold?: boolean; color?: string };
/** What the laptop last asked the headset to attend to. */
interface Target {
  rev: number; building?: number | null; scan_id?: string | null; sweep_id?: string | null; bearing?: number | null;
  action_id?: string | null; lon?: number | null; lat?: number | null; label?: string | null; image?: string | null; kind?: string | null;
}

/** Text drawn onto a canvas and shown as a flat card that always faces the viewer. */
function card(lines: Line[], width: number, fill: string, W = 768): THREE.Sprite {
  const pad = 26;
  const canvas = document.createElement("canvas");
  const ctx = canvas.getContext("2d")!;
  const wrapped: Line[] = [];
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

/**
 * A round numbered badge marking one action. Filled means it is in this room; a ring means it is outside,
 * seen through the wall in its real direction. Green means the owner has approved it.
 */
function badge(n: string, outside: boolean, approved: boolean): THREE.Sprite {
  const canvas = document.createElement("canvas");
  canvas.width = canvas.height = 256;
  const ctx = canvas.getContext("2d")!;
  const colour = approved ? "#1f9d61" : "#cf4a1a";
  ctx.beginPath(); ctx.arc(128, 128, 110, 0, Math.PI * 2);
  ctx.fillStyle = outside ? "rgba(11,21,34,0.82)" : colour; ctx.fill();
  ctx.lineWidth = outside ? 22 : 12; ctx.strokeStyle = outside ? colour : "#ffffff"; ctx.stroke();
  ctx.fillStyle = "#ffffff"; ctx.font = "700 150px Barlow Condensed, Arial, sans-serif";
  ctx.textAlign = "center"; ctx.textBaseline = "middle"; ctx.fillText(approved ? "✓" : n, 128, 138);
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

/** An arrow at the edge of view pointing toward what the agent is looking at. */
function chevron(left: boolean): THREE.Sprite {
  const s = card([{ text: left ? "‹ look" : "look ›", size: 56, bold: true, color: "#ffb38f" }], 0.3, "rgba(11,21,34,0.8)", 230);
  s.position.set(left ? -0.62 : 0.62, 0.12, -1.4);
  s.visible = false;
  return s;
}

const VOICE_LABEL: Record<VoiceState, string> = {
  off: "Voice off", connecting: "Connecting the voice…", live: "Voice on: speak to the inspector",
  narration: "Reading the steps aloud", silent: "No voice: captions only",
};

export function VrPage({ id, scenario, step }: Props) {
  const mount = useRef<HTMLDivElement>(null);
  const [b, setB] = useState<Building | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [started, setStarted] = useState(false);
  const [stereo, setStereo] = useState(() => window.matchMedia("(pointer: coarse)").matches);
  const [where, setWhere] = useState("");
  const [voiceReady, setVoiceReady] = useState(false);
  const [wantVoice, setWantVoice] = useState(true);
  const [voiceState, setVoiceState] = useState<VoiceState>("off");
  const live = useRef({ stereo, started });
  live.current = { stereo, started };
  const voice = useRef<Voice | null>(null);
  /** What the scene offers to the Start button, the voice's tools and the bar. Filled once the space is built. */
  const control = useRef<{
    recenter: () => void;
    tool: (name: string, args: Record<string, unknown>) => Promise<unknown>;
    caption: (who: "agent" | "you", text: string) => void;
    greeting: () => string;
  } | null>(null);

  useEffect(() => { api.building(id, scenario.id, step).then(setB).catch((e) => setError(e.message)); }, [id, scenario.id, step]);
  useEffect(() => { api.config().then((c) => setVoiceReady(c.voice_ready)).catch(() => setVoiceReady(false)); }, []);
  useEffect(() => () => { voice.current?.close(); voice.current = null; }, []);

  useEffect(() => {
    const el = mount.current;
    if (!el || !b) return;
    const actions: Action[] = b.plan?.actions ?? [];
    const scans = b.scans.filter((s) => s.sweeps.length > 0);
    if (scans.length === 0) { setError("No space in this building has been scanned, so there is nothing to stand in."); return; }
    const number = (a: Action) => a.id.replace("A", "");

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
    const attention = new THREE.Group();  // where the agent is looking right now
    world.add(faces, things, attention);

    const reticle = disc(0xffffff, 0.012, 0.95);
    reticle.position.z = -1;
    const progress = new THREE.Mesh(new THREE.RingGeometry(0.016, 0.021, 40, 1, 0, 0.001),
      new THREE.MeshBasicMaterial({ color: 0xff8a4d, depthTest: false, transparent: true }));
    progress.position.z = -1; progress.renderOrder = 6;
    const lookLeft = chevron(true), lookRight = chevron(false);
    camera.add(reticle, progress, lookLeft, lookRight);
    let hud: THREE.Sprite | null = null;
    const setHud = (scan: Scan) => {
      if (hud) camera.remove(hud);
      const t = b.threat;
      hud = card([{ text: `${t.name}: ${t.hours_left != null ? `about ${hours(t.hours_left)} left` : t.label ?? ""}`, size: 34, bold: true, color: "#ffb38f" },
        { text: `${b.record.name}, ${scan.name}`, size: 28 }], 0.9, "rgba(11,21,34,0.78)");
      hud.position.set(0, -0.62, -1.4);
      camera.add(hud);
    };
    // The last thing said, as a caption under the view: a loud hall should not hide what the agent said.
    let caption: THREE.Sprite | null = null, captionUntil = 0;
    const setCaption = (who: "agent" | "you", text: string) => {
      if (caption) camera.remove(caption);
      caption = card([{ text: who === "you" ? `You: ${text}` : text, size: 30, color: who === "you" ? "#9fc5ff" : "#ffffff" }], 0.95, "rgba(11,21,34,0.78)");
      caption.position.set(0, -0.36, -1.4);
      camera.add(caption);
      captionUntil = performance.now() + Math.min(12_000, 3_000 + text.length * 55);
    };

    const loader = new THREE.TextureLoader();
    /** A photo shown as a card; it takes the picture's own shape once it has loaded. */
    const photo = (url: string, width: number): THREE.Sprite => {
      const material = new THREE.SpriteMaterial({ depthTest: false, transparent: true, opacity: 0 });
      const sprite = new THREE.Sprite(material);
      sprite.renderOrder = 5;
      loader.load(url, (tex) => {
        tex.colorSpace = THREE.SRGBColorSpace;
        material.map = tex; material.opacity = 1; material.needsUpdate = true;
        sprite.scale.set(width, (width * tex.image.height) / tex.image.width, 1);
      });
      return sprite;
    };

    let current: { scan: Scan; sweepId: string; heading: number; lon: number | null; lat: number | null } | null = null;
    let targets: { object: THREE.Object3D; act: () => void }[] = [];
    let extras: THREE.Object3D[] = [];          // the open card and whatever hangs off it
    let selectedAction: string | null = null;
    let attending: { bearing: number; until: number } | null = null;
    let finding = -1;                            // where "next finding" has got to
    const approved = new Set<string>();
    const pins = new Map<string, { action: Action; at: THREE.Vector3; outside: boolean; metres: number | null; sprite: THREE.Sprite }>();

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
    /** Compass bearing and distance from where the viewer stands to a point on the site. Null when this scan has no fix. */
    const from = (lon: number, lat: number): { bearing: number; metres: number } | null => {
      if (!current || current.lon == null || current.lat == null) return null;
      const e = (lon - current.lon) * M_PER_DEG * Math.cos(rad(current.lat)), n = (lat - current.lat) * M_PER_DEG;
      return { bearing: (THREE.MathUtils.radToDeg(Math.atan2(e, n)) + 360) % 360, metres: Math.hypot(e, n) };
    };

    /** Where an action's pin belongs from this position: in the room, through a wall, or not shown here. */
    const place = (a: Action, scan: Scan, sweepId: string, heading: number): { at: THREE.Vector3; outside: boolean; metres: number | null } | null => {
      if (a.interior && a.interior.scan_id === scan.id && a.interior.sweep_id === sweepId) {
        const d: Direction = a.interior.direction;
        const at = d === "up" ? new THREE.Vector3(0.3, 2.2, -0.6) : d === "down" ? new THREE.Vector3(0.3, -1.3, -0.9)
          : toward(a.interior.bearing ?? BEARING[d] ?? heading).multiplyScalar(PIN_DISTANCE);
        return { at, outside: false, metres: null };
      }
      if (a.interior && a.interior.scan_id === scan.id) return null;   // in this space but from another spot: walk there
      const lon = a.site?.lon ?? a.interior?.lon, lat = a.site?.lat ?? a.interior?.lat;
      const there = lon != null && lat != null ? from(lon, lat) : null;
      if (!there) return null;
      // Something a few metres away is over this roof or against this wall, so it sits high; far things sit near the horizon.
      const lift = there.metres < 6 ? 1.6 : there.metres < 20 ? 0.7 : 0.22;
      return { at: toward(there.bearing, lift).normalize().multiplyScalar(PIN_DISTANCE), outside: true, metres: there.metres };
    };

    const closeCard = () => { for (const x of extras) things.remove(x); targets = targets.filter((t) => !extras.includes(t.object)); extras = []; };
    const repaint = (aid: string) => {
      const pin = pins.get(aid);
      if (!pin) return;
      const fresh = badge(number(pin.action), pin.outside, approved.has(aid));
      fresh.position.copy(pin.at);
      things.remove(pin.sprite); things.add(fresh);
      const slot = targets.find((t) => t.object === pin.sprite);
      if (slot) slot.object = fresh;
      pin.sprite = fresh;
    };

    const approve = async (a: Action, aloud: boolean): Promise<{ ok: boolean; say: string }> => {
      const result = await fetch("/api/vr/approve", { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ building: id, scenario: scenario.id, step, action_id: a.id }) })
        .then((r) => r.json() as Promise<{ ok: boolean; say: string }>)
        .catch(() => ({ ok: false, say: "The approval could not be saved. The laptop is not reachable." }));
      if (result.ok) { approved.add(a.id); repaint(a.id); if (selectedAction === a.id) open(a); }
      if (aloud) voice.current?.cue("say", result.say);
      return result;
    };

    /** Open an action's card beside its pin, with its photo when it is outside and a place to look to approve it. */
    const open = (a: Action) => {
      const pin = pins.get(a.id);
      if (!pin) return;
      closeCard();
      const high = pin.at.y > 1.4;
      const text = card([
        ...(pin.outside ? [{ text: `Outside, about ${Math.max(1, Math.round(pin.metres ?? 0))} m this way${a.structure ? `, on ${a.structure}` : ""}`, size: 28, bold: true, color: "#ffb38f" }] : []),
        { text: a.title, size: 36, bold: true },
        { text: a.why, size: 28, color: "#d5dde7" },
        { text: `${a.crew}. ${a.hours_of_work} h. ${costRange(a.cost_low, a.cost_high)}.`, size: 30, bold: true, color: "#ffb38f" },
      ], 2.4, "rgba(11,21,34,0.9)");
      text.position.copy(pin.at).add(new THREE.Vector3(0, high ? -1.25 : 1.2, 0));
      const done = approved.has(a.id);
      const ask = card(done ? [{ text: "Approved", size: 64, bold: true }] : [{ text: "Approve", size: 72, bold: true }, { text: "keep looking here", size: 34 }],
        0.7, done ? "rgba(31,157,97,0.95)" : "rgba(207,74,26,0.95)", 340);
      ask.position.copy(text.position).add(new THREE.Vector3(1.65, 0, 0).applyAxisAngle(new THREE.Vector3(0, 1, 0), -rad(from0(pin.at))));
      extras = [text, ask];
      const image = a.site?.oblique_image ?? a.site?.image;
      if (pin.outside && image) {
        const shot = photo(api.file(id, image), 1.5);
        shot.position.copy(text.position).add(new THREE.Vector3(-1.95, 0, 0).applyAxisAngle(new THREE.Vector3(0, 1, 0), -rad(from0(pin.at))));
        extras.push(shot);
      }
      things.add(...extras);
      if (!done) targets.push({ object: ask, act: () => { void approve(a, true); } });
      selectedAction = a.id;
      attention.clear();
      attending = { bearing: from0(pin.at), until: performance.now() + 14_000 };   // the edge arrows lead the eye to it
    };
    /** Compass bearing of a point in the space, used to set things beside it rather than in front of it. */
    const from0 = (p: THREE.Vector3) => THREE.MathUtils.radToDeg(Math.atan2(p.x, -p.z));

    const go = (scan: Scan, sweepId: string, bearing?: number | null) => {
      const sweep = scan.sweeps.find((s) => s.id === sweepId) ?? scan.sweeps[0];
      const heading = sweep.heading ?? 0;
      current = { scan, sweepId: sweep.id, heading, lon: sweep.lon ?? scan.origin?.[0] ?? null, lat: sweep.lat ?? scan.origin?.[1] ?? null };
      buildFaces(scan, sweep.id, heading);
      setHud(scan);
      setWhere(scan.name);
      things.clear(); attention.clear(); attending = null;
      targets = []; extras = []; pins.clear();
      for (const a of actions) {
        const spot = place(a, scan, sweep.id, heading);
        if (!spot) continue;
        const sprite = badge(number(a), spot.outside, approved.has(a.id));
        sprite.position.copy(spot.at);
        things.add(sprite);
        pins.set(a.id, { action: a, ...spot, sprite });
        targets.push({ object: sprite, act: () => open(a) });
        if (spot.outside && spot.metres != null) {
          const far = card([{ text: `${Math.max(1, Math.round(spot.metres))} m out`, size: 64, bold: true }], 0.5, "rgba(11,21,34,0.75)", 300);
          far.position.copy(spot.at).add(new THREE.Vector3(0, -0.45, 0));
          things.add(far);
        }
      }
      // Stepping spots: nearby scan positions, drawn on the floor in their true direction.
      if (sweep.lon != null && sweep.lat != null) {
        const kx = M_PER_DEG * Math.cos(rad(sweep.lat));
        const near = scan.sweeps.filter((s) => s.id !== sweep.id && s.lon != null && s.lat != null)
          .map((s) => ({ s, e: (s.lon! - sweep.lon!) * kx, n: (s.lat! - sweep.lat!) * M_PER_DEG }))
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

    /** Show where the agent is looking outside: a ring in that direction, what it is doing, and the photo it took. */
    const attend = (t: Target) => {
      attention.clear(); attending = null;
      const there = t.lon != null && t.lat != null ? from(t.lon, t.lat) : null;
      if (!there) return;
      const at = toward(there.bearing, 0.12).normalize().multiplyScalar(3);
      const ring = disc(0xffffff, 0.2, 0.95);
      ring.position.copy(at); ring.lookAt(0, 0, 0); ring.name = "ring";
      attention.add(ring);
      if (t.label) {
        const says = card([{ text: t.label, size: 34, bold: true }, { text: `Outside, about ${Math.max(1, Math.round(there.metres))} m this way`, size: 26, color: "#d5dde7" }], 1.5, "rgba(11,21,34,0.85)");
        says.position.copy(at).add(new THREE.Vector3(0, -0.55, 0));
        attention.add(says);
      }
      if (t.image) {
        const shot = photo(api.file(id, t.image), 1.5);
        shot.position.copy(at).add(new THREE.Vector3(0, 0.95, 0));
        attention.add(shot);
      }
      attending = { bearing: there.bearing, until: performance.now() + 14_000 };
    };

    /** The scanned spot with a position fix that is closest to a point on the site. */
    const nearestFix = (lon: number, lat: number): { scan: Scan; sweepId: string } | null => {
      let best: { scan: Scan; sweepId: string; d: number } | null = null;
      for (const scan of scans) for (const s of scan.sweeps) {
        if (s.lon == null || s.lat == null) continue;
        const d = Math.hypot((s.lon - lon) * M_PER_DEG * Math.cos(rad(lat)), (s.lat - lat) * M_PER_DEG);
        if (!best || d < best.d) best = { scan, sweepId: s.id, d };
      }
      return best;
    };

    /** Take the viewer to an action: walk to it when it is inside, turn to face it through the wall when it is not. */
    const show = (a: Action): Record<string, unknown> => {
      const inside = a.interior ? scans.find((s) => s.id === a.interior!.scan_id) : null;
      if (a.interior && inside) go(inside, a.interior.sweep_id, a.interior.bearing ?? BEARING[a.interior.direction] ?? null);
      else if (a.site) {
        if (!pins.has(a.id)) { const fix = nearestFix(a.site.lon, a.site.lat); if (fix) go(fix.scan, fix.sweepId); }
        const pin = pins.get(a.id);
        if (pin) faceBearing(from0(pin.at));
      }
      const pin = pins.get(a.id);
      if (!pin) return { ok: false, say: "I cannot show that one from any scanned space." };
      open(a);
      finding = actions.indexOf(a);
      return { ok: true, id: a.id, title: a.title, where: pin.outside ? `outside, about ${Math.round(pin.metres ?? 0)} metres from where the owner stands` : `in this room, ${current?.scan.name}`,
               approved: approved.has(a.id) };
    };

    const tool = async (name: string, args: Record<string, unknown>): Promise<unknown> => {
      const wanted = typeof args.action_id === "string" ? actions.find((a) => a.id.toLowerCase() === (args.action_id as string).toLowerCase()) : undefined;
      if (name === "go_to_action") return wanted ? show(wanted) : { ok: false, say: "That is not an action in this plan." };
      if (name === "next_finding") {
        if (actions.length === 0) return { ok: false, say: "There are no actions in this plan." };
        return show(actions[(finding + 1) % actions.length]);
      }
      if (name === "approve_action") return wanted ? approve(wanted, false) : { ok: false, say: "That is not an action in this plan." };
      if (name === "where_am_i") {
        const here = [...pins.values()];
        return { space: current?.scan.name, kind: current?.scan.kind, pinned_in_this_room: here.filter((p) => !p.outside).map((p) => p.action.id),
                 seen_through_the_walls: here.filter((p) => p.outside).map((p) => ({ id: p.action.id, metres: Math.round(p.metres ?? 0) })) };
      }
      return { ok: false, say: "I cannot do that from here." };
    };
    control.current = {
      recenter: () => { if (current) faceBearing(current.heading); },
      tool,
      caption: setCaption,
      greeting: () => `Greet the owner in one sentence: name the building, say how long is left before ${b.threat.name} reaches it, and say they can ask what to fix first.`,
    };

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

    // Start where the plan has something to show inside; otherwise in a space whose position is known,
    // so the outside actions can be placed around it; otherwise in the first scanned space.
    const first = actions.find((a) => a.interior && scans.some((s) => s.id === a.interior!.scan_id))?.interior;
    const fixed = scans.find((s) => s.sweeps.some((w) => w.lon != null && w.lat != null));
    const startScan = (first && scans.find((s) => s.id === first.scan_id)) || fixed || scans[0];
    go(startScan, first?.sweep_id ?? startScan.sweeps[0].id, first?.bearing ?? null);

    // Follow the laptop, and tell it where the headset is looking.
    let rev = -1;
    const link = window.setInterval(async () => {
      try {
        const t = (await fetch("/api/vr/target").then((r) => r.json())) as Target;
        if (rev === -1) rev = t.rev;
        else if (t.rev !== rev) {
          rev = t.rev;
          if (t.building === id) {
            const scan = scans.find((s) => s.id === t.scan_id);
            const action = t.action_id ? actions.find((a) => a.id === t.action_id) : undefined;
            if (scan) go(scan, t.sweep_id ?? scan.sweeps[0].id, t.bearing ?? null);
            if (action && pins.has(action.id)) open(action);
            else if (!scan) attend(t);
            if (t.label && live.current.started) {
              if (t.kind === "action") voice.current?.cue("finding", `${t.action_id ?? ""} ${t.label}`.trim(), `Added to the plan: ${t.label}`);
              else voice.current?.cue("inspection", t.label);
            }
          }
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
      const dt = clock.getDelta(), now = performance.now();
      // Anything added since the last frame has no position yet. Without this, a new card counts as being
      // at the viewer's own eye for one frame, takes the gaze, and whatever is under the crosshair fires again.
      scene.updateMatrixWorld();
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

      if (caption && now > captionUntil) { camera.remove(caption); caption = null; }
      // The agent's marker breathes, and an arrow at the edge of view points to it when it is out of sight.
      if (attending && now > attending.until) { attention.clear(); attending = null; }
      const ring = attention.getObjectByName("ring");
      if (ring) ring.scale.setScalar(1 + 0.18 * Math.sin(now / 260));
      const off = attending ? ((attending.bearing - lookBearing() + 540) % 360) - 180 : 0;
      lookLeft.visible = off < -40; lookRight.visible = off > 40;

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
      control.current = null;
      renderer.dispose();
      el.removeChild(renderer.domElement);
    };
  }, [b, id, scenario.id, step]);

  const start = async () => {
    // iOS only hands over motion data after a tap and an explicit yes.
    const ask = (DeviceOrientationEvent as unknown as { requestPermission?: () => Promise<string> }).requestPermission;
    if (ask) { try { await ask(); } catch { /* denied: drag-to-look still works */ } }
    try { await document.documentElement.requestFullscreen?.(); } catch { /* not available on iPhone */ }
    try { await (navigator as unknown as { wakeLock?: { request: (t: string) => Promise<unknown> } }).wakeLock?.request("screen"); } catch { /* optional */ }
    setStarted(true);
    // The voice opens on the same tap, so the phone asks for the microphone before it goes into the headset.
    const scene = control.current;
    if (!scene || voice.current) return;
    voice.current = await openVoice({
      sessionUrl: `/api/voice/session?building=${id}&scenario=${encodeURIComponent(scenario.id)}${step ? `&step=${encodeURIComponent(step)}` : ""}`,
      run: (name, args) => control.current?.tool(name, args) ?? { ok: false },
      onState: setVoiceState,
      onCaption: (who, text) => control.current?.caption(who, text),
      greeting: scene.greeting(),
    }, wantVoice && voiceReady);
  };

  if (error) return <div className="fatal">{error}</div>;
  return (
    <div className="vr">
      <div className="vr-canvas" ref={mount} />
      {!b && <div className="vr-gate"><p>Loading the scanned space…</p></div>}
      {b && !started && (
        <div className="vr-gate">
          <h1>{b.record.name}</h1>
          <p>Turn the phone sideways, press Start, then put it in the headset. Look at a blue spot on the floor to walk there.
            Look at an orange number to read that action: a solid one is in this room, a ring is outside, seen through the wall.</p>
          <button className="primary" onClick={start}>Start</button>
          <label><input type="checkbox" checked={stereo} onChange={(e) => setStereo(e.target.checked)} /> Split the screen for a headset</label>
          <label><input type="checkbox" checked={wantVoice && voiceReady} disabled={!voiceReady} onChange={(e) => setWantVoice(e.target.checked)} />
            {voiceReady ? " Talk with the inspector (uses the microphone)" : " Two-way voice is not set up on this computer; steps are read aloud instead"}</label>
        </div>
      )}
      {b && started && !stereo && (
        <div className="vr-bar">
          <span>{where}. {VOICE_LABEL[voiceState]}</span>
          <button onClick={() => control.current?.recenter()}>Face the scan's front</button>
          <button onClick={() => setStereo(true)}>Headset view</button>
        </div>
      )}
    </div>
  );
}
