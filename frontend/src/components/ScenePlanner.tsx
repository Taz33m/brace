import { useEffect, useMemo, useState } from "react";
import * as THREE from "three";
import type { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import "./scene-planner.css";

type Kind = "barrier" | "shutters" | "equipment" | "tree";
type Change = { id: string; kind: Kind; x: number; y: number; z: number; enabled: boolean; height: number; low: number; high: number; hours: number };
export interface PlannerWorld { scene: THREE.Scene; camera: THREE.PerspectiveCamera; renderer: THREE.WebGLRenderer; controls: OrbitControls; terrain: THREE.Mesh | null; marks: THREE.Group; homes: THREE.Group; fly: unknown }
const TYPES: Record<Kind, { title: string; low: number; high: number; hours: number; height: number }> = {
  barrier: { title: "Door barrier", low: 200, high: 800, hours: 2, height: 0.6 },
  shutters: { title: "Window shutters", low: 400, high: 1200, hours: 3, height: 1.5 },
  equipment: { title: "Raise equipment", low: 800, high: 2500, hours: 6, height: 1.2 },
  tree: { title: "Remove tree", low: 600, high: 2000, hours: 4, height: 6 },
};
const money = (n: number) => new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 }).format(n);
function restore(key: string): { water: number; changes: Change[] } {
  try {
    const data = JSON.parse(localStorage.getItem(key) || "null");
    if (!data || data.version !== 1 || !Number.isFinite(data.water) || data.water < 0 || data.water > 3 || !Array.isArray(data.changes)) throw new Error();
    const changes = data.changes.filter((c: Change) => c && Object.prototype.hasOwnProperty.call(TYPES, c.kind) && typeof c.id === "string" && typeof c.enabled === "boolean" &&
      [c.x,c.y,c.z,c.height,c.low,c.high,c.hours].every(Number.isFinite) && Math.abs(c.x) < 10000 && Math.abs(c.z) < 10000 && c.y >= 0 && c.y < 1000 && c.height >= 0.1 && c.height <= 30 && c.low >= 0 && c.high >= c.low && c.hours > 0).slice(0, 50);
    return { water: data.water, changes };
  } catch { return { water: 0.9, changes: [] }; }
}
function dispose(group: THREE.Group) {
  group.traverse(o => { if (o instanceof THREE.Mesh || o instanceof THREE.LineSegments) { o.geometry.dispose(); for (const m of Array.isArray(o.material) ? o.material : [o.material]) m.dispose(); } });
}

