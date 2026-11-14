import { useEffect, useRef, useState } from "react";
import * as THREE from "three";
import "./story.css";

/**
 * Standing in the home while the water comes in. It plays by itself, like a film: nothing is steered. On a phone
 * in a cardboard viewer it is drawn twice, once for each eye; on a laptop it is drawn once. The room is the
 * Matterport scan from one standpoint. The water is drawn in over the floor of every room, at the depth the flood
 * test gives this building, round the furniture that stands taller than it.
 */
interface Pov {
  property_id: number; scan_id: string; name: string; site: string; sweep_id: string;
  standpoint: { e: number; n: number; z: number; h: number }; view: { yaw_deg: number };
  rooms: { name: string; outline: [number, number][] }[];
  pieces: { name: string; east_m: number; north_m: number; faces_deg: number; width_m: number; depth_m: number; height_m: number; stands_on_m: number }[];
  water: { set_ft: number; depth_ft: number; depth_m: number }; ceiling_m: number; cost: { low: number; high: number } | null; label: string;
}
const FACE_M = 40, LOOP_S = 44, EYES_M = 0.064;
const rad = (deg: number) => (deg * Math.PI) / 180;
const clamp = (v: number) => Math.min(1, Math.max(0, v));
const smooth = (t: number) => t * t * (3 - 2 * t);
const usd = (n: number) => `$${(Math.round(n / 100) * 100).toLocaleString("en-US")}`;

/** Words in the room: drawn to a picture and hung in the air, so each eye sees them in the same place. */
function sign(lines: [string, string]): THREE.Sprite {
  const c = document.createElement("canvas");
  c.width = 1024; c.height = 420;
  const g = c.getContext("2d")!;
  g.fillStyle = "rgba(11, 11, 12, 0.72)";
  g.beginPath(); g.roundRect(0, 0, 1024, 420, 36); g.fill();
  g.textAlign = "center"; g.fillStyle = "#ff5a3c"; g.font = "500 150px Georgia, serif";
  g.fillText(lines[0], 512, 190);
  g.fillStyle = "#f3ece0"; g.font = "400 64px Helvetica, Arial, sans-serif";
  g.fillText(lines[1], 512, 320);
  const tex = new THREE.CanvasTexture(c);
  tex.colorSpace = THREE.SRGBColorSpace;
  const sprite = new THREE.Sprite(new THREE.SpriteMaterial({ map: tex, transparent: true, opacity: 0, depthTest: false }));
  sprite.scale.set(1.5, 0.615, 1);
  sprite.renderOrder = 5;
  return sprite;
}

