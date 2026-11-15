import { useEffect, useRef, useState } from "react";
import * as THREE from "three";
import { RoomEnvironment } from "three/examples/jsm/environments/RoomEnvironment.js";
import { openVoice, type Voice, type VoiceState } from "../../voice";
import { askForMotion, createOrientationReader, motionSupport, yawOf } from "../headset/lib/motion";
import { EYES_M, eyeFov, eyeViewports, readSpacing, saveSpacing } from "../headset/lib/lens";
import { disposeObject, furniture, KINDS, type Furniture, type Kind } from "./furniture";
import { parseCommand, type Room } from "./commands";
import "./restoration.css";

const ROOT = "/aftermath/verdugo/";
const ROOMS = {
  kitchen: { title: "Kitchen", heading: 182.3, images: ["fire.png", "kitchen-cleared-burned.png", "kitchen-restored-empty.png"] },
  bathroom: { title: "Bathroom", heading: 157.9, images: ["bathroom-fire.png", "bathroom-cleared-burned.png", "bathroom-restored-empty.png"] },
};
type Snapshot = { room: Room; phases: Record<Room, number>; objects: Furniture[] };
const STAGES = ["After the fire", "Contents removed", "Ready to reimagine"];
const rad = (d: number) => d * Math.PI / 180;
const clamp = (v: number, lo: number, hi: number) => Math.max(lo, Math.min(hi, v));

/** What the room says, drawn into the scene for the headset: the page's own words cannot be read through the lenses. */
function wordsSprite(top: string, bottom: string): THREE.Sprite {
  const c = document.createElement("canvas"); c.width = 1200; c.height = 230;
  const g = c.getContext("2d")!;
  g.fillStyle = "rgba(11, 16, 22, 0.82)"; g.beginPath(); g.roundRect(4, 4, c.width - 8, c.height - 8, 26); g.fill();
  g.textAlign = "center"; g.fillStyle = "#f8d376"; g.font = "700 40px Arial, sans-serif"; g.fillText(top, c.width / 2, 62, c.width - 60);
  g.fillStyle = "#ffffff"; g.font = "500 38px Arial, sans-serif";
  const lines: string[] = [];
  for (const word of bottom.split(/\s+/)) { const last = lines[lines.length - 1]; if (last !== undefined && g.measureText(`${last} ${word}`).width < c.width - 90) lines[lines.length - 1] = `${last} ${word}`; else lines.push(word); }
  lines.slice(0, 2).forEach((line, i) => g.fillText(i === 1 && lines.length > 2 ? `${line}…` : line, c.width / 2, 124 + i * 50, c.width - 60));
  const texture = new THREE.CanvasTexture(c); texture.colorSpace = THREE.SRGBColorSpace;
  const sprite = new THREE.Sprite(new THREE.SpriteMaterial({ map: texture, transparent: true, depthTest: false, depthWrite: false }));
  sprite.scale.set(1.6, 1.6 * c.height / c.width, 1); sprite.renderOrder = 20;
  return sprite;
}