export function ScenePlanner({ world, width, depth, storageKey, onClose }: { world: PlannerWorld; width: number; depth: number; storageKey: string; onClose: () => void }) {
  const [initial] = useState(() => restore(storageKey));
  const [water, setWater] = useState(initial.water);
  const [changes, setChanges] = useState<Change[]>(initial.changes);
  const [tool, setTool] = useState<Kind | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [after, setAfter] = useState(true);
  const [view, setView] = useState<string | null>(null);
  const [storageError, setStorageError] = useState(false);
  const [notice, setNotice] = useState("");
  const active = changes.filter(c => c.enabled);
  const totals = active.reduce((v,c) => ({ low: v.low+c.low, high: v.high+c.high, hours: v.hours+c.hours }), { low: 0, high: 0, hours: 0 });
  const chosen = changes.find(c => c.id === selected);
  const group = useMemo(() => new THREE.Group(), []);

  useEffect(() => {
    const { controls, marks, homes } = world;
    const prior = { min: controls.minPolarAngle, max: controls.maxPolarAngle, auto: controls.autoRotate, marks: marks.visible, homes: homes.visible };
    world.fly = null;
    controls.autoRotate = false; controls.minPolarAngle = Math.PI * 35/180; controls.maxPolarAngle = Math.PI/3;
    marks.visible = false; homes.visible = false;
    world.scene.add(group);
    const changed = () => setView(null);
    controls.addEventListener("start", changed);
    return () => { controls.removeEventListener("start", changed); controls.minPolarAngle = prior.min; controls.maxPolarAngle = prior.max; controls.autoRotate = prior.auto; marks.visible = prior.marks; homes.visible = prior.homes; world.scene.remove(group); };
  }, [world, group]);

  useEffect(() => {
    try { localStorage.setItem(storageKey, JSON.stringify({ version: 1, water, changes })); setStorageError(false); }
    catch { setStorageError(true); }
  }, [water, changes, storageKey]);

  useEffect(() => {
    const key = (e: KeyboardEvent) => {
      if ((e.target as HTMLElement)?.closest("input,textarea,select,[contenteditable=true]") || e.ctrlKey || e.metaKey || e.altKey) return;
      if (e.key === "1") setAfter(false);
      if (e.key === "2") setAfter(true);
      if (e.key === "Escape") setTool(null);
    };
    window.addEventListener("keydown", key);
    return () => window.removeEventListener("keydown", key);
  }, []);

  useEffect(() => {
    const layer = new THREE.Group(); group.add(layer);
    if (water > 0) {
      const plane = new THREE.Mesh(new THREE.PlaneGeometry(width, depth).rotateX(-Math.PI/2), new THREE.MeshBasicMaterial({ color: 0x00b0e6, transparent: true, opacity: 0.45, depthWrite: false, side: THREE.DoubleSide }));
      plane.position.y = water; layer.add(plane);
    }
    for (const c of changes) {
      const item = new THREE.Group(); item.position.set(c.x,c.y,c.z); item.userData.changeId = c.id;
      const applied = after && c.enabled;
      const color = applied ? c.kind === "tree" ? 0xff7a3c : 0xffc20e : 0x9aa1ab;
      const material = new THREE.MeshStandardMaterial({ color, transparent: true, opacity: applied ? 0.95 : 0.35 });
      const add = (geometry: THREE.BufferGeometry, y: number) => { const m = new THREE.Mesh(geometry, material); m.position.y = y; item.add(m); };
      if (c.kind === "barrier") add(new THREE.BoxGeometry(3, applied ? c.height : 0.08, 0.5), applied ? c.height/2 : 0.04);
      if (c.kind === "shutters") {
        add(new THREE.BoxGeometry(2.4, c.height, 0.15), c.height/2);
        if (applied) for (let i = 1; i < 4; i++) { const slat = new THREE.Mesh(new THREE.BoxGeometry(2.3,0.06,0.2),new THREE.MeshBasicMaterial({color:0x0b1522})); slat.position.y=c.height*i/4; item.add(slat); }
      }
      if (c.kind === "equipment") { if (applied) add(new THREE.BoxGeometry(2.6,c.height,2.6),c.height/2); add(new THREE.BoxGeometry(2,1.3,2),0.65+(applied?c.height:0)); }
      if (c.kind === "tree") {
        const ring = new THREE.Mesh(new THREE.TorusGeometry(3,0.2,8,40).rotateX(Math.PI/2),material); ring.position.y=0.2; item.add(ring);
        if (!applied) add(new THREE.CylinderGeometry(0.3,0.45,c.height,8),c.height/2);
        else { for (const turn of [-Math.PI/4,Math.PI/4]) { const line = new THREE.Mesh(new THREE.BoxGeometry(6,0.15,0.25),material); line.rotation.y=turn; line.position.y=0.2; item.add(line); } }
      }
      const pin = new THREE.Mesh(new THREE.SphereGeometry(c.id === selected ? 1.3 : 0.8,12,8),new THREE.MeshBasicMaterial({color})); pin.position.y=c.height+2; item.add(pin);
      layer.add(item);
    }
    return () => { group.remove(layer); dispose(layer); };
  }, [group, changes, water, after, width, depth, selected]);

  useEffect(() => {
    const canvas = world.renderer.domElement;
    canvas.style.cursor = tool ? "crosshair" : "grab";
    let down = { x: 0, y: 0 };
    const start = (e: PointerEvent) => { down = { x: e.clientX, y: e.clientY }; };
    const end = (e: PointerEvent) => {
      if (e.button !== 0 || Math.hypot(e.clientX-down.x,e.clientY-down.y)>5) return;
      const bounds = canvas.getBoundingClientRect();
      const ray = new THREE.Raycaster(); ray.setFromCamera(new THREE.Vector2((e.clientX-bounds.left)/bounds.width*2-1, -(e.clientY-bounds.top)/bounds.height*2+1),world.camera);
      if (!tool) {
        const hit = ray.intersectObject(group,true).find(h => h.object.parent?.userData.changeId);
        if (hit) setSelected(hit.object.parent!.userData.changeId);
        return;
      }
      if (!world.terrain || changes.length >= 50) { setNotice("Keep this plan to 50 changes."); return; }
      const hit = ray.intersectObject(world.terrain)[0];
      if (!hit) { setNotice("Choose a position on the aerial site."); return; }
      const c: Change = { id: crypto.randomUUID(), kind: tool, x: hit.point.x, y: Math.max(0,hit.point.y), z: hit.point.z, enabled: true, ...TYPES[tool] };
      setChanges(old => [...old,c]); setSelected(c.id); setTool(null); setAfter(true); setNotice("Placed at your selected surface point. Verify position and dimensions before work.");
    };
    canvas.addEventListener("pointerdown",start); canvas.addEventListener("pointerup",end);
    return () => { canvas.style.cursor=""; canvas.removeEventListener("pointerdown",start); canvas.removeEventListener("pointerup",end); };
  }, [world, group, tool, changes.length]);

  function patch(id: string, data: Partial<Change>) { setChanges(old => old.map(c => c.id===id ? {...c,...data} : c)); }
  function focus(c: Change) { setSelected(c.id); world.controls.target.set(c.x,c.y+2,c.z); world.camera.position.set(c.x+45,c.y+55,c.z+65); world.controls.update(); }
  function direction(d: string) {
    const distance = Math.max(width,depth)*0.9;
    const offsets: Record<string,[number,number]> = { N:[0,-distance],E:[distance,0],S:[0,distance],W:[-distance,0] };
    const [x,z]=offsets[d]; world.controls.target.set(0,2,0); world.camera.position.set(x,distance*0.85,z); world.controls.update(); setView(d);
  }
  return <>
    <div className="planner-views" role="group" aria-label="View from side">{["N","E","S","W"].map(d=><button key={d} aria-pressed={view===d} onClick={()=>direction(d)}>{d}</button>)}</div>
    <div className="planner-compare" role="group" aria-label="Compare proposed changes"><button aria-pressed={!after} onClick={()=>setAfter(false)}>1 · Before</button><button aria-pressed={after} onClick={()=>setAfter(true)}>2 · Proposed</button></div>
    <aside className="planner-panel" aria-label="Building planner">
      <header><div><small>OWNER PLANNING</small><h2>Plan the building</h2></div><button onClick={onClose}>Close</button></header>
      <section><h3>What if the water reached {water.toFixed(1)} m?</h3><span className="planner-tag">HYPOTHETICAL</span><input aria-label="Hypothetical water level in metres" type="range" min="0" max="3" step="0.1" value={water} onChange={e=>setWater(Number(e.target.value))}/><p>Above the scene's ground reference. Uniform water level; no flood-flow or barrier simulation.</p></section>
      <section><h3>Place a change</h3><div className="planner-tools">{(Object.keys(TYPES) as Kind[]).map(k=><button key={k} aria-pressed={tool===k} onClick={()=>setTool(tool===k?null:k)}>{TYPES[k].title}</button>)}</div><p role="status">{tool ? `Click the site to place: ${TYPES[tool].title}. Escape cancels.` : notice || "Choose a change, then click the site. Drag to orbit."}</p></section>
      <section><h3>Your changes · {active.length}</h3>{!changes.length && <p>No changes placed yet.</p>}<ol>{changes.map((c,i)=><li key={c.id} className={selected===c.id?"is-selected":""}><input aria-label={`Include change ${i+1}`} type="checkbox" checked={c.enabled} onChange={e=>patch(c.id,{enabled:e.target.checked})}/><button onClick={()=>focus(c)}>{i+1}. {TYPES[c.kind].title}<small>{money(c.low)}–{money(c.high)} · {c.hours} crew-hours</small></button><button aria-label={`Remove change ${i+1}`} onClick={()=>{setChanges(old=>old.filter(x=>x.id!==c.id));setSelected(null);}}>×</button></li>)}</ol></section>
      {chosen && <section><h3>Edit {TYPES[chosen.kind].title.toLowerCase()}</h3><div className="planner-fields">{([['height','Height / lift (m)'],['low','Low cost ($)'],['high','High cost ($)'],['hours','Crew-hours']] as const).map(([key,label])=><label key={key}>{label}<input type="number" min={key==='height'?0.1:key==='hours'?0.25:0} max={key==='height'?30:1000000} step={key==='height'?0.1:key==='hours'?0.25:50} value={chosen[key]} onChange={e=>{const n=e.target.valueAsNumber;if(!Number.isFinite(n)||n<(key==='height'?0.1:key==='hours'?0.25:0)||n>(key==='height'?30:1000000))return;patch(chosen.id,{[key]:n,...(key==='low'&&n>chosen.high?{high:n}:key==='high'&&n<chosen.low?{low:n}:{})});}}/></label>)}</div><p>Owner-selected surface position; dimensions are assumptions. {chosen.kind==='tree'?'The removal marker leaves the captured terrain unchanged.':chosen.kind==='shutters'?'Shutters do not imply flood protection.':chosen.kind==='equipment'?`Proposed equipment base: ${(chosen.y+chosen.height-water).toFixed(1)} m relative to hypothetical water.`:'Barrier height is a proposal, not a tested protection level.'}</p></section>}
      <section className="planner-total" aria-live="polite"><h3>Planned allowance</h3><strong>{money(totals.low)}–{money(totals.high)}</strong><p>{totals.hours.toFixed(1)} crew-hours · one crew working sequentially, excluding travel</p><p>Editable illustrative allowances, not contractor quotes or predicted savings. Proposals have not been approved or installed.</p></section>
      <p className="planner-save" role="status">{storageError?"Browser storage unavailable. Changes last only while this planner stays open.":"Saved in this browser for this property and scenario."}</p>
    </aside>
  </>;
}
