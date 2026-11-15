import { useEffect, useRef, useState } from "react";
import * as THREE from "three";
import { RoomEnvironment } from "three/examples/jsm/environments/RoomEnvironment.js";
import { openVoice, type Voice, type VoiceState } from "../../voice";
import { askForMotion, createOrientationReader, motionSupport } from "../headset/lib/motion";
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

export function RestorationRoom({ room: initialRoom = "kitchen" }: { room?: Room }) {
  const [state, setState] = useState<Snapshot>({ room: initialRoom, phases: { kitchen: 0, bathroom: 0 }, objects: [] });
  const current = useRef(state);
  const history = useRef<Snapshot[]>([]);
  const mount = useRef<HTMLDivElement>(null);
  const [caption, setCaption] = useState("Let’s clean this place up.");
  const [draft, setDraft] = useState("");
  const [voiceState, setVoiceState] = useState<VoiceState>("off");
  const [motion, setMotion] = useState(false);
  const [stereo, setStereo] = useState(false);
  const [loading, setLoading] = useState(true);
  const [assetError, setAssetError] = useState(false);
  const voice = useRef<Voice | null>(null), starting = useRef(false), alive = useRef(true);
  const view = useRef({ yaw: 0, pitch: -10, motion: false, stereo: false, recenter: true, selected: null as { x: number; z: number; room: Room } | null });
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
      if (dragging && dragging.distance < 8 && !view.current.stereo) {
        const rect = renderer.domElement.getBoundingClientRect(); ray.setFromCamera(new THREE.Vector2((e.clientX - rect.left) / rect.width * 2 - 1, -(e.clientY - rect.top) / rect.height * 2 + 1), camera);
        if (ray.ray.intersectPlane(plane, hit) && Math.hypot(hit.x, hit.z) < 5) { view.current.selected = { x: hit.x, z: hit.z, room: current.current.room }; setCaption("Spot selected. Say ‘put it there’."); }
      }
      dragging = null;
    };
    renderer.domElement.addEventListener("pointerdown", down); renderer.domElement.addEventListener("pointermove", move); renderer.domElement.addEventListener("pointerup", up); renderer.domElement.addEventListener("pointercancel", () => { dragging = null; });
    const resize = () => renderer.setSize(el.clientWidth, el.clientHeight, false); resize(); const observer = new ResizeObserver(resize); observer.observe(el);
    let raf = 0;
    const frame = () => {
      raf = requestAnimationFrame(frame); const s = current.current, v = view.current;
      for (const pano of panoramas) for (let i = 0; i < pano.meshes.length; i++) { const mesh = pano.meshes[i]; mesh.visible = pano.room === s.room; mesh.material.opacity += ((s.phases[pano.room] === i ? 1 : 0) - mesh.material.opacity) * .09; }
      const nextSignature = JSON.stringify(s.objects);
      if (signature !== nextSignature) { signature = nextSignature; scene.remove(things); disposeObject(things); things = new THREE.Group(); s.objects.forEach(o => { const model = furniture(o); model.userData.room = o.room; things.add(model); }); scene.add(things); }
      things.children.forEach(o => { o.visible = o.userData.room === s.room; });
      marker.visible = v.selected?.room === s.room; if (v.selected) marker.position.set(v.selected.x, -1.54, v.selected.z);
      target.setFromEuler(pose.set(rad(v.pitch), -rad(v.yaw), 0));
      if (v.motion && orientation.read(raw)) { if (v.recenter) { anchor.copy(raw).invert(); v.recenter = false; } target.multiply(anchor.clone().multiply(raw)); }
      camera.quaternion.slerp(target, .22);
      const w = el.clientWidth, h = el.clientHeight;
      renderer.setScissorTest(v.stereo);
      for (let eye = 0; eye < (v.stereo ? 2 : 1); eye++) { const width = v.stereo ? w / 2 : w; camera.aspect = width / h; camera.updateProjectionMatrix(); renderer.setViewport(eye * width, 0, width, h); if (v.stereo) renderer.setScissor(eye * width, 0, width, h); renderer.render(scene, camera); }
    };
    frame();
    return () => { disposed = true; cancelAnimationFrame(raf); observer.disconnect(); orientation.stop(); panoramas.forEach(p => p.meshes.forEach(m => { m.material.map?.dispose(); m.material.dispose(); })); geometry.dispose(); disposeObject(things); disposeObject(marker); env.dispose(); renderer.dispose(); renderer.domElement.remove(); };
  }, []);

  const startVoice = async (listenOnly = false) => {
    if (voice.current) { voice.current.close(); voice.current = null; setVoiceState("off"); return; }
    if (starting.current) return; starting.current = true;
    try { const connection = await openVoice({ sessionUrl: "/api/restoration/voice", run: (name, args) => runner.current(name, args), listenOnly,
      greeting: "Call read_room and say: Let's clean this place up. Briefly invite the user to say clean up, more, or name a piece of furniture.",
      onState: s => { if (alive.current) setVoiceState(s); }, onCaption: (who, text) => { if (alive.current && who === "agent") setCaption(text); } }, true);
      if (alive.current) voice.current = connection; else connection.close();
    } catch { if (alive.current) setCaption("Voice couldn’t connect. Type a command below."); } finally { starting.current = false; }
  };
  const enableMotion = async () => {
    if (motion) { view.current.motion = false; setMotion(false); return; }
    if (!window.isSecureContext || motionSupport() === "unsupported") { setCaption("Motion needs a supported phone browser on HTTPS. Drag to look around here."); return; }
    const allowed = await askForMotion(); const on = allowed === "on"; view.current.motion = on; view.current.recenter = true; setMotion(on); setCaption(on ? "Motion enabled. Turn your phone to look around." : "Motion wasn’t allowed. You can still drag to look around.");
  };
  const submit = (text: string) => { const command = parseCommand(text); if (command) { const result = runner.current(command.name, command.args); if (result.say) setCaption(String(result.say)); voice.current?.note(JSON.stringify({ command: text, result })); } else if (voice.current && voiceState === "live") voice.current.text(text); else setCaption("Try ‘clean up’, ‘more’, ‘look left’, or ‘golden toilet in the bathroom’. Furniture: chair, sofa, table, lamp, plant, bed, toilet."); setDraft(""); };
  return <main className="restore-room">
    <div className="restore-canvas" ref={mount} aria-label="Interactive room panorama; drag to look around and tap the floor to select a placement" />
    <header className="restore-top"><a href="#/">BRACE</a><div><strong>{ROOMS[state.room].title}</strong><span>{STAGES[state.phases[state.room]]}</span></div><small>AI-illustrated room · Concept furniture</small></header>
    {loading && <div className="restore-loading" role="status">{assetError ? "Room image unavailable. Refresh to retry." : "Opening your room…"}</div>}
    <aside className="restore-controls" aria-label="Room controls">
      <div className="restore-buttons"><button onClick={() => runner.current("go_room", { room: state.room === "kitchen" ? "bathroom" : "kitchen" })}>{state.room === "kitchen" ? "Bathroom" : "Kitchen"}</button><button onClick={enableMotion}>{motion ? "Motion on" : "Enable motion"}</button><button onClick={() => { view.current.stereo = !stereo; setStereo(!stereo); }}>{stereo ? "Single view" : "Headset view"}</button><button onClick={() => runner.current("edit_furniture", { action: "undo" })}>Undo</button></div>
      <p role="status">{caption}</p>
      <div className="restore-buttons"><button className="restore-primary" onClick={() => runner.current("clean_room", {})}>{state.phases[state.room] === 0 ? "Clean up" : state.phases[state.room] === 1 ? "More" : "Clear furniture"}</button><button onClick={e => void startVoice(e.shiftKey)} disabled={voiceState === "connecting"}>{voiceState === "connecting" ? "Connecting…" : voice.current ? "End room voice" : "Talk with room companion"}</button></div>
      <form onSubmit={e => { e.preventDefault(); if (draft.trim()) submit(draft); }}><input aria-label="Room command" value={draft} onChange={e => setDraft(e.target.value)} placeholder="Give me a golden toilet in the bathroom" /><button type="submit">Go</button></form>
      <small>Drag to look · Tap a floor spot, then say “there” · Placement and scale are approximate</small>
    </aside>
  </main>;
}