export function InsidePov({ site, scan, stereo: forced }: { site: number; scan: string; stereo: boolean }) {
  const [pov, setPov] = useState<Pov | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [stereo, setStereo] = useState(() => forced || window.matchMedia("(pointer: coarse)").matches);
  const mount = useRef<HTMLDivElement>(null);
  const live = useRef({ stereo });
  live.current.stereo = stereo;

  useEffect(() => { document.documentElement.classList.add("st-on"); return () => document.documentElement.classList.remove("st-on"); }, []);
  useEffect(() => {
    fetch(`/api/file/${site}/${scan}/pov?water_ft=4`).then(async (r) => { if (!r.ok) throw new Error((await r.json().catch(() => null))?.detail || "this home cannot be shown from inside"); return r.json(); })
      .then(setPov).catch((e) => setError(e.message));
  }, [site, scan]);
  useEffect(() => {
    const key = (e: KeyboardEvent) => { if (e.key === "v") setStereo((s) => !s); else if (e.key === "Escape") window.location.hash = "#/"; };
    window.addEventListener("keydown", key);
    return () => window.removeEventListener("keydown", key);
  }, []);

  useEffect(() => {
    const el = mount.current;
    if (!el || !pov) return;
    const renderer = new THREE.WebGLRenderer({ antialias: true });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.setSize(el.clientWidth, el.clientHeight);
    renderer.outputColorSpace = THREE.SRGBColorSpace;
    renderer.autoClear = false;
    el.appendChild(renderer.domElement);
    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(84, 1, 0.05, 300);
    camera.rotation.order = "YXZ";
    const { e: e0, n: n0, z: eye, h: heading } = pov.standpoint, aim = heading + (pov.view.yaw_deg ?? 0);
    const at = (east: number, north: number) => [east - e0, -(north - n0)] as [number, number];

    // The room as the scan saw it: six pictures on the inside of a box, turned to the scan's own heading.
    const loader = new THREE.TextureLoader(), box = new THREE.Group(), side = FACE_M * 2.002;
    const face = (f: number) => {
      const tex = loader.load(`/api/buildings/${site}/pano/${scan}/${pov.sweep_id}/${f}.jpg?size=2048`);
      tex.colorSpace = THREE.SRGBColorSpace;
      const mesh = new THREE.Mesh(new THREE.PlaneGeometry(side, side), new THREE.MeshBasicMaterial({ map: tex, depthTest: false, depthWrite: false }));
      mesh.renderOrder = 0;
      return mesh;
    };
    for (let k = 0; k < 4; k++) { const pivot = new THREE.Group(), m = face(k + 1); m.position.z = -FACE_M; pivot.add(m); pivot.rotation.y = -rad(heading + 90 * k); box.add(pivot); }
    const caps = new THREE.Group(), up = face(0), down = face(5);
    up.position.y = FACE_M; up.rotation.x = Math.PI / 2; down.position.y = -FACE_M; down.rotation.x = -Math.PI / 2;
    caps.add(up, down); caps.rotation.y = -rad(heading); box.add(caps);
    scene.add(box);

    // The water: the floor of every room, with a gap where a piece of furniture stands taller than it.
    const depth = pov.water.depth_m, tall = pov.pieces.filter((p) => p.stands_on_m === 0 && p.height_m > depth + 0.03);
    const ripple = document.createElement("canvas");
    ripple.width = ripple.height = 256;
    const g = ripple.getContext("2d")!;
    g.fillStyle = "#65573f"; g.fillRect(0, 0, 256, 256);      // flood water is silt, not sea: a dull grey-brown with a little light on it
    for (let i = 0; i < 140; i++) { g.strokeStyle = `rgba(${i % 2 ? "214, 204, 180" : "40, 34, 24"}, ${0.05 + Math.random() * 0.07})`; g.lineWidth = 3 + Math.random() * 6; const y = Math.random() * 256, x = Math.random() * 256; g.beginPath(); g.moveTo(x, y); g.bezierCurveTo(x + 40, y - 9, x + 80, y + 9, x + 130, y); g.stroke(); }
    const skin = new THREE.CanvasTexture(ripple);
    skin.wrapS = skin.wrapT = THREE.RepeatWrapping; skin.repeat.set(0.22, 0.22); skin.colorSpace = THREE.SRGBColorSpace;
    const waterMat = new THREE.MeshBasicMaterial({ map: skin, transparent: true, opacity: 0, depthTest: false, depthWrite: false, side: THREE.DoubleSide });
    const water = new THREE.Group();
    for (const room of pov.rooms) {
      const shape = new THREE.Shape(room.outline.map(([east, north]) => { const [x, z] = at(east, north); return new THREE.Vector2(x, -z); }));
      for (const p of tall) {
        const [cx, cz] = at(p.east_m, p.north_m), turn = Math.PI - rad(p.faces_deg), hw = p.width_m / 2, hd = p.depth_m / 2;
        const corners = [[-hw, -hd], [hw, -hd], [hw, hd], [-hw, hd]].map(([x, z]) => new THREE.Vector2(cx + x * Math.cos(turn) + z * Math.sin(turn), -(cz - x * Math.sin(turn) + z * Math.cos(turn))));
        if (corners.every((c) => inside(c, shape.getPoints()))) shape.holes.push(new THREE.Path(corners));
      }
      const mesh = new THREE.Mesh(new THREE.ShapeGeometry(shape).rotateX(-Math.PI / 2), waterMat);
      mesh.renderOrder = 2;
      water.add(mesh);
    }
    water.position.y = -eye;
    scene.add(water);

    const first = sign([`${pov.water.depth_ft} ft`, "of water in this home"]);
    const second = sign([pov.cost ? usd(pov.cost.low) : "", pov.cost ? `to ${usd(pov.cost.high)} to put it back` : "no price confirmed"]);
    scene.add(first, second);

    const left = new THREE.PerspectiveCamera(), right = new THREE.PerspectiveCamera();
    const resize = () => renderer.setSize(el.clientWidth, el.clientHeight, false);
    resize();
    const watch = new ResizeObserver(resize);
    watch.observe(el);
    const t0 = performance.now();
    let raf = 0;
    const frame = () => {
      raf = requestAnimationFrame(frame);
      const t = ((performance.now() - t0) / 1000) % LOOP_S;
      // The film: the dry room, the water coming up, what it is and what it costs, and the room dry again.
      const rise = smooth(clamp((t - 5) / 15)) * (1 - smooth(clamp((t - 36) / 5)));
      water.position.y = -eye + Math.max(0.005, depth * rise) + Math.sin(t * 1.3) * 0.006 * rise;
      waterMat.opacity = Math.min(0.86, rise * 3);
      skin.offset.set(t * 0.012, t * 0.007);
      (first.material as THREE.SpriteMaterial).opacity = smooth(clamp((t - 19) / 1.5)) * (1 - smooth(clamp((t - 26) / 1.5)));
      (second.material as THREE.SpriteMaterial).opacity = smooth(clamp((t - 27.5) / 1.5)) * (1 - smooth(clamp((t - 35) / 1.5)));
      // The head turns slowly from side to side and looks down as the water comes.
      camera.rotation.set(rad(-6 - 16 * rise * (1 - smooth(clamp((t - 18) / 3))) - 4), -rad(aim + 38 * Math.sin((t / LOOP_S) * Math.PI * 2)), 0);
      camera.updateMatrixWorld();
      // The words stay in front of the eyes as the head turns, a little above the middle.
      const ahead = new THREE.Vector3(0, 0.16, -1).applyEuler(new THREE.Euler(0, camera.rotation.y, 0)).multiplyScalar(2.1);
      first.position.copy(ahead); second.position.copy(ahead);
      const W = el.clientWidth, H = el.clientHeight;      // three.js scales these by the pixel ratio itself
      renderer.setScissorTest(true);
      renderer.setViewport(0, 0, W, H); renderer.setScissor(0, 0, W, H); renderer.clear();
      if (!live.current.stereo) {
        camera.fov = 78; camera.aspect = W / H; camera.updateProjectionMatrix();
        renderer.render(scene, camera);
      } else {
        const off = new THREE.Vector3(1, 0, 0).applyQuaternion(camera.quaternion).multiplyScalar(EYES_M / 2);
        [left, right].forEach((eyeCam, i) => {
          eyeCam.fov = 84; eyeCam.aspect = W / 2 / H; eyeCam.near = 0.05; eyeCam.far = 300; eyeCam.updateProjectionMatrix();
          eyeCam.quaternion.copy(camera.quaternion);
          eyeCam.position.copy(off).multiplyScalar(i ? 1 : -1);
          eyeCam.updateMatrixWorld();
          renderer.setViewport((i * W) / 2, 0, W / 2, H); renderer.setScissor((i * W) / 2, 0, W / 2, H);
          renderer.render(scene, eyeCam);
        });
      }
    };
    frame();
    return () => { cancelAnimationFrame(raf); watch.disconnect(); renderer.dispose(); el.removeChild(renderer.domElement); };
  }, [pov, site, scan]);

  if (error) return <div className="fatal" role="alert">{error}</div>;
  // One tap fills the screen and keeps the phone awake; nothing else is touched.
  const fill = () => { document.documentElement.requestFullscreen?.().catch(() => {}); (navigator as Navigator & { wakeLock?: { request(kind: string): Promise<unknown> } }).wakeLock?.request("screen").catch(() => {}); };
  return (
    <div className={`pov${stereo ? " is-stereo" : ""}`} onClick={fill}>
      <div ref={mount} className="pov-stage" />
      {stereo && <i className="pov-split" aria-hidden="true" />}
      {pov && !stereo && <p className="pov-label">{pov.label}</p>}
    </div>
  );
}

/** Whether a point lies inside an outline: a count of the edges a line from it crosses. */
function inside(pt: THREE.Vector2, ring: THREE.Vector2[]): boolean {
  let hit = false;
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
    const a = ring[i], b = ring[j];
    if ((a.y > pt.y) !== (b.y > pt.y) && pt.x < ((b.x - a.x) * (pt.y - a.y)) / (b.y - a.y) + a.x) hit = !hit;
  }
  return hit;
}