export function RestorationRoom({ room: initialRoom = "kitchen" }: { room?: Room }) {
  const [state, setState] = useState<Snapshot>({ room: initialRoom, phases: { kitchen: 0, bathroom: 0 }, objects: [] });
  const current = useRef(state);
  const history = useRef<Snapshot[]>([]);
  const mount = useRef<HTMLDivElement>(null);
  const [caption, setCaption] = useState("Let’s clean this place up.");
  const [draft, setDraft] = useState("");
  const [voiceState, setVoiceState] = useState<VoiceState>("off");
  const [motion, setMotion] = useState(false);
  // The headset: "fit" sets the two pictures under the viewer's lenses, "on" is the room for two eyes with nothing else on the screen.
  const [headset, setHeadset] = useState<"off" | "fit" | "on">("off");
  const [spacing, setSpacingState] = useState(readSpacing);
  // A phone is not this computer, so the server asks it for the owner password once before it will open a voice.
  const [signin, setSignin] = useState<{ needed: boolean; busy: boolean; error: string | null }>({ needed: false, busy: false, error: null });
  const [secret, setSecret] = useState("");
  const words = useRef({ top: "", bottom: "" });
  const [loading, setLoading] = useState(true);
  const [assetError, setAssetError] = useState(false);
  const voice = useRef<Voice | null>(null), starting = useRef(false), alive = useRef(true);
  const view = useRef({ yaw: 0, pitch: -10, motion: false, stereo: false, recenter: true, spacing, offset: 0, selected: null as { x: number; z: number; room: Room } | null });
  const leave = useRef(() => {});
  const commit = (next: Snapshot) => { history.current.push(structuredClone(current.current)); history.current = history.current.slice(-15); current.current = next; setState(next); };
  const face = (object: Furniture) => { view.current.yaw = Math.atan2(object.x, -object.z) * 180 / Math.PI; view.current.pitch = -32; view.current.recenter = true; };
  const run = (name: string, args: Record<string, unknown>): Record<string, unknown> => {
    const before = current.current;
    const next = structuredClone(before);
    let say = "";
    const last = next.objects[next.objects.length - 1];
    const selected = view.current.selected;
    if (name === "read_room") return { room: before.room, stage: STAGES[before.phases[before.room]], objects: before.objects.map(o => ({ kind: o.kind, room: o.room, finish: o.finish, color: o.color })), basis: "Illustrative panoramas and parametric concept furniture; approximate placement and scale." };
    if (name === "clean_room") {
      next.phases[next.room] = Math.min(2, next.phases[next.room] + 1);
      next.objects = next.objects.filter(o => o.room !== next.room);
      say = next.phases[next.room] === 1 ? "Contents removed. Say ‘more’ to restore the empty room." : "The room is clear. What would you like to put here?";
    } else if (name === "go_room") {
      if (args.room !== "kitchen" && args.room !== "bathroom") return { ok: false, say: "Choose the kitchen or bathroom." };
      next.room = args.room; view.current.yaw = 0; view.current.pitch = -10; view.current.recenter = true; say = `You’re in the ${next.room}.`;
    } else if (name === "look") {
      const direction = String(args.direction);
      if (direction === "left") view.current.yaw -= 40;
      else if (direction === "right") view.current.yaw += 40;
      else if (direction === "behind") view.current.yaw += 180;
      else if (direction === "up") view.current.pitch = clamp(view.current.pitch + 25, -70, 70);
      else if (direction === "down") view.current.pitch = clamp(view.current.pitch - 25, -70, 70);
      else if (direction === "forward") { view.current.yaw = 0; view.current.pitch = 0; }
      else return { ok: false, say: "Choose left, right, up, down, behind or forward." };
      view.current.recenter = true; say = `Looking ${direction}.`; setCaption(say); return { ok: true, say };
    } else if (name === "place_furniture") {
      if (!KINDS.includes(args.kind as Kind)) return { ok: false, say: "I can place a chair, sofa, table, lamp, plant, bed or toilet." };
      if (next.objects.length >= 16) return { ok: false, say: "Remove a piece before adding another." };
      const destination = args.room === "bathroom" || args.room === "kitchen" ? args.room : args.kind === "toilet" ? "bathroom" : next.room;
      const changedRoom = destination !== next.room;
      next.room = destination; next.phases[destination] = 2;
      let yaw = changedRoom ? 0 : view.current.yaw;
      const position = String(args.position ?? "front");
      yaw += position === "left" ? -45 : position === "right" ? 45 : position === "back" ? 180 : position === "window" ? -70 : position === "door" ? 80 : 0;
      const selected = view.current.selected;
      const at = position === "there" && selected?.room === destination ? selected : { x: Math.sin(rad(yaw)) * 2, z: -Math.cos(rad(yaw)) * 2 };
      const item: Furniture = { id: crypto.randomUUID(), kind: args.kind as Kind, room: destination, x: at.x, z: at.z, rotation: -rad(yaw), scale: 1,
        finish: ["gold", "chrome", "wood"].includes(String(args.finish)) ? args.finish as Furniture["finish"] : "matte", color: /^#[0-9a-f]{6}$/i.test(String(args.color)) ? String(args.color) : "#dfd3bd" };
      next.objects.push(item); face(item); say = `${item.finish === "gold" ? "Golden " : ""}${item.kind} placed in the ${destination}.`;
    } else if (name === "edit_furniture") {
      if (args.action === "undo") {
        const saved = history.current.pop(); if (!saved) return { ok: false, say: "There’s nothing to undo." };
        current.current = saved; setState(saved); setCaption("Undone."); return { ok: true, say: "Undone." };
      }
      if (!last) return { ok: false, say: "Place an object first." };
      next.room = last.room;
      if (args.action === "remove") next.objects.pop();
      else if (args.action === "bigger") last.scale = clamp(last.scale * 1.2, .4, 2);
      else if (args.action === "smaller") last.scale = clamp(last.scale / 1.2, .4, 2);
      else if (args.action === "gold") last.finish = "gold";
      else if (args.action === "left" || args.action === "right") { const dx = args.action === "left" ? -.4 : .4; last.x = clamp(last.x + Math.cos(rad(view.current.yaw)) * dx, -3, 3); last.z = clamp(last.z + Math.sin(rad(view.current.yaw)) * dx, -3, 3); }
      else if (args.action === "there" && selected && selected.room === last.room) { last.x = selected.x; last.z = selected.z; }
      else if (args.action !== "focus") return { ok: false, say: "Tap a floor spot, then say ‘put it there’." };
      face(last); say = args.action === "focus" ? `Facing your ${last.kind} in the ${last.room}.` : `Updated your ${last.kind}.`;
    } else return { ok: false, say: "That command is not available in this room." };
    commit(next); setCaption(say); return { ok: true, say, room: next.room, stage: STAGES[next.phases[next.room]], objects: next.objects.length };
  };
  const runner = useRef(run); runner.current = run;

  useEffect(() => {
    alive.current = true;
    return () => { alive.current = false; voice.current?.close(); voice.current = null; };
  }, []);

  useEffect(() => {
    const el = mount.current; if (!el) return;
    const renderer = new THREE.WebGLRenderer({ antialias: true }); renderer.setPixelRatio(Math.min(devicePixelRatio, 1.75)); renderer.outputColorSpace = THREE.SRGBColorSpace;
    renderer.setClearColor(0x090b0e); el.appendChild(renderer.domElement);
    const scene = new THREE.Scene(), camera = new THREE.PerspectiveCamera(75, 1, .03, 80); camera.rotation.order = "YXZ";
    const pmrem = new THREE.PMREMGenerator(renderer), environment = new RoomEnvironment();
    const env = pmrem.fromScene(environment).texture; scene.environment = env; environment.dispose(); pmrem.dispose();
    scene.add(new THREE.HemisphereLight(0xffffff, 0x827063, 2)); const sun = new THREE.DirectionalLight(0xffeed7, 3); sun.position.set(3, 4, 2); scene.add(sun);
    const loader = new THREE.TextureLoader(), geometry = new THREE.SphereGeometry(30, 64, 40); geometry.scale(-1, 1, 1);
    let disposed = false;
    const panoramas = (Object.keys(ROOMS) as Room[]).map(room => ({ room, meshes: ROOMS[room].images.map((url, index) => {
      const texture = loader.load(ROOT + url, tex => { if (disposed) { tex.dispose(); return; } if (room === current.current.room && index === 0) setLoading(false); }, undefined, () => { if (!disposed) { setAssetError(true); setCaption("A room image could not load. Refresh to try again."); } }); texture.colorSpace = THREE.SRGBColorSpace;
      const mat = new THREE.MeshBasicMaterial({ map: texture, transparent: true, opacity: index === 0 ? 1 : 0, depthWrite: false });
      const mesh = new THREE.Mesh(geometry, mat); mesh.rotation.y = -Math.PI / 2 - rad(ROOMS[room].heading); mesh.renderOrder = -10 + index; scene.add(mesh); return mesh;
    }) }));
    let things = new THREE.Group(), signature = ""; scene.add(things);
    const marker = new THREE.Mesh(new THREE.RingGeometry(.10, .15, 32), new THREE.MeshBasicMaterial({ color: 0xf5cf71, side: THREE.DoubleSide })); marker.rotation.x = -Math.PI / 2; marker.visible = false; scene.add(marker);
    const orientation = createOrientationReader(), raw = new THREE.Quaternion(), anchor = new THREE.Quaternion(), target = new THREE.Quaternion(), pose = new THREE.Euler(0, 0, 0, "YXZ");
    const ray = new THREE.Raycaster(), plane = new THREE.Plane(new THREE.Vector3(0, 1, 0), 1.55), hit = new THREE.Vector3();
    let dragging: { x: number; y: number; distance: number } | null = null;
    const down = (e: PointerEvent) => { dragging = { x: e.clientX, y: e.clientY, distance: 0 }; renderer.domElement.setPointerCapture(e.pointerId); };
    const move = (e: PointerEvent) => { if (!dragging) return; const dx = e.clientX - dragging.x, dy = e.clientY - dragging.y; dragging.distance += Math.abs(dx) + Math.abs(dy); dragging.x = e.clientX; dragging.y = e.clientY; view.current.yaw -= dx * .15; view.current.pitch = clamp(view.current.pitch + dy * .15, -70, 70); view.current.recenter = true; };
    const up = (e: PointerEvent) => {
      if (dragging && dragging.distance < 8 && view.current.stereo) {
        // In the viewer a tap is all there is: near the top edge it leaves the headset, anywhere else it takes the room one step on.
        const rect = renderer.domElement.getBoundingClientRect();
        if (e.clientY - rect.top < rect.height * 0.2) leave.current();
        else if (current.current.phases[current.current.room] < 2) runner.current("clean_room", {});
      } else if (dragging && dragging.distance < 8) {
        const rect = renderer.domElement.getBoundingClientRect(); ray.setFromCamera(new THREE.Vector2((e.clientX - rect.left) / rect.width * 2 - 1, -(e.clientY - rect.top) / rect.height * 2 + 1), camera);
        if (ray.ray.intersectPlane(plane, hit) && Math.hypot(hit.x, hit.z) < 5) { view.current.selected = { x: hit.x, z: hit.z, room: current.current.room }; setCaption("Spot selected. Say ‘put it there’."); }
      }
      dragging = null;
    };
    renderer.domElement.addEventListener("pointerdown", down); renderer.domElement.addEventListener("pointermove", move); renderer.domElement.addEventListener("pointerup", up); renderer.domElement.addEventListener("pointercancel", () => { dragging = null; });
    const resize = () => renderer.setSize(el.clientWidth, el.clientHeight, false); resize(); const observer = new ResizeObserver(resize); observer.observe(el);
    let raf = 0, said: THREE.Sprite | null = null, saidWhat = "";
    const left = new THREE.PerspectiveCamera(), right = new THREE.PerspectiveCamera(), upAxis = new THREE.Vector3(0, 1, 0), level = new THREE.Euler(0, 0, 0, "YXZ"), ahead = new THREE.Vector2(0, 0);
    const frame = () => {
      raf = requestAnimationFrame(frame); const s = current.current, v = view.current;
      for (const pano of panoramas) for (let i = 0; i < pano.meshes.length; i++) { const mesh = pano.meshes[i]; mesh.visible = pano.room === s.room; mesh.material.opacity += ((s.phases[pano.room] === i ? 1 : 0) - mesh.material.opacity) * .09; }
      const nextSignature = JSON.stringify(s.objects);
      if (signature !== nextSignature) { signature = nextSignature; scene.remove(things); disposeObject(things); things = new THREE.Group(); s.objects.forEach(o => { const model = furniture(o); model.userData.room = o.room; things.add(model); }); scene.add(things); }
      things.children.forEach(o => { o.visible = o.userData.room === s.room; });
      marker.visible = v.selected?.room === s.room; if (v.selected) marker.position.set(v.selected.x, -1.54, v.selected.z);
      target.setFromEuler(pose.set(rad(v.pitch), -rad(v.yaw), 0));
      if (v.stereo && v.motion && orientation.read(raw)) {
        // In the viewer the head is the camera: the phone's own orientation, level with the real floor, turned so that
        // where the head pointed when the view was last set is where the room should face. No smoothing, which would lag the head.
        if (v.recenter) { v.offset = -rad(v.yaw) - yawOf(raw); v.recenter = false; }
        camera.quaternion.setFromAxisAngle(upAxis, v.offset).multiply(raw);
        level.setFromQuaternion(camera.quaternion); v.yaw = -level.y * 180 / Math.PI; v.pitch = level.x * 180 / Math.PI;      // so "in front" and "look left" start from where the head is
      } else {
        if (v.motion && orientation.read(raw)) { if (v.recenter) { anchor.copy(raw).invert(); v.recenter = false; } target.multiply(anchor.clone().multiply(raw)); }
        camera.quaternion.slerp(target, .22);
      }
      const w = el.clientWidth, h = el.clientHeight;
      camera.aspect = w / h; camera.fov = 75; camera.updateProjectionMatrix(); camera.updateMatrixWorld();
      if (v.stereo) {
        // Hands are busy holding the viewer, so "there" is where the eyes rest on the floor.
        ray.setFromCamera(ahead, camera);
        if (ray.ray.intersectPlane(plane, hit) && Math.hypot(hit.x, hit.z) < 5) v.selected = { x: hit.x, z: hit.z, room: s.room };
        marker.visible = v.selected?.room === s.room; if (v.selected) marker.position.set(v.selected.x, -1.54, v.selected.z);
        const now = `${words.current.top}|${words.current.bottom}`;
        if (now !== saidWhat) { saidWhat = now; if (said) { scene.remove(said); said.material.map?.dispose(); said.material.dispose(); } said = wordsSprite(words.current.top, words.current.bottom); scene.add(said); }
        // The words ride at the foot of the view wherever the head points, so they never cover what is being looked at, the floor included.
        if (said) { said.visible = true; said.position.set(0, -1.2, -2.2).applyQuaternion(camera.quaternion); }
      } else if (said) said.visible = false;
      renderer.setScissorTest(v.stereo);
      if (!v.stereo) { renderer.setViewport(0, 0, w, h); renderer.render(scene, camera); }
      else {
        // Each eye's picture is centred under its lens at the fitted spacing and seen from its own side, so the furniture has depth.
        renderer.setViewport(0, 0, w, h); renderer.setScissor(0, 0, w, h); renderer.clear();
        const off = new THREE.Vector3(1, 0, 0).applyQuaternion(camera.quaternion).multiplyScalar(EYES_M / 2), ports = eyeViewports(w, h, v.spacing);
        [left, right].forEach((eye, i) => {
          const { x, w: width } = ports[i];
          eye.aspect = width / h; eye.fov = eyeFov(eye.aspect); eye.near = .03; eye.far = 80; eye.updateProjectionMatrix();
          eye.quaternion.copy(camera.quaternion); eye.position.copy(off).multiplyScalar(i ? 1 : -1); eye.updateMatrixWorld();
          renderer.setViewport(x, 0, width, h); renderer.setScissor(x, 0, width, h); renderer.render(scene, eye);
        });
      }
    };
    frame();
    return () => { disposed = true; cancelAnimationFrame(raf); observer.disconnect(); orientation.stop(); panoramas.forEach(p => p.meshes.forEach(m => { m.material.map?.dispose(); m.material.dispose(); })); geometry.dispose(); disposeObject(things); disposeObject(marker); if (said) { said.material.map?.dispose(); said.material.dispose(); } env.dispose(); renderer.dispose(); renderer.domElement.remove(); };
  }, []);

  // Whether this device may use the voice at all: this computer may, a phone has to sign in once.
  useEffect(() => {
    fetch("/api/config", { credentials: "same-origin" }).then(r => { if (alive.current && (r.status === 401 || r.status === 403)) setSignin(v => ({ ...v, needed: true })); }).catch(() => {});
  }, []);
  const signIn = async () => {
    setSignin({ needed: true, busy: true, error: null });
    try {
      const r = await fetch("/api/recovery/session", { method: "POST", credentials: "same-origin", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ secret }) });
      if (!r.ok) throw new Error((await r.json().catch(() => null))?.error?.message || "That password was not accepted.");
      setSecret(""); setSignin({ needed: false, busy: false, error: null }); setCaption("Signed in. The room voice is ready.");
    } catch (problem) { setSignin({ needed: true, busy: false, error: (problem as Error).message }); }
  };
  const startVoice = async (listenOnly = false, keep = false) => {
    if (voice.current) { if (keep) return; voice.current.close(); voice.current = null; setVoiceState("off"); return; }
    if (signin.needed) { setCaption("Sign in on this phone first, then the room voice can start."); return; }
    if (starting.current) return; starting.current = true;
    try { const connection = await openVoice({ sessionUrl: "/api/restoration/voice", run: (name, args) => runner.current(name, args), listenOnly,
      greeting: "Call read_room and say: Let's clean this place up. Briefly invite the user to say clean up, more, or name a piece of furniture.",
      onState: s => { if (alive.current) setVoiceState(s); }, onCaption: (who, text) => { if (alive.current && who === "agent") setCaption(text); } }, true);
      if (alive.current) voice.current = connection; else connection.close();
    } catch { if (alive.current) setCaption("Voice couldn’t connect. Type a command below."); } finally { starting.current = false; }
  };
  const setSpacing = (mm: number) => { const v = clamp(Math.round(mm), 40, 80); setSpacingState(v); saveSpacing(v); view.current.spacing = v; };
  /** Into the viewer, from one tap: motion, a screen that stays awake, the voice, then the lenses are fitted. */
  const enterHeadset = async () => {
    if (window.isSecureContext && motionSupport() !== "unsupported") { const on = (await askForMotion()) === "on"; view.current.motion = on; setMotion(on); }
    (navigator as Navigator & { wakeLock?: { request(kind: string): Promise<unknown> } }).wakeLock?.request("screen").catch(() => {});
    document.documentElement.requestFullscreen?.().catch(() => {});
    void startVoice(false, true);
    // A laptop has no lenses to fit: go straight in. V or Escape comes back out.
    const phone = window.matchMedia("(pointer: coarse)").matches;
    view.current.recenter = true; view.current.stereo = !phone; setHeadset(phone ? "fit" : "on");
  };
  const leaveHeadset = () => { view.current.stereo = false; view.current.recenter = true; setHeadset("off"); if (document.fullscreenElement) document.exitFullscreen?.().catch(() => {}); };
  leave.current = leaveHeadset;
  useEffect(() => {
    const key = (e: KeyboardEvent) => {
      const el = e.target as HTMLElement | null;
      if (el && /^(INPUT|TEXTAREA|SELECT)$/.test(el.tagName)) return;
      if (e.key === "Escape" && headset !== "off") leaveHeadset();
      else if ((e.key === "v" || e.key === "V") && !e.metaKey && !e.ctrlKey) { if (headset === "off") void enterHeadset(); else leaveHeadset(); }
      else if (e.key === " " && headset === "on") { e.preventDefault(); if (current.current.phases[current.current.room] < 2) runner.current("clean_room", {}); }
    };
    window.addEventListener("keydown", key);
    return () => window.removeEventListener("keydown", key);
  });
  words.current = { top: `${ROOMS[state.room].title} · ${STAGES[state.phases[state.room]]}`, bottom: caption };
  const enableMotion = async () => {
    if (motion) { view.current.motion = false; setMotion(false); return; }
    if (!window.isSecureContext || motionSupport() === "unsupported") { setCaption("Motion needs a supported phone browser on HTTPS. Drag to look around here."); return; }
    const allowed = await askForMotion(); const on = allowed === "on"; view.current.motion = on; view.current.recenter = true; setMotion(on); setCaption(on ? "Motion enabled. Turn your phone to look around." : "Motion wasn’t allowed. You can still drag to look around.");
  };
  const submit = (text: string) => { const command = parseCommand(text); if (command) { const result = runner.current(command.name, command.args); if (result.say) setCaption(String(result.say)); voice.current?.note(JSON.stringify({ command: text, result })); } else if (voice.current && voiceState === "live") voice.current.text(text); else setCaption("Try ‘clean up’, ‘more’, ‘look left’, or ‘golden toilet in the bathroom’. Furniture: chair, sofa, table, lamp, plant, bed, toilet."); setDraft(""); };
  const ports = headset === "fit" ? eyeViewports(window.innerWidth, window.innerHeight, spacing) : [];
  return <main className={`restore-room${headset === "on" ? " is-headset" : ""}`}>
    <div className="restore-canvas" ref={mount} aria-label="Interactive room panorama; drag to look around and tap the floor to select a placement" />
    <header className="restore-top"><a href="#/">BRACE</a><div><strong>{ROOMS[state.room].title}</strong><span>{STAGES[state.phases[state.room]]}</span></div><small>AI-illustrated room · Concept furniture</small></header>
    {loading && <div className="restore-loading" role="status">{assetError ? "Room image unavailable. Refresh to retry." : "Opening your room…"}</div>}
    <aside className="restore-controls" aria-label="Room controls">
      <div className="restore-buttons"><button onClick={() => runner.current("go_room", { room: state.room === "kitchen" ? "bathroom" : "kitchen" })}>{state.room === "kitchen" ? "Bathroom" : "Kitchen"}</button><button onClick={enableMotion}>{motion ? "Motion on" : "Enable motion"}</button><button onClick={() => void enterHeadset()}>Headset view</button><button onClick={() => runner.current("edit_furniture", { action: "undo" })}>Undo</button></div>
      <p role="status">{caption}</p>
      {signin.needed && <form className="restore-signin" onSubmit={e => { e.preventDefault(); if (secret) void signIn(); }}>
        <label htmlFor="restore-secret">This phone needs the owner password once, for the room voice.</label>
        <div><input id="restore-secret" type="password" autoComplete="current-password" value={secret} onChange={e => setSecret(e.target.value)} placeholder="Owner password" /><button type="submit" disabled={signin.busy || !secret}>{signin.busy ? "Signing in…" : "Sign in"}</button></div>
        {signin.error && <small role="alert">{signin.error}</small>}
      </form>}
      <div className="restore-buttons"><button className="restore-primary" onClick={() => runner.current("clean_room", {})}>{state.phases[state.room] === 0 ? "Clean up" : state.phases[state.room] === 1 ? "More" : "Clear furniture"}</button><button onClick={e => void startVoice(e.shiftKey)} disabled={voiceState === "connecting"}>{voiceState === "connecting" ? "Connecting…" : voice.current ? "End room voice" : "Talk with room companion"}</button></div>
      <form onSubmit={e => { e.preventDefault(); if (draft.trim()) submit(draft); }}><input aria-label="Room command" value={draft} onChange={e => setDraft(e.target.value)} placeholder="Give me a golden toilet in the bathroom" /><button type="submit">Go</button></form>
      <small>Drag to look · Tap a floor spot, then say “there” · Placement and scale are approximate</small>
    </aside>
    {headset === "fit" && <div className="restore-fit">
      {ports.map((port, i) => <i key={i} style={{ left: port.x + port.w / 2 }} aria-hidden="true" />)}
      <p>Turn the phone sideways and hold the viewer to your eyes. Press − or + until the two crosses become one.</p>
      <div><button type="button" aria-label="Move the pictures closer" onClick={() => setSpacing(spacing - 1)}>−</button>
        <button type="button" className="restore-primary" onClick={() => { view.current.stereo = true; view.current.recenter = true; setHeadset("on"); }}>Done · {spacing} mm</button>
        <button type="button" aria-label="Move the pictures apart" onClick={() => setSpacing(spacing + 1)}>+</button></div>
      <small>In the viewer: speak to the room, or tap to clean it up one step. Look at the floor and say “a sofa there”. Tap near the top edge to come out.</small>
    </div>}
  </main>;
}
